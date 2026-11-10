"""qnap-client — Async Python client for QNAP NAS."""

from __future__ import annotations

from .client import QnapClient
from .container_station import ContainerStationClient
from .exceptions import (
    QnapAPIError,
    QnapAuthError,
    QnapConnectionError,
    QnapError,
    QnapPermissionError,
    QnapTimeoutError,
)
from .models import (
    Container,
    CpuStats,
    DriveHealth,
    ExternalDrive,
    FanStatus,
    FirmwareUpdate,
    MemoryStats,
    NasData,
    NetworkInterface,
    SystemHealth,
    SystemInfo,
    VolumeStats,
)

__version__ = "1.1.1"

__all__ = [
    "QnapClient",
    "ContainerStationClient",
    # Exceptions
    "QnapError",
    "QnapPermissionError",
    "QnapAuthError",
    "QnapConnectionError",
    "QnapTimeoutError",
    "QnapAPIError",
    # Models
    "SystemInfo",
    "SystemHealth",
    "CpuStats",
    "MemoryStats",
    "NetworkInterface",
    "DriveHealth",
    "VolumeStats",
    "FirmwareUpdate",
    "FanStatus",
    "ExternalDrive",
    "Container",
    "NasData",
    # Version
    "__version__",
]
