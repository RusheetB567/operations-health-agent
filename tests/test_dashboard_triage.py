import unittest

from render_dashboard import render
from test_incident_compare import snapshot


class DashboardTriageTests(unittest.TestCase):
    def test_failed_service_appears_before_healthy(self):
        page = render(snapshot({"aaa-healthy": "healthy", "zzz-failed": "warning"}))
        self.assertLess(page.index('scope="row">zzz-failed'), page.index('scope="row">aaa-healthy'))

    def test_group_counts_computed_from_rows(self):
        report = snapshot({"api": "warning", "web": "healthy", "db": "healthy"})
        report["services"][2]["group"] = "infrastructure"
        page = render(report)
        self.assertIn('<td>app</td><td>2</td><td>1</td><td>1</td>', page)
        self.assertIn('<td>infrastructure</td><td>1</td><td>1</td><td>0</td>', page)

    def test_group_labels_are_escaped(self):
        report = snapshot({"api": "healthy"})
        report["services"][0]["group"] = "<script>bad</script>"
        page = render(report)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", page)
