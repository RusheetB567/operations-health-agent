"""Compare service snapshots without mistaking catalogue changes for recovery."""
import argparse
import json
import sys
from pathlib import Path

from system_health import write_report


def validate_report(report):
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ValueError("unsupported service report")
    if not isinstance(report.get("services"), list) or not 1 <= len(report["services"]) <= 100:
        raise ValueError("report requires 1–100 services")
    names = set()
    for item in report["services"]:
        if not isinstance(item, dict):
            raise ValueError("invalid service record")
        if not isinstance(item.get("name"), str) or not item["name"] or item["name"] in names:
            raise ValueError("invalid or duplicate service name")
        names.add(item["name"])
        if item.get("status") not in ("healthy", "warning") or item.get("type") not in ("http", "tcp"):
            raise ValueError("invalid service state or type")
        if not isinstance(item.get("group"), str) or not isinstance(item.get("detail"), dict):
            raise ValueError("service requires group and diagnostic detail")
    return report


def load_report(path):
    with Path(path).open(encoding="utf-8") as stream:
        content = stream.read(1048577)
    if len(content) > 1048576:
        raise ValueError("service report exceeds one million characters")
    return validate_report(json.loads(content))


def identity(item):
    detail = item["detail"]
    return item["type"], item["group"], detail.get("url"), detail.get("host"), detail.get("port"), detail.get("expected_status")


def compare_reports(previous, current):
    validate_report(previous)
    validate_report(current)
    before = {item["name"]: item for item in previous["services"]}
    after = {item["name"]: item for item in current["services"]}
    changes = {key: [] for key in ("new_failures", "recovered", "ongoing_failures", "unchanged_healthy",
                                   "added", "removed", "reconfigured")}
    for name in sorted(before.keys() | after.keys()):
        if name not in before:
            changes["added"].append({"name": name, "status": after[name]["status"]})
        elif name not in after:
            changes["removed"].append({"name": name, "previous_status": before[name]["status"]})
        elif identity(before[name]) != identity(after[name]):
            changes["reconfigured"].append({"name": name, "previous_status": before[name]["status"], "status": after[name]["status"]})
        else:
            old, new = before[name]["status"], after[name]["status"]
            key = "new_failures" if (old, new) == ("healthy", "warning") else (
                "recovered" if (old, new) == ("warning", "healthy") else (
                    "ongoing_failures" if new == "warning" else "unchanged_healthy"))
            changes[key].append(name)
    return {"schema_version": 1, "previous_timestamp": previous.get("timestamp"),
            "current_timestamp": current.get("timestamp"),
            "status": "warning" if any(item["status"] == "warning" for item in after.values()) else "healthy",
            "counts": {key: len(value) for key, value in changes.items()}, "changes": changes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = compare_reports(load_report(args.previous), load_report(args.current))
        payload = json.dumps(report, indent=2) + "\n"
        if args.output:
            write_report(args.output, payload)
        print(payload, end="")
        return 1 if report["status"] == "warning" else 0
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "error", "error": "could not compare service reports; check schema and paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
