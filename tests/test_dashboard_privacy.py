import copy
import unittest

from render_dashboard import render
from test_incident_compare import snapshot


class DashboardPrivacyTests(unittest.TestCase):
    def test_http_target_hidden(self):
        report = snapshot({"api": "healthy"})
        report["services"][0]["detail"]["url"] = "http://private-host.example:9999/internal"
        page = render(report, redact_targets=True)
        self.assertNotIn("private-host.example", page)
        self.assertIn("[endpoint hidden]", page)

    def test_tcp_target_hidden(self):
        report = snapshot({"database": "healthy"})
        report["services"][0].update(type="tcp", detail={"host": "192.0.2.88", "port": 5432})
        self.assertNotIn("192.0.2.88", render(report, redact_targets=True))

    def test_default_preserves_detail(self):
        self.assertIn("http://localhost/api", render(snapshot({"api": "healthy"})))

    def test_original_report_unchanged(self):
        report = snapshot({"api": "warning"})
        original = copy.deepcopy(report)
        render(report, redact_targets=True)
        self.assertEqual(report, original)
