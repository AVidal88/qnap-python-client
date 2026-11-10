"""Synthetic loopback HTTP checks independent of aioresponses internals.

These validate the HTTP transport only, not any QTS or QuTS firmware contract.
"""

from __future__ import annotations

import pytest
from aiohttp import web

from qnap_client import (
    ContainerStationClient,
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapPermissionError,
)


@pytest.fixture
async def server(unused_tcp_port):
    state = {"status": 200, "requests": []}

    async def handle(request):
        state["requests"].append((request.method, request.path))
        if request.path.endswith("authLogin.cgi"):
            return web.Response(
                text=(
                    "<QDocRoot><authPassed>1</authPassed>"
                    "<authSid>loopback-secret</authSid></QDocRoot>"
                )
            )
        if state["status"] != 200:
            return web.Response(status=state["status"], text="loopback-secret")
        if request.method == "POST":
            return web.Response(status=204)
        return web.Response(
            text=(
                "<QDocRoot><hostname>Test NAS</hostname>"
                "<serialNumber>synthetic</serialNumber></QDocRoot>"
            )
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


async def test_context_login_read_action_and_logout_over_http(server):
    port, state = server
    async with QnapClient("127.0.0.1", port, "user", "test-password") as client:
        assert (await client.get_system_info()).name == "Test NAS"
        await ContainerStationClient(client).stop_container("test")
    assert [method for method, _ in state["requests"]] == ["POST", "GET", "POST", "GET"]
    assert client._sid is None
    assert client._session is None


@pytest.mark.parametrize(
    "status, error",
    [
        (401, QnapAuthError),
        (403, QnapPermissionError),
        (503, QnapAPIError),
    ],
)
async def test_real_http_errors_are_safe_and_actions_sent_once(server, status, error):
    port, state = server
    client = QnapClient("127.0.0.1", port, "user", "test-password")
    try:
        await client.login()
        state["status"] = status
        with pytest.raises(error) as caught:
            await ContainerStationClient(client).stop_container("test")
        assert "loopback-secret" not in str(caught.value)
        assert len(state["requests"]) == 2
        state["status"] = 200
        assert (await client.get_system_info()).name == "Test NAS"
    finally:
        await client.close(logout=False)
