"""Run the existing monitor from a validated JSON options profile."""
import argparse
import json
import math
import sys
from pathlib import Path

import system_health
from network_checks import endpoint, timeout_seconds
from http_checks import http_url


SCALARS = {"samples", "consecutive", "cpu-threshold", "memory-threshold", "disk-threshold",
           "network-timeout", "http-status", "max-reports", "disk", "output", "history-db"}
LISTS = {"tcp", "http"}
INTEGERS = {"samples", "consecutive", "max-reports", "http-status"}
PATHS = {"disk", "output", "history-db"}


def validate_option(key, value):
    if key in PATHS or key in LISTS:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError(f"{key} requires a nonempty string")
        if key == "tcp":
            endpoint(value)
        elif key == "http":
            http_url(value)
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} requires a finite number")
    if key in INTEGERS:
        if type(value) is not int or value < 1:
            raise ValueError(f"{key} requires a positive integer")
        if key == "http-status" and not 100 <= value <= 599:
            raise ValueError("http-status must be 100–599")
    elif key == "network-timeout":
        timeout_seconds(str(value))
    elif not 0 < value <= 100:
        raise ValueError(f"{key} must be greater than zero and at most 100")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate profile option")
        result[key] = value
    return result


def profile_arguments(path):
    with Path(path).open(encoding="utf-8") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("profile exceeds 64 KiB character limit")
    profile = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(profile, dict) or set(profile) - SCALARS - LISTS:
        raise ValueError("profile must be an object containing supported CLI option names")
    arguments = []
    for key, value in profile.items():
        values = value if key in LISTS else [value]
        if not isinstance(values, list) or (key in LISTS and len(values) > 100):
            raise ValueError("endpoint options must be lists of at most 100 entries")
        for item in values:
            validate_option(key, item)
            # Equals syntax prevents values from being interpreted as new flags.
            arguments.append(f"--{key}={item}")
    if profile.get("consecutive", 1) > profile.get("samples", 1):
        raise ValueError("consecutive cannot exceed samples")
    return arguments


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate only; do not run monitoring")
    args = parser.parse_args(argv)
    try:
        arguments = profile_arguments(args.profile)
    except (OSError, ValueError, argparse.ArgumentTypeError, RecursionError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 2
    if args.check:
        print(json.dumps({"status": "valid", "message": "profile validated; monitoring not started"}))
        return 0
    return system_health.main(arguments)


if __name__ == "__main__":
    sys.exit(main())
