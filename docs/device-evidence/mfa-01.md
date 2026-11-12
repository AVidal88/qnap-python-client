# TS-431P interactive MFA observation 01

The NAS owner reported a successful run of `inspect_qts_mfa.py` against a
QNAP TS-431P running QTS 5.2.11.3661.

## Provenance

- Source is the owner's conclusions supplied in this conversation.
- The message did not contain a literal `[QNAP-AUTH]` JSON block or raw XML.
- Exact execution time was not supplied.
- Transport was HTTPS on port 443, with certificate verification explicitly
  omitted using `--no-verify-ssl`.
- The owner supplied the NAS IPv4 address locally. Network and account
  identifiers are omitted from this record.

## Reported observations

| Stage | Observation |
| --- | --- |
| First authentication | MFA challenge, with no SID |
| Second authentication | `authPassed=1` and SID present |
| Second-factor indicators after success | `need_2sv=1` and `need_2_step_verification=1` |
| Authenticated validation | Confirmed the expected user |
| Session logout | A response was received. Revocation was not checked |

The separate local test adapter completed password plus manual TOTP
authentication on this model and firmware. Its completed-session decision
evaluates `authPassed=1` and a valid SID before interpreting the retained
second-factor indicators.

## Package boundary and test provenance

The diagnostic and power runner are separate trial infrastructure outside the
proposed library package and PR. The adapter retains its newly obtained SID
in memory and binds that authenticated session to the candidate's public
power methods. The library's public `login()` continues to perform password
authentication and reports a pending challenge through
`QnapTwoStepRequiredError`. General interactive MFA, persistent credentials
and session renewal remain separate contributions. The standard password
login supplies the session used by the public power implementation.

Any XML built from this summary is a reconstructed test fixture. Its element
order, wrappers, unreported fields and exact response bodies remain unavailable.
Label that XML as reconstructed and retain this provenance in the tests.

The adapter's authenticated session was retained for the subsequent
[shutdown](shutdown-01.md) and [reboot](reboot-01.md) trials. The owner
validated the physical shutdown and subsequent WOL power-on, and accepted
the reboot acknowledgement with a remotely observed availability cycle.
The energy trial round is closed. Minimum permissions, persistent credentials
and logout revocation remain unverified.
