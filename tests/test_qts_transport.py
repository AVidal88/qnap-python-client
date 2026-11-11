"""Synthetic transport checks; these do not establish a QTS power API contract."""

from __future__ import annotations

import base64
import logging
import traceback
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web

from qnap_client import (
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapConnectionError,
    QnapPermissionError,
    QnapTimeoutError,
)

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
    state = {"login_status": 200, "login_body": LOGIN_OK, "status": 200, "calls": []}

    async def handle(request):
        state["calls"].append((request.method, request.path, dict(request.query)))
        if request.path.endswith("authLogin.cgi"):
            return web.Response(status=state["login_status"], text=state["login_body"])
        if state["status"] == 302:
            return web.Response(status=302, headers={"Location": "/redirect-target"})
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
