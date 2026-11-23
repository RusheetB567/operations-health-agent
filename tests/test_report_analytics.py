import copy
import math
import unittest

from report_analytics import duration, order_services, select_report, statistics
from test_incident_compare import snapshot


def timed_report(values):
    report = snapshot({f"service-{index}": "healthy" for index in range(len(values))})
    for item, value in zip(report["services"], values):
        item["detail"]["duration_ms"] = value
    return report


class AnalyticsTests(unittest.TestCase):
    def test_percentiles_nearest_rank(self):
        stats = statistics(timed_report([10, 20, 30, 40, 100]), 40)
        self.assertEqual(stats["probe_duration"]["p50_ms"], 30)
        self.assertEqual(stats["probe_duration"]["p95_ms"], 100)
        self.assertEqual(stats["probe_duration"]["mean_ms"], 40)
        self.assertEqual(stats["probe_duration"]["slow_count"], 2)

    def test_invalid_timings_are_not_treated_as_zero(self):
        report = timed_report([None, "fast", True, -1, math.nan, math.inf, 0])
        stats = statistics(report)
        self.assertEqual(stats["probe_duration"]["valid"], 1)
        self.assertEqual(stats["probe_duration"]["missing_or_invalid"], 6)
        self.assertEqual(stats["probe_duration"]["p50_ms"], 0)

    def test_no_timing_data(self):
        stats = statistics(snapshot({"api": "healthy"}))
        self.assertIsNone(stats["probe_duration"]["p95_ms"])
        self.assertEqual(stats["slowest"], [])

    def test_single_timing(self):
        stats = statistics(timed_report([21]))
        self.assertEqual(stats["probe_duration"]["p50_ms"], 21)
        self.assertEqual(stats["probe_duration"]["p95_ms"], 21)

    def test_group_health_computed_from_rows(self):
        report = snapshot({"web": "healthy", "api": "warning"})
        report["services"][1]["group"] = "backend"
        report["summary"] = {"total": 999}
        stats = statistics(report)
        self.assertEqual(stats["healthy_percent"], 50)
        self.assertEqual(stats["groups"]["backend"]["healthy_percent"], 0)

    def test_duration_sort_missing_last(self):
        report = timed_report([None, 10, 100])
        self.assertEqual([item["name"] for item in order_services(report["services"], "duration")],
                         ["service-2", "service-1", "service-0"])

    def test_health_sort_prioritizes_warning(self):
        report = snapshot({"a": "healthy", "z": "warning"})
        self.assertEqual(order_services(report["services"])[0]["name"], "z")

    def test_group_and_warning_filters(self):
        report = snapshot({"api": "warning", "web": "healthy"})
        self.assertEqual(len(select_report(report, warnings_only=True)["services"]), 1)
        with self.assertRaises(ValueError):
            select_report(report, "missing")

    def test_source_is_not_mutated(self):
        report = timed_report([10, 20])
        original = copy.deepcopy(report)
        statistics(report)
        select_report(report)
        self.assertEqual(report, original)

    def test_invalid_threshold_rejected(self):
        for value in (0, -1, math.inf, math.nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                statistics(timed_report([10]), value)
