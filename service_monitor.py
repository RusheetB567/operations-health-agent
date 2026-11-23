"""Check a named catalogue of HTTP and TCP services with bounded concurrency."""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from http_checks import check_http, http_url
from network_checks import endpoint, timeout_seconds
from run_profile import unique_object
from system_health import write_report


def load_catalogue(path):
    with Path(path).open(encoding="utf-8") as stream:
        text = stream.read(65537)
    if len(text) > 65536:
        raise ValueError("catalogue exceeds 65536 characters")
    config = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(config, dict) or set(config) != {"version", "services"}:
        raise ValueError("catalogue requires only version and services")
    if type(config["version"]) is not int or config["version"] != 1:
        raise ValueError("unsupported catalogue version")
    services = config["services"]
    if not isinstance(services, list) or not 1 <= len(services) <= 100:
        raise ValueError("catalogue requires 1–100 services")
    names = set()
    validated = []
    for entry in services:
        if not isinstance(entry, dict):
            raise ValueError("each service must be an object")
        if set(entry) - {"name", "group", "type", "target", "timeout", "expected_status"}:
            raise ValueError("unsupported service option")
        name, group = entry.get("name"), entry.get("group", "default")
        for label in (name, group):
            if not isinstance(label, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", label):
                raise ValueError("service names and groups require 1–64 letters, numbers, dots, underscores or hyphens")
        if name in names:
            raise ValueError("service names must be unique")
        names.add(name)
        kind, target = entry.get("type"), entry.get("target")
        if kind not in ("http", "tcp") or not isinstance(target, str):
            raise ValueError("service requires http/tcp type and a string target")
        if kind == "http":
            http_url(target)
        else:
            endpoint(target)
            if "expected_status" in entry:
                raise ValueError("expected_status applies only to HTTP services")
        timeout = entry.get("timeout", 3)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout requires a number")
        timeout_seconds(str(timeout))
        expected = entry.get("expected_status", 200)
        if type(expected) is not int or not 100 <= expected <= 599:
            raise ValueError("expected_status requires an integer from 100 to 599")
        validated.append({"name": name, "group": group, "type": kind, "target": target,
                          "timeout": timeout, "expected_status": expected})
    return validated


def check_service(service):
    try:
        if service["type"] == "http":
            detail = check_http(service["target"], service["timeout"], service["expected_status"])
            healthy = detail["status"] == "ready"
        else:
            host, port = endpoint(service["target"])
            detail = probe_target(host, port, service["timeout"])
            healthy = detail["status"] == "reachable"
        return {"name": service["name"], "group": service["group"], "type": service["type"],
                "status": "healthy" if healthy else "warning", "detail": detail}
    except Exception:
        # Isolate a failed worker; never copy exception text into diagnostic reports.
        return {"name": service["name"], "group": service["group"], "type": service["type"],
                "status": "warning", "detail": {"status": "internal_error"}}


def probe_target(host, port, timeout):
    from network_checks import probe
    return probe(host, port, timeout)


def monitor(services, workers=4):
    if not 1 <= workers <= 16:
        raise ValueError("workers must be between 1 and 16")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(check_service, services))
    groups = {}
    for result in results:
        group = groups.setdefault(result["group"], {"healthy": 0, "warning": 0})
        group[result["status"]] += 1
    failures = sum(result["status"] != "healthy" for result in results)
    return {"schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "warning" if failures else "healthy",
            "summary": {"total": len(results), "healthy": len(results) - failures, "warning": failures},
            "groups": groups, "services": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=4, metavar="1–16")
    parser.add_argument("--check", action="store_true", help="Validate only; make no network requests")
    parser.add_argument("--group", help="Run only this service group")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        services = load_catalogue(args.catalogue)
        if args.group:
            services = [service for service in services if service["group"] == args.group]
            if not services:
                raise ValueError("no services match requested group")
        if args.check:
            print(json.dumps({"status": "valid", "services": len(services)}))
            return 0
        report = monitor(services, args.workers)
        payload = json.dumps(report, indent=2) + "\n"
        if args.output:
            write_report(args.output, payload)
        print(payload, end="")
        return 1 if report["status"] == "warning" else 0
    except (OSError, ValueError, argparse.ArgumentTypeError, RecursionError):
        print(json.dumps({"status": "error", "error": "invalid catalogue, group, or inaccessible input/output; check schema and paths"}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
