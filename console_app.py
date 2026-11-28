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
        self.closing = False
        self.schedule_enabled = False
        self.schedule_due = None
        self.schedule_result = "Not started"
        self.schedule_stop = threading.Event()
        self.demo_degraded = True
        self.evidence_verifications = {}
        self.export_previews = {}
        with self.db() as db:
            db.executescript('''
CREATE TABLE IF NOT EXISTS services(id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,group_name TEXT NOT NULL,protocol TEXT NOT NULL,target TEXT NOT NULL,timeout REAL NOT NULL,expected_status INTEGER NOT NULL,enabled INTEGER NOT NULL,revision INTEGER NOT NULL,is_demo INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,state TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,report TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS observations(run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,service_id TEXT,revision INTEGER,payload TEXT,PRIMARY KEY(run_id,service_id));
CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,service_id TEXT NOT NULL,revision INTEGER NOT NULL,service_name TEXT NOT NULL,target TEXT NOT NULL,state TEXT NOT NULL,owner TEXT NOT NULL DEFAULT '',opened_at TEXT NOT NULL,last_seen TEXT NOT NULL,resolved_at TEXT,resolution TEXT,failures INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_incident ON incidents(service_id,revision) WHERE state IN ('open','acknowledged');
CREATE TABLE IF NOT EXISTS incident_events(id INTEGER PRIMARY KEY AUTOINCREMENT,incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,kind TEXT NOT NULL,created_at TEXT NOT NULL,detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS console_settings(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS maintenance(id TEXT PRIMARY KEY,service_id TEXT NOT NULL REFERENCES services(id) ON DELETE CASCADE,reason TEXT NOT NULL,started_at REAL NOT NULL,expires_at REAL NOT NULL,ended_at REAL);
CREATE TABLE IF NOT EXISTS objectives(service_id TEXT PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,target_percent REAL NOT NULL,window_hours INTEGER NOT NULL,min_samples INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS latency_objectives(service_id TEXT PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,enabled INTEGER NOT NULL,threshold_ms INTEGER NOT NULL,target_percent REAL NOT NULL);
CREATE TABLE IF NOT EXISTS triages(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,summary TEXT NOT NULL);
''')
            for table in ("services", "observations"):
                if "maintenance_version" not in {column["name"] for column in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN maintenance_version INTEGER NOT NULL DEFAULT 0")
            if "source" not in {column["name"] for column in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
            saved = db.execute("SELECT value FROM console_settings WHERE key='interval_seconds'").fetchone()
            self.schedule_interval = saved[0] if saved and 10 <= saved[0] <= 3600 else 60
            db.execute("UPDATE runs SET state='interrupted',finished_at=?,error='Console restarted before this run completed.' WHERE state IN ('queued','running')", (now(),))

        self.scheduler = threading.Thread(target=self._schedule_loop, name="console-scheduler", daemon=True)
        self.scheduler.start()

    def schedule_status(self):
        with self.lock:
            remaining = max(0, self.schedule_due - time.monotonic()) if self.schedule_due is not None else None
            return {"enabled": self.schedule_enabled, "interval_seconds": self.schedule_interval,
                    "next_check_at": datetime.fromtimestamp(time.time() + remaining, timezone.utc).isoformat() if remaining is not None else None,
                    "last_result": self.schedule_result}

    def configure_schedule(self, payload):
        if set(payload) != {"enabled", "interval_seconds"} or type(payload["enabled"]) is not bool or type(payload["interval_seconds"]) is not int:
            raise RequestError("Send enabled and an integer interval_seconds.")
        interval, enabled = payload["interval_seconds"], payload["enabled"]
        if not 10 <= interval <= 3600:
            raise RequestError("Choose an interval from 10 to 3,600 seconds.")
        with self.lock:
            if self.closing:
                raise RequestError("The console is stopping.", 409)
            if enabled and not any(service["enabled"] for service in self.services()):
                raise RequestError("Add or enable a service before starting scheduled checks.")
            with self.db() as db:
                db.execute("INSERT INTO console_settings(key,value) VALUES('interval_seconds',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (interval,))
            changed = interval != self.schedule_interval or enabled != self.schedule_enabled
            self.schedule_interval, self.schedule_enabled = interval, enabled
            if changed:
                self.schedule_due = time.monotonic() + interval if enabled else None
                self.schedule_result = "Waiting for next check" if enabled else "Stopped; any running check will finish"
            return self.schedule_status()

    def _schedule_tick(self):
        with self.lock:
            if self.closing or not self.schedule_enabled or self.schedule_due is None or time.monotonic() < self.schedule_due:
                return
            # Advance from now: missed intervals never become a backlog.
            self.schedule_due = time.monotonic() + self.schedule_interval
            try:
                self.start_check(source="scheduled")
                self.schedule_result = "Scheduled check queued"
            except RequestError as error:
                self.schedule_result = "Skipped: " + str(error)

    def _schedule_loop(self):
        while not self.schedule_stop.wait(.25):
            try:
                self._schedule_tick()
            except Exception:
                with self.lock:
                    self.schedule_result = "Scheduling error; the next interval will retry"

    @contextmanager
    def db(self):
        # HTTP handlers, scheduler and check workers share this database. Serialize
        # connection lifetimes so polling cannot compete with a result commit on
        # Windows. Reuse the RLock to preserve the ordering of nested state calls.
        with self.lock:
            connection = sqlite3.connect(self.db_path, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                with connection:
                    yield connection
            finally:
                connection.close()

    def close(self):
        with self.lock:
            self.closing = True
            self.schedule_enabled = False
            self.schedule_due = None
        self.schedule_stop.set()
        self.scheduler.join()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def services(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM services ORDER BY created_at,id").fetchall()
            results = []
            for row in rows:
                last = db.execute("SELECT o.payload,r.finished_at FROM observations o JOIN runs r ON r.id=o.run_id WHERE o.service_id=? AND o.revision=? AND o.maintenance_version=? AND r.state='completed' ORDER BY r.finished_at DESC,r.rowid DESC LIMIT 1", (row["id"], row["revision"], row["maintenance_version"])).fetchone()
                value = {"id": row["id"], "name": row["name"], "group": row["group_name"], "type": row["protocol"],
                         "target": row["target"], "timeout": row["timeout"], "expected_status": row["expected_status"],
                         "enabled": bool(row["enabled"]), "is_demo": bool(row["is_demo"]), "revision": row["revision"],
                         "last": json.loads(last["payload"]) if last else None, "checked_at": last["finished_at"] if last else None}
                window=db.execute("SELECT id,reason,expires_at FROM maintenance WHERE service_id=? AND ended_at IS NULL AND expires_at>? ORDER BY started_at DESC LIMIT 1", (row["id"],time.time())).fetchone()
                value["maintenance"] = dict(window) if window else None
                value["maintenance_version"] = row["maintenance_version"]
                results.append(value)
            return results

    def maintenance_windows(self):
        with self.db() as db:
            rows=db.execute("SELECT m.*,s.name AS service_name FROM maintenance m JOIN services s ON s.id=m.service_id ORDER BY started_at DESC LIMIT 250").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            item["state"]="ended" if item["ended_at"] is not None else "expired" if item["expires_at"] <= time.time() else "active"
            result.append(item)
        return result

    def start_maintenance(self, service_id, payload):
        if set(payload) != {"duration_minutes","reason"} or type(payload.get("duration_minutes")) is not int or not 1 <= payload["duration_minutes"] <= 1440:
            raise RequestError("Choose a maintenance duration from 1 to 1,440 whole minutes.")
        reason=payload["reason"]
        if not isinstance(reason,str) or not reason.strip() or len(reason)>300 or any(ord(c)<32 for c in reason):
            raise RequestError("Enter a reason of 1–300 characters without control characters.")
        with self.lock, self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM services WHERE id=?",(service_id,)).fetchone():
                raise RequestError("Service not found.",404)
            timestamp=time.time()
            if db.execute("SELECT 1 FROM maintenance WHERE service_id=? AND ended_at IS NULL AND expires_at>?",(service_id,timestamp)).fetchone():
                raise RequestError("This service already has an active maintenance window.",409)
            identity=uuid.uuid4().hex
            db.execute("INSERT INTO maintenance VALUES(?,?,?,?,?,NULL)",(identity,service_id,reason.strip(),timestamp,timestamp+payload["duration_minutes"]*60))
            # A new generation prevents old or in-flight observations from claiming current health.
            db.execute("UPDATE services SET maintenance_version=maintenance_version+1 WHERE id=?",(service_id,))
            db.execute("DELETE FROM maintenance WHERE (ended_at IS NOT NULL OR expires_at<=?) AND id NOT IN (SELECT id FROM maintenance WHERE ended_at IS NOT NULL OR expires_at<=? ORDER BY started_at DESC LIMIT 200)",(timestamp,timestamp))
        return {"id":identity}

    def end_maintenance(self, identity):
        with self.lock, self.db() as db:
            if db.execute("UPDATE maintenance SET ended_at=? WHERE id=? AND ended_at IS NULL AND expires_at>?",(time.time(),identity,time.time())).rowcount != 1:
                raise RequestError("The maintenance window has already ended or was not found.",404)
        return {"ended":True}

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
                    db.execute("INSERT INTO services(id,name,group_name,protocol,target,timeout,expected_status,enabled,revision,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (identity, fields["name"], fields["group"], fields["type"], fields["target"], fields["timeout"], fields["expected_status"], int(fields["enabled"]), 1, 0, now()))
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
        current = db.execute("SELECT revision,enabled,maintenance_version FROM services WHERE id=?", (source["id"],)).fetchone()
        if not current or current["revision"] != source["revision"] or not current["enabled"] or current["maintenance_version"] != source["maintenance_version"]:
            return
        if db.execute("SELECT 1 FROM maintenance WHERE service_id=? AND ended_at IS NULL AND expires_at>?",(source["id"],time.time())).fetchone():
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

    def export_incident(self, identity, payload):
        if set(payload) != {"format","include_notes"} or payload.get("format") not in ("json","markdown") or type(payload.get("include_notes")) is not bool:
            raise RequestError("Choose JSON or Markdown and whether to include investigation notes.")
        with self.db() as db:
            db.execute("BEGIN")  # One consistent snapshot across incident, activity and retained evidence.
            row=db.execute("SELECT * FROM incidents WHERE id=?",(identity,)).fetchone()
            if not row:
                raise RequestError("Incident not found; it may have expired from history.",404)
            incident=dict(row)
            events=[dict(item) for item in db.execute("SELECT kind,created_at,detail FROM incident_events WHERE incident_id=? ORDER BY id LIMIT 200",(identity,)) if payload["include_notes"] or item["kind"] != "note"]
            records=db.execute("SELECT r.id,r.finished_at,r.source,o.payload FROM observations o JOIN runs r ON r.id=o.run_id WHERE o.service_id=? AND o.revision=? AND r.state='completed' AND r.finished_at>=? AND r.started_at<=? ORDER BY r.finished_at DESC,r.rowid DESC LIMIT 101",(incident["service_id"],incident["revision"],incident["opened_at"],incident["resolved_at"] or now())).fetchall()
        evidence=[]
        for item in reversed(records[:100]):
            result=json.loads(item["payload"])
            detail=result.get("detail",{})
            measured=detail.get("duration_ms")
            evidence.append({"run_id":item["id"],"finished_at":item["finished_at"],"source":item["source"],"status":result.get("status"),
                             "probe_status":detail.get("status"),"http_status":detail.get("http_status"),
                             "duration_ms":measured if type(measured) in (int,float) and math.isfinite(measured) and measured>=0 else None})
        report={"schema_version":1,"report_type":"incident-handoff","generated_at":now(),
                "incident":{key:incident[key] for key in ("id","service_name","target","revision","state","owner","opened_at","last_seen","resolved_at","resolution","failures","version")},
                "activity":events,"evidence":evidence,
                "scope":{"notes_included":payload["include_notes"],"evidence_limit":100,"evidence_truncated":len(records)>100,
                         "retained_history_only":True,"notice":"Evidence contains retained observations for this service revision during the incident window. Older runs may have expired. Observations do not establish a root cause. Owner is a local label, not an authenticated identity."}}
        if payload["format"] == "json":
            content=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
            extension,media_type="json","application/json"
        else:
            # Indented blocks keep user-authored notes/labels as literal text, including HTML/Markdown.
            def literal(value):
                return "\n".join("    "+line for line in str(value if value is not None else "Not recorded").splitlines()) or "    Not recorded"
            lines=["# Incident handoff", "", "Generated: "+report["generated_at"], ""]
            for label,key in (("Incident ID","id"),("Service","service_name"),("Target","target"),("State","state"),("Owner","owner"),("Opened","opened_at"),("Last warning","last_seen"),("Resolved","resolved_at"),("Resolution","resolution"),("Observed failed checks","failures")):
                lines.extend(["## "+label,"",literal(incident[key]),""])
            lines.extend(["## Scope","",report["scope"]["notice"],"", "Investigation notes included: "+str(payload["include_notes"]), "", "## Activity", ""])
            for event in events:
                lines.extend([event["created_at"]+" — "+event["kind"],"",literal(event["detail"]),""])
            lines.extend(["## Retained check evidence","",f"Included {len(evidence)} observations; limit 100. Truncated: {len(records)>100}.",""])
            for item in evidence:
                lines.extend([literal(json.dumps(item,ensure_ascii=False)),""])
            content="\n".join(lines)
            extension,media_type="md","text/markdown"
        result={"filename":f"incident-{identity}.{extension}","media_type":media_type,"content":content,
                "summary":{"state":incident["state"],"activity_entries":len(events),"evidence_entries":len(evidence),"notes_included":payload["include_notes"]}}
        return self._cache_export(result)

    def _cache_export(self, result, kind="incident"):
        with self.lock:
            preview_id=uuid.uuid4().hex
            self.export_previews={key:value for key,value in self.export_previews.items() if value["expires"]>time.monotonic()}
            while len(self.export_previews)>=8:
                self.export_previews.pop(next(iter(self.export_previews)))
            self.export_previews[preview_id]={"expires":time.monotonic()+900,"report":result.copy(),"saved":None,"kind":kind}
            result["preview_id"]=preview_id
        return result

    def save_incident_export(self, preview_id, payload):
        import hashlib
        import os
        if payload:
            raise RequestError("Saving uses the previewed report; no file paths or content are accepted.")
        with self.lock:
            preview=self.export_previews.get(preview_id)
            if not preview or preview["expires"]<=time.monotonic():
                raise RequestError("This preview expired. Preview the report again before saving.",410)
            if preview["saved"]:
                return preview["saved"]
            folder="reliability-exports" if preview.get("kind")=="reliability" else "incident-exports"
            directory=self.root/"reports"/folder
            if (self.root/"reports").is_symlink() or directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise RequestError("The local report folder must stay inside this repository.",409)
            directory.mkdir(parents=True,exist_ok=True)
            # A unique name per preview preserves earlier reports. Repeated saves are idempotent.
            name=Path(preview["report"]["filename"])
            target=directory/(name.stem+"-"+preview_id+name.suffix)
            if target.exists() or target.is_symlink():
                raise RequestError("The report path is already occupied. Create a fresh preview.",409)
            content=preview["report"]["content"]
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(mode="wb",dir=directory,prefix=".incident-",delete=False) as stream:
                    temporary=Path(stream.name)
                    stream.write(content.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            data=target.read_bytes()
            result={"path":target.relative_to(self.root).as_posix(),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            preview["saved"]=result
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

    def save_objective(self, service_id, payload):
        if set(payload) != {"target_percent","window_hours","min_samples"}:
            raise RequestError("Provide target_percent, window_hours and min_samples.")
        target,hours,minimum=payload["target_percent"],payload["window_hours"],payload["min_samples"]
        if type(target) not in (int,float) or not math.isfinite(target) or not 50 <= target <= 100:
            raise RequestError("Target must be a finite percentage from 50 to 100.")
        if type(hours) is not int or not 1 <= hours <= 168:
            raise RequestError("Choose a window of 1–168 whole hours.")
        if type(minimum) is not int or not 5 <= minimum <= 200:
            raise RequestError("Choose a minimum of 5–200 observations.")
        with self.db() as db:
            if not db.execute("SELECT 1 FROM services WHERE id=?",(service_id,)).fetchone():
                raise RequestError("Service not found.",404)
            db.execute("INSERT INTO objectives VALUES(?,?,?,?) ON CONFLICT(service_id) DO UPDATE SET target_percent=excluded.target_percent,window_hours=excluded.window_hours,min_samples=excluded.min_samples",(service_id,target,hours,minimum))
        return {"saved":True}

    def save_latency_objective(self, service_id, payload):
        if set(payload) != {"enabled","threshold_ms","target_percent"} or type(payload.get("enabled")) is not bool:
            raise RequestError("Provide enabled, threshold_ms and target_percent.")
        threshold,target=payload["threshold_ms"],payload["target_percent"]
        if type(threshold) is not int or not 1 <= threshold <= 60000:
            raise RequestError("Choose a threshold of 1–60,000 whole milliseconds.")
        if type(target) not in (int,float) or not math.isfinite(target) or not 50 <= target <= 100:
            raise RequestError("Latency target must be a finite percentage from 50 to 100.")
        with self.db() as db:
            if not db.execute("SELECT 1 FROM services WHERE id=?",(service_id,)).fetchone():
                raise RequestError("Service not found.",404)
            db.execute("INSERT INTO latency_objectives VALUES(?,?,?,?) ON CONFLICT(service_id) DO UPDATE SET enabled=excluded.enabled,threshold_ms=excluded.threshold_ms,target_percent=excluded.target_percent",(service_id,int(payload["enabled"]),threshold,target))
        return {"saved":True}

    def reliability(self):
        from datetime import timedelta
        as_of=datetime.now(timezone.utc)
        result=[]
        # One consistent snapshot for settings, configuration and retained observations.
        with self.db() as db:
            db.execute("BEGIN")
            services=self.services()
            for service in services:
                saved=db.execute("SELECT * FROM objectives WHERE service_id=?",(service["id"],)).fetchone()
                target=saved["target_percent"] if saved else 99
                hours=saved["window_hours"] if saved else 24
                minimum=saved["min_samples"] if saved else 10
                cutoff=(as_of-timedelta(hours=hours)).isoformat()
                rows=db.execute("SELECT r.finished_at,o.payload FROM observations o JOIN runs r ON r.id=o.run_id WHERE o.service_id=? AND o.revision=? AND o.maintenance_version=? AND r.state='completed' AND r.finished_at>=? AND r.finished_at<=? ORDER BY r.finished_at DESC,r.rowid DESC LIMIT 200",(service["id"],service["revision"],service["maintenance_version"],cutoff,as_of.isoformat())).fetchall()
                states=[json.loads(row["payload"]).get("status") for row in rows]
                healthy=states.count("healthy")
                total=len(states)
                failures=total-healthy
                achieved=healthy/total*100 if total else None
                allowance=total*(1-target/100)
                status="insufficient_data" if total<minimum else "met" if achieved>=target else "below_target"
                latency_saved=db.execute("SELECT * FROM latency_objectives WHERE service_id=?",(service["id"],)).fetchone()
                latency_enabled=bool(latency_saved and latency_saved["enabled"])
                threshold=latency_saved["threshold_ms"] if latency_saved else 500
                latency_target=latency_saved["target_percent"] if latency_saved else 95
                healthy_timings=[]
                for row in rows:
                    observation=json.loads(row["payload"])
                    timing=observation.get("detail",{}).get("duration_ms")
                    if observation.get("status")=="healthy" and type(timing) in (int,float) and math.isfinite(timing) and timing>=0:
                        healthy_timings.append(timing)
                within=sum(value<=threshold for value in healthy_timings)
                timed=len(healthy_timings)
                missing=healthy-timed
                latency_achieved=within/timed*100 if timed else None
                latency_status="not_enabled" if not latency_enabled else "insufficient_data" if timed<minimum or missing else "met" if latency_achieved>=latency_target else "below_target"
                ordered=sorted(healthy_timings)
                latency={"enabled":latency_enabled,"threshold_ms":threshold,"target_percent":latency_target,"status":latency_status,
                    "healthy_checks":healthy,"timed_healthy_checks":timed,"missing_healthy_timings":missing,"within_threshold":within,
                    "achieved_percent":round(latency_achieved,4) if latency_achieved is not None else None,
                    "p95_healthy_probe_ms":ordered[math.ceil(timed*.95)-1] if timed else None}
                result.append({"id":service["id"],"name":service["name"],"group":service["group"],"enabled":service["enabled"],"maintenance":bool(service["maintenance"]),
                               "latency":latency,"configured":saved is not None,"target_percent":target,"window_hours":hours,"min_samples":minimum,"samples":total,"healthy":healthy,"failures":failures,
                               "achieved_percent":round(achieved,4) if achieved is not None else None,"failure_allowance":round(allowance,6),
                               "remaining_allowance":round(allowance-failures,6),"status":status,"last_checked_at":rows[0]["finished_at"] if rows else None})
        return {"as_of":as_of.isoformat(),"services":result,"scope":"Sampled completed checks from retained history for the current configuration and maintenance cycle. This is not continuous uptime or request-level availability."}

    def reliability_review(self):
        # Keep objective assessment and incident ownership within one database view.
        with self.db() as db:
            db.execute("BEGIN")
            report=self.reliability()
            incidents=[dict(row) for row in db.execute("SELECT id,service_id,state,owner FROM incidents WHERE state IN ('open','acknowledged') ORDER BY opened_at DESC,id")]
        items=[]
        counts={key:0 for key in ("action_required","evidence_needed","deferred","within_target")}
        for service in report["services"]:
            reasons=[]
            if not service["configured"]:
                reasons.append("availability_objective_not_saved")
            elif service["status"]=="below_target":
                reasons.append("availability_below_target")
            if service["status"]=="insufficient_data":
                reasons.append("availability_needs_samples")
            latency=service["latency"]
            if latency["enabled"]:
                if latency["status"]=="below_target":
                    reasons.append("latency_below_target")
                elif latency["status"]=="insufficient_data":
                    reasons.append("latency_missing_timings" if latency["missing_healthy_timings"] else "latency_needs_samples")
            breached=any(reason.endswith("below_target") for reason in reasons)
            deferred="paused" if not service["enabled"] else "maintenance" if service["maintenance"] else None
            category="deferred" if deferred else "action_required" if breached else "evidence_needed" if reasons else "within_target"
            counts[category]+=1
            items.append({"id":service["id"],"name":service["name"],"group":service["group"],"category":category,"reasons":reasons,
                "deferred_reason":deferred,"incidents":[item for item in incidents if item["service_id"]==service["id"]],
                "availability_status":service["status"],"latency_status":latency["status"],"samples":service["samples"]})
        rank={key:index for index,key in enumerate(counts)}
        return {"as_of":report["as_of"],"reliability":report,"counts":counts,"items":sorted(items,key=lambda item:(rank[item["category"]],item["name"],item["id"])),
            "scope":"Read-only review of saved objectives and retained sampled checks. Deferred items can still have unresolved incidents; meeting objectives does not close incidents."}

    # SQLite insertion order breaks timestamp ties; UUIDs are not chronological.
    def export_reliability_review(self, payload):
        categories={"all","action_required","evidence_needed","deferred","within_target"}
        if set(payload)!={"format","category"} or payload.get("format") not in ("json","markdown") or not isinstance(payload.get("category"),str) or payload["category"] not in categories:
            raise RequestError("Choose JSON or Markdown and a supported review category.")
        review=self.reliability_review()
        selected=[item for item in review["items"] if payload["category"]=="all" or item["category"]==payload["category"]]
        objectives={service["id"]:service for service in review["reliability"]["services"]}
        counts={key:sum(item["category"]==key for item in selected) for key in review["counts"]}
        services=[{**item,"objective":objectives[item["id"]]} for item in selected]
        report={"schema_version":1,"report_type":"reliability-review","as_of":review["as_of"],"category":payload["category"],
            "counts":counts,"services":services,"scope":review["scope"],
            "limitations":["Sampled checks, not continuous uptime or request-level availability.","Current configuration and maintenance cycle only; retained history is bounded to 200 runs.","Latency uses successful probes and complete valid timing coverage.","Incident ownership labels are local text; investigation notes and endpoint addresses are excluded."]}
        if payload["format"]=="json":
            content=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
            extension,media_type="json","application/json"
        else:
            lines=["# Reliability review","","Evaluated: "+report["as_of"],"","Category: "+payload["category"],"",f"Included services: {len(services)}","",review["scope"],"","## Limits",""]
            lines.extend("- "+item for item in report["limitations"])
            lines.extend(["","## Category counts","",*('    '+key+': '+str(value) for key,value in counts.items()),""])
            for service in services:
                # Literal blocks prevent user labels from becoming Markdown/HTML structure.
                lines.extend(["## Service","",*("    "+line for line in json.dumps(service,indent=2,ensure_ascii=False).splitlines()),""])
            content="\n".join(lines)
            extension,media_type="md","text/markdown"
        return self._cache_export({"filename":"reliability-review."+extension,"media_type":media_type,"content":content,
            "summary":{"services":len(services),"category":payload["category"],"as_of":report["as_of"]}},kind="reliability")

    def reliability_history(self, service_id):
        from datetime import timedelta
        with self.db() as db:
            db.execute("BEGIN")
            service=next((s for s in self.services() if s["id"]==service_id),None)
            if service is None:
                raise RequestError("Service not found.",404)
            report=self.reliability()
            objective=next(s for s in report["services"] if s["id"]==service_id)
            end=datetime.fromisoformat(report["as_of"])
            start=end-timedelta(hours=objective["window_hours"])
            rows=db.execute("SELECT r.id,r.source,r.finished_at,o.payload FROM observations o JOIN runs r ON r.id=o.run_id WHERE o.service_id=? AND o.revision=? AND o.maintenance_version=? AND r.state='completed' AND r.finished_at>=? AND r.finished_at<=? ORDER BY r.finished_at DESC,r.rowid DESC LIMIT 200",(service_id,service["revision"],service["maintenance_version"],start.isoformat(),end.isoformat())).fetchall()
        observations=[]
        for row in rows:
            value=json.loads(row["payload"])
            detail=value.get("detail",{})
            duration=detail.get("duration_ms")
            observations.append({"run_id":row["id"],"source":row["source"],"finished_at":row["finished_at"],"status":value.get("status"),
                "probe_status":detail.get("status"),"http_status":detail.get("http_status"),
                "duration_ms":duration if type(duration) in (int,float) and math.isfinite(duration) and duration>=0 else None})
        states=[item["status"] for item in observations]
        streak=0
        for state in states:
            if state=="healthy":
                break
            streak+=1
        measured=sorted(item["duration_ms"] for item in observations if item["duration_ms"] is not None)
        trend={"status":"insufficient_data","samples_per_group":0,"previous_percent":None,"recent_percent":None,"difference_pp":None}
        if len(states)>=max(6,objective["min_samples"]):
            half=len(states)//2
            recent=states[:half].count("healthy")/half*100
            previous=states[half:half*2].count("healthy")/half*100
            delta=recent-previous
            trend={"status":"improving" if delta>0 else "declining" if delta<0 else "unchanged","samples_per_group":half,
                "previous_percent":round(previous,4),"recent_percent":round(recent,4),"difference_pp":round(delta,4)}
        width=objective["window_hours"]*3600/12
        buckets=[{"start":(start+timedelta(seconds=width*i)).isoformat(),"end":(start+timedelta(seconds=width*(i+1))).isoformat(),"samples":0,"healthy":0,"healthy_percent":None} for i in range(12)]
        for item in observations:
            index=min(11,max(0,int((datetime.fromisoformat(item["finished_at"])-start).total_seconds()/width)))
            buckets[index]["samples"]+=1
            buckets[index]["healthy"]+=int(item["status"]=="healthy")
        for bucket in buckets:
            if bucket["samples"]:
                bucket["healthy_percent"]=round(bucket["healthy"]/bucket["samples"]*100,4)
        return {"as_of":report["as_of"],"service":objective,"observations":observations,"buckets":buckets,"trend":trend,
            "consecutive_warnings":streak,"timed_samples":len(measured),"p95_probe_ms":measured[math.ceil(len(measured)*.95)-1] if measured else None,
            "scope":report["scope"]}

    def runs(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY started_at DESC,rowid DESC LIMIT 30").fetchall()
        return [{"id": row["id"], "state": row["state"], "started_at": row["started_at"], "finished_at": row["finished_at"],
                 "report": json.loads(row["report"]) if row["report"] else None, "error": row["error"], "source": row["source"]} for row in rows]

    def compare_runs(self, payload):
        from incident_compare import compare_reports, identity, validate_report
        if set(payload) != {"baseline_id","current_id"} or any(not isinstance(payload[k],str) or not payload[k] or len(payload[k])>64 for k in payload):
            raise RequestError("Choose two saved runs to compare.")
        if payload["baseline_id"] == payload["current_id"]:
            raise RequestError("Choose two different runs.")
        with self.db() as db:
            records=[]
            observations=[]
            for key in ("baseline_id","current_id"):
                row=db.execute("SELECT * FROM runs WHERE id=?",(payload[key],)).fetchone()
                if not row:
                    raise RequestError("A selected run was not found; it may have expired from history.",404)
                if row["state"] != "completed" or not row["report"]:
                    raise RequestError("Only completed check runs can be compared.",409)
                try:
                    report=validate_report(json.loads(row["report"]))
                    items={item["service_id"]:dict(item) for item in db.execute("SELECT * FROM observations WHERE run_id=?",(row["id"],))}
                    if len(items) != len(report["services"]):
                        raise ValueError
                    for item in items.values():
                        item["result"]=json.loads(item["payload"])
                        validate_report({"schema_version":1,"services":[item["result"]]})
                except (ValueError,TypeError,KeyError):
                    raise RequestError("This run lacks complete comparison metadata.",409) from None
                records.append({"id":row["id"],"started_at":row["started_at"],"source":row["source"]})
                observations.append(items)
        if records[0]["started_at"] >= records[1]["started_at"]:
            raise RequestError("The baseline must be older than the current run.")
        before,after=observations
        counts={key:0 for key in ("new_failure","recovered","ongoing_failure","unchanged_healthy","added_to_run","absent_from_run","configuration_changed","maintenance_boundary")}
        rows=[]
        for service_id in before.keys() | after.keys():
            old,new=before.get(service_id),after.get(service_id)
            old_result=old["result"] if old else None
            new_result=new["result"] if new else None
            if old is None:
                classification="added_to_run"
            elif new is None:
                classification="absent_from_run"
            elif old["revision"] != new["revision"] or identity(old_result) != identity(new_result):
                classification="configuration_changed"
            elif old["maintenance_version"] != new["maintenance_version"]:
                classification="maintenance_boundary"
            else:
                comparison=compare_reports({"schema_version":1,"services":[old_result]}, {"schema_version":1,"services":[new_result]})
                classification=next({"new_failures":"new_failure","recovered":"recovered","ongoing_failures":"ongoing_failure","unchanged_healthy":"unchanged_healthy","reconfigured":"configuration_changed"}[key] for key,value in comparison["counts"].items() if value)
            def measured(result):
                value=result["detail"].get("duration_ms") if result else None
                return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
            old_ms,new_ms=measured(old_result),measured(new_result)
            counts[classification]+=1
            rows.append({"service_id":service_id,"name":(new_result or old_result)["name"],"classification":classification,
                         "previous_status":old_result["status"] if old else None,"current_status":new_result["status"] if new else None,
                         "previous_duration_ms":old_ms,"current_duration_ms":new_ms,
                         "duration_delta_ms":round(new_ms-old_ms,2) if old_ms is not None and new_ms is not None and classification in ("new_failure","recovered","ongoing_failure","unchanged_healthy") else None})
        return {"baseline":records[0],"current":records[1],"counts":counts,"services":sorted(rows,key=lambda item:(item["name"],item["service_id"]))}

    def start_check(self, ids=None, source="manual"):
        if ids is not None and (not isinstance(ids, list) or not ids or len(ids) > 50 or any(not isinstance(value, str) for value in ids)):
            raise RequestError("Select one or more service IDs.")
        with self.lock:
            if self.closing:
                raise RequestError("The console is stopping.", 409)
            snapshots = [item for item in self.services() if item["enabled"] and not item["maintenance"] and (ids is None or item["id"] in ids)]
            if not snapshots:
                raise RequestError("Add or enable a service outside maintenance first.")
            with self.db() as db:
                if db.execute("SELECT COUNT(*) FROM runs WHERE state IN ('queued','running')").fetchone()[0]:
                    raise RequestError("A check is already running. Please wait for it to finish.", 409)
                identity = uuid.uuid4().hex
                db.execute("INSERT INTO runs(id,state,started_at,source) VALUES(?,?,?,?)", (identity, "queued", now(), source))
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
                    db.execute("INSERT INTO observations(run_id,service_id,revision,payload,maintenance_version) VALUES(?,?,?,?,?)", (identity, source["id"], source["revision"], json.dumps(result), source["maintenance_version"]))
                db.execute("UPDATE runs SET state='completed',finished_at=?,report=? WHERE id=?", (now(), json.dumps(report), identity))
                db.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY started_at DESC,rowid DESC LIMIT 200)")
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
                        db.execute("INSERT INTO services(id,name,group_name,protocol,target,timeout,expected_status,enabled,revision,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, name, "local-lab", protocol, target, 3, 200, 1, 1, 1, now()))
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
        monitoring = [item for item in enabled if not item["maintenance"]]
        durations = sorted(item["last"]["detail"].get("duration_ms", 0) for item in monitoring if item["last"])
        memory = psutil.virtual_memory()
        return {"services": services, "runs": runs, "incidents": self.incidents(), "schedule": self.schedule_status(), "maintenance_windows": self.maintenance_windows(), "summary": {
            "total": len(services), "enabled": len(enabled), "monitoring":len(monitoring), "maintenance":len(enabled)-len(monitoring), "healthy": sum(bool(item["last"] and item["last"]["status"] == "healthy") for item in monitoring),
            "warning": sum(bool(item["last"] and item["last"]["status"] != "healthy") for item in monitoring),
            "unchecked": sum(item["last"] is None for item in monitoring), "p95_ms": durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None},
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
                if path == "/api/reliability/review":
                    return self.response(200,self.state.reliability_review())
                if path.startswith("/api/reliability/"):
                    return self.response(200,self.state.reliability_history(path.split("/")[-1]))
                if path == "/api/reliability":
                    return self.response(200,self.state.reliability())
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
            if method == "POST" and path.startswith("/api/services/") and path.endswith("/maintenance"):
                return self.response(201, self.state.start_maintenance(path.split("/")[3], payload))
            if method == "POST" and path.startswith("/api/maintenance/") and path.endswith("/end"):
                if payload:
                    raise RequestError("End maintenance takes no options.")
                return self.response(200,self.state.end_maintenance(path.split("/")[3]))
            if method == "POST" and path == "/api/services":
                return self.response(201, self.state.save_service(payload))
            if method == "PATCH" and path.startswith("/api/services/") and path.endswith("/objective"):
                return self.response(200,self.state.save_objective(path.split("/")[3],payload))
            if method == "PATCH" and path.startswith("/api/services/") and path.endswith("/latency-objective"):
                return self.response(200,self.state.save_latency_objective(path.split("/")[3],payload))
            if method == "PATCH" and path.startswith("/api/services/"):
                return self.response(200, self.state.save_service(payload, path.split("/")[-1]))
            if method == "PATCH" and path == "/api/schedule":
                return self.response(200, self.state.configure_schedule(payload))
            if method == "POST" and path.startswith("/api/exports/") and path.endswith("/save"):
                return self.response(200,self.state.save_incident_export(path.split("/")[3],payload))
            if method == "POST" and path.startswith("/api/incidents/") and path.endswith("/export"):
                return self.response(200,self.state.export_incident(path.split("/")[3],payload))
            if method == "POST" and path == "/api/reliability/export":
                return self.response(200,self.state.export_reliability_review(payload))
            if method == "POST" and path == "/api/runs/compare":
                return self.response(200,self.state.compare_runs(payload))
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
