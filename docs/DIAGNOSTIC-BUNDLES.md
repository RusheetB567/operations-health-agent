# Diagnostic bundles

Run an application catalogue and save the raw report, dashboard and manifest together:

```powershell
.\.venv\Scripts\python run_diagnostics.py services.example.json --output-dir reports/runs
```

Each run has a unique `run-*` directory containing `services.json`, `dashboard.html` and `manifest.json`. With an explicit baseline, the bundle also includes `changes.json` and dashboard transitions:

```powershell
.\.venv\Scripts\python run_diagnostics.py services.example.json --output-dir reports/runs --previous reports/runs/run-EXAMPLE/services.json
```

Replace the illustrative baseline path with a real previous report. `latest.json` in the output directory identifies the last completely written bundle. The baseline is not automatically chosen, preventing a surprising comparison against a different catalogue or group.

Validation and baseline loading happen before network probing or bundle creation. A warning run is still a successfully collected bundle and returns exit 1. All healthy returns 0; configuration or output failure returns 2. `--group` and `--workers` follow the service-monitor behaviour.

Each run writes into a distinct directory. The latest pointer updates only after all artifact writes succeed. A failed run can leave an incomplete directory, but does not replace the previous pointer. This is not a single filesystem-wide transaction or a crash-proof store. Concurrent successful runs use last-pointer-update-wins semantics, not chronological ordering.

No automatic bundle deletion or storage quota is implemented; manage retention yourself. Reports and dashboards include operational endpoints. Keep the output under ignored local reports and review before sharing. This command does not start applications, schedule continuous checks, upload reports, or perform repairs.

## Verify saved artifacts

New bundles include SHA-256 digests for their report, dashboard and optional changes file in manifest.json. Run `.\.venv\Scripts\python artifact_integrity.py reports/runs/run-EXAMPLE` with an actual bundle path. Exit 0 means all recorded artifacts match; 1 means changed or missing files; 2 means an invalid manifest or inaccessible input. Artifact paths cannot escape the bundle directory.

These checks detect accidental changes, not malicious tampering by someone who can rewrite both files and manifest. The manifest is not signed, extra unlisted files are not checked, and old bundles without checksums cannot be verified by this command.
