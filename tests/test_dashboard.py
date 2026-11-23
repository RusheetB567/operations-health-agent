import unittest

from render_dashboard import render
from test_incident_compare import snapshot


class DashboardTests(unittest.TestCase):
    def test_escapes_untrusted_fields(self):
        report = snapshot({"<script>alert(1)</script>": "healthy"})
        report["services"][0]["group"] = '<img src=x onerror="alert(1)">'
        page = render(report)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img ", page)
        self.assertIn("&lt;script&gt;", page)

    def test_summary_computed_from_service_rows(self):
        report = snapshot({"api": "warning", "web": "healthy"})
        report["summary"] = {"total": 999, "healthy": 999}
        page = render(report)
        self.assertIn('Warnings<strong>1</strong>', page)
        self.assertNotIn("999", page)

    def test_offline_content_policy(self):
        page = render(snapshot({"api": "healthy"}))
        self.assertIn("default-src 'none'", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<link", page)
        self.assertIn('scope="col"', page)

    def test_recovery_included(self):
        page = render(snapshot({"api": "healthy"}), snapshot({"api": "warning"}))
        self.assertIn("recovered", page)
        self.assertIn("api", page)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            render({"schema_version": 1, "services": []})
