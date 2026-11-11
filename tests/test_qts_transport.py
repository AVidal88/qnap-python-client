"""Synthetic transport checks; these do not establish a QTS power API contract."""

from __future__ import annotations

import asyncio
import base64
import logging
import traceback
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import web

from qnap_client import (
    ContainerStationClient,
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapConnectionError,
    QnapPermissionError,
    QnapTimeoutError,
    QnapTwoStepRequiredError,
)
from qnap_client.models import SystemInfo

SID = "synthetic-secret-sid"
PASSWORD = "synthetic-secret-password"
LOGIN_OK = f"<QDocRoot><authPassed>1</authPassed><authSid>{SID}</authSid></QDocRoot>"
SECRETS = (SID, PASSWORD, base64.b64encode(PASSWORD.encode()).decode())


def assert_no_secrets(value: BaseException | str) -> None:
    rendered = (
        "".join(traceback.format_exception(value))
        if isinstance(value, BaseException)
        else value
    )
    for secret in SECRETS:
        assert secret not in rendered


@pytest.fixture
async def server(unused_tcp_port):
    state = {
        "login_status": 200,
        "login_body": LOGIN_OK,
        "status": 200,
        "cs_body": '{"data":{"items":[]}}',
        "calls": [],
    }

    async def handle(request):
        state["calls"].append((request.method, request.path, dict(request.query)))
        if request.path.endswith("authLogin.cgi"):
            return web.Response(status=state["login_status"], text=state["login_body"])
        if state["status"] == 302:
            return web.Response(status=302, headers={"Location": "/redirect-target"})
        if request.path.startswith("/container-station/api/"):
            assert request.headers.get("Authorization") == f"Bearer {SID}"
            return web.Response(status=state["status"], text=state["cs_body"])
        return web.Response(
            status=state["status"],
            text=f"<QDocRoot><hostname>{SID}</hostname></QDocRoot>",
        )

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
        yield unused_tcp_port, state
    finally:
        await runner.cleanup()


async def test_login_does_not_log_sid_and_offline_close_sends_no_request(
    server, caplog
):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    with caplog.at_level(logging.DEBUG):
        await client.login()
        owned_session = client._session
        await client.close(logout=False)
        await client.close(logout=False)

    assert client._sid is None
    assert owned_session.closed
    assert client._session is None
    assert [method for method, _, _ in state["calls"]] == ["POST"]
    assert_no_secrets(caplog.text)


async def test_failed_login_clears_old_sid_and_sanitizes_malformed_xml(server):
    port, state = server
    state["login_body"] = f"not XML: {SID} {PASSWORD}"
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    client._sid = "old-session"
    try:
        with pytest.raises(QnapAPIError) as caught:
            await client.login()
        assert client._sid is None
        assert_no_secrets(caught.value)
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize("marker", ["need_2sv", "need_2_step_verification"])
async def test_two_step_challenge_has_specific_safe_error(server, marker):
    port, state = server
    state["login_body"] = (
        f"<QDocRoot><authPassed>0</authPassed><{marker}>1</{marker}>"
        f"<authSid>{SID}</authSid></QDocRoot>"
    )
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        with pytest.raises(QnapTwoStepRequiredError) as caught:
            await client.login()
        assert client._sid is None
        assert_no_secrets(caught.value)
        assert [method for method, _, _ in state["calls"]] == ["POST"]
    finally:
        await client.close(logout=False)


async def test_failed_context_entry_closes_owned_session(server):
    port, state = server
    state["login_status"] = 401
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    with pytest.raises(QnapAuthError):
        async with client:
            pytest.fail("A failed login must not enter the context")
    assert client._session is None
    assert client._sid is None


@pytest.mark.parametrize(
    "status, error, clears_sid",
    [
        (401, QnapAuthError, True),
        (403, QnapPermissionError, False),
        (302, QnapAPIError, False),
        (503, QnapAPIError, False),
    ],
)
async def test_read_errors_are_typed_sanitized_and_sent_once(
    server, status, error, clears_sid
):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        state["status"] = status
        with pytest.raises(error) as caught:
            await client.get_system_info()
        assert_no_secrets(caught.value)
        assert len(state["calls"]) == 2
        assert state["calls"][1][2]["sid"] == SID
        if clears_sid:
            assert client._sid is None
        else:
            assert client._sid == SID
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize(
    "failure, error",
    [
        (aiohttp.ClientConnectionError(SID), QnapConnectionError),
        (aiohttp.ClientPayloadError(PASSWORD), QnapConnectionError),
        (TimeoutError(PASSWORD), QnapTimeoutError),
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_transport_failures_are_sanitized_and_never_retried(
    server, failure, error, method
):
    port, _ = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    client._sid = SID
    session = await client._ensure_session()
    try:
        with (
            patch.object(session, "request", side_effect=failure) as request,
            pytest.raises(error) as caught,
        ):
            if method == "GET":
                await client._get("/generic-test-path")
            else:
                await client._request(
                    "POST", f"{client._base}/generic-test-path", params={"sid": SID}
                )
        assert request.call_count == 1
        assert request.call_args.args[0] == method
        assert caught.value.__cause__ is None
        assert_no_secrets(caught.value)
    finally:
        await client.close(logout=False)


async def test_supplied_session_response_error_cannot_expose_request_url(server):
    port, state = server
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        client = QnapClient("127.0.0.1", port, "user", PASSWORD, session=session)
        await client.login()
        state["status"] = 401
        with pytest.raises(QnapAuthError) as caught:
            await client.get_system_info()
        assert client._sid is None
        assert_no_secrets(caught.value)
        await client.close(logout=False)
        assert not session.closed


async def test_supplied_session_keeps_ownership_and_receives_transport_options(server):
    port, _ = server
    async with aiohttp.ClientSession() as session:
        client = QnapClient(
            "127.0.0.1",
            port,
            "user",
            PASSWORD,
            session=session,
            timeout=3,
            verify_ssl=False,
        )
        with patch.object(session, "request", wraps=session.request) as request:
            await client.login()
        assert request.call_count == 1
        assert request.call_args.kwargs["allow_redirects"] is False
        assert request.call_args.kwargs["ssl"] is False
        assert request.call_args.kwargs["timeout"].total == 3
        await client.close(logout=False)
        assert not session.closed


OPTIONAL_READS = (
    "get_system_health",
    "get_cpu_stats",
    "get_memory_stats",
    "get_network_interfaces",
    "get_drive_health",
    "get_volumes",
    "get_firmware_update",
    "get_fans",
    "get_external_drives",
)
INFO = SystemInfo("TS-431P", "NAS", "synthetic-serial", "5.2.11", 100)


@pytest.mark.parametrize(
    "error_type", [QnapConnectionError, QnapAuthError, QnapAPIError]
)
async def test_get_all_propagates_core_read_failure(error_type):
    client = QnapClient("127.0.0.1", 1, "user", PASSWORD)
    error = error_type("Core read failed")
    with ExitStack() as patches:
        for name in OPTIONAL_READS:
            patches.enter_context(
                patch.object(client, name, AsyncMock(return_value=None))
            )
        patches.enter_context(
            patch.object(client, "get_system_info", AsyncMock(side_effect=error))
        )
        with pytest.raises(error_type) as caught:
            await client.get_all()
    assert caught.value is error


async def test_get_all_preserves_optional_defaults_without_logging_response_values(
    caplog,
):
    client = QnapClient("127.0.0.1", 1, "user", PASSWORD)
    with ExitStack() as patches:
        for name in OPTIONAL_READS:
            patches.enter_context(
                patch.object(
                    client,
                    name,
                    AsyncMock(side_effect=QnapAPIError(f"{SID} {PASSWORD}")),
                )
            )
        patches.enter_context(
            patch.object(client, "get_system_info", AsyncMock(return_value=INFO))
        )
        with caplog.at_level(logging.WARNING):
            data = await client.get_all()
    assert data.system_info is INFO
    assert data.network_interfaces == []
    assert data.firmware is None
    assert "QnapAPIError" in caplog.text
    assert_no_secrets(caplog.text)


async def test_get_all_propagates_cancelled_optional_read():
    client = QnapClient("127.0.0.1", 1, "user", PASSWORD)
    with ExitStack() as patches:
        for name in OPTIONAL_READS:
            patches.enter_context(
                patch.object(client, name, AsyncMock(return_value=None))
            )
        patches.enter_context(
            patch.object(client, "get_system_info", AsyncMock(return_value=INFO))
        )
        patches.enter_context(
            patch.object(
                client, "get_fans", AsyncMock(side_effect=asyncio.CancelledError())
            )
        )
        with pytest.raises(asyncio.CancelledError):
            await client.get_all()


async def test_malformed_network_values_are_not_logged(caplog):
    client = QnapClient("127.0.0.1", 1, "user", PASSWORD)
    with (
        patch.object(
            client,
            "_get",
            AsyncMock(
                side_effect=[
                    f"<QDocRoot><net><eth0><rx>{PASSWORD}</rx></eth0></net></QDocRoot>",
                    "<QDocRoot><func><ownContent><root><nic_cnt>0</nic_cnt></root></ownContent></func></QDocRoot>",
                ]
            ),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        assert await client.get_network_interfaces() == []
    assert "ValueError" in caplog.text
    assert_no_secrets(caplog.text)


async def test_malformed_fan_values_are_not_logged(caplog):
    client = QnapClient("127.0.0.1", 1, "user", PASSWORD)
    with (
        patch.object(
            client,
            "_get",
            AsyncMock(
                return_value=f"<QDocRoot><sysfan><fan><rpm>{PASSWORD}</rpm></fan></sysfan></QDocRoot>"
            ),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        assert await client.get_fans() == []
    assert "ValueError" in caplog.text
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize("operation", ["list", "action"])
async def test_container_auth_failure_preserves_qts_session(server, operation):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        state["status"] = 401
        cs = ContainerStationClient(client)
        with pytest.raises(QnapAuthError) as caught:
            if operation == "list":
                await cs.get_containers()
            else:
                await cs.stop_container("test-container")
        assert client._sid == SID
        assert_no_secrets(caught.value)
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize("operation", ["list", "action"])
async def test_container_error_response_cannot_expose_response_values(
    server, operation
):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        state["status"] = 500
        state["cs_body"] = f"{SID} {PASSWORD}"
        cs = ContainerStationClient(client)
        with pytest.raises(QnapAPIError) as caught:
            if operation == "list":
                await cs.get_containers()
            else:
                await cs.stop_container("test-container")
        assert_no_secrets(caught.value)
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


async def test_container_invalid_json_is_sanitized(server):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        state["cs_body"] = f"{SID} {PASSWORD}"
        with pytest.raises(QnapAPIError) as caught:
            await ContainerStationClient(client).get_containers()
        assert_no_secrets(caught.value)
    finally:
        await client.close(logout=False)


async def test_container_list_and_stop_preserve_existing_request_shapes(server):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        state["cs_body"] = (
            '{"data":{"items":[{"id":"test-container","name":"web",'
            '"status":"running","image":"test"}]}}'
        )
        cs = ContainerStationClient(client)
        containers = await cs.get_containers()
        assert containers[0].state == "running"
        state["status"] = 204
        state["cs_body"] = ""
        await cs.stop_container(containers[0].id)
        assert state["calls"][1:] == [
            ("GET", "/container-station/api/v3/containers", {}),
            (
                "POST",
                "/container-station/api/v3/containers/docker/test-container/stop",
                {},
            ),
        ]
    finally:
        await client.close(logout=False)
