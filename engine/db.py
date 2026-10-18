"""SQLite case store and audit log. Holds scores, tiers, reason codes, decisions and
passkey public keys. Never raw audio (RED evidence clips are separate encrypted files)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from engine.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, public_key BLOB NOT NULL,
  sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT, device_label TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, channel TEXT NOT NULL, call_id TEXT,
  action TEXT NOT NULL, details TEXT NOT NULL, tier TEXT, policy TEXT NOT NULL,
  status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  cooloff_until REAL
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, kind TEXT NOT NULL, target_customer TEXT NOT NULL,
  challenge TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
  created_at REAL NOT NULL, decided_at REAL, credential_id TEXT
);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, call_id TEXT, request_id TEXT, customer_id TEXT, channel TEXT NOT NULL,
  opened_at REAL NOT NULL, status TEXT NOT NULL, tier TEXT, reasons TEXT, scores TEXT,
  model_version TEXT, timeline TEXT NOT NULL, clip_path TEXT, clip_expires REAL, outcome TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
  event TEXT NOT NULL, ref TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, case_id TEXT, created_at REAL NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_landmarks (
  hash INTEGER NOT NULL, case_id TEXT NOT NULL, t INTEGER NOT NULL
);
DROP TABLE IF EXISTS replay_hashes;
CREATE INDEX IF NOT EXISTS ix_requests_customer ON requests(customer_id, channel);
CREATE INDEX IF NOT EXISTS ix_approvals_target ON approvals(target_customer, status);
CREATE INDEX IF NOT EXISTS ix_cases_call ON cases(call_id, status);
CREATE INDEX IF NOT EXISTS ix_cases_request ON cases(request_id, status);
CREATE INDEX IF NOT EXISTS ix_audit_ref ON audit(ref);
"""

_JSON_COLS = {"details", "policy", "reasons", "scores", "timeline", "detail", "payload", "summary", "transports"}


class DB:
    def __init__(self, path):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def _row(self, r: sqlite3.Row | None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        for k in _JSON_COLS & d.keys():
            if isinstance(d[k], str):
                with contextlib.suppress(json.JSONDecodeError):
                    d[k] = json.loads(d[k])
        return d

    def _enc(self, data: dict) -> dict:
        return {k: (json.dumps(v) if k in _JSON_COLS and not isinstance(v, str | bytes | None) else v) for k, v in data.items()}

    def insert(self, table: str, data: dict) -> None:
        data = self._enc(data)
        cols = ",".join(data)
        qs = ",".join("?" * len(data))
        with self._lock:
            self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(data.values()))

    def update(self, table: str, id_: str, data: dict) -> None:
        data = self._enc(data)
        sets = ",".join(f"{k}=?" for k in data)
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*data.values(), id_])

    def get(self, table: str, id_: str) -> dict | None:
        with self._lock:
            return self._row(self._conn.execute(f"SELECT * FROM {table} WHERE id=?", [id_]).fetchone())

    def query(self, sql: str, args: list[Any] | tuple = ()) -> list[dict]:
        with self._lock:
            return [self._row(r) for r in self._conn.execute(sql, args).fetchall()]

    def execute(self, sql: str, args: list[Any] | tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, args)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)

    def audit(self, actor: str, event: str, ref: str | None = None, **detail) -> None:
        self.insert("audit", {"ts": time.time(), "actor": actor, "event": event, "ref": ref, "detail": detail or None})

    def wipe_world(self) -> None:
        """Demo reset: clears requests, cases, reports. Keeps enrolled passkeys."""
        with self._lock:
            for t in ("requests", "approvals", "cases", "reports", "audit", "replay_landmarks"):
                self._conn.execute(f"DELETE FROM {t}")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


db = DB(settings.runtime_dir / "countersign.db")
