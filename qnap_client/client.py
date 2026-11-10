"""Main QnapClient — async Python client for QNAP NAS."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import aiohttp
import xmltodict

from .exceptions import (
    QnapAPIError,
    QnapAuthError,
    QnapConnectionError,
    QnapPermissionError,
    QnapTimeoutError,
)
from .models import (
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

_LOGGER = logging.getLogger(__name__)


class QnapClient:
    """Async client for the QNAP NAS CGI API.

    Designed for use in Home Assistant custom integrations but general-purpose.

    Usage::

        async with QnapClient("192.168.1.10", 8080, "admin", "pass") as client:
            data = await client.get_all()
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        ssl: bool = False,
        verify_ssl: bool = True,
        timeout: int = 10,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._ssl = ssl
        self._verify_ssl = verify_ssl
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._provided_session = session

        self._scheme = "https" if ssl else "http"
        self._base = f"{self._scheme}://{host}:{port}"
        self._session: aiohttp.ClientSession | None = None
        self._sid: str | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "QnapClient":
        try:
            await self.login()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self, *, logout: bool = True) -> None:
        """Close an owned session, optionally without network I/O.

        A supplied HTTP session is never closed. Set logout=False when the NAS
        is unavailable or the integration is unloading; the local SID is cleared.
        """
        try:
            if logout:
                await self.logout()
        finally:
            self._sid = None
            if self._provided_session is None and self._session is not None:
                await self._session.close()
                self._session = None

    # ------------------------------------------------------------------
    # Session / auth
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._provided_session is not None:
            return self._provided_session
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=self._timeout
            )
        return self._session

    @property
    def _active_session(self) -> aiohttp.ClientSession:
        session = self._provided_session or self._session
        if session is None or session.closed:
            raise QnapConnectionError("No active HTTP session — call login() first")
        return session

    async def login(self) -> None:
        """Authenticate and store the session ID (authSid)."""
        self._sid = None
        pwd_b64 = base64.b64encode(self._password.encode()).decode()
        text = await self._request(
            "POST",
            f"{self._base}/cgi-bin/authLogin.cgi",
            data={"user": self._username, "pwd": pwd_b64},
        )

        root = self._root(text)
        auth_passed = root.get("authPassed", "0")
        if str(auth_passed) != "1":
            raise QnapAuthError("Login failed — check username and password")

        sid = root.get("authSid")
        if not isinstance(sid, str) or not sid:
            raise QnapAuthError("Login succeeded but no authSid in response")

        self._sid = sid
        _LOGGER.debug("Logged in to QNAP")

    async def logout(self) -> None:
        """Invalidate the current session."""
        if self._sid is None:
            return
        try:
            await self._get("/cgi-bin/authLogin.cgi", params={"logout": "1"})
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._sid = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, str] | None = None) -> str:
        """GET a URL, appending the session SID, return response text."""
        if self._sid is None:
            raise QnapAuthError("Not logged in — call login() first")
        all_params = dict(params or {})
        all_params["sid"] = self._sid

        return await self._request("GET", f"{self._base}{path}", params=all_params)

    def _check_status(
        self,
        status: int,
        expected: tuple[int, ...] | None,
        *,
        invalidate_session: bool,
    ) -> None:
        """Raise safe exceptions without response URLs, headers, or bodies."""
        if status == 401:
            if invalidate_session:
                self._sid = None
            raise QnapAuthError("Authentication rejected (HTTP 401)")
        if status == 403:
            raise QnapPermissionError("Permission denied (HTTP 403)")
        if not 200 <= status < 300 or (expected is not None and status not in expected):
            raise QnapAPIError(f"QNAP request failed (HTTP {status})")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        expected: tuple[int, ...] | None = None,
        invalidate_session: bool = True,
        **kwargs: Any,
    ) -> str:
        """Send one request, without retries or credential-bearing redirects."""
        session = await self._ensure_session()
        if session.closed:
            raise QnapConnectionError("HTTP session is closed")
        try:
            async with session.request(
                method,
                url,
                timeout=self._timeout,
                ssl=self._verify_ssl,
                allow_redirects=False,
                **kwargs,
            ) as resp:
                self._check_status(
                    resp.status, expected, invalidate_session=invalidate_session
                )
                return await resp.text()
        except aiohttp.ClientResponseError as exc:
            # A supplied session may enable raise_for_status itself.
            # Suppress its context, which can contain URLs and auth headers.
            try:
                self._check_status(
                    exc.status, expected, invalidate_session=invalidate_session
                )
            except (QnapAuthError, QnapPermissionError, QnapAPIError) as error:
                raise error from None
            raise QnapAPIError("Invalid HTTP response") from None
        except asyncio.TimeoutError:
            raise QnapTimeoutError("QNAP request timed out") from None
        except aiohttp.ClientError:
            raise QnapConnectionError(
                "QNAP connection failed or was interrupted"
            ) from None
        except UnicodeError:
            raise QnapAPIError("QNAP response could not be decoded") from None

    @staticmethod
    def _parse_xml(text: str) -> dict[str, Any]:
        try:
            return xmltodict.parse(text)  # type: ignore[no-any-return]
        except Exception:
            raise QnapAPIError("Failed to parse XML response") from None

    def _root(self, text: str) -> dict[str, Any]:
        root = self._parse_xml(text).get("QDocRoot")
        if not isinstance(root, dict):
            raise QnapAPIError("Response has no QDocRoot object")
        return root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo:
        """Return basic NAS system information."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "hd": "no", "multicpu": "1"},
        )
        root = self._root(text)

        # qnapstats-style: data lives under func/ownContent/root
        inner = root.get("func", {}).get("ownContent", {}).get("root", root)
        model_info = root.get("model", {})
        firmware_info = root.get("firmware", {})

        uptime_seconds = 0
        try:
            days = int(inner.get("uptime_day", 0))
            hours = int(inner.get("uptime_hour", 0))
            minutes = int(inner.get("uptime_min", 0))
            seconds = int(inner.get("uptime_sec", 0))
            uptime_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
        except (ValueError, TypeError):
            pass

        system_temp: int | None = None
        try:
            raw_temp = inner.get("sys_tempc")
            if raw_temp is not None:
                system_temp = int(raw_temp)
        except (ValueError, TypeError):
            pass

        return SystemInfo(
            model=model_info.get("displayModelName", inner.get("model_name", "")),
            name=inner.get("server_name", root.get("hostname", "")),
            serial_number=inner.get("serial_number", root.get("serialNumber", "")),
            firmware_version=firmware_info.get("version", root.get("version", "")),
            uptime_seconds=uptime_seconds,
            system_temp=system_temp,
        )

    async def get_system_health(self) -> SystemHealth:
        """Return overall system health status."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "sysHealth": "1"},
        )
        root = self._root(text)
        status = root.get("sysHealth", {}).get("status", "Unknown")
        return SystemHealth(status=status)

    async def get_cpu_stats(self) -> CpuStats:
        """Return current CPU usage percentage and temperature."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "hd": "no", "multicpu": "1"},
        )
        root = self._root(text)
        inner = root.get("func", {}).get("ownContent", {}).get("root", root)

        cpu_usage_str = inner.get(
            "cpu_usage", root.get("cpu", {}).get("cpu_usage", "0")
        )
        try:
            cpu_usage = float(str(cpu_usage_str).rstrip("%"))
        except (ValueError, TypeError):
            cpu_usage = 0.0

        cpu_temp: int | None = None
        try:
            raw_temp = inner.get("cpu_tempc")
            if raw_temp is not None:
                cpu_temp = int(raw_temp)
        except (ValueError, TypeError):
            pass

        return CpuStats(usage_percent=cpu_usage, cpu_temp=cpu_temp)

    async def get_memory_stats(self) -> MemoryStats:
        """Return RAM stats in megabytes."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi", {"subfunc": "sysinfo"}
        )
        root = self._root(text)
        mem = root.get("memory_status", {})

        def _mb(key: str) -> int:
            raw = mem.get(key, "0")
            try:
                return int(raw)
            except (ValueError, TypeError):
                return 0

        total = _mb("total")
        free = _mb("free")
        used = total - free if total >= free else _mb("used")
        return MemoryStats(total_mb=total, free_mb=free, used_mb=used)

    async def get_network_interfaces(self) -> list[NetworkInterface]:
        """Return stats for all active network interfaces.

        Merges bandwidth data (rx/tx bytes/sec) from chartReq with
        NIC metadata (link status, mask, max speed, packets) from sysinfo.
        """
        # Bandwidth data
        bw_text = await self._get(
            "/cgi-bin/management/chartReq.cgi",
            {"chart_func": "net_usage", "disk_select": "all"},
        )
        bw_root = self._root(bw_text)
        ifaces_bw: dict[str, dict] = bw_root.get("net", {})

        # NIC metadata from sysinfo
        sys_text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "hd": "no", "multicpu": "1"},
        )
        sys_root = self._root(sys_text)
        inner = sys_root.get("func", {}).get("ownContent", {}).get("root", sys_root)

        nic_count = 0
        try:
            nic_count = int(inner.get("nic_cnt", 0))
        except (ValueError, TypeError):
            pass

        # Build sysinfo NIC map: eth0 -> {link_status, mask, max_speed, ...}
        nic_meta: dict[str, dict] = {}
        for nic_idx in range(nic_count):
            i = str(nic_idx + 1)
            iface_name = f"eth{nic_idx}"
            try:
                status_raw = inner.get(f"eth_status{i}", "0")
                link_status = "Up" if str(status_raw) == "1" else "Down"
                max_speed = int(inner.get(f"eth_max_speed{i}", 0) or 0)
                mask = inner.get(f"eth_mask{i}", "")
                mac = inner.get(f"eth_mac{i}", "")
                ip = inner.get(f"eth_ip{i}", "")
                rx_packets = int(inner.get(f"rx_packet{i}", 0) or 0)
                tx_packets = int(inner.get(f"tx_packet{i}", 0) or 0)
                err_packets = int(inner.get(f"err_packet{i}", 0) or 0)
                nic_meta[iface_name] = {
                    "link_status": link_status,
                    "mask": mask,
                    "mac": mac,
                    "ip": ip,
                    "max_speed": max_speed,
                    "rx_packets": rx_packets,
                    "tx_packets": tx_packets,
                    "err_packets": err_packets,
                }
            except (ValueError, TypeError) as exc:
                _LOGGER.debug("Skipping invalid NIC metadata: %s", type(exc).__name__)

        # Merge bandwidth + metadata
        results: list[NetworkInterface] = []
        seen: set[str] = set()

        if isinstance(ifaces_bw, dict):
            for key, val in ifaces_bw.items():
                if not isinstance(val, dict):
                    continue
                meta = nic_meta.get(key, {})
                try:
                    results.append(
                        NetworkInterface(
                            name=key,
                            mac=meta.get("mac", val.get("mac", "")),
                            ip=meta.get("ip", val.get("ip", "")),
                            rx_bytes_per_sec=float(val.get("rx", 0)),
                            tx_bytes_per_sec=float(val.get("tx", 0)),
                            link_status=meta.get("link_status", "Unknown"),
                            mask=meta.get("mask", ""),
                            max_speed=meta.get("max_speed", 0),
                            rx_packets=meta.get("rx_packets", 0),
                            tx_packets=meta.get("tx_packets", 0),
                            err_packets=meta.get("err_packets", 0),
                        )
                    )
                    seen.add(key)
                except (ValueError, TypeError) as exc:
                    _LOGGER.debug("Skipping invalid interface: %s", type(exc).__name__)

        # Add any NICs from sysinfo that weren't in bandwidth data
        for iface_name, meta in nic_meta.items():
            if iface_name not in seen:
                results.append(
                    NetworkInterface(
                        name=iface_name,
                        mac=meta.get("mac", ""),
                        ip=meta.get("ip", ""),
                        rx_bytes_per_sec=0.0,
                        tx_bytes_per_sec=0.0,
                        link_status=meta.get("link_status", "Unknown"),
                        mask=meta.get("mask", ""),
                        max_speed=meta.get("max_speed", 0),
                        rx_packets=meta.get("rx_packets", 0),
                        tx_packets=meta.get("tx_packets", 0),
                        err_packets=meta.get("err_packets", 0),
                    )
                )

        return results

    async def get_drive_health(self) -> list[DriveHealth]:
        """Return SMART/health info for all drives."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "hd_smart": "1"},
        )
        root = self._root(text)
        drives_raw = (
            root.get("func", {})
            .get("ownContent", {})
            .get("hdList", {})
            .get("hdInfo", [])
        )

        if isinstance(drives_raw, dict):
            drives_raw = [drives_raw]

        results: list[DriveHealth] = []
        for i, drive in enumerate(drives_raw):
            if not isinstance(drive, dict):
                continue
            temp_raw = drive.get("hd_temperature")
            try:
                temp: int | None = int(temp_raw) if temp_raw else None
            except (ValueError, TypeError):
                temp = None

            results.append(
                DriveHealth(
                    drive_number=i + 1,
                    model=drive.get("hd_model", ""),
                    health=drive.get("hd_health", ""),
                    temperature=temp,
                )
            )
        return results

    async def get_volumes(self) -> list[VolumeStats]:
        """Return storage volume statistics."""
        text = await self._get(
            "/cgi-bin/management/chartReq.cgi",
            {"chart_func": "disk_usage", "disk_select": "all", "include": "all"},
        )
        root = self._root(text)
        vols_raw = root.get("volumeList", {}).get("volume", [])

        if isinstance(vols_raw, dict):
            vols_raw = [vols_raw]

        results: list[VolumeStats] = []
        for vol in vols_raw:
            if not isinstance(vol, dict):
                continue

            def _bytes(key: str) -> int:
                raw = vol.get(key, "0")
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return 0

            results.append(
                VolumeStats(
                    name=vol.get("volumeLabel", vol.get("label", "")),
                    total_bytes=_bytes("sizeTotal"),
                    used_bytes=_bytes("sizeUsed"),
                    free_bytes=_bytes("sizeFree"),
                    status=vol.get("status", ""),
                )
            )
        return results

    async def get_firmware_update(self) -> FirmwareUpdate:
        """Return current and available firmware version."""
        text = await self._get(
            "/cgi-bin/sys/sysRequest.cgi", {"subfunc": "firm_update"}
        )
        root = self._root(text)

        # Response can be nested under func/ownContent or at root level
        content = root.get("func", {}).get("ownContent", root)
        firmware_root = content.get("firmware", content)

        # Current version: look in multiple places
        current = (
            firmware_root.get("curVersion")
            or firmware_root.get("version")
            or root.get("firmware", {}).get("version", "")
            or ""
        )
        # Latest version: only set if a newer version is available
        latest = firmware_root.get("newVersion") or content.get("newVersion") or None
        if latest == "" or latest == current:
            latest = None

        return FirmwareUpdate(current_version=current, latest_version=latest)

    async def get_fans(self) -> list[FanStatus]:
        """Return fan speed readings (empty list if unsupported)."""
        text = await self._get(
            "/cgi-bin/management/manaRequest.cgi",
            {"subfunc": "sysinfo", "sysfans": "1"},
        )
        root = self._root(text)
        fans_raw = root.get("sysfan", {})

        if not isinstance(fans_raw, dict):
            return []

        results: list[FanStatus] = []
        for i, (_, val) in enumerate(fans_raw.items()):
            if not isinstance(val, dict):
                continue
            try:
                rpm = int(val.get("speed_rpm", val.get("rpm", 0)))
                results.append(FanStatus(fan_number=i + 1, speed_rpm=rpm))
            except (ValueError, TypeError) as exc:
                _LOGGER.debug("Skipping fan entry %d: %s", i, type(exc).__name__)

        return results

    async def get_external_drives(self) -> list[ExternalDrive]:
        """Return stats for externally-connected drives (empty list if none)."""
        text = await self._get(
            "/cgi-bin/management/chartReq.cgi",
            {"chart_func": "disk_usage", "disk_select": "all", "include": "all"},
        )
        root = self._root(text)
        ext_raw = root.get("externalDriveList", {}).get("drive", [])

        if isinstance(ext_raw, dict):
            ext_raw = [ext_raw]

        results: list[ExternalDrive] = []
        for drv in ext_raw:
            if not isinstance(drv, dict):
                continue

            def _bytes(key: str) -> int:
                raw = drv.get(key, "0")
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return 0

            results.append(
                ExternalDrive(
                    name=drv.get("name", ""),
                    total_bytes=_bytes("sizeTotal"),
                    used_bytes=_bytes("sizeUsed"),
                )
            )
        return results

    async def get_all(self) -> NasData:
        """Fetch all NAS data in parallel and return a NasData aggregate."""
        (
            system_info,
            system_health,
            cpu,
            memory,
            network_interfaces,
            drives,
            volumes,
            firmware,
            fans,
            external_drives,
        ) = await asyncio.gather(
            self.get_system_info(),
            self.get_system_health(),
            self.get_cpu_stats(),
            self.get_memory_stats(),
            self.get_network_interfaces(),
            self.get_drive_health(),
            self.get_volumes(),
            self.get_firmware_update(),
            self.get_fans(),
            self.get_external_drives(),
            return_exceptions=True,
        )

        # Core system information is required to distinguish unavailable NASes
        # from successfully polled devices with unsupported optional sections.
        if isinstance(system_info, Exception):
            raise system_info

        def _unwrap(result: Any, default: Any) -> Any:
            if isinstance(result, Exception):
                _LOGGER.warning("get_all partial failure: %s", type(result).__name__)
                return default
            return result

        return NasData(
            system_info=system_info,
            system_health=_unwrap(system_health, SystemHealth("Unknown")),
            cpu=_unwrap(cpu, CpuStats(usage_percent=0.0)),
            memory=_unwrap(memory, MemoryStats(0, 0, 0)),
            network_interfaces=_unwrap(network_interfaces, []),
            drives=_unwrap(drives, []),
            volumes=_unwrap(volumes, []),
            firmware=_unwrap(firmware, None),
            fans=_unwrap(fans, []),
            external_drives=_unwrap(external_drives, []),
        )
