"""Exceptions for the qnap-client library."""

from __future__ import annotations


class QnapError(Exception):
    """Base exception for all qnap-client errors."""


class QnapAuthError(QnapError):
    """Authentication failed — bad credentials or session expired."""


class QnapTwoStepRequiredError(QnapAuthError):
    """The account requires a second login factor unsupported by this client."""


class QnapPermissionError(QnapError):
    """The authenticated account lacks permission for the request."""


class QnapConnectionError(QnapError):
    """Could not connect to the NAS."""


class QnapTimeoutError(QnapError):
    """Request to the NAS timed out."""


class QnapAPIError(QnapError):
    """NAS returned an unexpected or malformed response."""


class QnapPowerBlockedError(QnapError):
    """QTS reports work that must finish before shutdown or reboot."""


class QnapPowerOutcomeUnknown(QnapError):
    """A power request may have been accepted; do not retry it automatically."""
