import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from history_store import recent_reports, save_report
import system_health as health


class HistoryTests(unittest.TestCase):
    def test_retention_and_order_survive_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "nested" / "history.sqlite3"
            for index in range(5):
                save_report(database, {"timestamp": str(index), "hostname": "test'host",
                                       "status": "healthy", "metrics": {"cpu": index}}, 3)
            reports = recent_reports(database)
            self.assertEqual([item["metrics"]["cpu"] for item in reports], [4, 3, 2])
            self.assertEqual(len(recent_reports(database, 1)), 1)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite3"
            with self.assertRaises(sqlite3.OperationalError):
                recent_reports(database)
            self.assertFalse(database.exists())

    def test_cli_history_does_not_collect_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            report = {"timestamp": "2026-11-14T00:00:00Z", "hostname": "test", "status": "warning"}
            save_report(database, report)
            with patch.object(health, "collect", side_effect=AssertionError("must not collect")):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(health.main(["--history-db", str(database), "--show-history", "5"]), 0)
            self.assertEqual(json.loads(output.getvalue()), [report])

    def test_corrupt_database_returns_error(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "broken.sqlite3"
            database.write_text("not a database", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(health.main(["--history-db", str(database), "--show-history", "1"]), 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "error")
