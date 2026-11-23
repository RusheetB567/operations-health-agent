# Troubleshooting runbook

Record the command, exit code, current working directory and sanitised report before changing configuration. Do not paste credentials or private log lines into issues.

| Symptom | Check | Action |
| --- | --- | --- |
| Python command fails | Is the virtual environment installed? | Use the explicit interpreter path from the quickstart |
| Missing psutil | Was the dependency installed in that interpreter? | Run that interpreter with `-m pip install -r requirements.txt` |
| Valid profile, failed run | Validation does not prove service availability or output permissions | Inspect diagnostic results and destination permissions |
| CPU spike causes alerts | Sample count and consecutive threshold | Require multiple consecutive breaches within the requested window |
| Alert does not recover | Value must fall strictly below threshold minus five points | Review actual values; thresholds at or below five cannot recover in the same run |
| TCP reachable, application unavailable | TCP checks only the listener | Add a dedicated HTTP readiness endpoint |
| HTTP 302 | Redirects are deliberately not followed | Configure the final read-only health URL |
| HTTP 401/403 | Endpoint requires authentication or policy access | Use a suitable unauthenticated readiness endpoint; do not embed credentials |
| HTTP connection_error | Service, DNS or TLS failure | Verify address and certificate separately; do not disable TLS verification |
| localhost works but numeric address fails | Application host/origin behaviour | Check both explicitly; use app integration tests for login/cookies |
| One group unexpectedly empty | Exact group name and catalogue validity | Validate the full catalogue and select an existing group |
| History database error | Missing, corrupt, locked or incompatible database | Preserve a copy; verify the path; stop conflicting writers before recovery work |
| History file remains large | Row retention does not shrink allocated pages | Plan database maintenance separately; do not delete evidence impulsively |
| Report write fails | Destination is a directory, permission denied or conflict | Choose a writable file path; previous report should remain intact |
| Log marked warning | Error/critical entries or malformed/oversized lines | Review counts and investigate the original log locally |

## Investigation workflow

1. Run validation-only mode first.
2. Check host pressure, then each named application dependency.
3. Distinguish stopped listeners, wrong HTTP status, timeouts and host-origin differences.
4. Preserve local evidence and compare with history.
5. Apply a reviewed application or infrastructure fix.
6. Repeat the same checks and verify recovery; do not infer success from a process merely starting.

This tool diagnoses. It does not restart applications, repair databases or change authentication settings.
