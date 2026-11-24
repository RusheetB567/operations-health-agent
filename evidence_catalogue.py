"""Local SQLite evidence metadata index; no raw artifacts are stored."""
import argparse
import hashlib
import html
import json
import re
import sqlite3
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import portable_pack as portable
from run_profile import unique_object
from system_health import write_report
from triage_logs import time_argument, timestamp

TABLES = {"packs", "locations", "pack_files", "services", "categories"}
CATEGORIES = {"timeout", "connection", "database", "authentication", "capacity", "other"}
SCHEMA = (
    "CREATE TABLE packs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, health TEXT NOT NULL, selected_records INTEGER NOT NULL, error_records INTEGER NOT NULL, service_events INTEGER NOT NULL, indexed_at TEXT NOT NULL)",
    "CREATE TABLE locations (path TEXT PRIMARY KEY, pack_id TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE, integrity TEXT NOT NULL, checked_at TEXT NOT NULL)",
    "CREATE TABLE pack_files (pack_id TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE, name TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, PRIMARY KEY(pack_id,name))",
    "CREATE TABLE services (pack_id TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE, service TEXT NOT NULL, PRIMARY KEY(pack_id,service))",
    "CREATE TABLE categories (pack_id TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE, category TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(pack_id,category))",
    "CREATE INDEX packs_created ON packs(created_at)",
    "CREATE INDEX locations_pack ON locations(pack_id)",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def schema(connection, create=False):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if version == 0 and not tables and create:
        with connection:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute("PRAGMA user_version=1")
    elif version != 1 or tables != TABLES:
        raise ValueError("not a supported evidence catalogue")


@contextmanager
def database(path, create=False, readonly=False):
    path = Path(path).resolve()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5)
    else:
        connection = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        schema(connection, create)
        yield connection
    finally:
        connection.close()


def integer(value, maximum=1000000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid evidence count")
    return value


def pack_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("use a full catalogue pack ID")
    return value


def inspect_source(path):
    root = Path(path).resolve()
    blobs, names = portable.source_files(root, portable.Limits())
    manifest = portable.metadata(blobs["manifest.json"], portable.Limits())
    report = json.loads(blobs[manifest["files"]["report"]].decode("utf-8"), object_pairs_hook=unique_object)
    log = json.loads(blobs[manifest["files"]["log_summary"]].decode("utf-8"), object_pairs_hook=unique_object)
    observations = json.loads(blobs[manifest["files"]["observations"]].decode("utf-8"), object_pairs_hook=unique_object)
    for value in (report, log, observations):
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            raise ValueError("unsupported investigation artifact schema")
    created = timestamp(manifest.get("created_at")).isoformat(timespec="microseconds")
    if not isinstance(report, dict) or report.get("status") not in ("healthy", "warning"):
        raise ValueError("invalid timeline health")
    counts = report.get("summary")
    if not isinstance(counts, dict):
        raise ValueError("missing timeline counts")
    selected = integer(counts.get("selected_log_records"))
    errors = integer(counts.get("error_records"))
    events = integer(counts.get("service_events"), 1000)
    if errors > selected or not isinstance(log, dict) or not isinstance(observations, dict):
        raise ValueError("inconsistent investigation metadata")
    log_counts, levels = log.get("counts"), log.get("levels")
    if (not isinstance(log_counts, dict) or not isinstance(levels, dict)
            or integer(log_counts.get("selected_records")) != selected
            or integer(levels.get("ERROR", 0)) + integer(levels.get("CRITICAL", 0)) != errors
            or manifest.get("status") != report["status"] or manifest.get("summary") != counts):
        raise ValueError("inconsistent manifest, timeline or log counts")
    labels = set()
    entries = observations.get("events")
    if not isinstance(entries, list) or len(entries) != events:
        raise ValueError("inconsistent observation count")
    for entry in entries:
        label = entry.get("service") if isinstance(entry, dict) else None
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", label):
            raise ValueError("invalid service label")
        labels.add(label)
    categories = log.get("categories")
    if not isinstance(categories, dict) or set(categories) - CATEGORIES:
        raise ValueError("invalid diagnostic categories")
    category_counts = {name: integer(count) for name, count in categories.items()}
    if sum(category_counts.values()) > errors:
        raise ValueError("category counts exceed errors")
    return {"id": portable.checksum(blobs["manifest.json"]), "path": str(root), "created_at": created,
            "health": report["status"], "selected_records": selected, "error_records": errors,
            "service_events": events, "services": sorted(labels), "categories": category_counts,
            "files": {name: {"sha256": portable.checksum(data), "bytes": len(data)} for name, data in blobs.items()}}


def index_pack(path, db):
    evidence = inspect_source(path)
    if Path(db).resolve().is_relative_to(Path(evidence["path"])):
        raise ValueError("catalogue database must be outside evidence pack")
    now = utc_now()
    with database(db, create=True) as connection:
        with connection:
            connection.execute("INSERT INTO packs VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                               (evidence["id"], evidence["created_at"], evidence["health"], evidence["selected_records"],
                                evidence["error_records"], evidence["service_events"], now))
            connection.execute("INSERT INTO locations VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET pack_id=excluded.pack_id, integrity=excluded.integrity, checked_at=excluded.checked_at",
                               (evidence["path"], evidence["id"], "verified", now))
            for name, detail in evidence["files"].items():
                connection.execute("INSERT OR IGNORE INTO pack_files VALUES(?,?,?,?)", (evidence["id"], name, detail["sha256"], detail["bytes"]))
            for label in evidence["services"]:
                connection.execute("INSERT OR IGNORE INTO services VALUES(?,?)", (evidence["id"], label))
            for category, count in evidence["categories"].items():
                connection.execute("INSERT OR IGNORE INTO categories VALUES(?,?,?)", (evidence["id"], category, count))
    return {"status": "indexed", "id": evidence["id"], "health": evidence["health"],
            "services": evidence["services"], "categories": evidence["categories"]}


def search(db, since=None, until=None, category=None, service=None, health=None, limit=20, show_paths=False):
    if type(limit) is not int or not 1 <= limit <= 200 or health not in (None, "healthy", "warning"):
        raise ValueError("invalid search options")
    if category is not None and category not in CATEGORIES:
        raise ValueError("unknown category")
    if since and until and since > until:
        raise ValueError("reversed time filter")
    if any(value is not None and (value.tzinfo is None or value.utcoffset() is None) for value in (since, until)):
        raise ValueError("time filters require timezones")
    clauses, values = [], []
    if since:
        clauses.append("created_at >= ?")
        values.append(since.astimezone(timezone.utc).isoformat(timespec="microseconds"))
    if until:
        clauses.append("created_at <= ?")
        values.append(until.astimezone(timezone.utc).isoformat(timespec="microseconds"))
    if health:
        clauses.append("health = ?")
        values.append(health)
    if category:
        clauses.append("EXISTS(SELECT 1 FROM categories c WHERE c.pack_id=packs.id AND c.category=? AND c.count>0)")
        values.append(category)
    if service is not None:
        clauses.append("EXISTS(SELECT 1 FROM services s WHERE s.pack_id=packs.id AND s.service=?)")
        values.append(service)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with database(db, readonly=True) as connection:
        matched = connection.execute("SELECT COUNT(*) FROM packs" + where, values).fetchone()[0]
        rows = connection.execute("SELECT * FROM packs" + where + " ORDER BY created_at DESC,id LIMIT ?", [*values, limit]).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["services"] = [item[0] for item in connection.execute("SELECT service FROM services WHERE pack_id=? ORDER BY service", (row["id"],))]
            result["categories"] = {item[0]: item[1] for item in connection.execute("SELECT category,count FROM categories WHERE pack_id=? ORDER BY category", (row["id"],))}
            locations = [dict(item) for item in connection.execute("SELECT path,integrity,checked_at FROM locations WHERE pack_id=? ORDER BY path", (row["id"],))]
            result["locations"] = len(locations)
            result["integrity_counts"] = {state: sum(item["integrity"] == state for item in locations) for state in ("verified", "changed", "missing", "unreadable")}
            if show_paths:
                result["location_details"] = locations
            results.append(result)
    return {"status": "ok", "matched": matched, "returned": len(results), "limited": matched > len(results),
            "paths_included": show_paths, "results": results}


def verify_location(path, expected):
    root = Path(path)
    if not root.exists():
        return "missing"
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        return "unreadable"
    changed = missing = False
    total = 0
    try:
        for row in expected:
            name = portable.safe_name(row["name"])
            target = root / name
            if target.is_symlink() or target.resolve().parent != root:
                return "unreadable"
            if not target.exists():
                missing = True
                continue
            if not stat.S_ISREG(target.lstat().st_mode):
                return "unreadable"
            with target.open("rb") as stream:
                data = portable.read_bounded(stream, min(portable.Limits().max_file_bytes, portable.Limits().max_total_bytes - total))
            total += len(data)
            changed = changed or len(data) != row["bytes"] or portable.checksum(data) != row["sha256"]
    except (OSError, ValueError):
        return "unreadable"
    return "changed" if changed else "missing" if missing else "verified"


def recheck(db, identity=None, limit=100):
    if identity:
        pack_id(identity)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid recheck limit")
    with database(db) as connection:
        where, values = (" WHERE pack_id=?", [identity]) if identity else ("", [])
        locations = connection.execute("SELECT path,pack_id FROM locations" + where + " ORDER BY path LIMIT ?", [*values, limit + 1]).fetchall()
        if len(locations) > limit:
            raise ValueError("location limit exceeded; narrow the scan")
        results = []
        for location in locations:
            expected = connection.execute("SELECT name,sha256,bytes FROM pack_files WHERE pack_id=? ORDER BY name", (location["pack_id"],)).fetchall()
            state = verify_location(location["path"], expected)
            results.append({"id": location["pack_id"], "location_token": hashlib.sha256(location["path"].encode()).hexdigest()[:16], "integrity": state})
        with connection:
            now = utc_now()
            for location, result in zip(locations, results):
                connection.execute("UPDATE locations SET integrity=?,checked_at=? WHERE path=?", (result["integrity"], now, location["path"]))
    return {"status": "verified" if results and all(item["integrity"] == "verified" for item in results) else "warning",
            "checked_locations": len(results), "results": results}


def forget(db, identity):
    pack_id(identity)
    with database(db) as connection:
        with connection:
            removed = connection.execute("DELETE FROM packs WHERE id=?", (identity,)).rowcount
    return {"status": "forgotten" if removed else "not_found", "id": identity, "evidence_files_deleted": False}


def overview(db):
    with database(db, readonly=True) as connection:
        packs = connection.execute("SELECT COUNT(*) FROM packs").fetchone()[0]
        locations = connection.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
        unlocated = connection.execute("SELECT COUNT(*) FROM packs WHERE NOT EXISTS(SELECT 1 FROM locations l WHERE l.pack_id=packs.id)").fetchone()[0]
        health = {row[0]: row[1] for row in connection.execute("SELECT health,COUNT(*) FROM packs GROUP BY health")}
        integrity = {row[0]: row[1] for row in connection.execute("SELECT integrity,COUNT(*) FROM locations GROUP BY integrity")}
        categories = {row[0]: row[1] for row in connection.execute("SELECT category,SUM(count) FROM categories GROUP BY category ORDER BY category")}
    return {"status": "ok", "packs": packs, "locations": locations, "packs_without_locations": unlocated,
            "recorded_health_counts": health, "last_integrity_counts": integrity,
            "sum_reported_categories": categories,
            "interpretation": "category sums may include overlapping reports; these are not unique log-event totals"}


def render_results(result):
    escape = lambda value: html.escape(str(value), quote=True)
    rows = []
    for entry in result["results"]:
        rows.append('<tr>' + ''.join(f'<td>{escape(value)}</td>' for value in (
            entry["id"], entry["created_at"], entry["health"], entry["error_records"],
            ', '.join(entry["services"]), json.dumps(entry["categories"]), entry["locations"], json.dumps(entry["integrity_counts"]))) + '</tr>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Evidence catalogue</title><style>body{{font:16px/1.5 system-ui;margin:2rem;background:#101827;color:#e5edf7}}.scroll{{overflow:auto}}table{{border-collapse:collapse}}th,td{{padding:.7rem;border:1px solid #50627c;overflow-wrap:anywhere;max-width:28rem}}@media print{{body{{background:white;color:black}}}}</style></head>
<body><main><h1>Evidence catalogue search</h1><p>Matched: {result["matched"]}. Shown: {result["returned"]}. Limited: {escape(result["limited"])}.</p>
<p>Integrity reflects the last local check, not current service health or continuous verification. Raw logs and location paths are omitted.</p><div class="scroll"><table><thead><tr>
<th scope="col">Pack ID</th><th scope="col">Created UTC</th><th scope="col">Recorded health</th><th scope="col">Errors</th><th scope="col">Services</th><th scope="col">Categories</th><th scope="col">Locations</th><th scope="col">Last integrity counts</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div></main></body></html>'''


def protect_output(db, target):
    resolved = Path(target).resolve()
    if resolved == Path(db).resolve():
        raise ValueError("report cannot overwrite database")
    with database(db, readonly=True) as connection:
        for row in connection.execute("SELECT path FROM locations"):
            if resolved.is_relative_to(Path(row[0])) or resolved.is_relative_to(Path(row[0]).resolve()):
                raise ValueError("report cannot modify indexed evidence")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("pack", type=Path)
    find = commands.add_parser("search")
    find.add_argument("--since", type=time_argument)
    find.add_argument("--until", type=time_argument)
    find.add_argument("--category", choices=sorted(CATEGORIES))
    find.add_argument("--service")
    find.add_argument("--health", choices=("healthy", "warning"))
    find.add_argument("--limit", type=int, default=20)
    find.add_argument("--show-paths", action="store_true")
    find.add_argument("--html-output", type=Path)
    check = commands.add_parser("recheck")
    check.add_argument("--id")
    check.add_argument("--limit", type=int, default=100)
    remove = commands.add_parser("forget")
    remove.add_argument("id")
    stats = commands.add_parser("stats")
    for command in (add, find, check, remove, stats):
        command.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            result = index_pack(args.pack, args.db)
        elif args.command == "search":
            if args.html_output:
                protect_output(args.db, args.html_output)
            result = search(args.db, args.since, args.until, args.category, args.service, args.health, args.limit, args.show_paths)
            if args.html_output:
                write_report(args.html_output, render_results(result))
        elif args.command == "recheck":
            result = recheck(args.db, args.id, args.limit)
        elif args.command == "stats":
            result = overview(args.db)
        else:
            result = forget(args.db, args.id)
        print(json.dumps(result, indent=2))
        return 1 if result["status"] in ("warning", "not_found") else 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, sqlite3.Error):
        print(json.dumps({"status": "error", "error": "catalogue operation failed; check schema evidence filters limits and paths"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
