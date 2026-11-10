# QNAP NAS Integration for Home Assistant

[![PyPI version](https://img.shields.io/pypi/v/qnap-client.svg)](https://pypi.org/project/qnap-client/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Async Python client for QNAP NAS. Replaces the unmaintained `python-qnapstats` with a fully async, `aiohttp`-based library with typed models, proper exception handling, Container Station support, and graceful handling of unexpected API responses.

## Why This Exists

`python-qnapstats` hasn't had a meaningful update in years. Fan sensor support and external drive support were added to the source repo but never published to PyPI. The library is synchronous, has no typed return values, and crashes on certain NAS models due to missing key handling.

This library fixes all of that.

## Installation

```bash
pip install qnap-client
```

## Quick Start

```python
import asyncio
from qnap_client import QnapClient

async def main():
    async with QnapClient("192.168.1.100", 8080, "admin", "password") as client:
        data = await client.get_all()
        print(f"NAS: {data.system_info.name} ({data.system_info.model})")
        print(f"CPU: {data.system_info.cpu_usage_percent:.1f}%")
        print(f"Health: {data.system_health.status}")
        for vol in data.volumes:
            used_pct = vol.used_bytes / vol.total_bytes * 100
            print(f"Volume {vol.name}: {used_pct:.1f}% used")
        if data.firmware_update.latest_version:
            print(f"Firmware update available: {data.firmware_update.latest_version}")

asyncio.run(main())
```

## API Reference

### `QnapClient`

```python
QnapClient(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    ssl: bool = False,
    verify_ssl: bool = True,
    timeout: int = 10,
    session: aiohttp.ClientSession | None = None,
)
```

| Method | Returns | Description |
|---|---|---|
| `login()` | `None` | Authenticate and store session ID |
| `logout()` | `None` | Log out and clear session |
| `close()` | `None` | Log out and close an owned HTTP session; leave a supplied session open |
| `get_system_info()` | `SystemInfo` | CPU, memory, firmware version, uptime |
| `get_system_health()` | `SystemHealth` | Overall health status string |
| `get_network_interfaces()` | `list[NetworkInterface]` | Per-interface RX/TX rates |
| `get_drive_health()` | `list[DriveHealth]` | S.M.A.R.T. status + temperature per drive |
| `get_volumes()` | `list[VolumeStats]` | Storage volume usage |
| `get_firmware_update()` | `FirmwareUpdate` | Current + latest firmware version |
| `get_fans()` | `list[FanStatus]` | Fan speed RPM (empty list if unsupported) |
| `get_external_drives()` | `list[ExternalDrive]` | External USB/eSATA drives |
| `get_all()` | `NasData` | All of the above in parallel |

### `ContainerStationClient`

```python
from qnap_client import ContainerStationClient

async with QnapClient(...) as client:
    cs = ContainerStationClient(client)
    containers = await cs.get_containers()
    await cs.stop_container(containers[0].id)
```

| Method | Returns | Description |
|---|---|---|
| `get_containers()` | `list[Container]` | All containers with id, name, status, image, type |
| `start_container(id, type)` | `None` | Start a container |
| `stop_container(id, type)` | `None` | Stop a container |
| `restart_container(id, type)` | `None` | Restart a container |
| `container_action(id, type, action)` | `None` | Generic action (start/stop/restart) |

### Models

| Model | Fields |
|---|---|
| `SystemInfo` | `name`, `model`, `serial_number`, `firmware_version`, `uptime_seconds`, `cpu_usage_percent`, `memory_total_mb`, `memory_free_mb`, `memory_used_mb` |
| `SystemHealth` | `status` |
| `NetworkInterface` | `name`, `mac`, `ip`, `rx_bytes_per_sec`, `tx_bytes_per_sec` |
| `DriveHealth` | `drive_number`, `model`, `health`, `temperature` |
| `VolumeStats` | `name`, `total_bytes`, `used_bytes`, `free_bytes`, `status` |
| `FirmwareUpdate` | `current_version`, `latest_version` (None = up to date) |
| `FanStatus` | `fan_number`, `speed_rpm` |
| `ExternalDrive` | `name`, `total_bytes`, `used_bytes`, `free_bytes` |
| `Container` | `id`, `name`, `status`, `image`, `type` |
| `NasData` | All of the above combined |

### Exceptions

| Exception | When |
|---|---|
| `QnapError` | Base exception |
| `QnapAuthError` | Bad credentials or session expired (HTTP 401) |
| `QnapPermissionError` | Request forbidden (HTTP 403) |
| `QnapConnectionError` | NAS unreachable |
| `QnapTimeoutError` | Request timed out |
| `QnapAPIError` | Unexpected or malformed API response |

## Transport and availability (unreleased 1.1.1)

Requests are sent once, with the configured timeout and SSL verification, including
when a caller supplies an HTTP session. Redirects are rejected to avoid forwarding
credentials. QTS HTTP 401 raises `QnapAuthError` and clears the SID. Container Station HTTP 401
raises the same error but preserves the QTS SID because its access checks can
differ from monitoring access. HTTP 403 raises
`QnapPermissionError`; other unsuccessful statuses raise `QnapAPIError`. Exception
messages and library logs exclude session IDs, credentials, response bodies, and
request URLs. XML authorization fields outside login are not interpreted as an
expired session because their meaning can depend on the endpoint and permissions.

`get_all()` requires a successful system-information request. Its failures propagate
so consumers can mark the NAS unavailable; optional sections still use defaults on
failure. These defaults do not prove that a firmware feature is unsupported.
Use the async context manager or call the idempotent `close()` method. Closing logs
out the current QTS session, but never closes a caller-supplied HTTP session.
Use `close(logout=False)` during offline unload to clear the local SID and close an
owned session without making a network request.

NAS shutdown and reboot are not implemented. No request/response contract has been
validated sufficiently for QTS 5.2 or QuTS hero. A disconnected request cannot prove
that a power operation succeeded. The regression fixtures are synthetic and do not
establish firmware compatibility. See the [QuTS hero report](https://github.com/disforw/python-qnap/issues/1)
for known parser limitations in existing monitoring functions.

Version 1.1.1 in this working branch is unreleased. Publish the library before a
Home Assistant integration pins `qnap-client==1.1.1`; local editable installs are
for development only.

Run `pip install -e ".[dev]"` and `pytest tests/ -v` for the synthetic regressions.
The dev extra temporarily limits aiohttp to `<3.14` because
[aioresponses 0.7.9 cannot construct responses for aiohttp 3.14](https://github.com/pnuckowski/aioresponses/issues/289).
This is a mock-tool limitation; the runtime dependency is not capped by this change.
In a separate environment, install `pip install -e . pytest pytest-asyncio` and run
`pytest tests/test_http.py -v` to check the transport with current aiohttp using a
local synthetic HTTP server, without aioresponses or a physical NAS.

## HTTPS / Self-Signed Certificates

```python
client = QnapClient("nas.local", 443, "admin", "password", ssl=True, verify_ssl=False)
```

## Home Assistant Integration

This library is the backing library for the [QNAP NAS Integration for Home Assistant](https://github.com/disforw/qnap).

## Contributing

PRs welcome. This library is actively maintained. If your QNAP model returns unexpected data, open an issue with the raw API response and we'll fix it.

## License

MIT
