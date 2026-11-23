# Offline service dashboard

```powershell
.\.venv\Scripts\python render_dashboard.py reports/current.json --previous reports/previous.json --output reports/dashboard.html
```

Omit `--previous` for a standalone snapshot. Open the resulting HTML file in a browser. It shows healthy/warning totals, named service results and optional incident transitions. Counts are calculated from validated service rows rather than trusting a supplied summary.

All dynamic text is HTML-escaped. The document has a restrictive content policy, no scripts, no forms and no remote assets. It is a static report, not a live dashboard, and has no automatic refresh. Targets appear as plain text, not executable links. Review operational details before sharing the file.

Successful rendering returns exit 0 even for a warning snapshot: rendering succeeded, and service health is shown inside the report. Invalid input or a failed write returns 2. Generated output belongs under ignored local reports. JSON service reports only; host reports and log summaries are rejected.

## Hide endpoints in HTML

Add --redact-targets to omit HTTP URLs and TCP host/port values from rendered HTML. Service names, groups and timestamps remain visible; review before sharing. Input JSON is unchanged and still contains targets. This flag does not anonymise the complete report or its other artifacts.

## Triage order

The table lists warnings before healthy services, then sorts by group and service name. Group health totals are computed from the service rows and shown separately, making it easier to identify which part of an application needs investigation. These display changes do not reorder the source JSON report.
