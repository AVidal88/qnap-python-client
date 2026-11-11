# Evidence for QTS power actions

This note records what can be verified without sending a shutdown or restart request to a NAS. It is evidence for the proposed `qnap-client` methods, not a claim of device-level validation.

## QTS 5.2.11 implementation on the TS-431P family

The NAS owner reported QTS **5.2.11.3661**. QNAP's [matching TS-431P family firmware, build 20261023](https://download.qnap.com/Storage/TS-X41/TS-131P_231P_431P_X31%2B_X31K_20261023-5.2.11.3661.zip) was downloaded and inspected locally. ZIP SHA-256: `2cd84ff1721369daa4dd9fbeb3fa24a7daa3c7e6c81b7df4200b7679dd58d7f0`. The image footer identifies the `TS-X41` family and version `5.2.11`. [QNAP's release notes](https://www.qnap.com/en/release-notes/qts/overview/5.2.0) list this build. No firmware files are included in this repository, and no NAS was contacted.

The earlier [TS-431P family firmware, build 5.2.7.3256](https://download.qnap.com/Storage/TS-131P_231P_431P_X31%2B_X31K/TS-131P_231P_431P_X31%2B_X31K_20250913-5.2.7.3256.zip) was used as a comparison. ZIP SHA-256: `95d0eae7f9804a89594229c603d030f960104941107f2721355dd4f7680218d1`. The full JavaScript files differ across builds, but the relevant function bodies were compared textually and are unchanged: `rebootNas`/`shutdownNas` in `qos-core-base.js`, `getCgiUrl` in `qos-lib.js`, and the desktop's power actions, preflight, confirmation, and iSCSI target-store definition. The bundled `sysRequest.cgi` binaries differ, so unchanged browser code does not prove identical server-side behavior.

The bundled web client in `home/httpd/cgi-bin/js/qos-core-base.js` sends one `POST` to `/cgi-bin/sys/sysRequest.cgi` with query parameters `sid=<current session SID>`, `subfunc=power_mgmt`, and `apply=shutdown` or `apply=restart`. It supplies no action-specific request body. `qos-lib.js` builds the URL from the current web session SID. The browser may also send its usual cookies; inspection of client code alone cannot prove that the SID is sufficient without them. The client does not inspect a success response body for these two actions; it begins monitoring disconnection or reconnection.

The `qos-core-desktop.js` UI applies checks before either power action:

- The menu is available to administrator-group users. The desktop diverts to the High Availability or Live Migration management app when those modes are active.
- A read-only `GET` to the same CGI with `apply=chk_shutdown_running` parses XML `item/name` and `item/status`. Status `1` for `Rsync`, `VMs`, or `RTRR` produces a warning; `ssd_cache_upgrading` blocks the UI action. The browser accepts a response with only a subset of these items; the proposed library fails closed if any is missing, so live compatibility must be checked.
- It separately checks iSCSI target connections via `disk/iscsi_portal_setting.cgi`; a `targetStatus` of `1` produces a warning. The warnings for Rsync, VMs, RTRR, and iSCSI allow the user to continue after confirmation.
- On failed or delayed checks, the web UI can continue to confirmation after 60 seconds with incomplete warning data. The client-side checks do not establish what the final CGI enforces.

The bundled `sysRequest.cgi` binary contains action and preflight strings, but static string inspection did not establish its response schema, error codes, administrator enforcement, or whether it independently blocks active jobs. An [older third-party Go client](https://github.com/mkch/qnap-tool/blob/main/qnap/qnap.go#L394-L444) also sends a POST to the shutdown URL and expects XML `authPassed`; it is not proof of the response on QTS 5.2.11.3661.

## Authentication and scope

QNAP's [HTTP API Authentication v5.1.0](https://eu1.qnap.com/dev/QTS_HTTP_API-Authentication_v5.1.0.pdf) documents `authLogin.cgi` issuing `authSid`, `authPassed`, and `isAdmin`; its examples include `PermissionDeny` and `errorValue=-2` for a non-administrator. It also documents read-only validation with `authLogin.cgi?sid=<sid>`. These examples describe the authentication endpoint, **not** the power-action response. A password or qtoken is used to obtain a SID; the observed action request contains a SID, not the password. Neither credentials nor SIDs should appear in logs, exceptions, or shared diagnostics.

The same QNAP document shows that a password accepted as the first step of two-step verification may return `authPassed=0` with `need_2sv=1`. It also documents `need_2_step_verification=1` for the newer flow. The proposed client detects those flags and reports a specific unsupported-login error; it does not bypass or complete MFA. A password-only failure on the owner's NAS is compatible with MFA, but the response flags have not yet been inspected there.

QNAP's [QTS 5.2.x user guide](https://docs.qnap.com/operating-system/qts/5.2.x/en-us/task-bar-33FA3D49.html) calls the UI actions a restart and an orderly shutdown of QTS before power off. The [QuTS hero h5.2.x guide](https://docs.qnap.com/operating-system/quts-hero/5.2.x/en-us/task-bar-94411C9.html) describes equivalent UI actions, but no QuTS hero firmware or live device was inspected for this CGI contract. QuTS hero API compatibility remains unverified.

## Safe validation on the TS-431P

1. Record the exact QTS version/build and confirm the test account is in the administrator group. Do not disclose the password, qtoken, or SID.
2. With an authenticated QTS browser session, inspect the *read-only* `authLogin.cgi?sid=<sid>` response for `authPassed` and `isAdmin`. Then inspect the *read-only* `GET /cgi-bin/sys/sysRequest.cgi?sid=<sid>&subfunc=power_mgmt&apply=chk_shutdown_running` response for HTTP status, content type, XML validity, and `item/name`/`item/status`. Opening the UI shutdown/restart confirmation without accepting it can also reveal current warnings. Do not click **Yes**.
3. Share only redacted field summaries. Do not export a raw HAR, URL, or complete response: requests contain the SID and other device details.
4. A maintenance-window test of each final action is still required to establish its response, permissions, and actual behavior. It must be explicitly authorized by the NAS owner; send one action at a time, with no automatic retry. A lost connection after a request is ambiguous until the device state is observed.

There is no known non-destructive dry-run of `apply=shutdown` or `apply=restart`; neither endpoint should be probed merely to learn its response.
