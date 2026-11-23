# Report contracts

The report families are distinct. A shared `schema_version: 1` does not mean they have interchangeable structures. Consumers should know which command produced the report and tolerate additive fields.

## Host reports

Contain UTC timestamp, hostname, operating system, disk path, sampling settings, final metrics, active alerts, alert events, dependency results and HTTP checks. `status` describes the final state. A recovered alert can remain in `alert_events` while status is healthy.

An alert event contains the metric, opening/recovery state, sample number, timestamp, measured value and threshold. State is reset when the next invocation starts.

## Service reports

Illustrative combined report (timings and timestamp omitted here):

```json
{
  "schema_version": 1,
  "status": "warning",
  "summary": {"total": 2, "healthy": 1, "warning": 1},
  "groups": {"application": {"healthy": 1, "warning": 1}},
  "services": [
    {"name": "web", "group": "application", "type": "http", "status": "healthy", "detail": {"status": "ready", "http_status": 200}},
    {"name": "api", "group": "application", "type": "http", "status": "warning", "detail": {"status": "unexpected_status", "http_status": 503}}
  ]
}
```

Service detail preserves the underlying check's result. HTTP outcomes include `ready`, `unexpected_status`, `connection_error`, `timeout` and `error`. TCP outcomes include `reachable`, `dns_error`, `refused`, `timeout`, `unreachable` and `error`. A worker exception becomes `internal_error` without exception text.

## Log summaries

Contain valid-record count, malformed/oversized line counts and fixed severity buckets. Unknown level strings become `UNKNOWN` and are not echoed. Raw messages and arbitrary fields are absent. WARN normalises to WARNING. Warnings alone do not make the command return 1.

## Storage boundaries

Host and service reports can be written atomically to JSON files. Only the host monitor currently writes to SQLite history. History queries return an array, newest insertion first, and read without collecting metrics.

No command automatically uploads reports. Generated operational reports should stay out of Git; `.gitignore` does not remove files already tracked. Backups and file permissions remain the operator's responsibility.
