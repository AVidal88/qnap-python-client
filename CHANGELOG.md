# Changelog

All notable changes to `qnap-client` will be documented here.

## [1.1.1] - Unreleased

### Fixed
- Remove session IDs, response bodies, request URLs, and raw transport errors from
  library logs and exceptions. Disable credential-bearing redirects.
- Preserve the QTS session when Container Station rejects access with HTTP 401.
- Normalize HTTP authentication, permission, API, timeout, and connection failures;
  add the exported `QnapPermissionError` for HTTP 403.
- Add idempotent `close()`, preserve caller-owned sessions, and close owned sessions
  after context-entry failures. Failed login discards any previous session ID.
- Require successful system information in `get_all()` so an offline NAS is not
  returned as empty successful telemetry; retain optional-section fallbacks.
- Apply timeout and SSL verification when using caller-supplied sessions.
- Align the runtime version with package metadata.

### Validation limits
- Transport tests use synthetic responses, not captured firmware fixtures.
- NAS shutdown/reboot and QTS 5.2/QuTS hero power API compatibility remain unverified
  and are not implemented. This version must be published before consumers pin it.

## [1.0.3] - 2026-05-05

### Fixed
- `ContainerStationClient._ensure_cs_auth()` was referencing `_password_b64` on `QnapClient`,
  which does not exist. Changed to `_password` (the correct attribute). This caused `AttributeError`
  when trying to start/stop containers via Container Station v1 API.

## [1.0.2] - 2026-05-05

### Added
- `Container.state` field (renamed from `status`) — `get_containers()` now maps the raw API
  `status` field to `state` for consistency with the model naming
- `NasData.containers` field — coordinator now populates containers directly on `NasData`

### Changed
- `get_containers()` reads `state` key first, falls back to `status` key from QNAP API response

## [1.0.0] - 2026-05-05

Initial release. Full async rewrite replacing `python-qnapstats`.

### Added
- `QnapClient` — fully async aiohttp-based client
- `ContainerStationClient` — Docker/LXC container management via Container Station API
- Typed dataclass models for all API responses
- Full exception hierarchy (`QnapError`, `QnapAuthError`, `QnapConnectionError`, `QnapTimeoutError`, `QnapAPIError`)
- `get_all()` — fetches all NAS data in parallel with `asyncio.gather`
- Fan speed support (`get_fans()`)
- External drive support (`get_external_drives()`)
- Graceful handling of missing/unexpected API response fields
- Proper handling of `newVersion` key absence in firmware update API
- Graceful skip of unrecognized network interface keys (fixes eth_status5 crash on QNAP-473e)
- Drive temperature returns `None` instead of `0` when data unavailable
- Session auto-retry on 401 for Container Station v1 API
