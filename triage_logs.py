"""Bounded JSONL triage with UTC windows and per-run private error grouping."""
import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from run_profile import unique_object
from system_health import write_report

LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
CATEGORIES = (
    ("timeout", re.compile(r"\btimeout\b|timed out", re.I)),
    ("connection", re.compile(r"connection refused|connection reset|unreachable|dns failure", re.I)),
    ("database", re.compile(r"deadlock|database.*locked|database.*unavailable|too many connections", re.I)),
    ("authentication", re.compile(r"unauthorized|invalid credentials|authentication failed|permission denied", re.I)),
    ("capacity", re.compile(r"out of memory|disk full|no space left|rate limit|too many requests", re.I)),
)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp requires an explicit timezone")
    return result.astimezone(timezone.utc)


def time_argument(value):
    try:
        return timestamp(value)
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError("use an ISO-8601 timestamp with Z or a timezone offset") from None


def reject_constant(value):
    raise ValueError("non-finite JSON constant")


def fingerprint(message, key):
    # Only the keyed digest leaves this function; no normalised template is retained.
    normalized = re.sub(r"\b[\w.+-]+@[\w.-]+\b", "<email>", message.lower())
    normalized = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>", normalized)
    normalized = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", normalized)
    normalized = re.sub(r"\b\d+\b", "<number>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def triage(paths, since=None, until=None, max_lines=100000, max_patterns=1000):
    if type(max_lines) is not int or not 1 <= max_lines <= 1000000:
        raise ValueError("max_lines must be 1–1000000")
    if type(max_patterns) is not int or not 1 <= max_patterns <= 10000:
        raise ValueError("max_patterns must be 1–10000")
    if since is not None and (since.tzinfo is None or since.utcoffset() is None):
        raise ValueError("since must have timezone")
    if until is not None and (until.tzinfo is None or until.utcoffset() is None):
        raise ValueError("until must have timezone")
    if since and until and since > until:
        raise ValueError("since must not be after until")
    if not paths:
        raise ValueError("at least one log is required")
    levels, categories = Counter(), Counter()
    patterns = {}
    key = os.urandom(32)
    counts = dict(lines_scanned=0, valid_records=0, selected_records=0, malformed_lines=0,
                  oversized_lines=0, untimed_records=0, outside_window=0, ungrouped_errors=0,
                  unusable_error_messages=0)
    truncated = False
    earliest = latest = None
    for path in paths:
        with Path(path).open("rb") as stream:
            while True:
                line = stream.readline(65537)
                if not line:
                    break
                if counts["lines_scanned"] >= max_lines:
                    truncated = True
                    break
                counts["lines_scanned"] += 1
                if len(line) > 65536:
                    counts["oversized_lines"] += 1
                    while not line.endswith(b"\n"):
                        line = stream.readline(65537)
                        if not line:
                            break
                    continue
                if not line.strip():
                    continue
                try:
                    record = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object,
                                        parse_constant=reject_constant)
                    if not isinstance(record, dict) or not isinstance(record.get("level", "UNKNOWN"), str):
                        raise ValueError("invalid record")
                    if isinstance(record.get("message"), str):
                        record["message"].encode("utf-8")
                except (ValueError, UnicodeError, RecursionError):
                    counts["malformed_lines"] += 1
                    continue
                counts["valid_records"] += 1
                try:
                    observed = timestamp(record.get("timestamp"))
                except (ValueError, OverflowError):
                    observed = None
                    counts["untimed_records"] += 1
                if (since or until) and observed is None:
                    continue
                if observed is not None and ((since and observed < since) or (until and observed > until)):
                    counts["outside_window"] += 1
                    continue
                counts["selected_records"] += 1
                if observed is not None:
                    earliest = min(earliest, observed) if earliest else observed
                    latest = max(latest, observed) if latest else observed
                level = record.get("level", "UNKNOWN").upper()
                level = "WARNING" if level == "WARN" else level
                level = level if level in LEVELS else "UNKNOWN"
                levels[level] += 1
                if level not in ("ERROR", "CRITICAL"):
                    continue
                message = record.get("message")
                if not isinstance(message, str) or not message.strip():
                    counts["unusable_error_messages"] += 1
                    continue
                category = next((name for name, pattern in CATEGORIES if pattern.search(message)), "other")
                categories[category] += 1
                token = fingerprint(message, key)
                if token not in patterns and len(patterns) >= max_patterns:
                    counts["ungrouped_errors"] += 1
                    continue
                item = patterns.setdefault(token, {"fingerprint": token, "category": category, "count": 0,
                                                    "first_seen": None, "last_seen": None})
                item["count"] += 1
                if observed is not None:
                    utc = observed.isoformat()
                    item["first_seen"] = min(item["first_seen"], utc) if item["first_seen"] else utc
                    item["last_seen"] = max(item["last_seen"], utc) if item["last_seen"] else utc
        if truncated:
            break
    warning = (levels["ERROR"] > 0 or levels["CRITICAL"] > 0 or truncated
               or any(counts[name] for name in ("malformed_lines", "oversized_lines", "ungrouped_errors", "unusable_error_messages"))
               or bool((since or until) and counts["untimed_records"]))
    return {"schema_version": 1, "status": "warning" if warning else "healthy", "files_requested": len(paths),
            "counts": counts, "truncated": truncated, "levels": dict(sorted(levels.items())),
            "categories": dict(sorted(categories.items())), "patterns": sorted(patterns.values(), key=lambda item: (-item["count"], item["fingerprint"])),
            "window": {"since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
                       "earliest_selected": earliest.isoformat() if earliest else None,
                       "latest_selected": latest.isoformat() if latest else None},
            "privacy": "no raw messages, arbitrary fields or input filenames; fingerprints use an ephemeral per-run key"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--since", type=time_argument)
    parser.add_argument("--until", type=time_argument)
    parser.add_argument("--max-lines", type=int, default=100000)
    parser.add_argument("--max-patterns", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() in {path.resolve() for path in args.logs}:
            raise ValueError("output must not overwrite input")
        report = triage(args.logs, args.since, args.until, args.max_lines, args.max_patterns)
        payload = json.dumps(report, indent=2) + "\n"
        if args.output:
            write_report(args.output, payload)
        print(payload, end="")
        return 1 if report["status"] == "warning" else 0
    except (OSError, ValueError, OverflowError, RecursionError):
        print(json.dumps({"status": "error", "error": "log triage failed; check input paths window and limits"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
