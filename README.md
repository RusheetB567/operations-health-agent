# Operations Health Agent

Diagnose host resource pressure and application availability from a local command line. Capture useful evidence, distinguish service failures, and keep a local report history.

## What it does

- Collects CPU, memory, disk and uptime metrics with configurable sustained alerts.
- Checks named frontend, API and database services with bounded parallel HTTP/TCP probes.
- Groups service results into a combined JSON health report.
- Stores final host reports in SQLite with record-count retention.
- Summarises JSONL log severity without copying raw log fields.

The diagnostic commands run when invoked and stop afterward. The optional console runs until its terminal is stopped, with opt-in scheduled service checks. They do not install background monitoring, upload reports or repair applications automatically.

## Start here

Requires Python 3.11 or newer. From the repository root on Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python tools/demo_local.py
```

The self-contained demo starts a temporary loopback service, simulates an outage and recovery, demonstrates history and log analysis, and removes temporary data afterward. No external applications or credentials are required.

For your own environment:

```powershell
.\.venv\Scripts\python run_profile.py local-profile.example.json --check
.\.venv\Scripts\python run_profile.py local-profile.example.json
.\.venv\Scripts\python service_monitor.py services.example.json --check
```

Review the catalogue's illustrative targets before running actual service checks. Exit 0 means healthy, exit 1 means a diagnostic warning, and exit 2 means an operational or configuration error for monitoring commands.

## Documentation

| Guide | Purpose |
| --- | --- |
| [Quickstart](docs/QUICKSTART.md) | Install, try the local demo, then monitor your environment |
| [CLI reference](docs/CLI.md) | Commands, options and exit codes |
| [Service catalogue](SERVICE-CATALOGUE.md) | Named checks, groups and configuration schema |
| [Architecture](docs/ARCHITECTURE.md) | Data flow, persistence and design boundaries |
| [Report contracts](docs/REPORTS.md) | Host, service and log output formats |
| [Troubleshooting](docs/RUNBOOK.md) | Interpret failures and verify recovery |
| [Detailed operations](OPERATIONS.md) | Implementation behaviour and operational limits |
| [Contributing](CONTRIBUTING.md) | Verification and review practices |
| [Release review](docs/RELEASE-REVIEW.md) | Checklist before publication |

## Verification and limits

Run the full suite with `.\.venv\Scripts\python -m unittest discover -s tests -v`. Additional commands check documentation links and test sensitivity to known defects; see the contributor guide.

Local checks are verified on Windows. Prepared CI targets Windows and Linux, but remote execution must be checked before claiming a cross-platform release. HTTP status alone does not prove successful login or correct page content. Alert state resets between runs. SQLite retention bounds record count rather than physical database size.

Hostnames and service addresses can be sensitive. Keep operational reports and local databases out of public commits; ignore rules do not remove already-tracked files.

## Engineering notes

- [Initial monitoring and reliability](DAY-ONE-REPORT.md)
- [Profiles and named services](DAY-TWO-REPORT.md)
- [Regression verification](DAY-2.2-VERIFICATION.md)
- [Documentation and reproducible demo](DAY-2.3-REPORT.md)

## Offline analytics and export

Generate a numeric dashboard and reviewable exports from synthetic data:

```powershell
.\.venv\Scripts\python render_dashboard.py examples/service-snapshot.json --output reports/dashboard-preview.html --csv-output reports/dashboard-preview.csv --analytics-output reports/dashboard-analytics.json --redact-targets
```

Includes group health percentages, P50/P95 probe durations, slow-check highlights, warning/group filters and standard CSV export. These are snapshot statistics rather than historical uptime. See [dashboard analytics guide](docs/OFFLINE-DASHBOARD.md) for commands, safety boundaries and statistical definitions.

## Repeated monitoring sessions

Run a finite sequence of catalogue checks, preserve each bundle and track incident opening/recovery. See [monitoring sessions](docs/MONITORING-SESSIONS.md), or try `.\.venv\Scripts\python tools/demo_session.py` for a self-contained loopback demonstration.

## Application log triage

Use timezone windows and recurring-error groups while excluding raw log fields from output. See [log triage](docs/LOG-TRIAGE.md) and the [Day 3.1 report](DAY-3.1-REPORT.md).

```powershell
.\.venv\Scripts\python triage_logs.py examples/incident-logs.jsonl --output reports/log-triage.json
```

## Investigation packs

Combine monitoring observations, privacy-safe log triage and the incident timeline into a verified local package. See [investigation packs](docs/INVESTIGATION-PACKS.md).

```powershell
.\.venv\Scripts\python investigation_pack.py examples/session-timeline.json examples/incident-logs.jsonl --window-seconds 30 --output-dir reports/investigations
```

The synthetic example returns warning status while producing a complete integrity-verified pack. Raw logs are not copied into it.

## SignalDesk browser console

Double-click `Start-SignalDesk.cmd` to manage local services, investigate incidents and run scheduled HTTP/TCP checks in the browser. Read [the console guide](docs/WEB-CONSOLE.md), [incident workflow](docs/DAY-4.1-REPORT.md), and [scheduled-check workflow](docs/DAY-4.2-REPORT.md).
