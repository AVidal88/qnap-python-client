"""Transport and lifecycle regressions; fixtures are synthetic, not firmware captures."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from qnap_client import (
    ContainerStationClient,
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapConnectionError,
    QnapPermissionError,
    QnapTimeoutError,
)
from qnap_client.models import SystemInfo

BASE = "http://192.0.2.1:8080"
LOGIN = f"{BASE}/cgi-bin/authLogin.cgi"
SID = "secret-session-id"
PASSWORD = "secret-password"
LOGIN_OK = f"<QDocRoot><authPassed>1</authPassed><authSid>{SID}</authSid></QDocRoot>"
READ = re.compile(re.escape(f"{BASE}/cgi-bin/management/manaRequest.cgi") + r".*")
CS_LIST = f"{BASE}/container-station/api/v3/containers"
CS_ACTION = f"{CS_LIST}/docker/container/stop"
SECRETS = (SID, PASSWORD, base64.b64encode(PASSWORD.encode()).decode())
INFO = SystemInfo("TS-test", "NAS", "serial", "test-version", 1)
OPTIONAL = (
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


@pytest.fixture
async def client():
    instance = QnapClient("192.0.2.1", 8080, "user", PASSWORD)
    yield instance
    # Avoid unmocked logout requests in teardown.
    instance._sid = None
    await instance.close()


def assert_no_secrets(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


async def test_login_logs_without_credentials(client, caplog):
    with caplog.at_level(logging.DEBUG), aioresponses() as responses:
        responses.post(LOGIN, body=LOGIN_OK)
        await client.login()
    assert client._sid == SID
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize(
    "body, error",
    [
        ("<QDocRoot><authPassed>0</authPassed></QDocRoot>", QnapAuthError),
        ("<QDocRoot><authPassed>1</authPassed></QDocRoot>", QnapAuthError),
        (f"not XML: {SID} {PASSWORD}", QnapAPIError),
        ("<QDocRoot/>", QnapAPIError),
    ],
)
async def test_failed_login_discards_previous_session(client, body, error):
    client._sid = "previous-session"
    with aioresponses() as responses:
        responses.post(LOGIN, body=body)
        with pytest.raises(error) as caught:
            await client.login()
    assert client._sid is None
    assert_no_secrets("".join(traceback.format_exception(caught.value)))


async def test_failed_context_entry_closes_owned_session(client):
    with aioresponses() as responses:
        responses.post(LOGIN, status=401)
        with pytest.raises(QnapAuthError):
            async with client:
                pytest.fail("Failed login must not enter context")
    assert client._session is None
    assert client._sid is None


async def test_close_is_idempotent_and_logs_out(client):
    with aioresponses() as responses:
        responses.post(LOGIN, body=LOGIN_OK)
        responses.get(re.compile(re.escape(LOGIN) + r".*"), body="<QDocRoot/>")
        await client.login()
        owned = client._session
        await client.close()
        await client.close()
    assert owned.closed
    assert client._session is None
    assert client._sid is None
    assert sum(len(calls) for calls in responses.requests.values()) == 2


@pytest.mark.parametrize("login_status", [200, 401])
async def test_supplied_session_is_preserved(login_status, caplog):
    async with aiohttp.ClientSession() as session:
        instance = QnapClient("192.0.2.1", 8080, "user", PASSWORD, session=session)
        with caplog.at_level(logging.DEBUG), aioresponses() as responses:
            responses.post(LOGIN, body=LOGIN_OK, status=login_status)
            if login_status == 200:
                await instance.login()
                responses.get(re.compile(re.escape(LOGIN) + r".*"), status=503)
                await instance.close()
            else:
                with pytest.raises(QnapAuthError):
                    await instance.__aenter__()
            await instance.close()
        assert not session.closed
        assert instance._sid is None
        assert_no_secrets(caplog.text)


@pytest.mark.parametrize("operation", ["login", "read", "cs_list", "cs_action"])
@pytest.mark.parametrize(
    "status, error",
    [
        (401, QnapAuthError),
        (403, QnapPermissionError),
        (404, QnapAPIError),
        (500, QnapAPIError),
        (302, QnapAPIError),
    ],
)
async def test_http_failures_are_typed_and_sanitized(client, operation, status, error):
    client._sid = SID
    cs = ContainerStationClient(client)
    calls = {
        "login": ("POST", LOGIN, client.login),
        "read": ("GET", READ, client.get_system_info),
        "cs_list": ("GET", CS_LIST, cs.get_containers),
        "cs_action": ("POST", CS_ACTION, lambda: cs.stop_container("container")),
    }
    method, url, call = calls[operation]
    with aioresponses() as responses:
        responses.add(url, method=method, status=status, body=f"{SID} {PASSWORD}")
        with pytest.raises(error) as caught:
            await call()
    assert_no_secrets("".join(traceback.format_exception(caught.value)))
    assert sum(len(requests) for requests in responses.requests.values()) == 1
    if operation == "login" or (status == 401 and operation == "read"):
        assert client._sid is None
    else:
        assert client._sid == SID


def response_error():
    return aiohttp.ClientResponseError(
        SimpleNamespace(real_url=URL(f"{BASE}/?sid={SID}")),
        (),
        status=500,
        message=PASSWORD,
        headers={"Authorization": f"Bearer {SID}"},
    )


@pytest.mark.parametrize(
    "factory, error",
    [
        (lambda: aiohttp.ServerDisconnectedError(SID), QnapConnectionError),
        (lambda: aiohttp.ClientPayloadError(PASSWORD), QnapConnectionError),
        (lambda: aiohttp.ClientConnectionError(SID), QnapConnectionError),
        (lambda: asyncio.TimeoutError(PASSWORD), QnapTimeoutError),
        (response_error, QnapAPIError),
        (
            lambda: UnicodeDecodeError("utf-8", PASSWORD.encode(), 0, 1, "bad data"),
            QnapAPIError,
        ),
    ],
)
@pytest.mark.parametrize("operation", ["read", "cs_action"])
async def test_transport_failures_are_safe_and_never_retried(
    client, factory, error, operation
):
    client._sid = SID
    with aioresponses() as responses:
        if operation == "read":
            responses.get(READ, exception=factory())
            call = client.get_system_info
        else:
            responses.post(CS_ACTION, exception=factory())

            async def call():
                await ContainerStationClient(client).stop_container("container")

        with pytest.raises(error) as caught:
            await call()
    assert caught.value.__cause__ is None
    assert_no_secrets("".join(traceback.format_exception(caught.value)))
    assert sum(len(requests) for requests in responses.requests.values()) == 1


async def test_external_session_receives_timeout_ssl_and_no_redirects():
    async with aiohttp.ClientSession() as session:
        instance = QnapClient(
            "192.0.2.1",
            8080,
            "user",
            PASSWORD,
            timeout=3,
            verify_ssl=False,
            session=session,
        )
        with aioresponses() as responses:
            responses.post(LOGIN, body=LOGIN_OK)
            await instance.login()
            request = next(iter(responses.requests.values()))[0]
            assert request.kwargs["timeout"].total == 3
            assert request.kwargs["ssl"] is False
            assert request.kwargs["allow_redirects"] is False
            instance._sid = None
            await instance.close()


@pytest.mark.parametrize(
    "error", [QnapConnectionError("offline"), QnapAuthError("expired")]
)
async def test_get_all_propagates_required_system_failure(client, error):
    with patch.object(client, "get_system_info", AsyncMock(side_effect=error)):
        patches = [
            patch.object(client, name, AsyncMock(return_value=[])) for name in OPTIONAL
        ]
        for item in patches:
            item.start()
        try:
            with pytest.raises(type(error)):
                await client.get_all()
        finally:
            for item in patches:
                item.stop()


async def test_get_all_retains_optional_failure_defaults_without_logging_details(
    client, caplog
):
    with patch.object(client, "get_system_info", AsyncMock(return_value=INFO)):
        patches = [
            patch.object(
                client, name, AsyncMock(side_effect=QnapAPIError(f"{SID} {PASSWORD}"))
            )
            for name in OPTIONAL
        ]
        for item in patches:
            item.start()
        try:
            with caplog.at_level(logging.WARNING):
                data = await client.get_all()
        finally:
            for item in patches:
                item.stop()
    assert data.system_info is INFO
    assert data.network_interfaces == []
    assert data.firmware is None
    assert "QnapAPIError" in caplog.text
    assert_no_secrets(caplog.text)


async def test_container_list_and_action_keep_existing_behavior(client):
    client._sid = SID
    cs = ContainerStationClient(client)
    with aioresponses() as responses:
        responses.get(
            CS_LIST,
            payload={
                "data": {
                    "items": [
                        {
                            "id": "container",
                            "name": "web",
                            "status": "running",
                            "image": "test",
                        },
                    ]
                }
            },
        )
        responses.post(CS_ACTION, status=204)
        containers = await cs.get_containers()
        await cs.stop_container(containers[0].id)
    assert containers[0].state == "running"
    assert containers[0].name == "web"


async def test_container_invalid_json_is_sanitized(client):
    client._sid = SID
    with aioresponses() as responses:
        responses.get(CS_LIST, body=f"invalid JSON {SID} {PASSWORD}")
        with pytest.raises(QnapAPIError) as caught:
            await ContainerStationClient(client).get_containers()
    assert_no_secrets("".join(traceback.format_exception(caught.value)))


async def test_offline_close_does_not_make_network_requests(client):
    client._sid = SID
    session = await client._ensure_session()
    with patch.object(session, "request", side_effect=AssertionError("Network I/O")):
        await client.close(logout=False)
        await client.close(logout=False)
    assert session.closed
    assert client._sid is None


async def test_invalid_optional_values_do_not_leak_into_debug_logs(client, caplog):
    with patch.object(
        client,
        "_get",
        AsyncMock(
            side_effect=[
                f"<QDocRoot><net><eth0><rx>{PASSWORD}</rx></eth0></net></QDocRoot>",
                "<QDocRoot><func><ownContent><root><nic_cnt>0</nic_cnt></root></ownContent></func></QDocRoot>",
            ]
        ),
    ):
        with caplog.at_level(logging.DEBUG):
            assert await client.get_network_interfaces() == []
    assert "ValueError" in caplog.text
    assert_no_secrets(caplog.text)


@pytest.mark.parametrize("operation", ["list", "action"])
async def test_container_auth_failure_keeps_qts_monitoring_session(client, operation):
    client._sid = SID
    cs = ContainerStationClient(client)
    with aioresponses() as responses:
        if operation == "list":
            responses.get(CS_LIST, status=401)
            call = cs.get_containers
        else:
            responses.post(CS_ACTION, status=401)

            async def call():
                await cs.stop_container("container")

        with pytest.raises(QnapAuthError):
            await call()
        assert client._sid == SID
        responses.get(
            READ, body="<QDocRoot><hostname>Still online</hostname></QDocRoot>"
        )
        assert (await client.get_system_info()).name == "Still online"
        assert client._sid == SID
