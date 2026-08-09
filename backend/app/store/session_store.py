"""Session persistence.

SQLite rather than a dict, for one reason that matters in a demo: the browser
refreshing, the server restarting, or a laptop lid closing must not destroy an
interview in progress. Sessions are stored as JSON blobs with a version column
for optimistic concurrency, which is also what makes double-submitted answers
safe.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..models.domain import InterviewState

log = logging.getLogger("cohortiq.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    done         INTEGER NOT NULL DEFAULT 0,
    state_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
"""


class SessionStore:
    def __init__(self, db_path: str, ttl_seconds: int) -> None:
        self.ttl = ttl_seconds
        self._lock = threading.RLock()
        self.durable = True
        self.degraded_reason: str | None = None

        try:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
        except (OSError, sqlite3.Error) as exc:
            # Read-only volume, locked file, bad path. Losing durability is bad;
            # refusing to start is worse — an interview in memory still works.
            log.error("session store falling back to memory (%s): %s", db_path, exc)
            self.durable = False
            self.degraded_reason = f"{type(exc).__name__}: {exc}"
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)

        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            if self.durable:
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA synchronous=NORMAL")
                except sqlite3.DatabaseError:  # pragma: no cover - pragma support varies
                    pass
            self._conn.commit()

    # ---- CRUD ---------------------------------------------------------
    def get(self, session_id: str) -> InterviewState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json, updated_at FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        if time.time() - row["updated_at"] > self.ttl:
            self.delete(session_id)
            return None
        try:
            return InterviewState.model_validate_json(row["state_json"])
        except Exception:
            # A schema change or a corrupt row must not 500 the endpoint.
            log.exception("failed to deserialise session %s; dropping it", session_id)
            self.delete(session_id)
            return None

    def save(self, state: InterviewState) -> None:
        payload = state.model_dump_json()
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (session_id, created_at, updated_at, version, done, state_json)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    version    = sessions.version + 1,
                    done       = excluded.done,
                    state_json = excluded.state_json
                """,
                (state.session_id, state.created_at, now, int(state.done), payload),
            )
            self._conn.commit()

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self._conn.commit()

    def sweep(self) -> int:
        cutoff = time.time() - self.ttl
        with self._lock:
            cur = self._conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, SUM(done) AS completed FROM sessions"
            ).fetchone()
        return {
            "sessions": row["total"] or 0,
            "completed": row["completed"] or 0,
            "durable": self.durable,
            "degradedReason": self.degraded_reason,
        }

    def completed_states(self, limit: int = 500) -> list[InterviewState]:
        """Every finished interview, for cohort-level aggregation."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_json FROM sessions WHERE done = 1 ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        states: list[InterviewState] = []
        for row in rows:
            try:
                states.append(InterviewState.model_validate_json(row["state_json"]))
            except Exception:  # a single bad row must not break the dashboard
                continue
        return states

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class SessionLocks:
    """Per-session async-safe serialisation.

    Two answers submitted from a double-click must not interleave inside the
    orchestrator; the second waits, sees the updated fingerprint, and is served
    the cached reply.
    """

    def __init__(self) -> None:
        import asyncio

        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = threading.Lock()

    def get(self, session_id: str):
        import asyncio

        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            if len(self._locks) > 2000:
                for key in list(self._locks)[:500]:
                    if not self._locks[key].locked():
                        self._locks.pop(key, None)
            return lock


#: A resend of the same answer inside this window is a double-click or a client
#: retry. Outside it, a candidate repeating themselves is a real answer.
DUPLICATE_WINDOW_SECONDS = 8.0


def fingerprint(session_id: str, message: str | None) -> str:
    import hashlib

    raw = f"{session_id}|{(message or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def json_safe(value: Any) -> Any:
    """Defensive JSON round-trip for anything we hand to the API layer."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))
