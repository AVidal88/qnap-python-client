"""Synthetic responses verify power classification and transport offline."""

from __future__ import annotations

import asyncio
import traceback
from unittest.mock import patch

import pytest
from aiohttp import ClientSession, ClientTimeout, web

from qnap_client import (
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapPermissionError,
    QnapPowerOutcomeUnknown,
    QnapPowerRejectedError,
)

SID = "secret-test-sid"
PASSWORD = "secret-test-password"
LOGIN_OK = f"<QDocRoot><authPassed>1</authPassed><authSid>{SID}</authSid></QDocRoot>"
# Reconstructed projection of the owner's shutdown summary. The unreported
# elements are omitted. This is not the complete XML or a captured NAS response.
SHUTDOWN_SUMMARY_PROJECTION = b"<QDocRoot><authPassed>1</authPassed></QDocRoot>"
# Reconstructed from the statically inspected firmware's XML emitters. General
# metadata is omitted. This acknowledgement was not captured from the NAS.
FIRMWARE_ACKNOWLEDGEMENT = (
    b'<QDocRoot version="1.0"><authPassed><![CDATA[1]]></authPassed>'
    b"<setting_result><![CDATA[0]]></setting_result></QDocRoot>"
)


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
    state["body"] = FIRMWARE_ACKNOWLEDGEMENT
    async with QnapClient("127.0.0.1", port, "user", PASSWORD) as client:
        assert await getattr(client, method)() is None
        assert client._sid is None

    assert state["calls"] == [
        ("POST", "/cgi-bin/authLogin.cgi", {}),
        (
            "POST",
            "/cgi-bin/sys/sysRequest.cgi",
            {"sid": SID, "subfunc": "power_mgmt", "apply": apply},
        ),
    ]


@pytest.mark.parametrize("method", ["shutdown", "reboot"])
@pytest.mark.parametrize("verify_ssl", [True, False])
@pytest.mark.parametrize("supplied_session", [False, True], ids=["owned", "supplied"])
async def test_power_methods_respect_tls_options_and_session_ownership(
    server, method, verify_ssl, supplied_session
):
    # HTTP loopback verifies the selected request/connector options. It does
    # not establish a real TLS handshake or certificate-verification result.
    port, state = server
    state["body"] = FIRMWARE_ACKNOWLEDGEMENT
    provided = ClientSession() if supplied_session else None
    client = QnapClient(
        "127.0.0.1",
        port,
        "user",
        PASSWORD,
        verify_ssl=verify_ssl,
        timeout=3,
        session=provided,
    )
    session = await client._ensure_session()
    connector = session.connector
    expected_connector_ssl = True if supplied_session else verify_ssl
    try:
        assert connector._ssl is expected_connector_ssl
        with patch.object(session, "request", wraps=session.request) as request:
            await client.login()
            assert await getattr(client, method)() is None
            assert request.call_count == 2
            for call in request.call_args_list:
                assert call.args[0] == "POST"
                assert call.kwargs["ssl"] is verify_ssl
                assert call.kwargs["allow_redirects"] is False
                assert call.kwargs["timeout"].total == 3
            assert client._sid is None
            await client.close()
            assert request.call_count == 2
        assert session.closed is (not supplied_session)
        if supplied_session:
            assert session.connector is connector
            assert connector._ssl is expected_connector_ssl
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)
        if provided is not None:
            await provided.close()


@pytest.mark.parametrize(
    "body,reason",
    [
        (b"", "empty_response"),
        (b"<QDocRoot/>", "unrecognized_response"),
        (b"<html><body>login</body></html>", "unexpected_document"),
        (
            b"<QDocRoot><PermissionDeny>1</PermissionDeny></QDocRoot>",
            "unrecognized_response",
        ),
        (b"<QDocRoot><errorValue>-1</errorValue></QDocRoot>", "unrecognized_response"),
        (b"<QDocRoot><errorValue>-2</errorValue></QDocRoot>", "unrecognized_response"),
        (
            b"<QDocRoot><authPassed>1</authPassed><success>1</success></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>0</authPassed><setting_result>0</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>0</authPassed><setting_result>-1</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result>1</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><setting_result>0</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><authPassed>1</authPassed><setting_result>0</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result>0</setting_result><setting_result>-1</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><response><setting_result>0</setting_result></response></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><response><authPassed>1</authPassed></response><setting_result>0</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result>0</setting_result><PermissionDeny>1</PermissionDeny></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result>0</setting_result><errorValue>-1</errorValue></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result value='0'>0</setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result><status>0</status></setting_result></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<QDocRoot xmlns:x='urn:synthetic'><authPassed>1</authPassed><setting_result>0</setting_result><x:authPassed>0</x:authPassed></QDocRoot>",
            "unrecognized_response",
        ),
        (
            b"<!DOCTYPE QDocRoot><QDocRoot><authPassed>1</authPassed><setting_result>0</setting_result></QDocRoot>",
            "invalid_response",
        ),
        (b"invalid XML " + SID.encode(), "invalid_response"),
        (b"\xff", "invalid_response"),
    ],
)
@pytest.mark.parametrize("method", ["shutdown", "reboot"])
async def test_unverified_response_never_reports_success_or_guesses_error_meaning(
    server, body, reason, method
):
    port, state = server
    state["body"] = body
    client = QnapClient("127.0.0.1", port, "user", PASSWORD)
    try:
        await client.login()
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await getattr(client, method)()
        assert caught.value.reason == reason
        assert_safe_exception(caught.value)
        assert client._sid is None
        await client.close()
        assert len(state["calls"]) == 2
    finally:
        await client.close(logout=False)


@pytest.mark.parametrize("method", ["shutdown", "reboot"])
async def test_reconstructed_shutdown_summary_does_not_establish_acknowledgement(
    server, method
):
    port, state = server
    state["body"] = SHUTDOWN_SUMMARY_PROJECTION
    async with QnapClient("127.0.0.1", port, "user", PASSWORD) as client:
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await getattr(client, method)()
        assert caught.value.reason == "unrecognized_response"
        assert_safe_exception(caught.value)
    assert len(state["calls"]) == 2


@pytest.mark.parametrize("method", ["shutdown", "reboot"])
@pytest.mark.parametrize(
    "body,reason",
    [
        (
            b"<QDocRoot><authPassed>0</authPassed></QDocRoot>",
            "authentication_or_permission",
        ),
        (
            b"<QDocRoot><authPassed>1</authPassed><setting_result>-1</setting_result></QDocRoot>",
            "setting_failed",
        ),
    ],
)
async def test_reconstructed_firmware_rejections_are_typed_and_not_retried(
    server, method, body, reason
):
    port, state = server
    state["body"] = body
    async with QnapClient("127.0.0.1", port, "user", PASSWORD) as client:
        with pytest.raises(QnapPowerRejectedError) as caught:
            await getattr(client, method)()
        assert caught.value.reason == reason
        assert_safe_exception(caught.value)
        assert client._sid is None
    assert len(state["calls"]) == 2


async def test_acknowledgement_with_active_mfa_flags_and_private_metadata(server):
    port, state = server
    state["body"] = (
        "<QDocRoot><authPassed> 1 </authPassed><need_2sv>1</need_2sv>"
        "<need_2_step_verification>1</need_2_step_verification>"
        f"<authSid>{SID}</authSid><user>{PASSWORD}</user>"
        "<setting_result> 0 </setting_result></QDocRoot>"
    ).encode()
    async with QnapClient("127.0.0.1", port, "user", PASSWORD) as client:
        assert await client.shutdown() is None
        assert client._sid is None
    assert len(state["calls"]) == 2


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
        if status in {302, 500, 503}:
            assert caught.value.reason == "http_response"
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
        assert caught.value.reason == "connection_failure"
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
        with pytest.raises(QnapPowerOutcomeUnknown) as caught:
            await client.shutdown()
        assert caught.value.reason == "timeout"
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
