import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import service_monitor as service


class ServiceTests(unittest.TestCase):
    def test_real_http_tcp_catalogue_and_saved_report(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.end_headers()
            def log_message(self, *args):
                pass
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with tempfile.TemporaryDirectory() as directory:
                    catalogue = Path(directory) / "services.json"
                    output = Path(directory) / "report.json"
                    port = server.server_port
                    catalogue.write_text(json.dumps({"version": 1, "services": [
                        self.entry(target=f"http://127.0.0.1:{port}/ready", expected_status=204),
                        self.entry(name="listener", type="tcp", target=f"127.0.0.1:{port}")
                    ]}), encoding="utf-8")
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(service.main([str(catalogue), "--output", str(output)]), 0)
                    self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["summary"]["healthy"], 2)
            finally:
                server.shutdown()
                worker.join()
    def test_real_http_tcp_catalogue_and_saved_report(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.end_headers()
            def log_message(self, *args):
                pass
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with tempfile.TemporaryDirectory() as directory:
                    catalogue = Path(directory) / "services.json"
                    output = Path(directory) / "report.json"
                    port = server.server_port
                    catalogue.write_text(json.dumps({"version": 1, "services": [
                        self.entry(target=f"http://127.0.0.1:{port}/ready", expected_status=204),
                        self.entry(name="listener", type="tcp", target=f"127.0.0.1:{port}")
                    ]}), encoding="utf-8")
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(service.main([str(catalogue), "--output", str(output)]), 0)
                    self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["summary"]["healthy"], 2)
            finally:
                server.shutdown()
                worker.join()
    def entry(self, **changes):
        return {"name": "api", "type": "http", "target": "http://localhost/health", **changes}

    def load(self, entries):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "services.json"
            path.write_text(json.dumps({"version": 1, "services": entries}), encoding="utf-8")
            return service.load_catalogue(path)

    def test_strict_schema(self):
        for entries in ([], [self.entry(), self.entry()], [self.entry(name="../secret")],
                        [self.entry(timeout=False)], [self.entry(timeout=float("inf"))],
                        [self.entry(expected_status=99)], [self.entry(extra="typo")],
                        [self.entry(type="tcp", target="localhost:5432", expected_status=200)]):
            with self.subTest(entries=entries), self.assertRaises((ValueError, service.argparse.ArgumentTypeError)):
                self.load(entries)

    def test_expected_status_and_group_summary(self):
        entries = self.load([self.entry(expected_status=204), self.entry(name="web", group="frontend")])
        with patch.object(service, "check_http", side_effect=[{"status": "ready"}, {"status": "unexpected_status"}]) as check:
            report = service.monitor(entries, workers=1)
        self.assertEqual(check.call_args_list[0].args[2], 204)
        self.assertEqual(report["summary"], {"total": 2, "healthy": 1, "warning": 1})
        self.assertEqual(report["groups"]["frontend"]["warning"], 1)

    def test_worker_failure_isolated_and_sanitized(self):
        entries = self.load([self.entry(), self.entry(name="web")])
        with patch.object(service, "check_http", side_effect=[RuntimeError("secret-value"), {"status": "ready"}]):
            report = service.monitor(entries, 1)
        self.assertEqual(report["summary"]["healthy"], 1)
        self.assertNotIn("secret-value", json.dumps(report))

    def test_parallelism_bounded_and_order_preserved(self):
        entries = self.load([self.entry(name=f"api-{index}") for index in range(8)])
        lock = threading.Lock()
        active = maximum = 0
        def check(*args):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"status": "ready"}
        with patch.object(service, "check_http", side_effect=check):
            report = service.monitor(entries, 2)
        self.assertEqual(maximum, 2)
        self.assertEqual([item["name"] for item in report["services"]], [item["name"] for item in entries])

    def test_tcp_service(self):
        entries = self.load([self.entry(type="tcp", target="localhost:5432")])
        with patch.object(service, "probe_target", return_value={"status": "reachable"}):
            self.assertEqual(service.monitor(entries)["status"], "healthy")

    def test_validation_and_group_filter_make_no_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "services.json"
            path.write_text(json.dumps({"version": 1, "services": [self.entry(group="backend")]}), encoding="utf-8")
            with patch.object(service, "monitor", side_effect=AssertionError("network must not run")):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(service.main([str(path), "--check", "--group", "backend"]), 0)
                    self.assertEqual(service.main([str(path), "--check", "--group", "missing"]), 2)
