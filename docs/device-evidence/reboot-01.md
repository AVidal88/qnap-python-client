# TS-431P reboot API observation 01

The NAS owner reported one reboot trial through the existing Python runner on
their QNAP TS-431P running QTS 5.2.11.3661. The library recognized the CGI
acknowledgement and returned normally. A subsequent local executor error
produced a second, conflicting summary. The owner later reported that the NAS
became remotely unavailable for an unmeasured interval and then accessible
again. Post-reboot uptime and physical inspection were unrecorded. The owner
considered this evidence satisfactory and closed the energy validation round.

## Provenance

This record normalizes the fields supplied by the owner in the conversation.
The visible message contains field summaries rather than a literal complete
`[QNAP-TRIAL]` JSON block or raw CGI XML. Exact execution time and the trial's
candidate metadata were not supplied. Any XML reconstructed from these fields
must retain that reconstructed provenance.

## Reported API and executor observations

| Field | Owner-reported value |
| --- | --- |
| Operation | `reboot` |
| `authPassed` | `1` |
| `setting_result` | `0` |
| `cgi_acceptance` | `accepted` |
| `library_outcome` | `returned_normally` |
| `power_post_requests_started` | `1` |
| `request_result` in the first final summary | `accepted` |
| `post_matches_preflight_text` | `true` |
| Subsequent executor `error` | `trial_failed` |
| Subsequent executor `error_category` | `internal_error` |
| Subsequent executor `exception_class` | `KeyError` |
| `request_result` in the subsequent error summary | `unknown` |
| Remotely observed behavior | NAS became unavailable and later accessible again |
| Availability interval | Unmeasured |
| Post-reboot uptime | Unrecorded |
| Physical inspection | Unperformed |
| Owner's assessment | Satisfactory for proceeding with the contribution, validation round closed |

The first summary is positive real-device evidence for the acknowledgement
classifier described in [power-api-evidence.md](../power-api-evidence.md).
The separate local failure occurred after the library had returned and the
runner had printed acceptance. The API observation remains accepted.

The remote availability cycle is recorded independently from that acceptance.
It is the owner's observed behavior during this trial. Its evidence is limited
to remote access and the reported CGI response on this model and firmware.

`post_matches_preflight_text=true` records equality of the complete decoded
preflight and POST response text compared in memory by the runner. It supplies
more information than matching lossy summaries. That equality establishes
neither inactive jobs nor completion of the physical reboot. The preflight's
warning-list interpretation retains its unresolved status. CGI acceptance
uses the fixed action request and the coherent acknowledgement fields.

## Exact local failure

In the preserved pre-fix `diagnostics/run_qts_power_trial.py`, line 691 printed
the final result. Lines 695–697 then indexed the exit-code dictionary with
`result["request_result"]`. The request result existed and contained
`accepted`. The dictionary contained only `unknown`, `rejected` and
`not_submitted`, so the missing dictionary key was `accepted`.

The outer exception handler at lines 710–723 emitted `trial_failed` and chose
`request_result=unknown` from the `trial_started` flag. It discarded the
already recorded API result when constructing that error summary. These two
local defects explain the output sequence without requiring another NAS
request. The correction and its offline regressions belong to the existing
runner and preserve API results independently of later executor failures.

The correction adds the explicit `accepted: 0` exit code and calculates the
exit status before final output. A returned API record is retained during
later processing and output. Any subsequent local failure is recorded in
`executor_error` and `executor_result`, preserving its original request result,
library outcome, acknowledgement, comparison and physical-observation fields.

The owner's sanitized projection reproduced the failure offline before the
fix. The regression now passes with one final block and exit status zero.
Tests also retain rejection/unknown/not-submitted exit codes, both operations,
single invocation, and preservation of recorded API outcomes during output
errors and cancellation. A missing result key still reports a local error
without an invented default. Historical validation of this offline correction
passed 116 Python diagnostic tests and 90 library tests. Ruff and format checks
passed on the runner and its tests at that stage.

The corrected runner observed after that offline validation has SHA256
`e103d8b4308accb21ffcfebff615773a140e528abea548fc0aedfe19eff47640`.
Its test file has SHA256
`6a54964ad3ace109dfd0f0c11428216dadca73f97cf45bed46e81967c00a8312`.
The actual NAS trial preceded this correction and used the earlier runner
identified in the preserved-source table below. These are separate versions
with separate validation records.

## Offline consolidation after trial closure

Further offline review found that cancellation during local client cleanup or
failure while closing the runner's HTTP session could prevent an already
recorded API result from reaching the final report. The existing runner now
preserves that result, retains the first local error and keeps cancellation
status independent of the operation outcome. Main reports the local failure
through `executor_result` and `executor_error` while preserving acceptance,
rejection or uncertainty from the API.

The previous KeyError-fixed runner and tests remain in the private archive
`source-runner-keyerror-fix.zip`, SHA256
`9ba37bce1658e8f5fbb9898efa77060ec954b40e2773fbc3ba5ca38fbbde102a`.
The consolidated runner SHA256 is
`cb8883ae4da1f2d7a64ef85ebb1af2569da4ad25bd3f96a4e6d18887ea2366b3`,
and its tests SHA256 is
`fde663c206a938adff7775446caed4813368379a37bf28ce9aba05174fcd6871`.
They are preserved privately in `source-runner-consolidated.zip`, SHA256
`5a6698d7b5b4575d186da529d844f50b325b9952226a11b3f1400687100322c2`.
The adjacent manifest identifies both offline revisions separately from the
earlier hardware trial snapshot.

The cleanup regression fails against the earlier offline runner and passes
after consolidation. All 120 Python diagnostic tests passed, including 45
runner tests. Both offline runner revisions postdate the real reboot trial.
The request guard, public power-method adapter, TLS selection and existing
authentication calls retain their behavior. These executors remain outside
the package and proposed PR.

## Preserved source and comparison status

The local source was captured after the owner's report and before the runner
fix at `2026-11-12T18:26:54.320033+00:00`. The candidate worktree was
`python-qnap-power-pr`, branch `feat/qts-power-api-pr`, based on
`4792a60e0175c6eda31e18474c245d98f926d681`, with local changes included.

The workspace archive is
`artifacts/qts-reboot-01/source-before-runner-fix.zip`, SHA256
`6c5843528c8111743364d0409a9303c5441301e6cc87e5c380b0067d7d8f5a3f`.
Its adjacent `source-manifest.json` lists all nine preserved files and their
hashes, records the owner-reported observations, and marks the comparison
with actual owner-run metadata as pending.

| Preserved source | SHA256 measured at local preservation |
| --- | --- |
| `diagnostics/run_qts_power_trial.py` | `c8a082c1e255dc341dc96ec3546dde3f1c5b87debec2b8c736e8ee243dab6e0d` |
| `diagnostics/inspect_qts_mfa.py` | `13e251c79cd4e86be18f380cdd02b67e74d2a286fafd1c35c1f88186806827ab` |
| `qnap_client/client.py` | `6755ee26bc3e9aa23b3664e5df2ef5512ff96fb042732bf1ff9d19efadf63fd1` |
| `qnap_client/exceptions.py` | `9549910981ccac7fb73a1c61d7b097e88c5b66abb18944c15cf0fcf2ecedd74d` |

These hashes identify the preserved local snapshot. Linking them to the
specific execution awaits the owner's existing candidate metadata. The
archive contains source files and the manifest records normalized evidence.
No raw CGI response is available in this preservation record.
The archive and manifest remain private backups outside the proposed PR.

## Trial closure

The owner accepted the CGI acknowledgement and remote availability cycle as
satisfactory for this contribution and closed the energy trial round.
The local exit-code defect was corrected and validated offline afterward.
The acceptance, remote observation and offline correction retain their own
evidence and provenance. Further power trials are outside the current scope.
