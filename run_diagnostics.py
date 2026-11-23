"""Run named checks, compare a baseline, and publish a local artifact bundle."""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from incident_compare import compare_reports, load_report
from render_dashboard import render
from service_monitor import load_catalogue, monitor
from system_health import write_report


def run(catalogue, output_dir, previous=None, group=None, workers=4):
    services = load_catalogue(catalogue)
    if group:
        services = [item for item in services if item["group"] == group]
        if not services:
            raise ValueError("no matching services")
    baseline = load_report(previous) if previous else None
    report = monitor(services, workers)
    delta = compare_reports(baseline, report) if baseline else None
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Every execution owns a distinct bundle; previous bundles are never overwritten.
    bundle = Path(tempfile.mkdtemp(prefix="run-", dir=output_dir))
    files = {"report": "services.json", "dashboard": "dashboard.html"}
    write_report(bundle / files["report"], json.dumps(report, indent=2) + "\n")
    write_report(bundle / files["dashboard"], render(report, baseline))
    if delta is not None:
        files["changes"] = "changes.json"
        write_report(bundle / files["changes"], json.dumps(delta, indent=2) + "\n")
    manifest = {"schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": report["status"], "summary": report["summary"], "files": files}
    write_report(bundle / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    # Publish latest only after the whole bundle has been written successfully.
    write_report(output_dir / "latest.json", json.dumps({"schema_version": 1, "bundle": bundle.name,
                                                        "status": report["status"]}, indent=2) + "\n")
    return {"status": report["status"], "bundle": str(bundle), "summary": report["summary"],
            "files": files, "comparison_included": baseline is not None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/runs"))
    parser.add_argument("--previous", type=Path, help="Previous services.json for comparison")
    parser.add_argument("--group")
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=4, metavar="1–16")
    args = parser.parse_args(argv)
    try:
        result = run(args.catalogue, args.output_dir, args.previous, args.group, args.workers)
        print(json.dumps(result, indent=2))
        return 1 if result["status"] == "warning" else 0
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "error", "error": "diagnostic bundle failed; check configuration, baseline and output paths"}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
