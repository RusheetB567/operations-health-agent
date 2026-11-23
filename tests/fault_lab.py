"""Loopback-only HTTP fault fixture; no external services or credentials needed."""
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace


@contextmanager
def application_lab():
    state = SimpleNamespace(unhealthy=False, requests=[], lock=threading.Lock(), release=threading.Event())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with state.lock:
                state.requests.append(self.path)
                unhealthy = state.unhealthy
            if self.path == "/stall":
                state.release.wait(5)
                return
            if self.path == "/disconnect":
                self.close_connection = True
                return
            code = 302 if self.path == "/redirect" else 503 if unhealthy else 200
            self.send_response(code)
            if code == 302:
                self.send_header("Location", "/ready")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        if worker.is_alive():
            raise RuntimeError("fault fixture did not stop")
