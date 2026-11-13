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
