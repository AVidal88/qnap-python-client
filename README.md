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
| `close(logout=True)` | `None` | Release an owned HTTP session, optionally without a logout request |
| `get_system_info()` | `SystemInfo` | CPU, memory, firmware version, uptime |
| `get_system_health()` | `SystemHealth` | Overall health status string |
| `get_network_interfaces()` | `list[NetworkInterface]` | Per-interface RX/TX rates |
| `get_drive_health()` | `list[DriveHealth]` | S.M.A.R.T. status + temperature per drive |
| `get_volumes()` | `list[VolumeStats]` | Storage volume usage |
| `get_firmware_update()` | `FirmwareUpdate` | Current + latest firmware version |
| `get_fans()` | `list[FanStatus]` | Fan speed RPM (empty list if unsupported) |
| `get_external_drives()` | `list[ExternalDrive]` | External USB/eSATA drives |
| `get_all()` | `NasData` | Parallel reads, with system information required for a successful refresh |
| `shutdown()` | `None` | Draft QTS shutdown request, currently reports an unverified outcome |
| `reboot()` | `None` | Draft QTS restart request, currently reports an unverified outcome |

`get_all()` propagates a failed system-information read so an unreachable NAS
can be reported as unavailable. Optional section failures retain their existing
defaults and log the exception type.

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
| `NetworkInterface` | `name`, `mac`, `ip`, `mask`, `link_status`, `max_speed`, RX/TX rates and packet counts |
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
| `QnapAuthError` | Bad credentials or session expired |
| `QnapTwoStepRequiredError` | QTS requires a second login factor; password-only login cannot complete it |
| `QnapPermissionError` | Request forbidden by HTTP 403 |
| `QnapConnectionError` | NAS unreachable |
| `QnapTimeoutError` | Request timed out |
| `QnapAPIError` | Unexpected or malformed API response |
| `QnapPowerOutcomeUnknown` | A power request may have been accepted; never retry automatically |

## Power actions — validation pending

`shutdown()` and `reboot()` send real power commands using the request found in
the TS-431P-family QTS 5.2.11.3661 web client. Each sends one authenticated POST
to `/cgi-bin/sys/sysRequest.cgi` with `subfunc=power_mgmt` and `apply=shutdown`
or `apply=restart`.

**This draft raises `QnapPowerOutcomeUnknown` after every HTTP 2xx response.**
The power CGI's acceptance response has yet to be established on a physical
NAS. Empty bodies, XML, and authentication-endpoint markers cannot currently
establish acceptance. A future validated response contract can enable a normal
return. The methods are pending device validation before release.

HTTP 401 and 403 raise authentication and permission errors. Other HTTP 4xx
responses raise `QnapAPIError` with a numeric `http_status` attribute. Connection
loss, timeout, redirects, HTTP 5xx, and undecodable responses after starting the
POST report an unknown outcome. Cancellation propagates with the same outcome
uncertainty. Every attempted POST clears the local SID so context exit can close
the client while QTS goes offline. Callers must observe the NAS state before
any further action and must never retry a power command automatically.

The QTS web UI has separate service warnings and checks for running jobs,
iSCSI, High Availability, and Live Migration. These draft methods do not run
those UI checks. Their response schemas and applicable models still require
device evidence. QuTS hero compatibility is also pending. See the
[firmware evidence and device validation plan](docs/power-api-evidence.md).

The tests use synthetic loopback responses to verify request shape, single
submission, error handling, and session cleanup. Device compatibility remains
pending.

Password-only login cannot complete QTS two-step verification. If the login
response contains `need_2sv=1` or `need_2_step_verification=1`, the client raises
`QnapTwoStepRequiredError` without retrying. This recognizes documented QTS
challenge flags; it does not implement a second-factor flow.

## HTTPS / Self-Signed Certificates

```python
client = QnapClient("nas.local", 443, "admin", "password", ssl=True, verify_ssl=False)
```

## Home Assistant Integration

This library is the backing library for the [QNAP NAS Integration for Home Assistant](https://github.com/disforw/qnap).

## Contributing

PRs welcome. If your QNAP model returns unexpected data, include the model,
firmware version, and a sanitized response sample in an issue. Remove passwords,
SIDs, tokens, cookies, and identifying device details before sharing it.

## License

MIT
