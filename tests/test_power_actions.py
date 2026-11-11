"""Synthetic QTS power fixtures; no physical NAS or firmware response is used."""

from __future__ import annotations

import asyncio
import traceback
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web

from qnap_client import (
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapPermissionError,
    QnapPowerBlockedError,
    QnapPowerOutcomeUnknown,
)

SID = "secret-test-sid"
PASSWORD = "secret-test-password"
LOGIN_OK = f"<QDocRoot><authPassed>1</authPassed><authSid>{SID}</authSid></QDocRoot>"
BLOCKERS = ("Rsync", "VMs", "RTRR", "ssd_cache_upgrading")


def preflight_xml(active: str | None = None) -> str:
    items = "".join(
        f"<item><name>{name}</name><status>{int(name == active)}</status></item>"
        for name in BLOCKERS
    )
    return f"<QDocRoot>{items}</QDocRoot>"


@pytest.fixture
async def server(unused_tcp_port):
    state = {
        "preflight_body": preflight_xml(),
        "preflight_status": 200,
        "post_body": "",
        "post_status": 200,
        "drop_post": False,
        "calls": [],
    }

    async def handle(request):
        state["calls"].append((request.method, request.path, dict(request.query)))
        if request.path.endswith("authLogin.cgi"):
            return web.Response(text=LOGIN_OK)
        if request.path.endswith("sysRequest.cgi") and request.method == "GET":
            return web.Response(
                status=state["preflight_status"], text=state["preflight_body"]
            )
        if request.path.endswith("sysRequest.cgi") and request.method == "POST":
            if started := state.get("post_started"):
                started.set()
            if release := state.get("post_release"):
                await release.wait()
            if state["drop_post"]:
                request.transport.close()
                return web.Response(text="response cannot be delivered")
            return web.Response(status=state["post_status"], text=state["post_body"])
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


def power_calls(state):
    return [
        call for call in state["calls"] if call[1].endswith("sysRequest.cgi")
    ]


@pytest.mark.parametrize("method,apply", [("shutdown", "shutdown"), ("reboot", "restart")])
async def test_power_action_uses_qts_route_once_without_logout(server, method, apply):
    port, state = server
    async with QnapClient("127.0.0.1", port, "user", PASSWORD) as client:
        await getattr(client, method)()
        assert client._sid is None

    assert [call[0] for call in state["calls"]] == ["POST", "GET", "POST"]
    preflight, action = power_calls(state)
    assert preflight == (
        "GET",
        "/cgi-bin/sys/sysRequest.cgi",
        {"subfunc": "power_mgmt", "apply": "chk_shutdown_running", "sid": SID},
    )
    assert action == (
        "POST",
        "/cgi-bin/sys/sysRequest.cgi",
        {"sid": SID, "subfunc": "power_mgmt", "apply": apply},
    )


@pytest.mark.parametrize("active", BLOCKERS)
async def test_running_work_blocks_power_post(server, active):
    port, state = server
    state["preflight_body"] = preflight_xml(active)
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapPowerBlockedError) as caught:
            await client.shutdown()
        assert active in str(caught.value)
        assert client._sid == SID
        assert [call[0] for call in power_calls(state)] == ["GET"]
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<QDocRoot>",
        "<QDocRoot/>",
        "<QDocRoot><item><name>unknown</name><status>0</status></item></QDocRoot>",
        "<QDocRoot><item><name>Rsync</name><status>maybe</status></item></QDocRoot>",
        "<QDocRoot><item><name>Rsync</name><status>0</status></item></QDocRoot>",
        preflight_xml().replace("<name>VMs</name>", "<name>Rsync</name>"),
    ],
)
async def test_ambiguous_preflight_never_sends_power_post(server, body):
    port, state = server
    state["preflight_body"] = body
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapAPIError):
            await client.reboot()
        assert [call[0] for call in power_calls(state)] == ["GET"]
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize(
    "marker,error",
    [
        ("<authPassed>0</authPassed>", QnapAPIError),
        ("<PermissionDeny>1</PermissionDeny>", QnapPermissionError),
        ("<errorValue>-2</errorValue>", QnapPermissionError),
        (
            "<authPassed>0</authPassed><PermissionDeny>1</PermissionDeny>",
            QnapPermissionError,
        ),
        (
            "<authPassed>0</authPassed><errorValue>-2</errorValue>",
            QnapPermissionError,
        ),
    ],
)
@pytest.mark.parametrize("phase", ["preflight", "post"])
async def test_explicit_xml_rejection_is_typed_and_never_retried(
    server, marker, error, phase
):
    port, state = server
    if phase == "preflight":
        state["preflight_body"] = f"<QDocRoot>{marker}</QDocRoot>"
    else:
        state["post_body"] = f"<QDocRoot>{marker}</QDocRoot>"
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(error) as caught:
            await client.shutdown()
        assert SID not in "".join(traceback.format_exception(caught.value))
        assert PASSWORD not in "".join(traceback.format_exception(caught.value))
        assert [call[0] for call in power_calls(state)] == (
            ["GET"] if phase == "preflight" else ["GET", "POST"]
        )
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize(
    "status,error",
    [
        (401, QnapAuthError),
        (403, QnapPermissionError),
        (302, QnapAPIError),
        (404, QnapAPIError),
        (500, QnapAPIError),
    ],
)
async def test_http_rejection_does_not_retry_or_logout(server, status, error):
    port, state = server
    state["post_status"] = status
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(error):
            await client.reboot()
        assert [call[0] for call in power_calls(state)] == ["GET", "POST"]
        assert client._sid is None
        await client.close()
        assert [call[0] for call in state["calls"]] == ["POST", "GET", "POST"]
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize(
    "failure", [aiohttp.ServerDisconnectedError(SID), TimeoutError(PASSWORD)]
)
async def test_disconnection_after_post_is_unknown_and_never_retried(server, failure):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    await client.login()
    session = client._session
    original_request = session.request

    def intercept(method, url, **kwargs):
        if method == "POST" and url.endswith("/cgi-bin/sys/sysRequest.cgi"):
            raise failure
        return original_request(method, url, **kwargs)

    try:
        with patch.object(session, "request", side_effect=intercept) as request:
            with pytest.raises(QnapPowerOutcomeUnknown) as caught:
                await client.shutdown()
            assert sum(
                call.args[0] == "POST"
                and call.args[1].endswith("/cgi-bin/sys/sysRequest.cgi")
                for call in request.call_args_list
            ) == 1
        assert client._sid is None
        assert SID not in "".join(traceback.format_exception(caught.value))
        assert PASSWORD not in "".join(traceback.format_exception(caught.value))
        await client.close()
        assert [call[0] for call in state["calls"]] == ["POST", "GET"]
    finally:
        await client.close(logout=False)


async def test_unparseable_response_after_post_has_unknown_outcome(server):
    port, state = server
    state["post_body"] = f"unrecognized response {SID}"
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await client.shutdown()
        assert [call[0] for call in power_calls(state)] == ["GET", "POST"]
        assert client._sid is None
        assert SID not in "".join(traceback.format_exception(caught.value))
    finally:
        await client.close(logout=False)


async def test_server_disconnect_after_receiving_post_has_unknown_outcome(server):
    port, state = server
    state["drop_post"] = True
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await client.shutdown()
        assert caught.value.__cause__ is None
        assert client._sid is None
        assert [call[0] for call in power_calls(state)] == ["GET", "POST"]
        await client.close()
        assert [call[0] for call in state["calls"]] == ["POST", "GET", "POST"]
    finally:
        await client.close(logout=False)


async def test_cancellation_after_post_does_not_retry_or_logout(server):
    port, state = server
    state["post_started"] = asyncio.Event()
    state["post_release"] = asyncio.Event()
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        task = asyncio.create_task(client.shutdown())
        await asyncio.wait_for(state["post_started"].wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client._sid is None
        await client.close()
        assert [call[0] for call in state["calls"]] == ["POST", "GET", "POST"]
    finally:
        state["post_release"].set()
        await client.close(logout=False)


async def test_concurrent_power_requests_send_only_one_post(server):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        results = await asyncio.gather(
            client.shutdown(), client.reboot(), return_exceptions=True
        )
        assert results[0] is None
        assert isinstance(results[1], QnapAuthError)
        assert [call[0] for call in power_calls(state)] == ["GET", "POST"]
    finally:
        await client.close(logout=False)
