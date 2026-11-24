import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import portable_pack as portable
import review_evidence as review
from triage_logs import timestamp


def rule(kind="error_records_at_least", severity="review", threshold=2, **values):
    result = {"id": "test-rule", "type": kind, "severity": severity, **values}
    if kind != "coverage_limited":
        result["threshold"] = threshold
    return result


def policy(*rules):
    return {"version": 1, "name": "test-policy", "rules": list(rules or [rule()])}


def facts(**changes):
    return {"pack_id": "a" * 64, "created_at": "2026-11-24T10:00:00Z", "error_records": 2,
            "service_events": 3, "categories": {"timeout": 2}, "coverage_limited": False, **changes}


class ReviewRuleTests(unittest.TestCase):
    def evaluate(self, data=None, rules=None, at="2026-11-24T10:05:00Z"):
        return review.evaluate(data or facts(), rules or policy(), timestamp(at))

    def test_inclusive_threshold_triggers_review(self):
        self.assertEqual(self.evaluate()["decision"], "review")

    def test_no_matches_pass(self):
        self.assertEqual(self.evaluate(rules=policy(rule(threshold=3)))["decision"], "pass")

    def test_block_takes_precedence(self):
        rules = policy(rule(), rule("category_records_at_least", "block", category="timeout", id="blocking"))
        self.assertEqual(self.evaluate(rules=rules)["decision"], "block")

    def test_unknown_coverage_forces_review_not_pass(self):
        result = self.evaluate(facts(coverage_limited=None), policy(rule("coverage_limited", "block")))
        self.assertEqual(result["decision"], "review")
        self.assertEqual(result["checks"][0]["state"], "unknown")

    def test_known_coverage_limit_matches(self):
        self.assertEqual(self.evaluate(facts(coverage_limited=True), policy(rule("coverage_limited", "block")))["decision"], "block")

    def test_age_threshold_uses_explicit_reference(self):
        result = self.evaluate(rules=policy(rule("age_minutes_at_least", "block", threshold=5)))
        self.assertEqual(result["decision"], "block")
        self.assertEqual(result["checks"][0]["observed"], 5)

    def test_future_pack_cannot_silently_pass(self):
        result = self.evaluate(rules=policy(rule(threshold=100)), at="2026-11-24T09:00:00Z")
        self.assertEqual(result["decision"], "review")
        self.assertIn("pack_creation_is_after_reference_time", result["guards"])

    def test_missing_category_is_zero(self):
        result = self.evaluate(rules=policy(rule("category_records_at_least", category="database")))
        self.assertEqual(result["checks"][0]["observed"], 0)

    def test_service_event_rule(self):
        result = self.evaluate(rules=policy(rule("service_events_at_least", threshold=3)))
        self.assertEqual(result["checks"][0]["state"], "matched")

    def test_duplicate_ids_unknown_fields_and_invalid_types_rejected(self):
        duplicate = policy(rule(), rule())
        unknown = policy({**rule(), "execute": "anything"})
        boolean = policy(rule(threshold=True))
        for value in (duplicate, unknown, boolean, policy(rule("shell"))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                review.validate_policy(value)

    def test_policy_identity_ignores_key_order(self):
        original = policy()
        reordered = {key: original[key] for key in reversed(original)}
        self.assertEqual(self.evaluate(rules=original)["policy_sha256"], self.evaluate(rules=reordered)["policy_sha256"])

    def test_inputs_not_mutated(self):
        data, rules = facts(), policy()
        before = copy.deepcopy((data, rules))
        self.evaluate(data, rules)
        self.assertEqual((data, rules), before)

    def test_html_static_and_explicitly_advisory(self):
        page = review.render_review(self.evaluate())
        self.assertNotIn("<script", page)
        self.assertIn("default-src 'none'", page)
        self.assertIn("recommendation only", page)


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack = self.root / "evidence"
        self.pack.mkdir()
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_text(json.dumps(policy(rule(severity="block"))), encoding="utf-8")
        summary = {"selected_log_records": 2, "error_records": 2, "service_events": 1}
        payloads = {
            "timeline.json": json.dumps({"schema_version": 1, "summary": summary, "quality": {"coverage_limited": False}}),
            "logs.json": json.dumps({"schema_version": 1, "categories": {"timeout": 2}}),
            "observations.json": '{}', "timeline.html": '<html>fixture</html>', "notes.md": "PRIVATE_RAW_CONTENT",
        }
        for name, text in payloads.items():
            (self.pack / name).write_text(text, encoding="utf-8")
        manifest = {"schema_version": 1, "pack_type": "incident-investigation", "created_at": "2026-11-24T10:00:00Z",
                    "summary": summary, "files": {"report": "timeline.json", "dashboard": "timeline.html",
                    "observations": "observations.json", "log_summary": "logs.json", "notes": "notes.md"},
                    "sha256": {name: portable.checksum((self.pack / name).read_bytes()) for name in payloads}}
        (self.pack / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_verified_pack_facts_exclude_private_contents(self):
        data = review.facts_from_pack(self.pack)
        self.assertNotIn("PRIVATE_RAW_CONTENT", json.dumps(data))
        self.assertNotIn(str(self.root), json.dumps(data))

    def test_changed_artifact_stops_evaluation(self):
        (self.pack / "notes.md").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            review.facts_from_pack(self.pack)

    def test_duplicate_json_policy_key_rejected(self):
        self.policy_path.write_text('{"version":1,"version":1}', encoding="utf-8")
        with self.assertRaises(ValueError):
            review.load_policy(self.policy_path)

    def test_cli_exports_block_recommendation_exit_three(self):
        output = self.root / "review.json"
        page = self.root / "review.html"
        result = subprocess.run([sys.executable, str(Path(review.__file__)), str(self.pack), "--policy", str(self.policy_path),
                                 "--at", "2026-11-24T10:05:00Z", "--output", str(output), "--html-output", str(page)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(json.loads(output.read_text())["decision"], "block")
        self.assertTrue(page.exists())

    def test_outputs_cannot_overwrite_policy_or_pack(self):
        for output in (self.policy_path, self.pack / "manifest.json"):
            with contextlib.redirect_stderr(io.StringIO()):
                code = review.main([str(self.pack), "--policy", str(self.policy_path), "--output", str(output)])
            self.assertEqual(code, 2)
