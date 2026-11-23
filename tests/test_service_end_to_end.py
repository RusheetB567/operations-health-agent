"""Real CLI processes against controlled local service failures."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fault_lab import application_lab

ROOT = Path(__file__).resolve().parents[1]


class ServiceEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue = self.root / "catalogue.json"

    def run_catalogue(self, services, *options):
        self.catalogue.write_text(json.dumps({"version": 1, "services": services}), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "service_monitor.py"), str(self.catalogue), *options],
                              cwd=self.root, capture_output=True, text=True, timeout=15)

    def entry(self, name, url, **options):
        return {"name": name, "type": "http", "target": url, "timeout": 2, **options}

    def test_outage_and_recovery_across_separate_processes(self):
        output = self.root / "health.json"
        with application_lab() as lab:
            entries = [self.entry("api", lab.url + "/ready")]
            for unhealthy, expected_code, expected_status in ((False, 0, "healthy"), (True, 1, "warning"), (False, 0, "healthy")):
                with lab.lock:
                    lab.unhealthy = unhealthy
                process = self.run_catalogue(entries, "--output", str(output))
                self.assertEqual(process.returncode, expected_code, process.stderr)
                report = json.loads(process.stdout)
                self.assertEqual(report["status"], expected_status)
                self.assertEqual(report, json.loads(output.read_text(encoding="utf-8")))

    def test_stalled_service_does_not_hide_healthy_service(self):
        with application_lab() as lab:
            process = self.run_catalogue([
                self.entry("stalled", lab.url + "/stall", timeout=1),
                self.entry("healthy", lab.url + "/ready"),
            ], "--workers", "2")
            self.assertEqual(process.returncode, 1, process.stderr)
            report = json.loads(process.stdout)
            self.assertEqual(report["summary"], {"total": 2, "healthy": 1, "warning": 1})
            self.assertEqual(report["services"][0]["detail"]["status"], "timeout")

    def test_redirect_is_not_followed(self):
        with application_lab() as lab:
            process = self.run_catalogue([self.entry("web", lab.url + "/redirect")])
            self.assertEqual(process.returncode, 1)
            self.assertEqual(json.loads(process.stdout)["services"][0]["detail"]["http_status"], 302)
            with lab.lock:
                self.assertEqual(lab.requests, ["/redirect"])

    def test_server_disconnect_is_controlled_warning(self):
        with application_lab() as lab:
            process = self.run_catalogue([self.entry("api", lab.url + "/disconnect")])
            self.assertEqual(process.returncode, 1)
            self.assertEqual(json.loads(process.stdout)["services"][0]["detail"]["status"], "connection_error")
            self.assertNotIn("Traceback", process.stdout + process.stderr)

    def test_validation_has_no_network_or_output_side_effects(self):
        output = self.root / "should-not-exist.json"
        with application_lab() as lab:
            process = self.run_catalogue([self.entry("api", lab.url)], "--check", "--output", str(output))
            self.assertEqual(process.returncode, 0)
            self.assertFalse(output.exists())
            with lab.lock:
                self.assertEqual(lab.requests, [])

    def test_output_failure_preserves_existing_directory_contents(self):
        destination = self.root / "existing-directory"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with application_lab() as lab:
            process = self.run_catalogue([self.entry("api", lab.url)], "--output", str(destination))
        self.assertEqual(process.returncode, 2)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        self.assertEqual(process.stdout, "")
        self.assertNotIn("Traceback", process.stderr)
        self.assertFalse(list(self.root.glob(".existing-directory.*")))
