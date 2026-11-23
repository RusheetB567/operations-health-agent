import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import watch_services as watcher
from fault_lab import application_lab
from test_incident_compare import snapshot


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalogue = self.root / "services.json"
        self.output = self.root / "sessions"
        self.catalogue.write_text(json.dumps({"version": 1, "services": [{
            "name": "api", "type": "http", "target": "http://localhost/ready"
        }]}), encoding="utf-8")

    def runner(self, reports):
        iterator = iter(reports)
        sequence = 0
        def execute(catalogue, output, previous, group, workers):
            nonlocal sequence
            report = next(iterator)
            if isinstance(report, BaseException):
                raise report
            sequence += 1
            report = {**report, "timestamp": f"2026-11-23T10:00:0{sequence}Z"}
            report["status"] = "warning" if any(item["status"] == "warning" for item in report["services"]) else "healthy"
            bundle = Path(output) / f"run-{sequence}"
            bundle.mkdir(parents=True)
            (bundle / "services.json").write_text(json.dumps(report), encoding="utf-8")
            return {"bundle": str(bundle), "status": report["status"]}
        return execute

    def execute(self, reports, cycles=3):
        with patch.object(watcher, "run_bundle", side_effect=self.runner(reports)):
            with patch.object(watcher.time, "sleep") as sleep:
                result = watcher.watch(self.catalogue, self.output, cycles, 0.1)
        return result, sleep

    def test_completes_exact_number_and_sleeps_only_between_cycles(self):
        result, sleep = self.execute([snapshot({"api": "healthy"})] * 3)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["completed_cycles"], 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(result["events"], [])

    def test_failure_opening_and_recovery_retained(self):
        result, _ = self.execute([snapshot({"api": state}) for state in ("healthy", "warning", "healthy")])
        self.assertEqual([(item["event"], item["cycle"]) for item in result["events"]], [("opened", 2), ("recovered", 3)])
        self.assertEqual(result["final_status"], "healthy")
        self.assertEqual(result["warning_cycles"], 1)

    def test_initial_warning_not_falsely_claimed_as_new_failure(self):
        result, _ = self.execute([snapshot({"api": "warning"})], 1)
        self.assertEqual(result["events"][0]["event"], "initial_warning")

    def test_ongoing_warning_not_repeated_as_new_incident(self):
        result, _ = self.execute([snapshot({"api": "warning"})] * 3)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["warning_cycles"], 3)

    def test_removed_service_is_not_recovered(self):
        result, _ = self.execute([snapshot({"api": "warning"}), snapshot({"other": "healthy"})], 2)
        events = [item["event"] for item in result["events"]]
        self.assertIn("removed", events)
        self.assertIn("added", events)
        self.assertNotIn("recovered", events)

    def test_reconfigured_service_not_falsely_recovered(self):
        after = snapshot({"api": "healthy"})
        after["services"][0]["detail"]["url"] = "http://localhost/new"
        result, _ = self.execute([snapshot({"api": "warning"}), after], 2)
        self.assertEqual(result["events"][-1]["event"], "reconfigured")

    def test_failed_cycle_preserves_completed_journal(self):
        result, _ = self.execute([snapshot({"api": "healthy"}), OSError("private detail")])
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["completed_cycles"], 1)
        self.assertEqual(result["failed_cycle"], 2)
        self.assertNotIn("private detail", json.dumps(result))
        saved = json.loads((Path(result["session"]) / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, result)

    def test_keyboard_interrupt_saves_progress(self):
        with patch.object(watcher, "run_bundle", side_effect=self.runner([snapshot({"api": "healthy"})])):
            with patch.object(watcher.time, "sleep", side_effect=KeyboardInterrupt):
                result = watcher.watch(self.catalogue, self.output, 3, 0.1)
        self.assertEqual(result["state"], "interrupted")
        self.assertEqual(result["completed_cycles"], 1)
        self.assertTrue((Path(result["session"]) / "session.json").exists())

    def test_invalid_options_do_not_create_session(self):
        for changes in ({"cycles": 0}, {"cycles": 101}, {"cycles": True}, {"workers": 0}, {"group": "absent"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                watcher.watch(self.catalogue, self.output, **changes)
        self.assertFalse(self.output.exists())

    def test_missing_catalogue_does_not_create_session(self):
        with self.assertRaises(OSError):
            watcher.watch(self.root / "missing.json", self.output)
        self.assertFalse(self.output.exists())

    def test_cli_exit_contract(self):
        for state, warnings, expected in (("completed", 0, 0), ("completed", 1, 1), ("failed", 0, 2), ("interrupted", 0, 130)):
            with patch.object(watcher, "watch", return_value={"state": state, "warning_cycles": warnings}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(watcher.main([str(self.catalogue)]), expected)

    def test_real_cli_two_cycles_preserve_bundle_integrity(self):
        from artifact_integrity import verify
        with application_lab() as lab:
            self.catalogue.write_text(json.dumps({"version": 1, "services": [{
                "name": "api", "type": "http", "target": lab.url + "/ready", "timeout": 2
            }]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(Path(watcher.__file__)), str(self.catalogue),
                                     "--output-dir", str(self.output), "--cycles", "2", "--interval", "0.1"],
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["completed_cycles"], 2)
        self.assertEqual(len(summary["runs"]), 2)
        for run in summary["runs"]:
            self.assertEqual(verify(run["bundle"])["status"], "verified")
