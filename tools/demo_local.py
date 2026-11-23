"""Run a self-contained loopback demo; remove generated data on exit."""
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_demo():
    state = {"failed": False}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503 if state["failed"] else 200)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    steps = []
    try:
        with tempfile.TemporaryDirectory(prefix="health-agent-demo-") as directory:
            temporary = Path(directory)
            def command(script, arguments, expected):
                process = subprocess.run([sys.executable, str(ROOT / script), *map(str, arguments)],
                                         cwd=temporary, text=True, capture_output=True, timeout=15)
                if process.returncode != expected:
                    raise RuntimeError(f"{script}: expected exit {expected}, got {process.returncode}")
                return json.loads(process.stdout)
            catalogue = temporary / "services.json"
            catalogue.write_text(json.dumps({"version": 1, "services": [{
                "name": "demo-api", "group": "demo", "type": "http",
                "target": f"http://127.0.0.1:{server.server_port}/ready", "timeout": 3
            }]}), encoding="utf-8")
            for label, failed, exit_code in (("healthy", False, 0), ("outage", True, 1), ("recovered", False, 0)):
                state["failed"] = failed
                report = command("service_monitor.py", [catalogue, "--output", temporary / "services-report.json"], exit_code)
                steps.append({"step": label, "exit_code": exit_code, "status": report["status"]})
            profile = temporary / "profile.json"
            database = temporary / "history.sqlite3"
            profile.write_text(json.dumps({"samples": 1, "history-db": str(database),
                                           "cpu-threshold": 100, "memory-threshold": 100, "disk-threshold": 100}),
                               encoding="utf-8")
            command("run_profile.py", [profile, "--check"], 0)
            # Resource saturation may legitimately return a warning on a busy machine.
            process = subprocess.run([sys.executable, str(ROOT / "run_profile.py"), str(profile)],
                                     cwd=temporary, text=True, capture_output=True, timeout=15)
            if process.returncode not in (0, 1):
                raise RuntimeError("profile collection failed")
            json.loads(process.stdout)
            history = command("system_health.py", ["--history-db", database, "--show-history", "1"], 0)
            if len(history) != 1:
                raise RuntimeError("history did not retain the report")
            steps.append({"step": "profile-and-history", "retained_reports": len(history)})
            log = temporary / "synthetic.jsonl"
            log.write_text('{"level":"ERROR","password":"demo-private-value"}\ninvalid synthetic record\n', encoding="utf-8")
            summary = command("log_analyzer.py", [log], 1)
            if "demo-private-value" in json.dumps(summary) or summary["malformed_lines"] != 1:
                raise RuntimeError("log privacy or malformed-record check failed")
            steps.append({"step": "log-analysis", "status": summary["status"], "sensitive_fields_excluded": True})
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return {"status": "passed", "steps": steps, "temporary_data_removed": True}


if __name__ == "__main__":
    try:
        print(json.dumps(run_demo(), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "failed", "error": "local demo failed; check environment and run the test suite"}), file=sys.stderr)
        sys.exit(2)
