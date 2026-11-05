"""SQLite-backed investigation history. Standard library only.

Every investigation gets a session row; every user-visible timeline entry
becomes an event row with a per-session sequence number and a UTC
timestamp. Connections are short-lived and each write commits atomically,
so a crash can lose at most the in-flight row. Sessions left live by an
older process without a checkpoint are swept to read-only archived status
on startup: history survives restarts, but a dead unrestorable session is
never presented as resumable. Checkpointed sessions stay open and restore
lazily through validated core/loop contracts. Uploaded photo bytes and
provider credentials are never stored here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    problem TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'live',
    run_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    case_status TEXT NOT NULL DEFAULT 'open',
    solved_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    glyph TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    record_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, seq);
CREATE TABLE IF NOT EXISTS checkpoints (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

SCHEMA_VERSION = 2

CASE_STATUSES = ("open", "awaiting", "inconclusive", "solved")

MAX_NAME_LENGTH = 80


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HistoryStore:
    """Durable log of investigations and their timeline events."""

    def __init__(self, path):
        self._path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._run_token = uuid.uuid4().hex
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute(
                "UPDATE sessions SET archived = 1, status = 'archived', updated_at = ?"
                " WHERE archived = 0 AND run_token != ?"
                " AND id NOT IN (SELECT session_id FROM checkpoints)",
                (_now(), self._run_token),
            )

    @staticmethod
    def _migrate(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "case_status" not in columns:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN case_status TEXT NOT NULL DEFAULT 'open'")
        if "solved_note" not in columns:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN solved_note TEXT NOT NULL DEFAULT ''")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @property
    def path(self):
        return self._path

    @property
    def run_token(self):
        return self._run_token

    @contextmanager
    def _connect(self):
        # Commits atomically and always closes: on Windows an unclosed
        # connection keeps the database file locked for other processes.
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_session(self, session_id, name, problem):
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, name, problem, status, run_token,"
                " created_at, updated_at, archived, case_status, solved_note)"
                " VALUES (?, ?, ?, 'live', ?, ?, ?, 0, 'open', '')",
                (session_id, name, problem, self._run_token, now, now),
            )
        return session_id

    def set_case_status(self, session_id, status, note=""):
        if status not in CASE_STATUSES:
            raise ValueError(f"Unknown case status: {status}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET case_status = ?, solved_note = ?, updated_at = ?"
                " WHERE id = ?",
                (status, note or "", _now(), session_id),
            )

    def adopt_session(self, session_id):
        """Mark a restored session owned by this process after validation."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET run_token = ?, updated_at = ? WHERE id = ?",
                (self._run_token, _now(), session_id),
            )

    def save_checkpoint(self, session_id, bundle):
        version = bundle.get("version") if isinstance(bundle, dict) else None
        if type(version) is not int:
            raise ValueError("Checkpoint bundle must carry an integer version")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints (session_id, version, payload, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (session_id, version, json.dumps(bundle), _now()),
            )

    def load_checkpoint(self, session_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def archive_session(self, session_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET archived = 1, status = 'archived', updated_at = ?"
                " WHERE id = ?",
                (_now(), session_id),
            )

    def rename_session(self, session_id, name):
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValueError("Session name must not be empty.")
        if len(cleaned) > MAX_NAME_LENGTH:
            raise ValueError(f"Session name must be {MAX_NAME_LENGTH} characters or fewer.")
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
                (cleaned, _now(), session_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"Unknown session: {session_id}")

    def record_event(self, session_id, kind, glyph, title, detail, record_id=None):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = row[0] + 1
            now = _now()
            conn.execute(
                "INSERT INTO events (session_id, seq, kind, glyph, title, detail,"
                " record_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, seq, kind, glyph, title, detail, record_id, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return seq

    def get_session(self, session_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_sessions(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY archived ASC, updated_at DESC",
            ).fetchall()
        return [dict(row) for row in rows]

    def get_events(self, session_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY seq ASC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]
