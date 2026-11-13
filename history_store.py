"""Transactional local report history with a maximum retained record count."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def save_report(database, report, max_reports=1000):
    if max_reports < 1:
        raise ValueError("max_reports must be positive")
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, allow_nan=False)
    with closing(sqlite3.connect(database, timeout=5)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS reports ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
                "hostname TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO reports(timestamp, hostname, status, payload) VALUES (?, ?, ?, ?)",
                (report["timestamp"], report["hostname"], report["status"], payload),
            )
            connection.execute(
                "DELETE FROM reports WHERE id NOT IN "
                "(SELECT id FROM reports ORDER BY id DESC LIMIT ?)", (max_reports,),
            )


def recent_reports(database, limit=20):
    """Read an existing database without accidentally creating an empty one."""
    if limit < 1:
        raise ValueError("limit must be positive")
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        rows = connection.execute(
            "SELECT payload FROM reports ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]
