# TS-431P preflight observation 01

The owner supplied this sanitized summary from a QNAP TS-431P running
QTS 5.2.11.3661. One GET to `/cgi-bin/sys/sysRequest.cgi` used
`subfunc=power_mgmt` and `apply=chk_shutdown_running` through an existing
Chrome session authenticated with MFA. Exact execution time, raw XML and
response headers beyond the reported MIME remain unavailable.

```text
[QNAP-DIAG] INICIO
[QNAP-DIAG] HTTP: 200
[QNAP-DIAG] Tipo de contenido: text/xml
[QNAP-DIAG] XML válido: sí
[QNAP-DIAG] Raíz QTS reconocida: sí
[QNAP-DIAG] authPassed: 1
[QNAP-DIAG] Estado previo Rsync: ausente
[QNAP-DIAG] Estado previo VMs: ausente
[QNAP-DIAG] Estado previo RTRR: ausente
[QNAP-DIAG] Estado previo ssd_cache_upgrading: ausente
[QNAP-DIAG] Otros estados o duplicados: 0
[QNAP-DIAG] FIN
```

The diagnostic used `getElementsByTagName("item")`. Its output establishes zero
matches for that exact tag. It does not establish the number of prefixed
`item` elements or the complete response structure.

This is an actual summary observation. Any XML used to exercise a similar
summary in unit tests remains synthetic until an actual sanitized structure
is established.

## Later structural summary supplied by the owner

The owner subsequently reported these results from the structural diagnostic.
This is a transcription of their description rather than a literal console log.

- There were 31 XML elements.
- There were 28 elements outside the diagnostic's fixed tag allowlist.
- Counts of `item` and `status` elements were zero.
- Namespaces and prefixes were absent.
- The printed tree was truncated.

The counters inspect the full parsed document. Tree truncation affects only
printed nodes. This observation excludes prefixed/namespaced `item` as an
explanation for the selector result. The hidden schema and full hierarchy
still require interpretation before establishing which response was returned.
Job activity and successful execution of the power precheck remain unresolved.

Both browser diagnostics set `redirect: "manual"`. Their method, CGI path and
fixed `subfunc`/`apply` query parameters match the inspected official frontend.
The raw response is unavailable for further local parsing. No XML fixture is
derived from these counts.

The later reboot trial recorded `post_matches_preflight_text=true`, comparing
its own complete decoded GET and POST response text in memory. That separate
observation is retained in [reboot observation 01](reboot-01.md). The owner
closed the energy validation round after the power trials. Interpretation
of missing warning items remains a documented limit of the preflight evidence.
