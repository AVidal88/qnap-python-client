# TS-431P shutdown observation 01

The NAS owner confirmed that one request through the power trial runner was
followed by physical shutdown of a TS-431P running QTS 5.2.11.3661. The NAS took
some time to complete shutdown. Exact duration and execution time were not
recorded in the information supplied.

## Observations supplied by the owner

| Dimension | Recorded result |
| --- | --- |
| Authentication | Interactive MFA succeeded |
| Operation | One call through the runner using QnapClient.shutdown() |
| HTTP response | HTTP 200 and XML received |
| CGI acceptance | Unknown in the trial, original full response unavailable |
| Library result | QnapPowerOutcomeUnknown |
| Physical effect | NAS powered off, observed by the owner |
| Duration | Unmeasured |
| Recovery | Owner confirmed subsequent power-on through WOL |
| Physical trial assessment | Validated on this device by the owner |
| Reboot | Later trial recorded independently in `reboot-01.md` |

This is positive physical evidence for the tested model and firmware. In this
observation QnapPowerOutcomeUnknown was generated unconditionally after HTTP
2xx by the original draft. A later static backend review identified the
`setting_result` acknowledgement, documented in
[power-api-evidence.md](../power-api-evidence.md). The unavailable trial body
prevents assigning that marker retrospectively. The owner subsequently
confirmed power-on through WOL and closed the
physical shutdown trial as validated. No additional shutdown trial or physical
checks are required for this observation.

The owner reported matching sanitized summaries for the preflight and shutdown
responses. The complete XML bodies remain unavailable for comparison. Equality
of those summaries leaves full-document identity undetermined. HTTP 200 and
authPassed=1 retain their recorded values without a generic acceptance rule.

## Source preservation and provenance

The tested candidate used local changes over base commit
`4792a60e0175c6eda31e18474c245d98f926d681` on `feat/qts-power-api-pr` in the
linked worktree `python-qnap-power-pr`. The local package metadata declares
`1.1.0`, while the inherited module version declares `1.0.3`.

A byte-preserving local source archive and SHA256 manifest were created in the
workspace at `artifacts/qts-shutdown-01/`. The archive preserves all package
modules, project metadata, tests, the two runtime diagnostic files and their
tests, the preparation documents and a binary Git diff of tracked changes.
The full source archive also includes the previously untracked test and
evidence files. The snapshot precedes the documentation update for this result.

| Preserved source | SHA256 observed at preservation |
| --- | --- |
| `qnap_client/client.py` | `824c1f2985ecd7b6f70b7eb2675ceded6ea7a03dd8bd8eb8c9766042fec21c72` |
| `qnap_client/exceptions.py` | `f7dd5d6b57b4650720ac5c00d03c954ab4e7ac19a282731fd625d4b0bbf3f480` |
| `diagnostics/inspect_qts_mfa.py` | `13e251c79cd4e86be18f380cdd02b67e74d2a286fafd1c35c1f88186806827ab` |
| `diagnostics/run_qts_power_trial.py` | `debdd759722760001fa54f8c263d1358f6bfe4db9a06613539a9b61b4d74a362` |

The library and MFA hashes match the values recorded during local preparation.
The literal candidate metadata from the physical trial is pending comparison.
The runner recorded hashes for the library and MFA adapter, and omitted a hash
of its own source. Its hash above was measured during preservation.

The archive is `source-snapshot-debdd759.zip`, SHA256
`74d886688bed8cdacaf2ed44438c5820602628812fdaf099b083fceb0d5bb490`.
`source-manifest.json` records every preserved file, archive integrity, the
capture environment and the pending link to the actual run metadata.
The archive and manifest remain private backups outside the proposed PR.

The provenance distinguishes the owner's physical observation, the local
source snapshot and the execution-hash comparison. Any response reconstructed
from the report must be labelled reconstructed. The supplied information
contains the owner's conclusions rather than a literal QNAP-TRIAL JSON block
or a raw CGI response.

## Trial closure

The owner validated this physical shutdown and subsequent power-on through
WOL. The later [reboot trial](reboot-01.md) has its own acceptance and remote
observation record. The owner considered the energy trial round satisfactory
and closed it. The source archive remains the historical snapshot of the
earlier shutdown draft, preceding the acknowledgement classifier and the
runner's later exit-code correction.
