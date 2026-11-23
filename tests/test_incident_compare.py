import copy
import unittest

from incident_compare import compare_reports, validate_report


def snapshot(states):
    return {"schema_version": 1, "services": [{"name": name, "group": "app", "type": "http",
            "status": status, "detail": {"url": f"http://localhost/{name}", "expected_status": 200}}
            for name, status in states.items()]}


class ComparisonTests(unittest.TestCase):
    def test_failure_and_recovery(self):
        before = snapshot({"web": "healthy", "api": "warning", "db": "warning"})
        after = snapshot({"web": "warning", "api": "healthy", "db": "warning"})
        result = compare_reports(before, after)
        self.assertEqual(result["changes"]["new_failures"], ["web"])
        self.assertEqual(result["changes"]["recovered"], ["api"])
        self.assertEqual(result["changes"]["ongoing_failures"], ["db"])

    def test_removed_failure_is_not_recovery(self):
        result = compare_reports(snapshot({"old": "warning"}), snapshot({"new": "healthy"}))
        self.assertEqual(result["changes"]["recovered"], [])
        self.assertEqual(result["changes"]["removed"], [{"name": "old", "previous_status": "warning"}])

    def test_changed_target_is_not_recovery(self):
        before = snapshot({"api": "warning"})
        after = snapshot({"api": "healthy"})
        after["services"][0]["detail"]["url"] = "http://localhost/different"
        self.assertEqual(compare_reports(before, after)["counts"]["reconfigured"], 1)

    def test_current_state_not_previous_failures_controls_status(self):
        self.assertEqual(compare_reports(snapshot({"api": "warning"}), snapshot({"api": "healthy"}))["status"], "healthy")

    def test_rejects_host_or_duplicate_reports(self):
        invalid = snapshot({"api": "healthy"})
        invalid["services"].append(copy.deepcopy(invalid["services"][0]))
        for report in ({"schema_version": 1, "metrics": {}}, invalid, snapshot({"api": "unknown"})):
            with self.assertRaises(ValueError):
                validate_report(report)

    def test_no_input_mutation(self):
        before = snapshot({"api": "warning"})
        original = copy.deepcopy(before)
        compare_reports(before, snapshot({"api": "healthy"}))
        self.assertEqual(before, original)
