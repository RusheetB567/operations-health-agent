# Running the health agent

Requires Python 3.11+. From the project directory on Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python system_health.py --samples 10 --consecutive 3 --output reports/health.json
.\.venv\Scripts\python system_health.py --tcp localhost:5432 --network-timeout 3
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Exit codes: `0` healthy final state, `1` active resource alert or failed dependency, `2` collection, persistence or argument error. Each resource sample takes approximately one second. Consecutive breaches must fit within the requested sample count.

## Alert behaviour

Each metric opens an alert after the configured consecutive breaches. An alert recovers strictly below its threshold minus five percentage points. Thresholds of five percent or less cannot recover within the same invocation. State resets between invocations.

The final metrics, active alerts and exit code reflect the end of the sampling window. `alert_events` preserves opening and recovery transitions with timestamps, sample numbers and measured values, so a recovered incident remains visible even when the final status is healthy. Event history is held in memory for the requested window; keep sample counts appropriate to available memory.

## Dependency checks

Repeat `--tcp HOST:PORT` for multiple dependencies; IPv6 uses `[::1]:443`. Checks run sequentially after resource sampling. Each target shares a DNS/TCP budget; resolver subprocess startup and cleanup can add overhead. Status distinguishes `reachable`, `dns_error`, `refused`, `timeout`, `unreachable` and internal `error`. TCP reachability does not verify application health, TLS or authentication. Only test authorised endpoints.

## Report persistence

Each writer uses a unique temporary file in the destination directory, flushes it, and replaces the destination. Concurrent successful writers leave one complete report; the last replacement wins. Windows permission conflicts receive bounded retries. A failed replacement preserves the previous destination and cleans up the temporary file. Persistent access failures return exit code `2`. This is not a durable event store or a guarantee against power loss.

Hostnames, addresses and metrics may be sensitive. Generated reports, virtual environments and Python caches are ignored by Git. Files already tracked remain tracked until explicitly removed from the index; review them before publishing.

## Verification

Nineteen tests passed on Windows with Python 3.13.15 and psutil 7.2.2. Coverage includes real loopback connectivity, simulated DNS/TCP failures, alert opening and recovery, invalid sampling configuration, concurrent writers, and failed replacement cleanup. A live three-sample run recorded a sustained memory alert and persisted valid JSON. Linux CI is configured but has not yet run.

## Persistent report history

Store the final report from each invocation in a local SQLite database:

```powershell
.\.venv\Scripts\python system_health.py --history-db reports/history.sqlite3 --max-reports 1000
.\.venv\Scripts\python system_health.py --history-db reports/history.sqlite3 --show-history 10
```

History queries return newest insertions first and do not collect fresh metrics. Query success returns exit code `0`, even if stored reports contain warnings. Missing or corrupt databases return code `2` without creating an empty database during a query.

Insertion and retention run in one database transaction. The default retains the newest 1,000 reports across the whole database, not per host. Each invocation stores its final report and alert transitions, not every raw sample. Retention limits row count, not file size; deleted SQLite pages can remain allocated for reuse. SQLite operations wait up to five seconds for a lock. There is no remote synchronisation or deduplication. JSON output and SQLite writes are separate operations: a later failure can leave a successful earlier write in place.

History can contain sensitive host and dependency details. Keep it in the ignored reports directory and restrict access. Twenty-three tests now pass on Windows, including retention, reopening, read-only queries, corrupt database handling and all existing diagnostics. A live save-and-read cycle also passed.

## HTTP readiness

A reachable TCP port does not prove the frontend or API is ready. Check each component explicitly:

```powershell
.\.venv\Scripts\python system_health.py --http http://localhost:8082/ --http http://127.0.0.1:3000/health --network-timeout 3
```

These are illustrative local addresses; replace them with your own running services. Each URL expects status 200 by default; `--http-status 204` changes the expected status for all URLs. Checks issue a GET, inspect headers and close without reading the response body. Redirects are reported as unexpected statuses rather than followed. HTTPS uses Python's default certificate verification. Each check has a subprocess timeout covering DNS and I/O, with process cleanup overhead possible.

Use dedicated, read-only readiness endpoints. URLs containing credentials, query strings, fragments or control characters are rejected. No login credentials or response bodies are stored. Connection and TLS failures are reported generically as connection_error. HTTP failures cause overall warning status and exit code 1. Application response headers and bodies are not retained.

Checking localhost and 127.0.0.1 independently can expose address-dependent availability, but cannot prove authentication, cookies, browser CORS behaviour or signup persistence. Those still require application-specific integration tests. A status-only check can also pass for an incorrect page; it does not validate page content.

## Failure regression coverage

- Backend reachable while frontend is unavailable: check both HTTP endpoints explicitly.
- Preview service stopped: a failed HTTP connection changes overall health to warning.
- Address-specific behaviour: URLs retain their requested host, allowing separate checks for local aliases.
- Port open while application is unhealthy: an HTTP 503 fails readiness.
- Redirect hides the expected endpoint: redirects are not followed automatically.
- Private exception output: HTTP subprocess stderr is excluded from reports.
- Partial persistence: a simulated retention failure rolls back the newly inserted SQLite report and preserves prior history.

Twenty-nine automated tests passed on Windows, including real local HTTP server responses, redirects, expected-status overrides, timeout handling and transaction rollback. Linux CI and checks against external applications remain unverified.

## Reusable monitoring profiles

```powershell
.\.venv\Scripts\python run_profile.py local-profile.example.json
```

Profiles are JSON objects using the existing CLI option names, without leading dashes. Repeated `tcp` and `http` targets are arrays. Unknown and duplicate options, booleans, nested values and oversized profiles are rejected. Existing CLI validation checks ranges and compatible sample counts. Paths resolve from the current working directory, not the profile directory. Profiles run only when invoked; they do not schedule background services. Review profiles before running: they can choose diagnostic targets and local output paths. Keep personal profiles and real endpoint details out of public commits.

## JSONL log summaries

```powershell
.\.venv\Scripts\python log_analyzer.py reports/synthetic-log.jsonl
```

The analyser streams a UTF-8 JSON object per line and counts DEBUG, INFO, WARNING, ERROR, CRITICAL and UNKNOWN severities. WARN maps to WARNING. Blank lines are ignored. Invalid JSON, invalid encoding and malformed records are counted. Lines over 65,536 bytes are discarded in bounded chunks, then parsing resumes at the next line.

The report contains aggregate counts only: raw messages, field values, exception traces and file contents are excluded. This deliberately avoids copying secrets instead of attempting incomplete message redaction. Errors, critical events, malformed records or oversized lines return exit code 1; an unreadable file returns 2. Warnings alone return 0. This is a finite file summary, not a live tailer or incident correlation engine. File processing time scales with total input size.

Verification: all 36 tests passed locally on Windows. A live profile collected and persisted metrics, and a synthetic log smoke test detected an error and malformed line without exposing the seeded secret. Remote CI and Linux execution remain unverified.

### Validate a monitoring profile without running it

```powershell
.\.venv\Scripts\python run_profile.py local-profile.example.json --check
```

Validation checks supported options, duplicate keys, exact integer types, numeric ranges, finite numbers, TCP/HTTP targets and compatible sampling counts. It does not collect metrics, contact configured targets, or write outputs. It cannot prove output permissions, service availability or correct installation. Success returns 0; invalid profiles return 2.
