"""Local-only web console for real service checks, log triage and evidence review."""
import argparse
import ipaddress
import json
import math
import secrets
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psutil
from http_checks import http_url
from network_checks import endpoint
from run_profile import unique_object
from service_monitor import monitor
from triage_logs import triage

MAX_BODY = 1024 * 1024
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}


def now():
    return datetime.now(timezone.utc).isoformat()


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def local_target(protocol, target):
    if not isinstance(target, str) or len(target) > 2048:
        raise RequestError("Enter a local service address.")
    try:
        if protocol == "http":
            http_url(target)
            host = urlsplit(target).hostname
        else:
            host, _ = endpoint(target)
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError
    except Exception:
        raise RequestError("Today’s console supports localhost and loopback IP addresses only.") from None
    return target


def service_fields(payload):
    import re
    allowed = {"name", "group", "type", "target", "timeout", "expected_status", "enabled"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise RequestError("Unsupported service fields.")
    result = dict(payload)
    for key, default in (("name", None), ("group", "application")):
        value = result.get(key, default)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            raise RequestError("Names and groups need 1–64 letters, digits, dots, underscores or hyphens.")
        result[key] = value
    if result.get("type") not in ("http", "tcp"):
        raise RequestError("Choose HTTP or TCP.")
    local_target(result["type"], result.get("target"))
    timeout = result.get("timeout", 3)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 10:
        raise RequestError("Timeout must be greater than zero and at most 10 seconds.")
    result["timeout"] = timeout
    expected = result.get("expected_status", 200)
    if type(expected) is not int or not 100 <= expected <= 599:
        raise RequestError("Expected HTTP status must be 100–599.")
    result["expected_status"] = expected
    enabled = result.get("enabled", True)
    if type(enabled) is not bool:
        raise RequestError("Enabled must be true or false.")
    result["enabled"] = enabled
    return result


class ConsoleState:
    def __init__(self, root, data_dir=None):
        self.root = Path(root).resolve()
        self.data_dir = Path(data_dir) if data_dir else self.root / "reports" / "console"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "console.sqlite3"
        self.token = secrets.token_urlsafe(32)
        self.port = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="console-check")
        self.lock = threading.RLock()
        self.demo_degraded = True
        self.evidence_verifications = {}
        with self.db() as db:
            db.executescript('''
CREATE TABLE IF NOT EXISTS services(id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,group_name TEXT NOT NULL,protocol TEXT NOT NULL,target TEXT NOT NULL,timeout REAL NOT NULL,expected_status INTEGER NOT NULL,enabled INTEGER NOT NULL,revision INTEGER NOT NULL,is_demo INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,state TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,report TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS observations(run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,service_id TEXT,revision INTEGER,payload TEXT,PRIMARY KEY(run_id,service_id));
CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,service_id TEXT NOT NULL,revision INTEGER NOT NULL,service_name TEXT NOT NULL,target TEXT NOT NULL,state TEXT NOT NULL,owner TEXT NOT NULL DEFAULT '',opened_at TEXT NOT NULL,last_seen TEXT NOT NULL,resolved_at TEXT,resolution TEXT,failures INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_incident ON incidents(service_id,revision) WHERE state IN ('open','acknowledged');
CREATE TABLE IF NOT EXISTS incident_events(id INTEGER PRIMARY KEY AUTOINCREMENT,incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,kind TEXT NOT NULL,created_at TEXT NOT NULL,detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS triages(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,summary TEXT NOT NULL);
''')
            db.execute("UPDATE runs SET state='interrupted',finished_at=?,error='Console restarted before this run completed.' WHERE state IN ('queued','running')", (now(),))

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def services(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM services ORDER BY created_at,id").fetchall()
            results = []
            for row in rows:
                last = db.execute("SELECT o.payload,r.finished_at FROM observations o JOIN runs r ON r.id=o.run_id WHERE o.service_id=? AND o.revision=? AND r.state='completed' ORDER BY r.finished_at DESC LIMIT 1", (row["id"], row["revision"])).fetchone()
                value = {"id": row["id"], "name": row["name"], "group": row["group_name"], "type": row["protocol"],
                         "target": row["target"], "timeout": row["timeout"], "expected_status": row["expected_status"],
                         "enabled": bool(row["enabled"]), "is_demo": bool(row["is_demo"]), "revision": row["revision"],
                         "last": json.loads(last["payload"]) if last else None, "checked_at": last["finished_at"] if last else None}
                results.append(value)
            return results

    def save_service(self, payload, identity=None):
        fields = service_fields(payload)
        with self.db() as db:
            current = db.execute("SELECT * FROM services WHERE id=?", (identity,)).fetchone() if identity else None
            if identity and not current:
                raise RequestError("Service not found.", 404)
            if not identity and db.execute("SELECT COUNT(*) FROM services").fetchone()[0] >= 50:
                raise RequestError("The local console supports up to 50 services.")
            try:
                if identity:
                    changed = any(current[key] != fields[value] for key, value in (("name", "name"), ("group_name", "group"), ("protocol", "type"), ("target", "target"), ("timeout", "timeout"), ("expected_status", "expected_status")))
                    if changed:
                        self._resolve_incidents(db, identity, "configuration_changed")
                    db.execute("UPDATE services SET name=?,group_name=?,protocol=?,target=?,timeout=?,expected_status=?,enabled=?,revision=revision+? WHERE id=?", (fields["name"], fields["group"], fields["type"], fields["target"], fields["timeout"], fields["expected_status"], int(fields["enabled"]), int(changed), identity))
                else:
                    identity = uuid.uuid4().hex
                    db.execute("INSERT INTO services VALUES(?,?,?,?,?,?,?,?,?,?,?)", (identity, fields["name"], fields["group"], fields["type"], fields["target"], fields["timeout"], fields["expected_status"], int(fields["enabled"]), 1, 0, now()))
            except sqlite3.IntegrityError:
                raise RequestError("A service with this name already exists.", 409) from None
        return {"id": identity}

    def delete_service(self, identity):
        with self.db() as db:
            self._resolve_incidents(db, identity, "service_removed")
            if db.execute("DELETE FROM services WHERE id=?", (identity,)).rowcount != 1:
                raise RequestError("Service not found.", 404)
        return {"deleted": True}

    @staticmethod
    def _incident_event(db, identity, kind, detail):
        db.execute("INSERT INTO incident_events(incident_id,kind,created_at,detail) VALUES(?,?,?,?)", (identity, kind, now(), detail))

    def _resolve_incidents(self, db, service_id, reason):
        for row in db.execute("SELECT id FROM incidents WHERE service_id=? AND state IN ('open','acknowledged')", (service_id,)).fetchall():
            db.execute("UPDATE incidents SET state='resolved',resolved_at=?,resolution=?,version=version+1 WHERE id=?", (now(), reason, row["id"]))
            self._incident_event(db, row["id"], "resolved", reason)
        db.execute("DELETE FROM incidents WHERE state='resolved' AND id NOT IN (SELECT id FROM incidents WHERE state='resolved' ORDER BY resolved_at DESC LIMIT 200)")

    def _observe_incident(self, db, source, result):
        # Ignore results from configurations that were edited, paused or removed mid-run.
        current = db.execute("SELECT revision,enabled FROM services WHERE id=?", (source["id"],)).fetchone()
        if not current or current["revision"] != source["revision"] or not current["enabled"]:
            return
        incident = db.execute("SELECT id FROM incidents WHERE service_id=? AND revision=? AND state IN ('open','acknowledged')", (source["id"], source["revision"])).fetchone()
        if result["status"] == "healthy":
            if incident:
                self._resolve_incidents(db, source["id"], "recovered")
            return
        if incident:
            db.execute("UPDATE incidents SET last_seen=?,failures=failures+1,version=version+1 WHERE id=?", (now(), incident["id"]))
            return
        identity = uuid.uuid4().hex
        timestamp = now()
        db.execute("INSERT INTO incidents(id,service_id,revision,service_name,target,state,opened_at,last_seen) VALUES(?,?,?,?,?,'open',?,?)", (identity, source["id"], source["revision"], source["name"], source["target"], timestamp, timestamp))
        self._incident_event(db, identity, "opened", "A completed check observed a warning.")
        # Keep the most recent 200 resolved incidents; never discard active work.
        db.execute("DELETE FROM incidents WHERE state='resolved' AND id NOT IN (SELECT id FROM incidents WHERE state='resolved' ORDER BY resolved_at DESC LIMIT 200)")

    def incidents(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM incidents ORDER BY CASE WHEN state='resolved' THEN 1 ELSE 0 END,opened_at DESC LIMIT 250").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["events"] = [dict(event) for event in db.execute("SELECT kind,created_at,detail FROM incident_events WHERE incident_id=? ORDER BY id DESC LIMIT 50", (row["id"],))]
                result.append(item)
            return result

    def update_incident(self, identity, payload):
        if set(payload) - {"version", "action", "owner", "note"} or type(payload.get("version")) is not int:
            raise RequestError("Send the current incident version and supported fields.")
        action = payload.get("action")
        owner, note = payload.get("owner", ""), payload.get("note", "")
        if action not in ("acknowledge", "note", "assign"):
            raise RequestError("Choose acknowledge, assign or note.")
        if not isinstance(owner, str) or len(owner) > 80 or any(ord(c) < 32 for c in owner):
            raise RequestError("Owner must be at most 80 characters without control characters.")
        if not isinstance(note, str) or len(note) > 2000 or any(ord(c) < 32 and c not in "\n\r\t" for c in note):
            raise RequestError("Notes must be at most 2,000 characters without control characters.")
        owner, note = owner.strip(), note.strip()
        if action in ("acknowledge", "assign") and not owner:
            raise RequestError("Enter an owner for this incident.")
        if action == "note" and not note:
            raise RequestError("Enter an investigation note.")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM incidents WHERE id=?", (identity,)).fetchone()
            if not row:
                raise RequestError("Incident not found.", 404)
            if row["version"] != payload["version"]:
                raise RequestError("This incident changed. Reopen it to load the latest version.", 409)
            if row["state"] == "resolved" and action != "note":
                raise RequestError("This incident has already resolved. You can still add a note.", 409)
            count = db.execute("SELECT COUNT(*) FROM incident_events WHERE incident_id=?", (identity,)).fetchone()[0]
            needed = int(action != "note") + int(bool(note))
            limit = 200 if row["state"] == "resolved" else 199
            if count + needed > limit:
                raise RequestError("This incident has reached its activity limit; space is reserved for recovery.", 409)
            if action == "acknowledge":
                if row["state"] != "open":
                    raise RequestError("This incident is already acknowledged.", 409)
                db.execute("UPDATE incidents SET state='acknowledged',owner=?,version=version+1 WHERE id=?", (owner, identity))
                self._incident_event(db, identity, "acknowledged", owner)
            elif action == "assign":
                db.execute("UPDATE incidents SET owner=?,version=version+1 WHERE id=?", (owner, identity))
                self._incident_event(db, identity, "assigned", owner)
            else:
                db.execute("UPDATE incidents SET version=version+1 WHERE id=?", (identity,))
            if note:
                self._incident_event(db, identity, "note", note)
        return {"updated": True}

    def runs(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 30").fetchall()
        return [{"id": row["id"], "state": row["state"], "started_at": row["started_at"], "finished_at": row["finished_at"],
                 "report": json.loads(row["report"]) if row["report"] else None, "error": row["error"]} for row in rows]

    def start_check(self, ids=None):
        if ids is not None and (not isinstance(ids, list) or not ids or len(ids) > 50 or any(not isinstance(value, str) for value in ids)):
            raise RequestError("Select one or more service IDs.")
        with self.lock:
            snapshots = [item for item in self.services() if item["enabled"] and (ids is None or item["id"] in ids)]
            if not snapshots:
                raise RequestError("Add or enable a service first.")
            with self.db() as db:
                if db.execute("SELECT COUNT(*) FROM runs WHERE state IN ('queued','running')").fetchone()[0]:
                    raise RequestError("A check is already running. Please wait for it to finish.", 409)
                identity = uuid.uuid4().hex
                db.execute("INSERT INTO runs(id,state,started_at) VALUES(?,?,?)", (identity, "queued", now()))
            self.executor.submit(self._check_worker, identity, snapshots)
            return {"id": identity, "state": "queued"}

    def _check_worker(self, identity, snapshots):
        try:
            with self.db() as db:
                db.execute("UPDATE runs SET state='running' WHERE id=?", (identity,))
            report = monitor(snapshots, workers=min(4, len(snapshots)))
            indexed = {item["name"]: item for item in snapshots}
            with self.db() as db:
                for result in report["services"]:
                    source = indexed[result["name"]]
                    self._observe_incident(db, source, result)
                    db.execute("INSERT INTO observations VALUES(?,?,?,?)", (identity, source["id"], source["revision"], json.dumps(result)))
                db.execute("UPDATE runs SET state='completed',finished_at=?,report=? WHERE id=?", (now(), json.dumps(report), identity))
                db.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY started_at DESC LIMIT 200)")
        except Exception:
            with self.db() as db:
                db.execute("UPDATE runs SET state='failed',finished_at=?,error=? WHERE id=?", (now(), "The check could not complete. Try again after reviewing the service settings.", identity))

    def demo(self, action):
        with self.lock:
            with self.db() as db:
                if db.execute("SELECT COUNT(*) FROM runs WHERE state IN ('queued','running')").fetchone()[0]:
                    raise RequestError("A check is already running. Please wait for it to finish.", 409)
            return self._demo(action)

    def _demo(self, action):
        if action not in ("seed", "recover", "degrade"):
            raise RequestError("Unknown local lab action.")
        if action == "seed":
            targets = [("lab-api", "http", f"http://127.0.0.1:{self.port}/demo/ready"),
                       ("lab-worker", "http", f"http://127.0.0.1:{self.port}/demo/worker"),
                       ("lab-listener", "tcp", f"127.0.0.1:{self.port}")]
            with self.db() as db:
                for name, protocol, target in targets:
                    current = db.execute("SELECT id,is_demo,target FROM services WHERE name=?", (name,)).fetchone()
                    if current and not current["is_demo"]:
                        raise RequestError("A local lab name is already in use by one of your services.", 409)
                additions = sum(not db.execute("SELECT 1 FROM services WHERE name=?", (item[0],)).fetchone() for item in targets)
                if db.execute("SELECT COUNT(*) FROM services").fetchone()[0] + additions > 50:
                    raise RequestError("Make room for three local lab services first.")
                for name, protocol, target in targets:
                    current = db.execute("SELECT id,target FROM services WHERE name=?", (name,)).fetchone()
                    if current:
                        db.execute("UPDATE services SET target=?,enabled=1,revision=revision+? WHERE id=?", (target, int(current["target"] != target), current["id"]))
                    else:
                        db.execute("INSERT INTO services VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, name, "local-lab", protocol, target, 3, 200, 1, 1, 1, now()))
        elif not any(item["is_demo"] for item in self.services()):
            raise RequestError("Load the local lab first.")
        with self.lock:
            self.demo_degraded = action != "recover"
        ids = [item["id"] for item in self.services() if item["is_demo"]]
        return self.start_check(ids)

    def overview(self):
        services = self.services()
        runs = self.runs()
        enabled = [item for item in services if item["enabled"]]
        durations = sorted(item["last"]["detail"].get("duration_ms", 0) for item in enabled if item["last"])
        memory = psutil.virtual_memory()
        return {"services": services, "runs": runs, "incidents": self.incidents(), "summary": {
            "total": len(services), "enabled": len(enabled), "healthy": sum(bool(item["last"] and item["last"]["status"] == "healthy") for item in enabled),
            "warning": sum(bool(item["last"] and item["last"]["status"] != "healthy") for item in enabled),
            "unchecked": sum(item["last"] is None for item in enabled), "p95_ms": durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None},
            "active_run": next((item["id"] for item in runs if item["state"] in ("queued", "running")), None),
            "host": {"hostname": socket.gethostname(), "memory_percent": memory.percent, "uptime_seconds": max(0, int(time.time() - psutil.boot_time()))},
            "lab": {"loaded": any(item["is_demo"] for item in services), "degraded": self.demo_degraded}}

    def triage_text(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 262144:
            raise RequestError("Paste a non-empty JSONL log of at most 256,000 characters.")
        try:
            with tempfile.TemporaryDirectory(prefix="console-triage-") as directory:
                source = Path(directory) / "input.jsonl"
                source.write_text(text, encoding="utf-8")
                result = triage([source], max_lines=10000, max_patterns=100)
        except (UnicodeError, ValueError):
            raise RequestError("The log input could not be processed as UTF-8 JSONL.") from None
        with self.db() as db:
            identity = uuid.uuid4().hex
            db.execute("INSERT INTO triages VALUES(?,?,?)", (identity, now(), json.dumps(result)))
            db.execute("DELETE FROM triages WHERE id NOT IN (SELECT id FROM triages ORDER BY created_at DESC LIMIT 20)")
        return result

    def latest_triage(self):
        with self.db() as db:
            row = db.execute("SELECT summary FROM triages ORDER BY created_at DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def evidence_path(self, name):
        import re
        base = (self.root / "reports" / "investigations").resolve()
        if not isinstance(name, str) or not re.fullmatch(r"run-[A-Za-z0-9_-]{1,120}", name):
            raise RequestError("Evidence not found.", 404)
        path = base / name
        if path.is_symlink() or path.resolve().parent != base or not path.is_dir():
            raise RequestError("Evidence not found.", 404)
        return path

    def evidence(self):
        base = self.root / "reports" / "investigations"
        results = []
        if not base.exists():
            return results
        for source in sorted(base.glob("run-*"), reverse=True)[:30]:
            try:
                path = self.evidence_path(source.name)
                metadata = path / "manifest.json"
                if metadata.is_symlink() or metadata.stat().st_size > 1024 * 1024:
                    continue
                manifest = json.loads(metadata.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
                if manifest.get("pack_type") != "incident-investigation":
                    continue
                counts = manifest.get("summary", {})
                results.append({"name": path.name, "created_at": manifest.get("created_at"), "status": manifest.get("status", "unknown"),
                                "events": counts.get("service_events", 0), "errors": counts.get("error_records", 0),
                                "artifacts": len(manifest.get("files", {})), "integrity": self.evidence_verifications.get(path.name, "not_checked")})
            except (OSError, ValueError, TypeError, AttributeError, RequestError):
                continue
        return sorted(results, key=lambda item: item["created_at"] or "", reverse=True)

    def verify_evidence(self, name):
        path = self.evidence_path(name)
        # The bounded existing auditor checks declared roles and file hashes.
        from audit_bundles import audit_bundle
        result = audit_bundle(path)
        self.evidence_verifications[name] = result["status"]
        return result


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(state, port=8765):
    server = ConsoleServer(("127.0.0.1", port), ConsoleHandler)
    server.state = state
    state.port = server.server_address[1]
    return server


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "SignalDesk/0.1"

    def log_message(self, *args):
        pass

    @property
    def state(self):
        return self.server.state

    def host_valid(self):
        allowed = {f"127.0.0.1:{self.state.port}", f"localhost:{self.state.port}"}
        return self.headers.get("Host") in allowed

    def response(self, code, value, content_type="application/json; charset=utf-8", sandbox=False):
        data = json.dumps(value).encode() if content_type.startswith("application/json") else value.encode("utf-8") if isinstance(value, str) else value
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox" if sandbox else policy)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def check_request(self, mutation=False):
        if not self.host_valid():
            raise RequestError("Unexpected host.", 403)
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            raise RequestError("Cross-origin requests are not supported.", 403)
        if mutation and not secrets.compare_digest(self.headers.get("X-Console-Token", ""), self.state.token):
            raise RequestError("Refresh the console before making changes.", 403)

    def body(self):
        if self.headers.get_content_type() != "application/json":
            raise RequestError("Send JSON content.", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise RequestError("Request is empty or too large.", 413)
            result = json.loads(self.rfile.read(length).decode("utf-8"), object_pairs_hook=unique_object)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError, RecursionError):
            raise RequestError("The request must contain a valid JSON object.") from None

    def handle_action(self, method):
        try:
            self.check_request(method != "GET")
            path = urlsplit(self.path).path
            if method == "GET":
                if path in STATIC:
                    filename, content_type = STATIC[path]
                    data = (self.state.root / "web_console" / filename).read_text(encoding="utf-8")
                    if path == "/":
                        data = data.replace("__CONSOLE_TOKEN__", self.state.token)
                    return self.response(200, data, content_type)
                if path == "/api/overview":
                    return self.response(200, self.state.overview())
                if path == "/api/evidence":
                    return self.response(200, {"items": self.state.evidence()})
                if path == "/api/triage/latest":
                    return self.response(200, {"summary": self.state.latest_triage()})
                if path == "/demo/ready":
                    return self.response(200, {"status": "ready"})
                if path == "/demo/worker":
                    return self.response(503 if self.state.demo_degraded else 200, {"status": "degraded" if self.state.demo_degraded else "ready"})
                if path.startswith("/api/evidence/") and path.endswith("/timeline"):
                    name = path.split("/")[3]
                    target = self.state.evidence_path(name) / "timeline.html"
                    if target.is_symlink() or target.stat().st_size > 8 * 1024 * 1024:
                        raise RequestError("Timeline is unavailable.", 404)
                    return self.response(200, target.read_text(encoding="utf-8"), "text/html; charset=utf-8", sandbox=True)
            if method == "DELETE" and path.startswith("/api/services/"):
                return self.response(200, self.state.delete_service(path.split("/")[-1]))
            payload = self.body() if method in ("POST", "PATCH") else {}
            if method == "PATCH" and path.startswith("/api/incidents/"):
                return self.response(200, self.state.update_incident(path.split("/")[-1], payload))
            if method == "POST" and path == "/api/services":
                return self.response(201, self.state.save_service(payload))
            if method == "PATCH" and path.startswith("/api/services/"):
                return self.response(200, self.state.save_service(payload, path.split("/")[-1]))
            if method == "POST" and path == "/api/checks":
                if set(payload) - {"service_ids"}:
                    raise RequestError("Unsupported check options.")
                return self.response(202, self.state.start_check(payload.get("service_ids")))
            if method == "POST" and path == "/api/demo":
                return self.response(202, self.state.demo(payload.get("action")))
            if method == "POST" and path == "/api/triage":
                return self.response(200, self.state.triage_text(payload.get("text")))
            if method == "POST" and path.startswith("/api/evidence/") and path.endswith("/verify"):
                return self.response(200, self.state.verify_evidence(path.split("/")[3]))
            raise RequestError("Not found.", 404)
        except RequestError as error:
            self.response(error.status, {"error": str(error)})
        except Exception:
            self.response(500, {"error": "The local console could not complete that request.", "request_id": uuid.uuid4().hex[:12]})

    def do_GET(self):
        self.handle_action("GET")

    def do_POST(self):
        self.handle_action("POST")

    def do_PATCH(self):
        self.handle_action("PATCH")

    def do_DELETE(self):
        self.handle_action("DELETE")

    def do_OPTIONS(self):
        self.response(403, {"error": "Cross-origin API access is disabled."})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the console in your default browser")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1–65535")
    state = ConsoleState(Path(__file__).parent)
    server = make_server(state, args.port)
    print(f"SignalDesk local console: http://127.0.0.1:{state.port}", flush=True)
    print("Press Ctrl+C to stop. Reports stay on this device.", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{state.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()


if __name__ == "__main__":
    main()
