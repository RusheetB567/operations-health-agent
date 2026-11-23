import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_diagnostics as diagnostics
from fault_lab import application_lab
from test_incident_compare import snapshot


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue = self.root / "catalogue.json"
        self.output = self.root / "runs"
        self.catalogue.write_text(json.dumps({"version": 1, "services": [{"name": "api", "type": "http",
                                                   "target": "http://localhost/ready"}]}), encoding="utf-8")

    def test_bundle_and_latest_pointer(self):
        report = snapshot({"api": "healthy"})
        report["summary"] = {"total": 1, "healthy": 1, "warning": 0}
        report["status"] = "healthy"
        with patch.object(diagnostics, "monitor", return_value=report):
            result = diagnostics.run(self.catalogue, self.output)
        bundle = Path(result["bundle"])
        self.assertEqual(json.loads((bundle / "services.json").read_text(encoding="utf-8")), report)
        self.assertTrue((bundle / "dashboard.html").exists())
        self.assertTrue((bundle / "manifest.json").exists())
        self.assertEqual(json.loads((self.output / "latest.json").read_text(encoding="utf-8"))["bundle"], bundle.name)
        self.assertFalse(result["comparison_included"])

    def test_failed_bundle_does_not_advance_latest(self):
        self.output.mkdir()
        latest = self.output / "latest.json"
        latest.write_text('{"bundle":"previous"}', encoding="utf-8")
        with patch.object(diagnostics, "monitor", return_value=snapshot({"api": "healthy"})):
            with patch.object(diagnostics, "render", side_effect=ValueError("render failed")):
                with self.assertRaises(ValueError):
                    diagnostics.run(self.catalogue, self.output)
        self.assertEqual(json.loads(latest.read_text(encoding="utf-8")), {"bundle": "previous"})

    def test_invalid_baseline_stops_before_probing(self):
        with patch.object(diagnostics, "monitor") as monitor:
            with self.assertRaises(OSError):
                diagnostics.run(self.catalogue, self.output, self.root / "missing.json")
            monitor.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_each_run_has_distinct_directory(self):
        report = snapshot({"api": "healthy"})
        report.update(status="healthy", summary={"total": 1, "healthy": 1, "warning": 0})
        with patch.object(diagnostics, "monitor", return_value=report):
            first = diagnostics.run(self.catalogue, self.output)
            second = diagnostics.run(self.catalogue, self.output)
        self.assertNotEqual(first["bundle"], second["bundle"])
        self.assertTrue((Path(first["bundle"]) / "manifest.json").exists())

    def test_real_cli_outage_and_recovery_bundle(self):
        root = Path(diagnostics.__file__).parent
        with application_lab() as lab:
            self.catalogue.write_text(json.dumps({"version": 1, "services": [{"name": "api", "type": "http",
                       "target": lab.url + "/ready", "timeout": 2}]}), encoding="utf-8")
            with lab.lock:
                lab.unhealthy = True
            command = [sys.executable, str(root / "run_diagnostics.py"), str(self.catalogue), "--output-dir", str(self.output)]
            first = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 1, first.stderr)
            baseline = Path(json.loads(first.stdout)["bundle"]) / "services.json"
            with lab.lock:
                lab.unhealthy = False
            second = subprocess.run([*command, "--previous", str(baseline)], capture_output=True, text=True, timeout=15)
            self.assertEqual(second.returncode, 0, second.stderr)
            bundle = Path(json.loads(second.stdout)["bundle"])
            delta = json.loads((bundle / "changes.json").read_text(encoding="utf-8"))
            self.assertEqual(delta["changes"]["recovered"], ["api"])
            self.assertIn("recovered", (bundle / "dashboard.html").read_text(encoding="utf-8"))
