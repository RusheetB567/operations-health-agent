"""Bounded, checksum-verified ZIP transport for local investigation packs."""
import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from run_profile import unique_object

INDEX = "archive-index.json"
ROLES = {"report", "dashboard", "observations", "log_summary", "notes"}


@dataclass(frozen=True)
class Limits:
    max_total_bytes: int = 32 * 1024 * 1024
    max_file_bytes: int = 8 * 1024 * 1024
    max_metadata_bytes: int = 1024 * 1024
    max_entries: int = 16
    max_ratio: int = 200

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("limits require positive integers")


def safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
        raise ValueError("unsafe archive filename")
    if name.endswith(".") or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("reserved archive filename")
    return name


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def metadata(data, limits):
    if len(data) > limits.max_metadata_bytes:
        raise ValueError("metadata too large")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return value


def manifest_files(manifest):
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("pack_type") != "incident-investigation"):
        raise ValueError("requires an investigation pack manifest")
    files, hashes = manifest.get("files"), manifest.get("sha256")
    if not isinstance(files, dict) or set(files) != ROLES:
        raise ValueError("unexpected investigation artifact roles")
    names = [safe_name(name) for name in files.values()]
    folded = [name.casefold() for name in [*names, "manifest.json", INDEX]]
    if len(set(folded)) != len(folded):
        raise ValueError("duplicate/reserved artifact filename")
    if not isinstance(hashes, dict) or set(hashes) != set(names):
        raise ValueError("artifact checksums incomplete")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes.values()):
        raise ValueError("invalid artifact digest")
    return names


def read_bounded(stream, limit):
    if limit < 0:
        raise ValueError("expanded byte budget exhausted")
    chunks, size = [], 0
    while True:
        chunk = stream.read(min(65536, limit - size + 1))
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise ValueError("expanded file size limit exceeded")
        chunks.append(chunk)
    return b"".join(chunks)


def source_files(bundle, limits):
    bundle = Path(bundle).resolve()
    if not bundle.is_dir():
        raise ValueError("pack directory unavailable")
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.resolve().parent != bundle:
        raise ValueError("manifest escapes pack")
    with manifest_path.open("rb") as stream:
        manifest_data = read_bounded(stream, limits.max_metadata_bytes)
    manifest = metadata(manifest_data, limits)
    names = manifest_files(manifest)
    blobs = {"manifest.json": manifest_data}
    total = len(manifest_data)
    if total > limits.max_total_bytes:
        raise ValueError("manifest exceeds total byte budget")
    for name in names:
        target = bundle / name
        if target.is_symlink() or target.resolve().parent != bundle or not stat.S_ISREG(target.lstat().st_mode):
            raise ValueError("artifact is not a local regular file")
        with target.open("rb") as stream:
            data = read_bounded(stream, min(limits.max_file_bytes, limits.max_total_bytes - total))
        total += len(data)
        if checksum(data) != manifest["sha256"][name]:
            raise ValueError("source artifact changed")
        blobs[name] = data
    return blobs, names


def preflight_archive(archive, limits):
    path = Path(archive)
    size = path.stat().st_size
    if size > limits.max_total_bytes + limits.max_metadata_bytes + 65557:
        raise ValueError("compressed archive size limit exceeded")
    with path.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise ValueError("missing ZIP end record")
    if position >= 20 and tail[position - 20:position - 16] == b"PK\x06\x07":
        raise ValueError("ZIP64 archives are unsupported")
    _, disk, directory_disk, disk_entries, total_entries, directory_size, directory_offset, comment_size = struct.unpack_from("<4s4H2LH", tail, position)
    if (disk or directory_disk or disk_entries != total_entries or not 1 <= total_entries <= limits.max_entries
            or total_entries == 65535 or directory_size > min(limits.max_metadata_bytes, 65536)
            or directory_offset + directory_size > size or position + 22 + comment_size != len(tail)):
        raise ValueError("split, ZIP64, oversized or inconsistent ZIP metadata")


def inspect_archive(archive, limits=Limits()):
    preflight_archive(archive, limits)
    blobs, issues = {}, []
    with zipfile.ZipFile(archive) as container:
        entries = container.infolist()
        if not 1 <= len(entries) <= limits.max_entries:
            raise ValueError("archive entry limit exceeded")
        names = [safe_name(entry.filename) for entry in entries]
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("duplicate or case-colliding archive entries")
        total = sum(entry.file_size for entry in entries)
        if total > limits.max_total_bytes:
            raise ValueError("archive expanded size limit exceeded")
        for entry in entries:
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if mode not in (0, stat.S_IFREG) or entry.is_dir() or entry.flag_bits & 1:
                raise ValueError("directories, special files and encrypted entries are unsupported")
            if entry.file_size > limits.max_file_bytes:
                raise ValueError("archive file size limit exceeded")
            if entry.file_size > 65536 and entry.file_size > max(entry.compress_size, 1) * limits.max_ratio:
                raise ValueError("suspicious compression ratio")
            with container.open(entry) as stream:
                blobs[entry.filename] = read_bounded(stream, min(entry.file_size, limits.max_file_bytes))
            if len(blobs[entry.filename]) != entry.file_size:
                raise ValueError("archive entry size mismatch")
    if INDEX not in blobs or "manifest.json" not in blobs:
        raise ValueError("missing archive index or manifest")
    index = metadata(blobs[INDEX], limits)
    if type(index.get("archive_format")) is not int or index["archive_format"] != 1:
        raise ValueError("unsupported archive format")
    records = index.get("files")
    if not isinstance(records, dict) or set(records) != set(blobs) - {INDEX}:
        raise ValueError("archive index coverage mismatch")
    for name, record in records.items():
        if (not isinstance(record, dict) or type(record.get("bytes")) is not int
                or record["bytes"] < 0 or not isinstance(record.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])):
            raise ValueError("invalid archive index entry")
        if record["bytes"] != len(blobs[name]) or record["sha256"] != checksum(blobs[name]):
            issues.append({"file": name, "issue": "archive_index_mismatch"})
    manifest = metadata(blobs["manifest.json"], limits)
    artifacts = manifest_files(manifest)
    if set(blobs) != set(artifacts) | {"manifest.json", INDEX}:
        raise ValueError("unexpected or missing archive members")
    for name in artifacts:
        if checksum(blobs[name]) != manifest["sha256"][name]:
            issues.append({"file": name, "issue": "manifest_digest_mismatch"})
    report = {"status": "warning" if issues else "verified", "artifacts": len(artifacts),
              "archive_entries": len(blobs), "expanded_bytes": sum(map(len, blobs.values())), "issues": issues}
    return report, {name: data for name, data in blobs.items() if name != INDEX}


def export_pack(bundle, output, limits=Limits()):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if output.is_relative_to(bundle) or output.exists():
        raise ValueError("archive must be new and outside source pack")
    blobs, artifacts = source_files(bundle, limits)
    index = {"archive_format": 1, "files": {name: {"bytes": len(data), "sha256": checksum(data)} for name, data in sorted(blobs.items())}}
    blobs[INDEX] = json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".pack-export-", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as container:
            for name, data in sorted(blobs.items()):
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o600) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                container.writestr(entry, data, compresslevel=6)
        report, _ = inspect_archive(temporary, limits)
        if report["status"] != "verified":
            raise ValueError("export archive failed integrity checks")
        # Same-directory hard-link publication fails atomically if output exists.
        os.link(temporary, output)
        return {"status": "exported", "archive": str(output), "integrity": "verified", "artifacts": len(artifacts),
                "archive_bytes": output.stat().st_size}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_pack(archive, destination, limits=Limits()):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination must not exist")
    report, blobs = inspect_archive(archive, limits)
    if report["status"] != "verified":
        raise ValueError("archive integrity failed; nothing imported")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # TemporaryDirectory owns only this newly created staging folder.
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".pack-import-") as directory:
        staging = Path(directory)
        for name, data in blobs.items():
            with (staging / safe_name(name)).open("xb") as stream:
                stream.write(data)
            if checksum((staging / name).read_bytes()) != checksum(data):
                raise ValueError("import write verification failed")
        if destination.exists() or destination.is_symlink():
            raise ValueError("destination appeared during import")
        staging.rename(destination)
    return {"status": "imported", "destination": str(destination), "integrity": "verified", "artifacts": report["artifacts"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    export = actions.add_parser("export")
    export.add_argument("pack", type=Path)
    export.add_argument("--output", type=Path, required=True)
    check = actions.add_parser("verify")
    check.add_argument("archive", type=Path)
    restore = actions.add_parser("import")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export_pack(args.pack, args.output)
        elif args.command == "verify":
            result, _ = inspect_archive(args.archive)
        else:
            result = import_pack(args.archive, args.destination)
        print(json.dumps(result, indent=2))
        return 1 if result["status"] == "warning" else 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
        print(json.dumps({"status": "error", "error": "portable pack operation failed; check format integrity limits and destination"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
