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
| `get_system_info()` | `SystemInfo` | CPU, memory, firmware version, uptime |
| `get_system_health()` | `SystemHealth` | Overall health status string |
| `get_network_interfaces()` | `list[NetworkInterface]` | Per-interface RX/TX rates |
| `get_drive_health()` | `list[DriveHealth]` | S.M.A.R.T. status + temperature per drive |
| `get_volumes()` | `list[VolumeStats]` | Storage volume usage |
| `get_firmware_update()` | `FirmwareUpdate` | Current + latest firmware version |
| `get_fans()` | `list[FanStatus]` | Fan speed RPM (empty list if unsupported) |
| `get_external_drives()` | `list[ExternalDrive]` | External USB/eSATA drives |
| `get_all()` | `NasData` | All of the above in parallel |
| `shutdown()` | `None` | Request QTS safe shutdown after a read-only running-work check |
| `reboot()` | `None` | Request QTS safe restart after a read-only running-work check |

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
| `QnapPermissionError` | Request forbidden (HTTP 403 or explicit QTS denial) |
| `QnapConnectionError` | NAS unreachable |
| `QnapTimeoutError` | Request timed out |
| `QnapAPIError` | Unexpected or malformed API response |
| `QnapPowerBlockedError` | QTS preflight reports running work |
| `QnapPowerOutcomeUnknown` | A power request may have been accepted; never retry automatically |

## Power actions — validation pending

`shutdown()` and `reboot()` send real QTS power commands. This draft follows the
frontend request shape found in QTS 5.2.11.3661 for the TS-431P family: a read-only GET to
`/cgi-bin/sys/sysRequest.cgi` with `subfunc=power_mgmt` and
`apply=chk_shutdown_running`, followed by one POST to the same CGI with
`apply=shutdown` or `apply=restart`. Both use the existing QTS session ID. The
preflight refuses the POST when an XML `item` reports status `1` for `Rsync`,
`VMs`, `RTRR`, or `ssd_cache_upgrading`, or when its response cannot be
interpreted, including when any of those four items is missing. The check is
advisory and cannot prevent work starting between
the GET and POST. It covers only those four CGI flags; it does not run separate
checks for iSCSI, HA, Live Migration, or other services.

An HTTP 2xx response without an explicit rejection marker means only that the
HTTP exchange completed; it does **not** confirm that the NAS shut down or
restarted. The actual QTS power response body, permissions, and the behavior of
QTS 5.2.11.3661 and QuTS hero have not been verified on a physical NAS.
The `authPassed`, `PermissionDeny`, and `errorValue` markers are documented for
QTS authentication responses; their presence and meaning in the power CGI are
not verified. The draft conservatively treats `PermissionDeny=1` or
`errorValue=-2` as permission denial, even when the same XML contains
`authPassed=0`. The meaning of `authPassed=0` alone for this CGI is not
established; it raises a generic rejection error without automatic
reauthentication. Other response formats may exist. A connection
drop or timeout after starting the POST raises `QnapPowerOutcomeUnknown`.
An unparseable nonempty POST response does the same. Never retry these actions
automatically. Cancellation during the POST also leaves the outcome unknown;
the cancellation propagates and must not trigger a retry. Every attempted POST
clears the local session ID so context
exit does not attempt logout while QTS may be going offline. The tests use synthetic
loopback responses and prove transport behavior only, not firmware compatibility.

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
