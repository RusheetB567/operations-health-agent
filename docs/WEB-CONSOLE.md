# SignalDesk local operations console

SignalDesk connects the existing diagnostics to a usable browser workspace. It runs on this device and supports local HTTP and TCP services.

## Launch

Double-click `Start-SignalDesk.cmd` in the repository, or run:

```powershell
.\.venv\Scripts\python.exe console_app.py --open
```

Open <http://127.0.0.1:8765>. Leave the terminal open; press Ctrl+C there to stop. If the port is occupied, use `--port 8766`. A fresh checkout needs Python 3.11+, a `.venv`, and `pip install -r requirements.txt` first.

## Try the complete workflow

1. Select **Start local lab**. Three endpoints are checked using the existing probe implementations. The worker deliberately returns HTTP 503: expect two healthy services and one warning.
2. Select **Recover lab worker**. A new check should show three healthy services. Open **Check history** to inspect both observations.
3. Under **Services**, add an actual loopback endpoint. Edit its expected status or target, pause it, or check it individually. Changing its configuration invalidates its previous current-health observation while preserving history.
4. Under **Log triage**, load the sample, paste JSONL, or select a local file. Analyse it to see categories and private recurring-pattern fingerprints. The input field is cleared after success. The backend removes its temporary input file and saves only the summary.
5. Under **Evidence library**, verify an existing investigation pack and open its sandboxed timeline. Packs are read from `reports/investigations/run-*`; they are not modified by the console.

## Storage and limits

The SQLite database is `reports/console/console.sqlite3`, covered by the repository's existing generated-report ignore rule. Service settings and observations persist across restarts. Queued/running jobs interrupted by a restart are marked interrupted rather than reported as successful.

- Up to 50 services; at most one check run at a time, with four concurrent probes.
- At most 10 seconds per probe. Scheduled checks are opt-in at intervals of 10–3,600 seconds; no automatic repairs.
- Keep 200 runs; display the latest 30.
- Keep 20 triage summaries; accept up to 262,144 input characters, scan at most 10,000 lines and group up to 100 patterns. The upload picker caps file size at 256 KiB.
- List up to 30 investigation packs. Verification results are session-only and must be rerun after restart or external changes.

Health cards show the latest completed observation for each enabled service. They are snapshots, not continuous monitoring or uptime percentages. P95 is calculated from those observations and includes probe process overhead. Lab endpoints exist only while the console is running; start the lab again after changing the console port.

## Local access boundary

The server binds only to `127.0.0.1` and accepts loopback targets. It checks Host and Origin, requires a fresh per-process token for mutations, rejects cross-origin API access, bounds JSON requests, and escapes user values in the UI. Timeline pages receive a restrictive sandbox policy. No CDN assets or telemetry are loaded.

This is a local development console, without user accounts or remote agent authentication. Do not expose it through a tunnel or public reverse proxy. Authenticated multi-user access and remote collectors need a separate implementation before hosted use.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The console integration tests exercise actual HTTP requests, failure/recovery probes, CRUD, configuration revisions, persistence, interrupted jobs, concurrent-run rejection, request protection, raw-log privacy, and evidence sandboxing.

## Scheduled checks

Use Overview to start, stop or update a schedule. The first check runs after the selected interval. Busy intervals are skipped and paused services are excluded. Check history labels each run as manual or scheduled. The interval persists, but scheduling always starts stopped after a console restart. Closing the browser does not stop an enabled schedule; stop it in Overview or close the console terminal. See [the Day 4.2 report](DAY-4.2-REPORT.md).

## Incident response

Open the Incidents tab to acknowledge failures, assign an owner, add investigation notes and inspect automatic recovery. See [the Day 4.1 workflow](DAY-4.1-REPORT.md) for steps, storage limits and behaviour when services change. Incidents are created by new checks; previous runs are preserved without backfilling incidents.

## Maintenance windows

In Services, select Maintenance to exclude a service for 1–1,440 minutes with a required reason. Both manual and scheduled checks skip it. End the window early from maintenance history, or let it expire. The next eligible check provides a fresh health observation; existing incidents stay open until recovery is observed. Paused services stay paused. Windows persist across restarts. See [the Day 4.3 report](DAY-4.3-REPORT.md) for limits and verification.

## Compare check runs

In Check history, select an older baseline and a newer completed run, then select Compare runs. The results distinguish failures/recoveries from configuration revisions, maintenance boundaries and changes in which services were checked. Timing differences are shown only for comparable observations. See [the Day 4.4 report](DAY-4.4-REPORT.md).

## Export incident reports

Open an incident and choose Markdown or JSON under Export incident report. Notes are excluded unless selected. Preview first, then download the exact previewed snapshot. Reports contain local addresses and ownership labels, so review them before sharing. The preview and API were verified; saving a download from the in-app browser could not be confirmed. Use the local console in your normal browser to check file saving. See [the Day 4.5 report](DAY-4.5-REPORT.md).

## Save a local report copy

After previewing an incident report, select Save local copy. The exact preview is saved atomically under reports/incident-exports, and its path, byte count and checksum appear in the dialog. Previews expire after 15 minutes; only the latest eight remain available. Re-preview if needed. Existing saved files are preserved and ignored by Git. This flow was verified independently of browser downloading. See [Day 4.6](DAY-4.6-REPORT.md) and [the Day 4 wrap-up](DAY-FOUR-WRAP-UP.md).

## Service reliability objectives

Open Reliability and choose Set objective to save a target, lookback window and minimum sample count per service. Assessments use retained completed checks for the current configuration and maintenance cycle. They show sampled-check health, not continuous uptime or a request-level SLA. Suggested defaults remain labelled until saved. See [the Day 5 report](DAY-FIVE-REPORT.md) for calculation examples and limits.

## Reliability history

On Reliability, select View history to inspect twelve time buckets, evidence gaps, warning streaks, P95 probe duration and the latest matching observations. Trends require at least six observations and the objective minimum, compare equal groups and remain descriptive. Close and reopen to refresh. See [Day 5.2](DAY-5.2-REPORT.md) and [the Day 5 wrap-up](DAY-FIVE-WRAP-UP.md).
