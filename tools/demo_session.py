"""Create a healthy/outage/recovery session using only a local temporary server."""
import argparse
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from watch_services import watch


def demo(output_dir):
    statuses = iter((200, 503, 200))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(next(statuses, 200))
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="session-demo-config-") as directory:
            catalogue = Path(directory) / "services.json"
            catalogue.write_text(json.dumps({"version": 1, "services": [{
                "name": "demo-api", "group": "demo", "type": "http",
                "target": f"http://127.0.0.1:{server.server_port}/ready", "timeout": 3
            }]}), encoding="utf-8")
            summary = watch(catalogue, output_dir, cycles=3, interval=0.1)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    if (summary["state"] != "completed" or summary["warning_cycles"] != 1
            or summary["final_status"] != "healthy"
            or [event["event"] for event in summary["events"]] != ["opened", "recovered"]):
        raise ValueError("demonstration outcomes did not match expected transitions")
    return {"status": "passed", "session": summary["session"], "cycles": summary["completed_cycles"],
            "warning_cycles": summary["warning_cycles"], "final_status": summary["final_status"],
            "events": summary["events"], "note": "evidence retained; temporary server stopped"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/session-demo"))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(demo(args.output_dir), indent=2))
        return 0
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "error": "session demonstration failed; run tests for details"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
