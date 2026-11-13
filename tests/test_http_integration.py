import contextlib
import io
import json
import unittest
from unittest.mock import patch

import system_health as health


class HttpIntegrationTests(unittest.TestCase):
    def test_http_failure_warns_even_when_resources_healthy(self):
        metrics = dict(cpu_percent=1, memory_percent=1, disk_percent=1, uptime_seconds=10)
        with patch.object(health, "collect", return_value=metrics):
            with patch.object(health, "check_http", return_value={"status": "unexpected_status", "http_status": 503}):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    code = health.main(["--http", "http://localhost:8080/ready"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["http_checks"][0]["http_status"], 503)
