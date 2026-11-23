"""Verify the documented demo as a user would run it."""
import json
import subprocess
import sys
import unittest
from pathlib import Path


class DemoTests(unittest.TestCase):
    def test_self_contained_demo_succeeds(self):
        root = Path(__file__).resolve().parents[1]
        process = subprocess.run([sys.executable, str(root / "tools" / "demo_local.py")],
                                 cwd=root, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["temporary_data_removed"])
        self.assertEqual([step["status"] for step in report["steps"][:3]], ["healthy", "warning", "healthy"])
        self.assertTrue(report["steps"][-1]["sensitive_fields_excluded"])
