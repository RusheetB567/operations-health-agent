"""Finite repeated diagnostic runs with a persisted incident timeline."""
import argparse
import json
import math
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from incident_compare import compare_reports, load_report
from run_diagnostics import run as run_bundle
from service_monitor import load_catalogue
from system_health import write_report


def interval_seconds(value):
    result = float(value)
    if not math.isfinite(result) or not 0.1 <= result <= 3600:
        raise argparse.ArgumentTypeError("interval must be between 0.1 and 3600 seconds")
    return result


def watch(catalogue, output_dir, cycles=3, interval=5, workers=4, group=None):
    if type(cycles) is not int or not 1 <= cycles <= 100:
        raise ValueError("cycles must be 1–100")
    interval_seconds(str(interval))
    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("workers must be 1–16")
    services = load_catalogue(catalogue)
    if group and not any(item["group"] == group for item in services):
        raise ValueError("no matching services")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="session-", dir=root))
    summary = {"schema_version": 1, "state": "running", "requested_cycles": cycles,
               "completed_cycles": 0, "warning_cycles": 0, "events": [], "runs": [],
               "session": str(session), "final_status": None,
               "started_at": datetime.now(timezone.utc).isoformat()}
    previous = None
    baseline_path = None
    def checkpoint():
        write_report(session / "session.json", json.dumps(summary, indent=2) + "\n")
    checkpoint()
    try:
        for index in range(cycles):
            cycle_started = time.monotonic()
            result = run_bundle(catalogue, session / "bundles", baseline_path, group, workers)
            report_path = Path(result["bundle"]) / "services.json"
            report = load_report(report_path)
            if previous is None:
                events = [{"event": "initial_warning", "service": item["name"]}
                          for item in report["services"] if item["status"] == "warning"]
            else:
                delta = compare_reports(previous, report)
                events = [{"event": event, "service": name}
                          for key, event in (("new_failures", "opened"), ("recovered", "recovered"))
                          for name in delta["changes"][key]]
                for key in ("added", "removed", "reconfigured"):
                    events.extend({"event": key, "service": item["name"]} for item in delta["changes"][key])
            observed = report.get("timestamp")
            summary["events"].extend({**event, "cycle": index + 1, "timestamp": observed} for event in events)
            summary["runs"].append({"cycle": index + 1, "bundle": str(result["bundle"]), "status": result["status"],
                                    "elapsed_ms": round((time.monotonic() - cycle_started) * 1000, 2)})
            summary["completed_cycles"] += 1
            summary["warning_cycles"] += result["status"] == "warning"
            summary["final_status"] = result["status"]
            checkpoint()
            previous, baseline_path = report, report_path
            if index + 1 < cycles:
                time.sleep(interval)
        summary["state"] = "completed"
    except KeyboardInterrupt:
        summary["state"] = "interrupted"
    except (OSError, ValueError, RecursionError):
        summary["state"] = "failed"
        summary["failed_cycle"] = summary["completed_cycles"] + 1
        summary["error"] = "cycle failed; previously completed bundles remain available"
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/sessions"))
    parser.add_argument("--cycles", type=int, choices=range(1, 101), default=3, metavar="1–100")
    parser.add_argument("--interval", type=interval_seconds, default=5)
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=4, metavar="1–16")
    parser.add_argument("--group")
    args = parser.parse_args(argv)
    try:
        summary = watch(args.catalogue, args.output_dir, args.cycles, args.interval, args.workers, args.group)
        print(json.dumps(summary, indent=2))
        if summary["state"] == "interrupted":
            return 130
        if summary["state"] == "failed":
            return 2
        return 1 if summary["warning_cycles"] else 0
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "error", "error": "session could not be created or saved"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
