"""Collect one local health sample. Exit 1 for alerts, 2 for collection errors."""
import argparse
import os
import json
import platform
import socket
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
from network_checks import endpoint, probe, timeout_seconds
from history_store import recent_reports, save_report


def write_report(destination, payload):
    """Replace a report atomically; preserve the previous report on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=f".{destination.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                temporary.replace(destination)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class AlertTracker:
    """Require consecutive breaches; retain alerts until below recovery level."""

    def __init__(self, limits, consecutive=3, recovery_margin=5):
        self.limits = limits
        self.consecutive = consecutive
        self.recovery_margin = recovery_margin
        self.counts = dict.fromkeys(limits, 0)
        self.active = set()

    def update(self, metrics):
        for name, limit in self.limits.items():
            value = metrics[name]
            self.counts[name] = self.counts[name] + 1 if value >= limit else 0
            if self.counts[name] >= self.consecutive:
                self.active.add(name)
            elif value < limit - self.recovery_margin:
                self.active.discard(name)
        return [{"metric": name, "value": metrics[name], "threshold": self.limits[name]}
                for name in self.limits if name in self.active]


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def threshold(value):
    number = float(value)
    if not 0 < number <= 100:
        raise argparse.ArgumentTypeError("threshold must be greater than 0 and at most 100")
    return number


def evaluate(metrics, limits):
    return [
        {"metric": name, "value": metrics[name], "threshold": limit}
        for name, limit in limits.items() if metrics[name] >= limit
    ]


def collect(disk_path):
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage(str(disk_path)).percent,
        "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", type=Path, default=Path.home().anchor)
    parser.add_argument("--output", type=Path, help="Optional report file; contains host information")
    parser.add_argument("--history-db", type=Path, help="Optional SQLite report history")
    parser.add_argument("--max-reports", type=positive_integer, default=1000,
                        help="Maximum retained history records (default: 1000)")
    parser.add_argument("--show-history", type=positive_integer, metavar="COUNT",
                        help="Read recent history instead of collecting metrics")
    parser.add_argument("--samples", type=positive_integer, default=1,
                        help="Number of samples; each CPU sample takes one second")
    parser.add_argument("--consecutive", type=positive_integer, default=1,
                        help="Consecutive breaches required to open an alert")
    parser.add_argument("--tcp", type=endpoint, action="append", default=[],
                        help="Dependency HOST:PORT to check; repeat for multiple targets")
    parser.add_argument("--network-timeout", type=timeout_seconds, default=3,
                        help="Total DNS/TCP budget per target, in seconds (default: 3)")
    for metric in ("cpu", "memory", "disk"):
        parser.add_argument(f"--{metric}-threshold", type=threshold, default=85)
    args = parser.parse_args(argv)
    if args.show_history and not args.history_db:
        parser.error("--show-history requires --history-db")
    if args.consecutive > args.samples:
        parser.error("--consecutive cannot exceed --samples")
    try:
        if args.show_history:
            print(json.dumps(recent_reports(args.history_db, args.show_history), indent=2))
            return 0
        limits = {f"{name}_percent": getattr(args, f"{name}_threshold")
                  for name in ("cpu", "memory", "disk")}
        tracker = AlertTracker(limits, args.consecutive)
        events = []
        previous = set()
        for sample_index in range(args.samples):
            metrics = collect(args.disk)
            alerts = tracker.update(metrics)
            current = set(tracker.active)
            for name in sorted(previous ^ current):
                events.append({"metric": name, "state": "opened" if name in current else "recovered",
                               "sample": sample_index + 1,
                               "timestamp": datetime.now(timezone.utc).isoformat(),
                               "value": metrics[name], "threshold": limits[name]})
            previous = current
        dependencies = [probe(host, port, args.network_timeout) for host, port in args.tcp]
        warning = bool(alerts) or any(item["status"] != "reachable" for item in dependencies)
        report = {
            "schema_version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": socket.gethostname(),
            "operating_system": platform.system(),
            "disk_path": str(args.disk),
            "sampling": {"samples": args.samples, "consecutive_breaches": args.consecutive,
                         "recovery_margin_percent": tracker.recovery_margin},
            "metrics": metrics,
            "alerts": alerts,
            "alert_events": events,
            "dependencies": dependencies,
            "status": "warning" if warning else "healthy",
        }
        payload = json.dumps(report, indent=2) + "\n"
        if args.output:
            write_report(args.output, payload)
        if args.history_db:
            save_report(args.history_db, report, args.max_reports)
        print(payload, end="")
        return 1 if warning else 0
    except (OSError, psutil.Error, sqlite3.Error) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
