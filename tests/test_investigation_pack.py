import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import investigation_pack as pack
from artifact_integrity import verify
from incident_timeline import load_evidence
from test_incident_timeline import session
from triage_logs import timestamp


class InvestigationPackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.session = self.root / "private-source-session.json"
        self.log = self.root / "private-source-log.jsonl"
        self.output = self.root / "packs"
        self.session.write_text(json.dumps({**session(), "secret": "private-session-value", "session": "private-local-path"}), encoding="utf-8")
        self.log.write_text(json.dumps({"timestamp": "2026-11-24T10:01:00Z", "level": "ERROR",
                       "message": "request timed out private-message-value", "password": "private-password-value"}) + "\n", encoding="utf-8")

    def build(self, **options):
        return pack.build(self.session, [self.log], self.output, **options)

    def test_complete_pack_verifies(self):
        result = self.build()
        bundle = Path(result["bundle"])
        self.assertEqual(result["artifacts"], 5)
        self.assertEqual(verify(bundle)["status"], "verified")
        self.assertEqual(len(list(bundle.iterdir())), 6)
        self.assertEqual(result["status"], "warning")

    def test_warning_evidence_still_passes_read_only_integrity_audit(self):
        from audit_bundles import audit
        self.build()
        result = audit(self.output)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["summary"]["verified"], 1)

    def test_private_fields_paths_and_raw_messages_are_excluded(self):
        bundle = Path(self.build()["bundle"])
        content = ''.join(path.read_text(encoding="utf-8") for path in bundle.iterdir())
        for value in ("private-session-value", "private-local-path", "private-message-value", "private-password-value",
                      "private-source-session", "private-source-log"):
            self.assertNotIn(value, content)

    def test_sources_remain_unchanged(self):
        before = self.session.read_bytes(), self.log.read_bytes()
        self.build()
        self.assertEqual((self.session.read_bytes(), self.log.read_bytes()), before)

    def test_minimal_session_remains_valid_timeline_input(self):
        bundle = Path(self.build()["bundle"])
        observation = load_evidence(bundle / "session-observations.json")
        self.assertEqual(set(observation), {"schema_version", "events"})
        self.assertEqual(set(observation["events"][0]), {"service", "event", "cycle", "timestamp"})

    def test_repeat_runs_do_not_overwrite_prior_pack(self):
        first, second = self.build(), self.build()
        self.assertNotEqual(first["bundle"], second["bundle"])
        self.assertEqual(verify(first["bundle"])["status"], "verified")

    def test_latest_pointer_references_complete_pack(self):
        result = self.build()
        latest = json.loads((self.output / "latest.json").read_text())
        self.assertEqual(latest["bundle"], Path(result["bundle"]).name)

    def test_failed_write_preserves_previous_pointer(self):
        self.build()
        previous = (self.output / "latest.json").read_bytes()
        original = pack.write_report
        def fail(path, text):
            if path.name == "timeline.html":
                raise OSError("private filesystem detail")
            return original(path, text)
        with patch.object(pack, "write_report", side_effect=fail):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual((self.output / "latest.json").read_bytes(), previous)

    def test_integrity_failure_prevents_latest_publication(self):
        with patch.object(pack, "verify", return_value={"status": "warning"}):
            with self.assertRaises(ValueError):
                self.build()
        self.assertFalse((self.output / "latest.json").exists())

    def test_invalid_session_does_not_read_logs_or_create_outputs(self):
        self.session.write_text('{"schema_version":1,"events":[{}]}', encoding="utf-8")
        with patch.object(pack, "triage") as triage:
            with self.assertRaises(ValueError):
                self.build()
            triage.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_invalid_options_and_missing_logs_create_no_pack(self):
        for options in ({"max_patterns": 1001}, {"window_seconds": -1}, {"max_lines": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.build(**options)
        with self.assertRaises(OSError):
            pack.build(self.session, [self.root / "missing.jsonl"], self.output)
        self.assertFalse(self.output.exists())

    def test_latest_path_cannot_overwrite_source(self):
        latest_source = self.root / "latest.json"
        latest_source.write_bytes(self.session.read_bytes())
        with self.assertRaises(ValueError):
            pack.build(latest_source, [self.log], self.root)
        self.assertEqual(latest_source.read_bytes(), self.session.read_bytes())

    def test_time_filters_recorded_and_applied(self):
        result = self.build(since=timestamp("2026-11-24T10:00:00Z"), until=timestamp("2026-11-24T10:02:00Z"))
        manifest = json.loads((Path(result["bundle"]) / "manifest.json").read_text())
        self.assertEqual(manifest["parameters"]["since"], "2026-11-24T10:00:00+00:00")

    def test_no_log_events_still_reports_incomplete_coverage(self):
        self.log.write_text("", encoding="utf-8")
        result = self.build()
        self.assertTrue(result["coverage_limited"])
        self.assertEqual(result["status"], "warning")

    def test_cli_failure_sanitized_and_machine_readable(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = pack.main([str(self.root / "private-missing-path"), str(self.log)])
        self.assertEqual(code, 2)
        self.assertNotIn("private-missing-path", stderr.getvalue())
        self.assertEqual(json.loads(stderr.getvalue())["status"], "error")

    def test_real_cli_warning_pack_can_be_verified(self):
        process = subprocess.run([sys.executable, str(Path(pack.__file__)), str(self.session), str(self.log),
                                 "--output-dir", str(self.output)], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 1, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(verify(result["bundle"])["status"], "verified")
