import json
import tempfile
import unittest
from pathlib import Path

from incident_compare import load_report
from test_incident_compare import snapshot


class ReportInputSafetyTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_bytes(data)
            return load_report(path)

    def test_duplicate_keys_rejected(self):
        data = json.dumps(snapshot({"api": "healthy"})).replace('"expected_status": 200', '"expected_status":200,"expected_status":503')
        with self.assertRaises(ValueError):
            self.load(data.encode())

    def test_nonfinite_numbers_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            data = json.dumps(snapshot({"api": "healthy"})).replace('"expected_status": 200', f'"duration_ms":{token}')
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.load(data.encode())

    def test_invalid_utf8_rejected(self):
        with self.assertRaises(ValueError):
            self.load(b"\xff")

    def test_size_limit_is_bytes(self):
        with self.assertRaises(ValueError):
            self.load(('"' + "é" * 600000 + '"').encode("utf-8"))

    def test_valid_report_still_loads(self):
        report = snapshot({"api": "healthy"})
        self.assertEqual(self.load(json.dumps(report).encode()), report)
