import json
import tempfile
import unittest
from pathlib import Path

from log_analyzer import summarize


class LogTests(unittest.TestCase):
    def summarize_bytes(self, content, limit=65536):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "application.jsonl"
            target.write_bytes(content)
            return summarize(target, limit)

    def test_severity_and_sensitive_fields_not_copied(self):
        content = b'{"level":"error","password":"secret123","message":"person@example.test"}\n'
        report = self.summarize_bytes(content)
        self.assertEqual(report["levels"]["ERROR"], 1)
        self.assertEqual(report["status"], "warning")
        self.assertNotIn("secret123", json.dumps(report))
        self.assertNotIn("person@example.test", json.dumps(report))

    def test_malformed_and_invalid_encoding(self):
        report = self.summarize_bytes(b'not json\n[]\n\xff\n{"level":false}\n')
        self.assertEqual(report["malformed_lines"], 4)

    def test_oversized_line_does_not_hide_following_record(self):
        report = self.summarize_bytes(b'x' * 100 + b'\n{"level":"INFO"}\n', 32)
        self.assertEqual(report["oversized_lines"], 1)
        self.assertEqual(report["valid_records"], 1)

    def test_unknown_level_is_not_echoed(self):
        report = self.summarize_bytes(b'{"level":"private-token"}\n{"level":"warn"}\n\n')
        self.assertEqual(report["levels"]["UNKNOWN"], 1)
        self.assertEqual(report["levels"]["WARNING"], 1)
        self.assertNotIn("private-token", json.dumps(report))

