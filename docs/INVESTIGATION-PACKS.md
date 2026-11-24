# Investigation packs

Build a local review package from a monitoring session and one or more JSONL logs:

```powershell
.\.venv\Scripts\python investigation_pack.py examples/session-timeline.json examples/incident-logs.jsonl --window-seconds 30 --output-dir reports/investigations
```

The synthetic example intentionally returns warning exit 1. It still saves a complete, verified pack. Use the returned bundle path to inspect timeline.html and investigation-notes.md.

## Artifacts

Every unique `run-investigation-*` directory contains five artifacts and a manifest:

| Artifact | Purpose |
| --- | --- |
| session-observations.json | Whitelisted service/event/cycle/time fields only |
| log-summary.json | Privacy-safe severity, pattern and quality summary |
| timeline.json | Service windows, pattern-span matches and uncertainty flags |
| timeline.html | Standalone offline evidence review |
| investigation-notes.md | Review order, interpretation and handling notes |
| manifest.json | Roles, parameters, counts and SHA-256 digests |

Raw logs, complete source sessions, arbitrary metadata and source file paths are not copied. Service labels, timestamps, categories and per-run fingerprints remain visible; this is privacy reduction, not complete anonymity. A local CLI result includes the output path so the operator can open the pack; that path is not recorded inside its artifacts.

## Controls and publication

--since and --until accept timezone-aware ISO timestamps. --max-lines defaults to 100000, --max-patterns to 1000, --max-matches to 10 and --window-seconds to 60. Pattern storage is capped at 1000 here to fit the timeline's input limit. Multiple log paths are processed as supplied, so duplicate inputs count twice.

Input validation and report generation finish before output creation. Every run uses a new directory. The command writes all artifacts, writes the manifest and verifies the recorded hashes before updating latest.json. If a write or verification fails, earlier complete evidence and the previous latest pointer remain untouched. A partial failed-run directory can remain; it is not silently deleted.

Files use individual atomic replacement, not a filesystem-wide transaction. Concurrent successful publishers use last-pointer-update-wins semantics. A process crash can leave an incomplete pack. No automatic pruning, archive upload, scheduling or application remediation is provided.

## Verification and interpretation

```powershell
.\.venv\Scripts\python artifact_integrity.py reports/investigations/run-investigation-EXAMPLE
.\.venv\Scripts\python audit_bundles.py reports/investigations
```

Replace the illustrative directory with an actual result. The existing read-only audit recognises the manifest's report/dashboard roles and verifies all five artifact checksums. Checksums are not signatures; changing files and manifest together can defeat them.

Temporal overlap is not proof of causality, log ownership or individual events within a window. Pattern counts cover their entire span. Clocks are not verified. Review [timeline limitations](INCIDENT-TIMELINE.md) and [log triage](LOG-TRIAGE.md) before interpreting apparent proximity.

Exit 0 means generation succeeded with healthy evidence; 1 means a complete pack containing warning/limited evidence; 2 means invalid configuration, unavailable inputs or failed persistence/integrity verification. Warning content and corrupt artifacts are separate concepts.
