import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from triage_logs import main, timestamp, triage


class LogTriageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.log = self.root / "application.jsonl"

    def records(self, records):
        self.log.write_text(''.join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def event(self, **changes):
        return {"timestamp": "2026-11-24T10:00:00Z", "level": "ERROR", "message": "request 123 timed out", **changes}

    def test_inclusive_window_with_timezone_conversion(self):
        self.records([self.event(timestamp="2026-11-24T11:00:00+01:00"), self.event(timestamp="2026-11-24T10:00:01Z")])
        report = triage([self.log], timestamp("2026-11-24T10:00:00Z"), timestamp("2026-11-24T10:00:00Z"))
        self.assertEqual(report["counts"]["selected_records"], 1)
        self.assertEqual(report["counts"]["outside_window"], 1)

    def test_repeated_normalized_errors_group(self):
        self.records([self.event(), self.event(message="request 456 timed out")])
        report = triage([self.log])
        self.assertEqual(len(report["patterns"]), 1)
        self.assertEqual(report["patterns"][0]["count"], 2)
        self.assertEqual(report["patterns"][0]["category"], "timeout")

    def test_fingerprints_change_between_runs(self):
        self.records([self.event()])
        self.assertNotEqual(triage([self.log])["patterns"][0]["fingerprint"], triage([self.log])["patterns"][0]["fingerprint"])

    def test_no_sensitive_fields_or_input_names_in_output(self):
        self.records([self.event(message="connection refused private-host secret-credential", password="secret-value", email="person@example.test")])
        output = json.dumps(triage([self.log]))
        for text in ("private-host", "secret-credential", "secret-value", "person@example.test", "application.jsonl"):
            self.assertNotIn(text, output)

    def test_untimed_excluded_when_filtering_and_counted(self):
        self.records([self.event(timestamp="invalid"), self.event(timestamp="2026-11-24T10:00:00")])
        report = triage([self.log], since=timestamp("2026-11-24T00:00:00Z"))
        self.assertEqual(report["counts"]["untimed_records"], 2)
        self.assertEqual(report["counts"]["selected_records"], 0)
        self.assertEqual(report["status"], "warning")

    def test_untimed_included_without_window(self):
        self.records([{"level": "INFO", "message": "started"}])
        self.assertEqual(triage([self.log])["counts"]["selected_records"], 1)

    def test_duplicate_keys_nonfinite_and_encoding_are_malformed(self):
        self.log.write_bytes(b'{"level":"INFO","level":"ERROR"}\n{"level":"INFO","x":NaN}\n\xff\n[]\n')
        self.assertEqual(triage([self.log])["counts"]["malformed_lines"], 4)

    def test_oversized_line_skipped_and_next_parsed(self):
        self.log.write_bytes(b'x' * 70000 + b'\n{"level":"INFO"}\n')
        report = triage([self.log])
        self.assertEqual(report["counts"]["oversized_lines"], 1)
        self.assertEqual(report["counts"]["valid_records"], 1)

    def test_line_budget_reports_truncation(self):
        self.records([self.event()] * 3)
        report = triage([self.log], max_lines=2)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["counts"]["lines_scanned"], 2)

    def test_pattern_budget_retains_known_patterns(self):
        self.records([self.event(message="first failure"), self.event(message="second failure"), self.event(message="first failure")])
        report = triage([self.log], max_patterns=1)
        self.assertEqual(report["counts"]["ungrouped_errors"], 1)
        self.assertEqual(report["patterns"][0]["count"], 2)

    def test_known_diagnostic_categories(self):
        messages = ["connection reset", "database is locked", "invalid credentials", "disk full", "unclassified failure"]
        self.records([self.event(message=message) for message in messages])
        self.assertEqual(set(triage([self.log])["categories"]), {"connection", "database", "authentication", "capacity", "other"})

    def test_multiple_files_aggregate(self):
        self.records([self.event()])
        second = self.root / "second.jsonl"
        second.write_bytes(self.log.read_bytes())
        report = triage([self.log, second])
        self.assertEqual(report["counts"]["selected_records"], 2)
        self.assertEqual(report["patterns"][0]["count"], 2)

    def test_missing_error_message_is_visible(self):
        self.records([self.event(message=None)])
        self.assertEqual(triage([self.log])["counts"]["unusable_error_messages"], 1)

    def test_invalid_options(self):
        self.records([])
        for options in ({"max_lines": 0}, {"max_patterns": True}, {"since": timestamp("2026-11-25T00:00:00Z"), "until": timestamp("2026-11-24T00:00:00Z")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                triage([self.log], **options)

    def test_cli_persists_summary_and_cannot_overwrite_input(self):
        self.records([self.event()])
        output = self.root / "summary.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.log), "--output", str(output)]), 1)
        self.assertEqual(json.loads(output.read_text())["counts"]["selected_records"], 1)
        original = self.log.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.log), "--output", str(self.log)]), 2)
        self.assertEqual(self.log.read_bytes(), original)

    def test_cli_unreadable_input_sanitized_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main([str(self.root / "private-path.jsonl")]), 2)
        self.assertNotIn("private-path", output.getvalue())

    def test_first_last_seen_use_observed_order_not_file_order(self):
        self.records([self.event(timestamp="2026-11-24T10:00:02Z"), self.event(timestamp="2026-11-24T10:00:00Z")])
        report = triage([self.log])
        pattern = report["patterns"][0]
        self.assertLess(pattern["first_seen"], pattern["last_seen"])

    def test_healthy_log_has_no_error_patterns(self):
        self.records([self.event(level="INFO"), self.event(level="WARN")])
        report = triage([self.log])
        self.assertEqual(report["status"], "healthy")
        self.assertEqual(report["patterns"], [])

    def test_invalid_unicode_message_does_not_abort_following_records(self):
        self.records([self.event(message="\ud800"), self.event(level="INFO")])
        report = triage([self.log])
        self.assertEqual(report["counts"]["malformed_lines"], 1)
        self.assertEqual(report["counts"]["selected_records"], 1)
