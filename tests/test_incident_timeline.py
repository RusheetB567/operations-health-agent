import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from incident_timeline import align, load_evidence, main, render_timeline


def session(events=None):
    return {"schema_version": 1, "events": events if events is not None else [
        {"service": "api", "event": "opened", "cycle": 2, "timestamp": "2026-11-24T10:01:00Z"}]}


def logs(patterns=None):
    return {"schema_version": 1, "counts": {"selected_records": 20}, "levels": {"ERROR": 20},
            "truncated": False, "patterns": patterns if patterns is not None else [
                {"fingerprint": "a" * 24, "category": "timeout", "count": 2,
                 "first_seen": "2026-11-24T10:00:30Z", "last_seen": "2026-11-24T10:01:30Z"}]}


class TimelineTests(unittest.TestCase):
    def test_empty_evidence_is_not_claimed_complete(self):
        result = align(session([]), logs([]))
        self.assertTrue(result["quality"]["coverage_limited"])
        self.assertEqual(result["status"], "warning")

    def test_inclusive_boundary_overlap(self):
        result = align(session(), logs(), window_seconds=30)
        self.assertEqual(result["summary"]["events_with_span_overlap"], 1)
        self.assertEqual(result["timeline"][0]["matches"][0]["total_pattern_observations"], 2)

    def test_pattern_span_not_exact_log_event_claim(self):
        result = align(session(), logs(), window_seconds=0)
        self.assertEqual(result["timeline"][0]["matches"][0]["basis"], "pattern_range_overlap_not_exact_event_match")
        self.assertIn("do not prove", result["interpretation"])

    def test_non_overlapping_span(self):
        data = logs()
        data["patterns"][0].update(first_seen="2026-11-24T12:00:00Z", last_seen="2026-11-24T12:01:00Z")
        result = align(session(), data)
        self.assertEqual(result["timeline"][0]["alignment"], "no_pattern_span_overlap")

    def test_timezone_normalisation(self):
        data = session()
        data["events"][0]["timestamp"] = "2026-11-24T11:01:00+01:00"
        self.assertEqual(align(data, logs())["timeline"][0]["timestamp"], "2026-11-24T10:01:00+00:00")

    def test_events_sorted_by_observation_time(self):
        data = session()
        data["events"].append({"service": "web", "event": "initial_warning", "cycle": 1, "timestamp": "2026-11-24T10:00:00Z"})
        self.assertEqual([item["service"] for item in align(data, logs())["timeline"]], ["web", "api"])

    def test_untimed_service_event_is_not_given_false_matches(self):
        data = session()
        data["events"][0]["timestamp"] = None
        result = align(data, logs())
        self.assertEqual(result["timeline"][0]["matches"], [])
        self.assertTrue(result["quality"]["coverage_limited"])

    def test_untimed_pattern_reports_limited_coverage(self):
        data = logs()
        data["patterns"][0].update(first_seen=None, last_seen=None)
        result = align(session(), data)
        self.assertEqual(result["summary"]["unanchored_patterns"], 1)
        self.assertEqual(result["timeline"][0]["matches"], [])

    def test_match_cap_is_visible(self):
        patterns = [dict(logs()["patterns"][0], fingerprint=f"{index:024x}") for index in range(3)]
        result = align(session(), logs(patterns), max_matches=1)
        self.assertEqual(result["timeline"][0]["overlapping_patterns"], 3)
        self.assertTrue(result["timeline"][0]["matches_limited"])
        self.assertEqual(len(result["timeline"][0]["matches"]), 1)

    def test_log_window_boundary_limits_visible(self):
        data = logs()
        data["window"] = {"since": "2026-11-24T10:01:00Z", "until": "2026-11-24T10:02:00Z"}
        result = align(session(), data, window_seconds=60)
        self.assertTrue(result["timeline"][0]["window_extends_beyond_selected_log_window"])

    def test_truncated_logs_are_not_claimed_complete(self):
        data = logs()
        data["truncated"] = True
        self.assertTrue(align(session(), data)["quality"]["coverage_limited"])

    def test_unknown_fields_and_secrets_not_copied(self):
        data, summary = session(), logs()
        data["password"] = "private-secret"
        summary["patterns"][0]["message"] = "private-log-message"
        output = json.dumps(align(data, summary))
        self.assertNotIn("private-secret", output)
        self.assertNotIn("private-log-message", output)

    def test_rejects_reversed_duplicate_and_invalid_patterns(self):
        reversed_span = logs()
        reversed_span["patterns"][0]["first_seen"] = "2026-11-25T00:00:00Z"
        duplicate = logs()
        duplicate["patterns"] *= 2
        invalid = logs()
        invalid["patterns"][0]["category"] = "private-arbitrary-value"
        for data in (reversed_span, duplicate, invalid):
            with self.subTest(data=data), self.assertRaises(ValueError):
                align(session(), data)

    def test_invalid_counts_rejected(self):
        data = logs()
        data["counts"]["selected_records"] = 1
        with self.assertRaises(ValueError):
            align(session(), data)

    def test_invalid_options_and_event_labels(self):
        for options in ({"window_seconds": -1}, {"window_seconds": 3601}, {"max_matches": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                align(session(), logs(), **options)
        data = session()
        data["events"][0]["service"] = "<script>alert(1)</script>"
        with self.assertRaises(ValueError):
            align(data, logs())

    def test_no_input_mutation(self):
        data, summary = session(), logs()
        original = copy.deepcopy((data, summary))
        align(data, summary)
        self.assertEqual((data, summary), original)

    def test_html_is_static_and_warns_about_causality(self):
        page = render_timeline(align(session(), logs()))
        self.assertIn("Temporal overlap only", page)
        self.assertNotIn("<script", page)
        self.assertIn("default-src 'none'", page)
        self.assertIn('scope="col"', page)

    def test_loader_rejects_duplicate_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_evidence(path)

    def test_cli_exports_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service, triage = root / "session.json", root / "logs.json"
            service.write_text(json.dumps(session()), encoding="utf-8")
            triage.write_text(json.dumps(logs()), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(service), str(triage), "--output", str(root / "timeline.json"),
                                       "--html-output", str(root / "timeline.html")]), 1)
            self.assertTrue((root / "timeline.html").exists())
            before = service.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(service), str(triage), "--output", str(service)]), 2)
            self.assertEqual(service.read_bytes(), before)
