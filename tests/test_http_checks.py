import argparse
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from http_checks import check_http, http_url


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = {"/ready": 200, "/down": 503, "/redirect": 302}.get(self.path, 404)
        self.send_response(code)
        if code == 302:
            self.send_header("Location", "/ready")
        self.end_headers()

    def log_message(self, *args):
        pass


class HttpTests(unittest.TestCase):
    def test_live_readiness_and_redirect_not_followed(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                self.assertEqual(check_http(origin + "/ready")["status"], "ready")
                self.assertEqual(check_http(origin + "/down")["http_status"], 503)
                self.assertEqual(check_http(origin + "/redirect")["status"], "unexpected_status")
                self.assertEqual(check_http(origin + "/down", expected_status=503)["status"], "ready")
            finally:
                server.shutdown()
                worker.join()

    def test_timeout(self):
        with patch("http_checks.subprocess.run", side_effect=subprocess.TimeoutExpired("http", 1)):
            self.assertEqual(check_http("http://localhost")["status"], "timeout")

    def test_private_exception_output_not_in_report(self):
        failure = subprocess.CompletedProcess([], 1, "", "private-token-in-error")
        with patch("http_checks.subprocess.run", return_value=failure):
            self.assertNotIn("private-token", str(check_http("http://localhost")))

    def test_reject_credential_and_invalid_urls(self):
        for value in ("file:///tmp/test", "http://user:password@localhost", "http://localhost/?token=x",
                      "http://localhost/#secret", "http://localhost:99999", "http://localhost/\n"):
            with self.assertRaises(argparse.ArgumentTypeError):
                http_url(value)
