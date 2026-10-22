"""SQLite storage: trend samples, alarms, batches, the audit/event log, users and sessions."""
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (ts REAL NOT NULL, key TEXT NOT NULL, value REAL);
CREATE INDEX IF NOT EXISTS samples_key_ts ON samples (key, ts);
CREATE TABLE IF NOT EXISTS alarms (
  id INTEGER PRIMARY KEY, key TEXT NOT NULL, text TEXT NOT NULL,
  raised REAL NOT NULL, cleared REAL, acked REAL, acked_by TEXT);
CREATE INDEX IF NOT EXISTS alarms_raised ON alarms (raised);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY, started REAL NOT NULL, ended REAL, quantity REAL,
  status TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS batches_started ON batches (started);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, user TEXT, action TEXT NOT NULL, detail TEXT, ok INTEGER);
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(SCHEMA)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).lastrowid

    # --- samples ---
    def add_samples(self, ts: float, values: dict):
        rows = [(ts, k, float(v)) for k, v in values.items() if v is not None]
        with self.lock:
            self.db.executemany("INSERT INTO samples (ts, key, value) VALUES (?, ?, ?)", rows)

    def series(self, key: str, t0: float, t1: float, points: int = 600):
        """Bucketed min/avg/max so a long range stays a fixed number of points."""
        width = max((t1 - t0) / points, 1e-6)
        return self.q(
            "SELECT CAST((ts - ?) / ? AS INTEGER) AS b, MIN(ts) AS ts, AVG(value) AS avg, "
            "MIN(value) AS min, MAX(value) AS max FROM samples WHERE key = ? AND ts BETWEEN ? AND ? "
            "GROUP BY b ORDER BY b", (t0, width, key, t0, t1))

    def purge(self, keep_days: float):
        cut = time.time() - keep_days * 86400
        with self.lock:
            self.db.execute("DELETE FROM samples WHERE ts < ?", (cut,))
            self.db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))

    # --- events (audit log) ---
    def event(self, action: str, detail: str = "", user: str | None = None, ok: bool = True):
        self.x("INSERT INTO events (ts, user, action, detail, ok) VALUES (?, ?, ?, ?, ?)",
               (time.time(), user, action, detail, int(ok)))

    # --- batches ---
    def batch_open(self, started: float, quantity, detail: dict) -> int:
        return self.x("INSERT INTO batches (started, quantity, status, detail) VALUES (?, ?, 'running', ?)",
                      (started, quantity, json.dumps(detail)))

    def batch_update(self, bid: int, detail: dict, status: str | None = None, ended: float | None = None):
        if status:
            self.x("UPDATE batches SET detail = ?, status = ?, ended = ? WHERE id = ?",
                   (json.dumps(detail), status, ended, bid))
        else:
            self.x("UPDATE batches SET detail = ? WHERE id = ?", (json.dumps(detail), bid))

    def batches(self, t0=0.0, t1=None, limit=200):
        rows = self.q("SELECT * FROM batches WHERE started BETWEEN ? AND ? ORDER BY started DESC LIMIT ?",
                      (t0, t1 or time.time() + 1, limit))
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows
