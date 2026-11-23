"""Operational failure regressions for catalogue and profile commands."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_profile
import service_monitor as service

ROOT = Path(service.__file__).parent


class ServiceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalogue.json"
        self.output = Path(self.directory.name) / "report.json"

    def catalogue(self, **overrides):
        record = {"name": "api", "type": "http", "target": "http://localhost/ready", **overrides}
        self.path.write_text(json.dumps({"version": 1, "services": [record]}), encoding="utf-8")

    def invoke(self, *options):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = service.main([str(self.path), *options])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_rejects_invalid_root_versions_and_duplicate_json_keys(self):
        for text in ('[]', '{"version":true,"services":[]}', '{"version":2,"services":[]}',
                     '{"version":1,"version":1,"services":[]}',
                     '{"version":1,"services":[],"typo":true}'):
            self.path.write_text(text, encoding="utf-8")
            with patch.object(service, "monitor") as monitor:
                self.assertEqual(self.invoke("--check")[0], 2)
                monitor.assert_not_called()

    def test_oversized_catalogue_rejected_without_network(self):
        self.path.write_text(" " * 65537, encoding="utf-8")
        with patch.object(service, "monitor") as monitor:
            self.assertEqual(self.invoke("--check")[0], 2)
            monitor.assert_not_called()

    def test_missing_input_returns_machine_readable_error(self):
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["status"], "error")

    def test_validation_does_not_overwrite_report(self):
        self.catalogue()
        self.output.write_text("existing", encoding="utf-8")
        with patch.object(service, "monitor") as monitor:
            self.assertEqual(self.invoke("--check", "--output", str(self.output))[0], 0)
            monitor.assert_not_called()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "existing")

    def test_group_selection_excludes_other_targets(self):
        entries = [{"name": name, "group": name, "type": "http", "target": "http://localhost/"}
                   for name in ("frontend", "backend")]
        self.path.write_text(json.dumps({"version": 1, "services": entries}), encoding="utf-8")
        with patch.object(service, "check_http", return_value={"status": "ready"}) as check:
            code, stdout, _ = self.invoke("--group", "backend")
        self.assertEqual(code, 0)
        check.assert_called_once()
        self.assertEqual([item["name"] for item in json.loads(stdout)["services"]], ["backend"])

    def test_timeout_is_warning_and_timeout_value_forwarded(self):
        self.catalogue(timeout=0.5, expected_status=204)
        with patch.object(service, "check_http", return_value={"status": "timeout"}) as check:
            code, stdout, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(check.call_args.args, ("http://localhost/ready", 0.5, 204))
        self.assertEqual(json.loads(stdout)["summary"]["warning"], 1)

    def test_report_failure_returns_error_without_exception_leak(self):
        self.catalogue()
        with patch.object(service, "check_http", return_value={"status": "ready"}):
            with patch.object(service, "write_report", side_effect=OSError("private filesystem detail")):
                code, stdout, stderr = self.invoke("--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn("private filesystem detail", stderr)

    def test_successful_stdout_matches_saved_report(self):
        self.catalogue()
        with patch.object(service, "check_http", return_value={"status": "ready", "http_status": 200}):
            code, stdout, _ = self.invoke("--output", str(self.output))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), json.loads(self.output.read_text(encoding="utf-8")))

    def test_cli_process_exit_codes_and_no_traceback(self):
        self.catalogue()
        valid = subprocess.run([sys.executable, str(ROOT / "service_monitor.py"), str(self.path), "--check"],
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(valid.returncode, 0)
        self.assertEqual(json.loads(valid.stdout)["status"], "valid")
        invalid = subprocess.run([sys.executable, str(ROOT / "service_monitor.py"), str(self.path), "--workers", "0"],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("Traceback", invalid.stderr)

    def test_profile_check_does_not_create_configured_output(self):
        self.path.write_text(json.dumps({"output": str(self.output), "samples": 1}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_profile.main([str(self.path), "--check"]), 0)
        self.assertFalse(self.output.exists())
