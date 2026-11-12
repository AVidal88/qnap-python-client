"""Exceptions for the qnap-client library."""

from __future__ import annotations

from typing import Literal


class QnapError(Exception):
    """Base exception for all qnap-client errors."""


class QnapAuthError(QnapError):
    """Authentication failed — bad credentials or session expired."""


class QnapTwoStepRequiredError(QnapAuthError):
    """The account requires a second login factor unsupported by this client."""


class QnapPermissionError(QnapError):
    """The authenticated account lacks permission for the request."""


class QnapPowerRejectedError(QnapError):
    """QTS explicitly rejected a power request."""

    def __init__(
        self,
        message: str,
        *,
        reason: Literal["authentication_or_permission", "setting_failed"],
    ) -> None:
        super().__init__(message)
        self.reason = reason


class QnapConnectionError(QnapError):
    """Could not connect to the NAS."""


class QnapTimeoutError(QnapError):
    """Request to the NAS timed out."""


class QnapAPIError(QnapError):
    """NAS returned an unexpected or malformed response."""

    def __init__(self, *args: object, http_status: int | None = None) -> None:
        super().__init__(*args)
        self.http_status = http_status


class QnapPowerOutcomeUnknown(QnapError):
    """A power request may have been accepted; do not retry it automatically."""

    def __init__(
        self,
        message: str,
        *,
        reason: Literal[
            "connection_failure",
            "timeout",
            "http_response",
            "invalid_response",
            "empty_response",
            "unexpected_document",
            "unrecognized_response",
        ] = "unrecognized_response",
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.http_status = http_status
