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
| `get_all()` | `NasData` | All of the above in parallel |
| `shutdown()` | `None` | Request safe QTS shutdown, returning after CGI acknowledgement |
| `reboot()` | `None` | Request safe QTS restart, returning after CGI acknowledgement |

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
| `QnapAuthError` | Bad credentials or session expired |
| `QnapTwoStepRequiredError` | QTS requests a second login factor unsupported by this password-only client |
| `QnapPermissionError` | Request forbidden by HTTP 403 |
| `QnapConnectionError` | NAS unreachable |
| `QnapTimeoutError` | Request timed out |
| `QnapAPIError` | Unexpected or malformed API response |
| `QnapPowerOutcomeUnknown` | A power request may have executed |
| `QnapPowerRejectedError` | QTS reports a negative setting result or ambiguous session/permission rejection |

## Shutdown and reboot

The power methods follow the single authenticated POST used by the TS-431P
QTS 5.2.11.3661 web client. `shutdown()` uses `apply=shutdown` and `reboot()`
uses `apply=restart` with `subfunc=power_mgmt` at
`/cgi-bin/sys/sysRequest.cgi`.

```python
from qnap_client import QnapClient

async def request_shutdown(host, port, username, password, *, verify_ssl=True):
    async with QnapClient(
        host, port, username, password, ssl=True, verify_ssl=verify_ssl
    ) as client:
        await client.shutdown()
```

Use `await client.reboot()` to request a restart. Each power request respects
the existing `ssl` and `verify_ssl` constructor options.
An owned HTTP session verifies certificates by default. A supplied session
retains its connector's TLS context, including any custom CA policy, while
`verify_ssl=False` explicitly disables verification for these requests.

The classifier recognizes unique direct `authPassed=1` and `setting_result=0`
under `QDocRoot` as nominal CGI acceptance. This contract comes from static
inspection of the official QTS 5.2.11.3661 backend. Returning `None` acknowledges
the request independently of physical completion. HTTP 200 or `authPassed=1`
alone leaves acceptance unknown.

Negative CGI results raise `QnapPowerRejectedError`. Its safe `reason` separates
`setting_failed` from `authentication_or_permission`, whose causes share one
server response. Unexpected responses, server errors and connection loss raise
`QnapPowerOutcomeUnknown` with a safe `reason` and available `http_status`.
Observe the device after an uncertain outcome. Each method sends one POST and
clears its local SID afterward so closing the client sends no logout request
while QTS may be going offline. Cancellation propagates with the same outcome
uncertainty.

Further API calls require authentication again. The public `login()` performs
password authentication and raises `QnapTwoStepRequiredError` when QTS requests
another factor. The interactive password/TOTP adapter used for the hardware
trials belongs to separate test infrastructure. General MFA, persistent
credentials and session renewal remain separate contributions. The public power
methods use the session established by the library's existing login flow.

The UI's optional warning checks are separate from the final QTS action. Missing
preflight items do not establish inactive services. See the
[firmware and device evidence](docs/power-api-evidence.md).

Tests use loopback servers and explicitly reconstructed responses. The owner
validated one physical shutdown and subsequent WOL power-on on a TS-431P with
QTS 5.2.11.3661. Its full response was unavailable. One subsequent reboot
returned the recognized CGI acknowledgement and was followed by a remotely
observed interval of unavailability and restored access. Its duration was
unmeasured. Post-reboot uptime and physical inspection were unrecorded. The
owner considered the trials satisfactory and closed this validation round.
Evidence is limited to that model and firmware. Minimum permissions, other
models and QuTS hero remain unverified.

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
