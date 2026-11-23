"""Detect changed or missing bundle artifacts using recorded SHA-256 digests."""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def verify(bundle):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    checksums = manifest.get("sha256")
    if not isinstance(checksums, dict) or not checksums:
        raise ValueError("bundle has no recorded checksums")
    results = []
    for filename, expected in checksums.items():
        if not isinstance(expected, str) or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise ValueError("invalid checksum")
        target = (bundle / filename).resolve()
        if not target.is_relative_to(bundle) or target == bundle:
            raise ValueError("artifact path leaves bundle")
        try:
            status = "verified" if digest(target) == expected else "changed"
        except FileNotFoundError:
            status = "missing"
        results.append({"file": filename, "status": status})
    return {"status": "verified" if all(item["status"] == "verified" for item in results) else "warning",
            "artifacts": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify(args.bundle)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "verified" else 1
    except (OSError, ValueError, TypeError, AttributeError):
        print(json.dumps({"status": "error", "error": "cannot verify bundle; check manifest and paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
