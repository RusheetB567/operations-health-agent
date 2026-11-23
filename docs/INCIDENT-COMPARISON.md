# Incident comparison

Compare two reports produced by the service catalogue monitor:

```powershell
.\.venv\Scripts\python incident_compare.py reports/previous.json reports/current.json --output reports/changes.json
```

The result separates new failures, recovered services, ongoing failures, healthy services, additions, removals and configuration changes. Changing an endpoint, expected HTTP status, group or transport prevents a false recovery claim. A removed failed service is recorded as removed, never recovered.

Exit 0 means all services in the current report are healthy; 1 means at least one currently warns; 2 means invalid report input or file failure. Reports are compared in the order supplied, not sorted by timestamps. This compares two observations; it does not calculate uptime, incident duration or root cause. Host reports and log summaries are rejected.

Review the compared catalogue scopes: a changed group selection may appear as additions/removals. An internal worker error can omit target details and is conservatively treated as a configuration/identity change. Sensitive endpoint data remains local unless you publish the report yourself.
