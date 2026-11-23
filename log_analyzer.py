"""Stream JSONL logs into aggregate severity counts without copying log contents."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def summarize(path, max_line_bytes=65536):
    counts = Counter()
    malformed = oversized = valid = 0
    with Path(path).open("rb") as stream:
        while True:
            line = stream.readline(max_line_bytes + 1)
            if not line:
                break
            if len(line) > max_line_bytes:
                oversized += 1
                while not line.endswith(b"\n"):
                    line = stream.readline(max_line_bytes + 1)
                    if not line:
                        break
                continue
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError
                level = record.get("level", "UNKNOWN")
                if not isinstance(level, str):
                    raise ValueError
                level = level.upper()
                level = "WARNING" if level == "WARN" else level
                counts[level if level in LEVELS else "UNKNOWN"] += 1
                valid += 1
            except (UnicodeError, ValueError, RecursionError):
                malformed += 1
    warning = bool(counts["ERROR"] or counts["CRITICAL"] or malformed or oversized)
    return {"schema_version": 1, "status": "warning" if warning else "healthy",
            "valid_records": valid, "malformed_lines": malformed, "oversized_lines": oversized,
            "levels": dict(sorted(counts.items())),
            "privacy": "aggregate-only: log fields and raw lines are excluded"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args(argv)
    try:
        report = summarize(args.log)
        print(json.dumps(report, indent=2))
        return 1 if report["status"] == "warning" else 0
    except OSError:
        print(json.dumps({"status": "error", "error": "could not read log input"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
