import sqlite3
import tempfile
import unittest
from pathlib import Path

from history_store import recent_reports, save_report


class HistoryAtomicityTests(unittest.TestCase):
    def test_retention_failure_rolls_back_new_report(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            original = {"timestamp": "before", "hostname": "test", "status": "healthy"}
            save_report(database, original, 1)
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON reports "
                                   "BEGIN SELECT RAISE(ABORT, 'simulated retention failure'); END")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(sqlite3.IntegrityError):
                save_report(database, {**original, "timestamp": "after"}, 1)
            self.assertEqual(recent_reports(database), [original])
