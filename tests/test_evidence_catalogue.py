import contextlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import evidence_catalogue as catalogue
import portable_pack as portable
from triage_logs import timestamp


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "catalogue.sqlite3"
        self.pack = self.make_pack("one")

    def make_pack(self, name, created="2026-11-24T10:00:00Z", service="api", category="timeout", health="warning"):
        path = self.root / name
        path.mkdir(exist_ok=True)
        errors = 2 if health == "warning" else 0
        summary = {"service_events": 1, "selected_log_records": 2, "error_records": errors}
        payloads = {
            "timeline.json": json.dumps({"schema_version": 1, "status": health, "summary": summary}),
            "timeline.html": "<html>synthetic evidence</html>",
            "observations.json": json.dumps({"schema_version": 1, "events": [{"service": service}]}),
            "logs.json": json.dumps({"schema_version": 1, "categories": {category: errors} if errors else {},
                                      "counts": {"selected_records": 2}, "levels": {"ERROR": errors}}),
            "notes.md": "PRIVATE_RAW_MARKER not to be indexed",
        }
        for filename, text in payloads.items():
            (path / filename).write_text(text, encoding="utf-8")
        manifest = {"schema_version": 1, "pack_type": "incident-investigation", "created_at": created,
                    "status": health, "summary": summary,
                    "files": {"report": "timeline.json", "dashboard": "timeline.html", "observations": "observations.json",
                              "log_summary": "logs.json", "notes": "notes.md"},
                    "sha256": {filename: portable.checksum((path / filename).read_bytes()) for filename in payloads}}
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_index_and_search(self):
        result = catalogue.index_pack(self.pack, self.db)
        found = catalogue.search(self.db)
        self.assertEqual(found["matched"], 1)
        self.assertEqual(found["results"][0]["id"], result["id"])
        self.assertEqual(found["results"][0]["categories"], {"timeout": 2})

    def test_repeat_index_idempotent(self):
        first = catalogue.index_pack(self.pack, self.db)
        second = catalogue.index_pack(self.pack, self.db)
        self.assertEqual(first["id"], second["id"])
        result = catalogue.search(self.db)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["results"][0]["locations"], 1)

    def test_identical_copy_has_two_locations_one_identity(self):
        catalogue.index_pack(self.pack, self.db)
        copy = self.root / "copy"
        shutil.copytree(self.pack, copy)
        catalogue.index_pack(copy, self.db)
        result = catalogue.search(self.db)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["results"][0]["locations"], 2)

    def test_filter_by_category_service_health_and_time(self):
        catalogue.index_pack(self.pack, self.db)
        catalogue.index_pack(self.make_pack("two", created="2026-11-25T10:00:00Z", service="worker", category="database"), self.db)
        result = catalogue.search(self.db, since=timestamp("2026-11-25T00:00:00Z"), category="database", service="worker", health="warning")
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["results"][0]["services"], ["worker"])

    def test_filter_boundary_and_limit_visible(self):
        catalogue.index_pack(self.pack, self.db)
        catalogue.index_pack(self.make_pack("two", created="2026-11-25T10:00:00Z"), self.db)
        result = catalogue.search(self.db, since=timestamp("2026-11-24T10:00:00Z"), limit=1)
        self.assertEqual(result["matched"], 2)
        self.assertTrue(result["limited"])

    def test_parameterized_service_query(self):
        catalogue.index_pack(self.pack, self.db)
        self.assertEqual(catalogue.search(self.db, service="api' OR 1=1 --")["matched"], 0)
        self.assertEqual(catalogue.search(self.db)["matched"], 1)

    def test_default_output_omits_paths(self):
        catalogue.index_pack(self.pack, self.db)
        result = catalogue.search(self.db)
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(Path(catalogue.search(self.db, show_paths=True)["results"][0]["location_details"][0]["path"]), self.pack.resolve())

    def test_raw_artifact_content_not_stored(self):
        catalogue.index_pack(self.pack, self.db)
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            dump = '\n'.join(connection.iterdump())
        self.assertNotIn("PRIVATE_RAW_MARKER", dump)

    def test_changed_pack_cannot_be_indexed(self):
        (self.pack / "notes.md").write_text("modified", encoding="utf-8")
        with self.assertRaises(ValueError):
            catalogue.index_pack(self.pack, self.db)
        self.assertFalse(self.db.exists())

    def test_database_cannot_be_inside_source_evidence(self):
        with self.assertRaises(ValueError):
            catalogue.index_pack(self.pack, self.pack / "index.sqlite3")

    def test_recheck_detects_changed_artifact(self):
        catalogue.index_pack(self.pack, self.db)
        (self.pack / "notes.md").write_text("modified", encoding="utf-8")
        result = catalogue.recheck(self.db)
        self.assertEqual(result["results"][0]["integrity"], "changed")
        self.assertEqual(catalogue.search(self.db)["results"][0]["integrity_counts"]["changed"], 1)

    def test_recheck_uses_indexed_hashes_not_rewritten_manifest(self):
        catalogue.index_pack(self.pack, self.db)
        self.make_pack("one", created="2026-12-01T00:00:00Z", category="database")
        self.assertEqual(catalogue.recheck(self.db)["results"][0]["integrity"], "changed")

    def test_missing_file_recorded(self):
        catalogue.index_pack(self.pack, self.db)
        (self.pack / "notes.md").unlink()
        self.assertEqual(catalogue.recheck(self.db)["results"][0]["integrity"], "missing")

    def test_scan_limit_stops_without_partial_updates(self):
        catalogue.index_pack(self.pack, self.db)
        catalogue.index_pack(self.make_pack("two"), self.db)
        with self.assertRaises(ValueError):
            catalogue.recheck(self.db, limit=1)
        self.assertEqual(catalogue.search(self.db)["returned"], 1)

    def test_forget_only_removes_index_records(self):
        identity = catalogue.index_pack(self.pack, self.db)["id"]
        before = {path.name: path.read_bytes() for path in self.pack.iterdir()}
        self.assertEqual(catalogue.forget(self.db, identity)["status"], "forgotten")
        self.assertEqual(catalogue.search(self.db)["matched"], 0)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.pack.iterdir()})

    def test_reindex_changed_path_preserves_old_metadata(self):
        original = catalogue.index_pack(self.pack, self.db)["id"]
        self.make_pack("one", created="2026-11-25T00:00:00Z")
        replacement = catalogue.index_pack(self.pack, self.db)["id"]
        results = {item["id"]: item for item in catalogue.search(self.db)["results"]}
        self.assertEqual(results[original]["locations"], 0)
        self.assertEqual(results[replacement]["locations"], 1)

    def test_search_missing_database_does_not_create_it(self):
        with self.assertRaises(sqlite3.OperationalError):
            catalogue.search(self.db)
        self.assertFalse(self.db.exists())

    def test_unrelated_database_not_modified(self):
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.execute("INSERT INTO unrelated VALUES('preserve')")
        with self.assertRaises(ValueError):
            catalogue.index_pack(self.pack, self.db)
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0], "preserve")

    def test_failed_index_transaction_rolls_back(self):
        catalogue.index_pack(self.pack, self.db)
        with contextlib.closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("CREATE TRIGGER reject_categories BEFORE INSERT ON categories BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        second = self.make_pack("two", created="2026-11-25T00:00:00Z", category="database")
        with self.assertRaises(sqlite3.IntegrityError):
            catalogue.index_pack(second, self.db)
        self.assertEqual(catalogue.search(self.db)["matched"], 1)

    def test_output_cannot_overwrite_database_or_evidence(self):
        catalogue.index_pack(self.pack, self.db)
        with self.assertRaises(ValueError):
            catalogue.protect_output(self.db, self.db)
        with self.assertRaises(ValueError):
            catalogue.protect_output(self.db, self.pack / "manifest.json")

    def test_html_has_no_scripts_or_paths(self):
        catalogue.index_pack(self.pack, self.db)
        page = catalogue.render_results(catalogue.search(self.db, show_paths=True))
        self.assertIn("default-src 'none'", page)
        self.assertNotIn("<script", page)
        self.assertNotIn(str(self.root), page)

    def test_real_cli_add_search_recheck_forget(self):
        command = [sys.executable, str(Path(catalogue.__file__))]
        added = subprocess.run([*command, "add", str(self.pack), "--db", str(self.db)], capture_output=True, text=True, timeout=15)
        self.assertEqual(added.returncode, 0, added.stderr)
        identity = json.loads(added.stdout)["id"]
        for arguments in (["search", "--category", "timeout"], ["recheck", "--id", identity], ["forget", identity]):
            result = subprocess.run([*command, *arguments, "--db", str(self.db)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_sanitizes_missing_database_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(catalogue.main(["search", "--db", str(self.root / "private-missing.sqlite3")]), 2)
        self.assertNotIn("private-missing", error.getvalue())

    def test_overview_counts_identity_not_duplicate_locations(self):
        catalogue.index_pack(self.pack, self.db)
        copy = self.root / "copy"
        shutil.copytree(self.pack, copy)
        catalogue.index_pack(copy, self.db)
        result = catalogue.overview(self.db)
        self.assertEqual(result["packs"], 1)
        self.assertEqual(result["locations"], 2)
        self.assertEqual(result["sum_reported_categories"], {"timeout": 2})

    def test_empty_catalogue_after_forgetting_remains_queryable(self):
        identity = catalogue.index_pack(self.pack, self.db)["id"]
        catalogue.forget(self.db, identity)
        self.assertEqual(catalogue.overview(self.db)["packs"], 0)

    def test_stats_cli_is_readable_json(self):
        catalogue.index_pack(self.pack, self.db)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(catalogue.main(["stats", "--db", str(self.db)]), 0)
        self.assertEqual(json.loads(output.getvalue())["locations"], 1)
