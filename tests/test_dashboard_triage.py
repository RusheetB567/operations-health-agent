import unittest

from render_dashboard import render
from test_incident_compare import snapshot


class DashboardTriageTests(unittest.TestCase):
    def test_failed_service_appears_before_healthy(self):
        page = render(snapshot({"aaa-healthy": "healthy", "zzz-failed": "warning"}))
        self.assertLess(page.index("<td>zzz-failed</td>"), page.index("<td>aaa-healthy</td>"))

    def test_group_counts_computed_from_rows(self):
        report = snapshot({"api": "warning", "web": "healthy", "db": "healthy"})
        report["services"][2]["group"] = "infrastructure"
        page = render(report)
        self.assertIn("app: 1 healthy, 1 warning", page)
        self.assertIn("infrastructure: 1 healthy, 0 warning", page)

    def test_group_labels_are_escaped(self):
        report = snapshot({"api": "healthy"})
        report["services"][0]["group"] = "<script>bad</script>"
        page = render(report)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", page)
