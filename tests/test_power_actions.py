"""Synthetic HTTP responses verify transport only, without contacting a NAS."""

from __future__ import annotations

import asyncio
import traceback

import pytest
from aiohttp import ClientTimeout, web

from qnap_client import (
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapPermissionError,
    QnapPowerOutcomeUnknown,
)

SID = "secret-test-sid"
PASSWORD = "secret-test-password"
LOGIN_OK = f"<QDocRoot><authPassed>1</authPassed><authSid>{SID}</authSid></QDocRoot>"


@pytest.fixture
async def server(unused_tcp_port):
    state = {
        "body": b"",
        "status": 200,
        "drop": False,
        "started": asyncio.Event(),
        "release": None,
        "calls": [],
    }

    async def handle(request):
        state["calls"].append((request.method, request.path, dict(request.query)))
        if request.path.endswith("authLogin.cgi"):
            return web.Response(text=LOGIN_OK)
        if request.path.endswith("sysRequest.cgi") and request.method == "POST":
            assert await request.read() == b""
            state["started"].set()
            if state["release"] is not None:
                await state["release"].wait()
            if state["drop"]:
                request.transport.close()
                return web.Response()
            return web.Response(
                status=state["status"],
                body=state["body"],
                content_type="text/xml",
                charset="utf-8",
                headers={"Location": "/redirect-target"},
            )
        return web.Response(status=404)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
        yield unused_tcp_port, state
    finally:
        await runner.cleanup()


def assert_safe_exception(error):
    rendered = "".join(traceback.format_exception(error))
    assert SID not in rendered
    assert PASSWORD not in rendered


@pytest.mark.parametrize(
    "method,apply", [("shutdown", "shutdown"), ("reboot", "restart")]
)
async def test_power_action_sends_exactly_one_qts_post_without_logout(
    server, method, apply
):
    port, state = server
    async with QnapClient("127.0.0.1", port, "user", PASSWORD) as client:
        with pytest.raises(QnapPowerOutcomeUnknown):
            await getattr(client, method)()
        assert client._sid is None

    assert state["calls"] == [
        ("POST", "/cgi-bin/authLogin.cgi", {}),
        (
            "POST",
            "/cgi-bin/sys/sysRequest.cgi",
            {"sid": SID, "subfunc": "power_mgmt", "apply": apply},
        ),
    ]


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<QDocRoot/>",
        b"<html><body>login</body></html>",
        b"<QDocRoot><authPassed>1</authPassed></QDocRoot>",
        b"<QDocRoot><authPassed>0</authPassed></QDocRoot>",
        b"<QDocRoot><PermissionDeny>1</PermissionDeny></QDocRoot>",
        b"<QDocRoot><errorValue>-1</errorValue></QDocRoot>",
        b"<QDocRoot><errorValue>-2</errorValue></QDocRoot>",
        b"invalid XML " + SID.encode(),
        b"\xff",
    ],
)
async def test_unverified_response_never_reports_success_or_guesses_error_meaning(
    server, body
):
    port, state = server
    state["body"] = body
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await client.shutdown()
        assert_safe_exception(caught.value)
        assert client._sid is None
        await client.close()
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize(
    "status,error",
    [
        (401, QnapAuthError),
        (403, QnapPermissionError),
        (404, QnapAPIError),
        (405, QnapAPIError),
        (302, QnapPowerOutcomeUnknown),
        (500, QnapPowerOutcomeUnknown),
        (503, QnapPowerOutcomeUnknown),
    ],
)
async def test_http_errors_never_follow_redirect_retry_or_logout(server, status, error):
    port, state = server
    state["status"] = status
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(error) as caught:
            await client.reboot()
        assert_safe_exception(caught.value)
        if status in {404, 405}:
            assert caught.value.http_status == status
        assert client._sid is None
        await client.close()
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


async def test_server_disconnect_after_receiving_post_has_unknown_outcome(server):
    port, state = server
    state["drop"] = True
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await client.shutdown()
        assert_safe_exception(caught.value)
        assert client._sid is None
        await client.close()
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


async def test_timeout_after_receiving_post_has_unknown_outcome(server):
    port, state = server
    state["release"] = asyncio.Event()
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        client._timeout = ClientTimeout(total=1)
        with pytest.raises(QnapPowerOutcomeUnknown):
            await client.shutdown()
        assert state["started"].is_set()
        assert client._sid is None
        await client.close()
        assert len(state["calls"]) == 2
    finally:
        state["release"].set()
        await client.close(logout=False)


async def test_cancellation_after_post_does_not_retry_or_logout(server):
    port, state = server
    state["release"] = asyncio.Event()
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        task = asyncio.create_task(client.shutdown())
        await asyncio.wait_for(state["started"].wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client._sid is None
        await client.close()
        assert len(state["calls"]) == 2
    finally:
        state["release"].set()
        await client.close(logout=False)


async def test_concurrent_power_requests_send_only_one_post(server):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        results = await asyncio.gather(
            client.shutdown(), client.reboot(), return_exceptions=True
        )
        assert isinstance(results[0], QnapPowerOutcomeUnknown)
        assert isinstance(results[1], QnapAuthError)
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


async def test_power_action_requires_login_before_any_request(server):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    with pytest.raises(QnapAuthError):
        await client.shutdown()
    assert state["calls"] == []
    await client.close(logout=False)
