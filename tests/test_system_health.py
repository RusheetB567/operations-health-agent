import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import system_health as health


class HealthTests(unittest.TestCase):
    def test_impossible_sampling_configuration_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                health.main(["--samples", "1", "--consecutive", "3"])
        self.assertEqual(result.exception.code, 2)

    def test_failed_report_replace_preserves_previous_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "health.json"
            target.write_text("previous", encoding="utf-8")
            with patch.object(Path, "replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    health.write_report(target, "replacement")
            self.assertEqual(target.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_concurrent_report_writers_produce_complete_json(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "health.json"
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda index: health.write_report(target, json.dumps({"id": index})),
                              range(20)))
            self.assertIn(json.loads(target.read_text(encoding="utf-8"))["id"], range(20))
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_failed_dependency_changes_exit_code(self):
        metrics = dict(cpu_percent=10, memory_percent=20, disk_percent=30, uptime_seconds=10)
        with patch.object(health, "collect", return_value=metrics):
            with patch.object(health, "probe", return_value={"status": "refused"}):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(health.main(["--tcp", "localhost:5432"]), 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "warning")

    def test_transient_spike_is_ignored(self):
        tracker = health.AlertTracker({"cpu": 85}, consecutive=2)
        self.assertEqual(tracker.update({"cpu": 90}), [])
        self.assertEqual(tracker.update({"cpu": 20}), [])
        self.assertEqual(tracker.update({"cpu": 90}), [])
        self.assertEqual(len(tracker.update({"cpu": 90})), 1)

    def test_recovery_uses_hysteresis(self):
        tracker = health.AlertTracker({"cpu": 85}, consecutive=1)
        tracker.update({"cpu": 90})
        self.assertEqual(len(tracker.update({"cpu": 83})), 1)
        self.assertEqual(len(tracker.update({"cpu": 80})), 1)
        self.assertEqual(tracker.update({"cpu": 79}), [])

    def test_multiple_samples_only_report_final_state(self):
        def sample(cpu):
            return dict(cpu_percent=cpu, memory_percent=20, disk_percent=30, uptime_seconds=10)
        with patch.object(health, "collect", side_effect=[sample(90), sample(90), sample(20)]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(health.main(["--samples", "3", "--consecutive", "2"]), 0)
        self.assertEqual(json.loads(output.getvalue())["sampling"]["samples"], 3)
        events = json.loads(output.getvalue())["alert_events"]
        self.assertEqual([(event["state"], event["sample"]) for event in events],
                         [("opened", 2), ("recovered", 3)])

    def test_threshold_boundary_triggers_alert(self):
        self.assertEqual(len(health.evaluate({"cpu": 85}, {"cpu": 85})), 1)
        self.assertEqual(health.evaluate({"cpu": 84.9}, {"cpu": 85}), [])

    def test_invalid_threshold_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                health.main(["--cpu-threshold", "101"])
        self.assertEqual(result.exception.code, 2)

    def test_report_and_alert_exit_code(self):
        metrics = dict(cpu_percent=90, memory_percent=20, disk_percent=30, uptime_seconds=10)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "health.json"
            with patch.object(health, "collect", return_value=metrics):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(health.main(["--output", str(target)]), 1)
            report = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(report, json.loads(output.getvalue()))
            self.assertEqual(report["alerts"][0]["metric"], "cpu_percent")

    def test_collection_failure_returns_error(self):
        with patch.object(health, "collect", side_effect=OSError("unavailable")):
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(health.main([]), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")

    def test_healthy_exit_code(self):
        metrics = dict(cpu_percent=10, memory_percent=20, disk_percent=30, uptime_seconds=10)
        with patch.object(health, "collect", return_value=metrics):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(health.main([]), 0)


if __name__ == "__main__":
    unittest.main()
