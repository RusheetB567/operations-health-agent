"""Read-only integrity and completeness audit of local diagnostic bundles."""
import argparse
import json
import re
import sys
from pathlib import Path

from artifact_integrity import digest
from run_profile import unique_object
from system_health import write_report


def read_json(path):
    if path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise ValueError("metadata path escapes directory")
    with path.open("rb") as stream:
        payload = stream.read(1048577)
    if len(payload) > 1048576:
        raise ValueError("metadata too large")
    return json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)


def audit_bundle(bundle):
    result = {"bundle": bundle.name, "status": "verified", "issues": [], "bytes_checked": 0}
    try:
        manifest = read_json(bundle / "manifest.json")
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
            raise ValueError("unsupported manifest")
        files = manifest.get("files")
        if not isinstance(files, dict) or not {"report", "dashboard"} <= files.keys() or not 2 <= len(files) <= 10:
            raise ValueError("incomplete manifest file list")
        names = list(files.values())
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) for name in names):
            raise ValueError("unsafe artifact name")
        if len(set(names)) != len(names):
            raise ValueError("duplicate artifact filename")
        extras = [path.name for path in bundle.iterdir() if path.name not in set(names) | {"manifest.json"}]
        result["issues"].extend(f"unlisted:{name}" for name in sorted(extras))
        checksums = manifest.get("sha256")
        if checksums is None:
            result["issues"].append("legacy_bundle_without_checksums")
            checksums = {}
        elif not isinstance(checksums, dict) or set(checksums) != set(names):
            raise ValueError("checksum coverage does not match declared artifacts")
        for name in names:
            target = bundle / name
            if target.is_symlink() or target.resolve().parent != bundle.resolve():
                raise ValueError("artifact escapes bundle")
            if not target.is_file():
                result["issues"].append(f"missing:{name}")
                continue
            result["bytes_checked"] += target.stat().st_size
            if name in checksums:
                expected = checksums[name]
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError("invalid digest")
                if digest(target) != expected:
                    result["issues"].append(f"changed:{name}")
        if result["issues"]:
            result["status"] = "warning"
    except (OSError, ValueError, TypeError, RecursionError):
        result["status"] = "warning"
        result["issues"].append("manifest_or_artifact_unreadable_or_invalid")
    return result


def audit(root, limit=100):
    root = Path(root).resolve()
    if not root.is_dir() or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid audit root or limit")
    candidates = []
    for path in root.glob("run-*"):
        candidates.append(path)
        if len(candidates) > limit:
            raise ValueError("bundle limit exceeded; narrow the audit directory")
    candidates.sort(key=lambda path: path.name)
    results = []
    for path in candidates:
        if path.is_symlink() or path.resolve().parent != root or not path.is_dir():
            results.append({"bundle": path.name, "status": "warning", "issues": ["unsafe_or_invalid_bundle_path"], "bytes_checked": 0})
        else:
            results.append(audit_bundle(path))
    pointer_issues = []
    try:
        pointer = read_json(root / "latest.json")
        name = pointer.get("bundle") if isinstance(pointer, dict) else None
        if not isinstance(name, str) or name not in {item["bundle"] for item in results}:
            pointer_issues.append("latest_pointer_missing_or_unknown_bundle")
        elif next(item for item in results if item["bundle"] == name)["status"] != "verified":
            pointer_issues.append("latest_bundle_not_verified")
    except (OSError, ValueError, TypeError, RecursionError):
        pointer_issues.append("latest_pointer_unreadable_or_invalid")
    warnings = sum(item["status"] != "verified" for item in results)
    return {"schema_version": 1, "status": "warning" if warnings or pointer_issues or not results else "verified",
            "summary": {"bundles": len(results), "verified": len(results) - warnings, "warning": warnings,
                        "bytes_checked": sum(item["bytes_checked"] for item in results)},
            "pointer_issues": pointer_issues, "bundles": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--limit", type=int, choices=range(1, 1001), default=100, metavar="1–1000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve().is_relative_to(args.directory.resolve()):
            raise ValueError("write audit evidence outside the audited directory")
        report = audit(args.directory, args.limit)
        payload = json.dumps(report, indent=2) + "\n"
        if args.output:
            write_report(args.output, payload)
        print(payload, end="")
        return 0 if report["status"] == "verified" else 1
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "error", "error": "audit could not run; check root limit and output paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
