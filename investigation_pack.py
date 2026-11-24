"""Build a local privacy-reduced investigation pack from a session and JSONL logs."""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from artifact_integrity import digest, verify
from incident_timeline import CAUTION, align, load_evidence, render_timeline
from system_health import write_report
from triage_logs import time_argument, triage


def notes(timeline, summary):
    stats = timeline["summary"]
    return f'''# Investigation evidence

This pack is a diagnostic snapshot, not a root-cause determination.

- Service observations: {stats["service_events"]}
- Selected log records: {stats["selected_log_records"]}
- ERROR/CRITICAL records: {stats["error_records"]}
- Events with overlapping pattern spans: {stats["events_with_span_overlap"]}
- Evidence coverage limited: {timeline["quality"]["coverage_limited"]}
- Physical log lines scanned: {summary["counts"]["lines_scanned"]}

## Review order

1. Open timeline.html for service observations and coarse pattern evidence.
2. Inspect timeline.json for alignment boundaries and quality flags.
3. Review log-summary.json for grouped counts and processing limits.
4. Check session-observations.json for the minimal service-event input.
5. Verify the artifacts against manifest.json before relying on a copied pack.

## Interpretation

{CAUTION}

Pattern counts cover their entire observed span. Service/log ownership and clock
synchronisation are not verified. No overlap is not proof of absence.

## Privacy and handling

Raw logs, arbitrary input metadata and source paths are excluded. Service labels,
timestamps, categories and per-run fingerprints remain visible. Review all
artifacts before sharing. Source files are not modified by this command.

SHA-256 checks detect accidental changes relative to this manifest. They are not
signatures and do not prove authenticity if both artifacts and manifest change.
'''


def build(session_path, log_paths, output_dir, since=None, until=None,
          window_seconds=60, max_lines=100000, max_patterns=1000, max_matches=10):
    if not log_paths or type(max_patterns) is not int or not 1 <= max_patterns <= 1000:
        raise ValueError("require logs and 1–1000 patterns")
    output_dir = Path(output_dir)
    sources = {Path(path).resolve() for path in [session_path, *log_paths]}
    if (output_dir / "latest.json").resolve() in sources:
        raise ValueError("latest pointer would overwrite source evidence")
    session = load_evidence(session_path)
    # Validate event schema/options before reading potentially large log inputs.
    align(session, {"schema_version": 1, "patterns": [], "counts": {"selected_records": 0},
                    "levels": {}, "truncated": False}, window_seconds, max_matches)
    summary = triage(log_paths, since, until, max_lines, max_patterns)
    timeline = align(session, summary, window_seconds, max_matches)
    observations = {"schema_version": 1, "events": [{key: event[key] for key in (
        "service", "event", "cycle", "timestamp")} for event in timeline["timeline"]]}
    payloads = {
        "session-observations.json": json.dumps(observations, indent=2) + "\n",
        "log-summary.json": json.dumps(summary, indent=2) + "\n",
        "timeline.json": json.dumps(timeline, indent=2) + "\n",
        "timeline.html": render_timeline(timeline),
        "investigation-notes.md": notes(timeline, summary),
    }
    # Input validation and report generation finish before creating output artifacts.
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = Path(tempfile.mkdtemp(prefix="run-investigation-", dir=output_dir))
    for filename, payload in payloads.items():
        write_report(bundle / filename, payload)
    files = {"report": "timeline.json", "dashboard": "timeline.html", "observations": "session-observations.json",
             "log_summary": "log-summary.json", "notes": "investigation-notes.md"}
    manifest = {"schema_version": 1, "pack_type": "incident-investigation", "created_at": datetime.now(timezone.utc).isoformat(),
                "status": timeline["status"], "summary": timeline["summary"], "files": files,
                "parameters": {"window_seconds": window_seconds, "max_lines": max_lines,
                               "max_patterns": max_patterns, "max_matches": max_matches,
                               "since": since.isoformat() if since else None, "until": until.isoformat() if until else None},
                "sha256": {filename: digest(bundle / filename) for filename in files.values()},
                "interpretation": CAUTION}
    write_report(bundle / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    if verify(bundle)["status"] != "verified":
        raise ValueError("pack integrity verification failed")
    write_report(output_dir / "latest.json", json.dumps({"schema_version": 1, "bundle": bundle.name,
                                                        "status": timeline["status"], "pack_type": "incident-investigation"}, indent=2) + "\n")
    return {"status": timeline["status"], "bundle": str(bundle), "artifacts": len(files),
            "integrity": "verified", "summary": timeline["summary"],
            "coverage_limited": timeline["quality"]["coverage_limited"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/investigations"))
    parser.add_argument("--since", type=time_argument)
    parser.add_argument("--until", type=time_argument)
    parser.add_argument("--window-seconds", type=int, default=60)
    parser.add_argument("--max-lines", type=int, default=100000)
    parser.add_argument("--max-patterns", type=int, default=1000)
    parser.add_argument("--max-matches", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        result = build(args.session, args.logs, args.output_dir, args.since, args.until,
                       args.window_seconds, args.max_lines, args.max_patterns, args.max_matches)
        print(json.dumps(result, indent=2))
        return 1 if result["status"] == "warning" else 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        print(json.dumps({"status": "error", "error": "investigation pack failed; check evidence paths schemas windows limits and output destination"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
