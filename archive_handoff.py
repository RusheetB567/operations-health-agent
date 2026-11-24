"""Archive inventory, externally expected hash checks, and import receipts."""
import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import portable_pack as portable


def expected_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("expected SHA-256 requires 64 hex characters")
    return value.lower()


@contextmanager
def snapshot_archive(archive, expected=None, limits=portable.Limits()):
    expected = expected_hash(expected) if expected is not None else None
    portable.preflight_archive(archive, limits)
    with Path(archive).open("rb") as stream:
        data = portable.read_bounded(stream, limits.max_total_bytes + limits.max_metadata_bytes + 65557)
    actual = hashlib.sha256(data).hexdigest()
    if expected is not None and not hmac.compare_digest(expected, actual):
        raise ValueError("archive does not match separately supplied SHA-256")
    # The verified import uses these exact bytes, not a second read of the source.
    with tempfile.TemporaryDirectory(prefix="archive-handoff-") as directory:
        snapshot = Path(directory) / "snapshot.zip"
        snapshot.write_bytes(data)
        yield snapshot, actual, len(data)


def inventory(archive, expected=None):
    with snapshot_archive(archive, expected) as (snapshot, actual, archive_bytes):
        result, blobs = portable.inspect_archive(snapshot)
        manifest = portable.metadata(blobs["manifest.json"], portable.Limits())
        roles = {filename: role for role, filename in manifest["files"].items()}
        members = [{"file": name, "role": roles.get(name, "manifest"), "bytes": len(data),
                    "sha256": portable.checksum(data)} for name, data in sorted(blobs.items())]
    return {"schema_version": 1, "status": result["status"], "archive_sha256": actual,
            "expected_sha256_matched": expected is not None, "archive_bytes": archive_bytes,
            "expanded_bytes": result["expanded_bytes"], "artifacts": result["artifacts"],
            "members": members, "issues": result["issues"], "extracted": False}


def write_new_json(path, value):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".handoff-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def receive(archive, destination, receipt, expected):
    archive, destination, receipt = Path(archive), Path(destination).absolute(), Path(receipt).absolute()
    if destination.exists() or destination.is_symlink() or receipt.exists() or receipt.is_symlink():
        raise ValueError("destination and receipt must be new")
    if receipt.resolve().is_relative_to(destination.resolve()) or receipt.resolve() == archive.resolve():
        raise ValueError("receipt must be outside imported pack and preserve archive")
    with snapshot_archive(archive, expected) as (snapshot, actual, archive_bytes):
        result, blobs = portable.inspect_archive(snapshot)
        if result["status"] != "verified":
            raise ValueError("archive internally inconsistent")
        record = {"schema_version": 1, "receipt_type": "investigation-import", "status": "imported",
                  "received_at": datetime.now(timezone.utc).isoformat(), "archive_sha256": actual,
                  "expected_sha256_matched": True, "archive_bytes": archive_bytes,
                  "files": {name: {"bytes": len(data), "sha256": portable.checksum(data)} for name, data in sorted(blobs.items())}}
        imported = portable.import_pack(snapshot, destination)
        try:
            write_new_json(receipt, record)
        except (OSError, ValueError):
            return {**imported, "status": "imported_receipt_failed", "archive_sha256": actual,
                    "receipt_saved": False, "note": "verified pack was imported; no rollback or overwrite was attempted"}
    return {**imported, "archive_sha256": actual, "receipt": str(receipt), "receipt_saved": True}


def verify_receipt(receipt, destination):
    limits = portable.Limits()
    with Path(receipt).open("rb") as stream:
        record = portable.metadata(portable.read_bounded(stream, limits.max_metadata_bytes), limits)
    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("receipt_type") != "investigation-import" or record.get("status") != "imported"
            or record.get("expected_sha256_matched") is not True):
        raise ValueError("invalid receipt format")
    expected_hash(record.get("archive_sha256"))
    destination = Path(destination).resolve()
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.resolve().parent != destination:
        raise ValueError("manifest is not local")
    with manifest_path.open("rb") as stream:
        manifest = portable.metadata(portable.read_bounded(stream, limits.max_metadata_bytes), limits)
    names = portable.manifest_files(manifest) + ["manifest.json"]
    files = record.get("files")
    if not isinstance(files, dict) or set(files) != set(names):
        raise ValueError("receipt coverage mismatch")
    results = []
    total = 0
    for name, value in sorted(files.items()):
        portable.safe_name(name)
        if not isinstance(value, dict) or type(value.get("bytes")) is not int or not 0 <= value["bytes"] <= limits.max_file_bytes:
            raise ValueError("invalid receipt file size")
        expected = expected_hash(value.get("sha256"))
        target = destination / name
        if target.is_symlink() or target.resolve().parent != destination:
            raise ValueError("receipt file escapes pack")
        if not target.exists():
            status = "missing"
        else:
            if not stat.S_ISREG(target.lstat().st_mode):
                raise ValueError("receipt entry is not regular")
            with target.open("rb") as stream:
                data = portable.read_bounded(stream, min(limits.max_file_bytes, limits.max_total_bytes - total))
            total += len(data)
            status = "verified" if len(data) == value["bytes"] and hmac.compare_digest(portable.checksum(data), expected) else "changed"
        results.append({"file": name, "status": status})
    return {"schema_version": 1, "status": "verified" if all(item["status"] == "verified" for item in results) else "warning",
            "archive_sha256": record["archive_sha256"], "files": results,
            "note": "receipt comparison only; receipt authenticity requires separate trust"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("archive", type=Path)
    inspect.add_argument("--expected-sha256")
    inspect.add_argument("--output", type=Path)
    incoming = commands.add_parser("receive")
    incoming.add_argument("archive", type=Path)
    incoming.add_argument("--expected-sha256", required=True)
    incoming.add_argument("--destination", type=Path, required=True)
    incoming.add_argument("--receipt", type=Path, required=True)
    check = commands.add_parser("verify-receipt")
    check.add_argument("receipt", type=Path)
    check.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            if args.output and args.output.resolve() == args.archive.resolve():
                raise ValueError("output cannot overwrite archive")
            result = inventory(args.archive, args.expected_sha256)
            if args.output:
                write_new_json(args.output, result)
        elif args.command == "receive":
            result = receive(args.archive, args.destination, args.receipt, args.expected_sha256)
        else:
            result = verify_receipt(args.receipt, args.destination)
        print(json.dumps(result, indent=2))
        return 2 if result["status"] == "imported_receipt_failed" else 1 if result["status"] == "warning" else 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, RuntimeError, portable.zipfile.BadZipFile, NotImplementedError):
        print(json.dumps({"status": "error", "error": "archive handoff failed; check expected hash evidence receipt and destination"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
