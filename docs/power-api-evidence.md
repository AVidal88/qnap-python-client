# QTS power API evidence

This record supports the proposed library power methods. The owner reported
a physically observed shutdown and subsequent power-on via WOL, followed by
one accepted reboot request and a remotely observed loss and restoration of
access. The owner considered both trials satisfactory and closed this
validation round. These observations concern a TS-431P with QTS 5.2.11.3661.

## Firmware provenance

The target is a QNAP TS-431P with QTS 5.2.11.3661, as reported by the owner.
The inspected [official firmware](https://download.qnap.com/Storage/TS-X41/TS-131P_231P_431P_X31%2B_X31K_20261023-5.2.11.3661.zip)
has ZIP SHA256
`2cd84ff1721369daa4dd9fbeb3fa24a7daa3c7e6c81b7df4200b7679dd58d7f0`.
Inspection used local extracted files.

The official web client has these separate operations.

| Source | Observed behavior |
| --- | --- |
| `qos-core-base.js`, `shutdownNas` / `rebootNas` | POST to `sys/sysRequest.cgi` with `subfunc=power_mgmt` and `apply=shutdown` / `restart`, without an action-specific body |
| `qos-lib.js`, `getCgiUrl` | Adds the current `QNAP.QOS.user.sid` to the URL |
| `qos-core-desktop.js`, `get_shutdown_warning_flag` | GET with `apply=chk_shutdown_running`, reading `item/name/status` for UI warnings |

The action callback ignores the response body. Inspection of a separate
session-timeout helper did not establish that the power-action callback uses
that helper. The server acknowledgement below was established separately by
static inspection of the official CGI.

## Server acknowledgement found during response review

The extracted `sys/sysRequest.cgi` has SHA256
`9cea07e0e3864cb2f8dd3107b8d77aefe427c1be0c4b05eb82e98c6bd3b1998f`.
Static ARM Thumb inspection identified the following call paths. Addresses are
virtual addresses, equal to file offsets within this binary's `.text` section.
The binary was read as data throughout this investigation.

| Address | Observed behavior |
| --- | --- |
| `0x14888..0x148b6` | Failed session checks emit `QDocRoot/authPassed=0` and return before dispatch |
| `0x149ae..0x149bc` | Insufficient delegation permissions also emit `authPassed=0` and return before dispatch |
| `0x1535a..0x15364` | Opens `QDocRoot`, emits `authPassed=1` and general metadata before dispatch |
| `0x152f0..0x152f4`, `0x43040..0x43046` | Dispatches an `apply` request for power management to handler `0x35574` |
| `0x3558c..0x35594` | Initializes the exported `ret_of_settingresult` global to zero |
| `0x355c0..0x35618` | Matches `restart`, calls imported `Restart_System` at `0x35614`, branches to common completion |
| `0x3561c..0x35674` | Matches `shutdown`, calls imported `Shutdown_System` at `0x35670`, branches to common completion |
| `0x36372..0x3637a` | Reads that global and calls the result emitter at `0x1254c` |
| `0x1254c..0x1258e` | Emits direct child `setting_result`, using CDATA, with `0` for zero or `-1` for nonzero |
| `0x15302..0x15310` | Emits final data and closes `QDocRoot` |

The `setting_result` literal is at `0x4648c`. Failure branches in the same
handler explicitly set the global to `-1`, including failed profile/schedule
updates at `0x357ba..0x357cc` and `0x3594e..0x35960`. This establishes the
negative-result meaning of that emitter. No negative power response has been
observed in a physical test.

The shutdown/restart branches ignore the return of their system call. The
nominal result therefore acknowledges execution of the CGI handler's action
path. Physical completion requires its own observation. `authPassed=1` is
emitted before dispatch and alone cannot acknowledge the operation.

This minimal XML is reconstructed from the static emitters. Metadata is
omitted and it is not a captured NAS response.

```xml
<QDocRoot version="1.0">
  <authPassed><![CDATA[1]]></authPassed>
  <setting_result><![CDATA[0]]></setting_result>
</QDocRoot>
```

Frontend provenance is `qos-core-base.js` SHA256
`fe3e0e9c977447f3edf9fb16eaed92e31dbc9e00710b7031358f4045b3ea0d34`,
with power methods at character offsets `166684` and `166951`, and
`qos-lib.js` SHA256
`6d6652d41c8b2fdc194721e8d217b8e9e3a166b2ac0794a1a0b3f16bbe8fd240`.
Its AJAX helper builds a session-check wrapper but passes the original
`o.success` callback to Ext. The server analysis supplies the acknowledgement
contract independently of that unused wrapper.

The warning flag starts at zero and is updated only for known items whose
status equals `1`. A response with no matched items leaves that particular UI
warning flag at zero. The UI also checks iSCSI and diverts to High Availability
or Live Migration management when those modes are active. The library
does not impose the UI's item list as a mandatory schema for power actions.

## First real read-only observation

The owner supplied this [sanitized browser summary](device-evidence/preflight-01.md)
from an existing MFA-authenticated QTS session. It establishes HTTP 200,
`text/xml`, XML recognized as `QDocRoot`, and `authPassed=1`. The diagnostic
matched no exact `item` elements.

Missing items can reflect an empty warning list, a different schema or namespace,
model-dependent behavior, or a response limited to authentication. The summary
cannot distinguish these cases. It also cannot establish inactivity of any
service, POST authorization, SID-only Python authentication, or action acceptance.

A later structural summary reported 31 elements, 28 outside the diagnostic
allowlist, zero item/status elements and no namespaces. Its interpretation
remains unresolved. The raw response remains unavailable and reconstructed
test data must retain its provenance.

## First physical shutdown observation

The owner confirmed one request, successful MFA, HTTP 200/XML and physical
power-off after an unmeasured delay. The library reported
QnapPowerOutcomeUnknown because the original draft always raised it after
HTTP 2xx. Its full response is unavailable, so the later-discovered
`setting_result` contract cannot be assigned to that trial retrospectively.
The owner subsequently confirmed power-on via WOL and closed
the physical shutdown trial as validated. Source preservation
and the execution-hash comparison are recorded in
[shutdown observation 01](device-evidence/shutdown-01.md).

The reported equality of sanitized preflight and shutdown summaries leaves
the identity of the complete XML documents undetermined.

## Response classification

The first draft discarded every successfully read body and unconditionally
raised `QnapPowerOutcomeUnknown` after HTTP 2xx. That code path explains the
exception in shutdown observation 01. The complete body was never retained,
so its actual `setting_result` remains unknown retrospectively.

The revised classifier uses the server contract established above.

| Response | Library result |
| --- | --- |
| `QDocRoot` with unique direct leaf `authPassed=1` and `setting_result=0` | Returns `None`, nominal CGI acceptance |
| Same structure with `setting_result=-1` | `QnapPowerRejectedError`, reason `setting_failed` |
| Unique direct leaf `authPassed=0`, without `setting_result` | `QnapPowerRejectedError`, reason `authentication_or_permission` |
| HTTP 401 / 403 | Existing `QnapAuthError` / `QnapPermissionError` |
| Other HTTP 4xx | `QnapAPIError` with safe numeric `http_status`, an HTTP rejection |
| Empty/malformed/foreign XML, unrecognized codes, duplicated/nested/contradictory control fields or namespaces | `QnapPowerOutcomeUnknown` with a safe reason |
| Redirect, server error, decode error, timeout or interrupted connection | `QnapPowerOutcomeUnknown`, preserving available HTTP status |

The XML rejection cannot distinguish expired/invalid sessions from insufficient
permissions, because both backend paths emit the same marker. Unknown marker
combinations retain uncertainty. Each action is submitted once. A lost
connection alone cannot determine rejection or physical completion.

The owner subsequently reported a real reboot request with `authPassed=1`,
`setting_result=0`, CGI acceptance and normal library return, with one power
POST. This correlates the classifier with a real device response. The runner
then failed locally while choosing its exit code because its map omitted
`accepted`. That later error preserves the earlier API observation. The owner
subsequently confirmed a remotely observed interval of unavailability followed
by restored access. Duration, post-reboot uptime and physical inspection were
unrecorded. The owner accepted this evidence as satisfactory for the current
contribution. See
[reboot observation 01](device-evidence/reboot-01.md).

## Sanitized evidence collection

The existing runner now retains a bounded ordered structural projection of the
received XML. Fixed names are derived from this firmware's frontend login/host
selectors and the CGI result emitter. Unknown names receive document-local
aliases. Text, attributes, tails and namespace values are excluded. The already
restricted numeric-code summary now includes `setting_result` and node positions.
The output identifies structure completeness, with limits of 512 elements and
65,536 characters. It also compares complete decoded preflight and POST text in memory,
reporting only equality as `post_matches_preflight_text`.
The owner reported `true` in the reboot trial. This establishes equality of
the compared decoded response texts. The remote availability observation and
the interpretation of missing preflight warning items retain separate states.

The frontend selectors used for name disclosure are in `qos-core-base.js`
host settings around character offsets `52400..57500`, `qos-core-login.js`
around `21100..22600` and its login handler, and `login-m.js` around `11850`.
The structure describes the received response and does not reconstruct omitted
values. HTTP error bodies are not captured because the library rejects their
status before returning text to the runner. Raw CGI bodies remain outside
the runner's output, files and fixtures.

## Authentication for a Python device trial

The owner validated interactive MFA through a separate local test adapter.
That adapter uses `security_code` and its own `client_id`, retains the SID in
memory and binds the newly authenticated session to the candidate before
invoking its public power method. Password and manual TOTP are entered locally.
The MFA diagnostic and power runner remain private trial infrastructure outside
this package and the proposed PR.

The public library's `login()` continues to perform password authentication.
A pending second-factor challenge raises `QnapTwoStepRequiredError`. The
power implementation uses the session established by that existing login
flow. Its package imports and execution path are self-contained. General
interactive MFA, persistent credentials, renewal and unattended Home Assistant
authentication remain separate contributions.

The observed shutdown used an earlier power draft that always raised an
unknown outcome after HTTP 2xx. The reboot used the revised acknowledgement
classifier and the runner version preceding its exit-code fix. The subsequent
runner correction was validated offline. Source hashes and preservation
records remain attached to each observation. Backups are retained privately
outside the proposed PR, including source ZIPs and manifests. The full raw
CGI bodies and literal execution metadata remain unavailable in the supplied
evidence, so archive-to-execution hash comparison retains its recorded limit.

The validation round is closed. CGI acknowledgement and observed device
behavior remain separate evidence. Compatibility claims remain limited to
the tested model and firmware. QuTS hero and other models require their own
evidence.

## Candidate verification after the device trials

The final review gives a successful `authPassed=1` response with a valid SID
priority over retained MFA indicators. It also removes unused private transport
options left over from the broader prototype. These post-trial changes have
offline regression coverage. The hardware observations retain the earlier
source fingerprints recorded in the individual evidence files.

The offline-validated implementation is commit
`31cac46c9ca36ab1621e8e87674c1622586042f2`. Its local `qnap_client/client.py`
SHA256 is `3ec8b8b16c1dc1e6c02fa71683178597c5ed32794d364852b98dfc660adabd59`.
This identifies the post-trial candidate separately from the earlier source
snapshots used to preserve the hardware observations.

Current checks used Python 3.12.10 on Windows. Installation from `.[dev]` into
a fresh environment resolved aiohttp 3.13.5, xmltodict 1.0.4, pytest 9.2.0,
pytest-asyncio 1.5.0 and aioresponses 0.7.9. All 99 library tests passed and
`pip check` found consistent requirements. The development extra constrains
aiohttp below 3.14 for the existing aioresponses-based suite. Separately, all
93 power/transport tests passed with isolated aiohttp 3.14.5 using loopback
servers. Runtime dependency bounds retain their upstream values.

The 116 local diagnostic tests also passed against the candidate. Those tests
and their interactive adapter remain separate test infrastructure outside this
PR. The 90-test library results recorded in the earlier trial notes describe
the source state before the final regression additions.

The wheel built locally with the inherited package metadata contains the five
package modules, distribution metadata and license. Source bytes were checked
against the candidate. Private backups, diagnostic executors and firmware stay
outside the proposed files. Release version selection remains with the
maintainer. Package metadata retains upstream's `1.1.0` and the module retains
upstream's `1.0.3` value.

Focused Ruff checks pass for the added tests and exception definitions. The
expanded library check retains three upstream findings, two B023 monitoring
closures and RUF022 for the grouped exports. Pytest emits the inherited
unset-async-fixture-scope deprecation warning. The existing CI matrix covers
Python 3.12 and 3.13. Current local execution covers Python 3.12.10.
