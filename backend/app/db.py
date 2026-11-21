"""SQLite session storage (stdlib sqlite3; schema is created on startup)."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.database_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    path = config.database_path()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")


def db_ok() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_history(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
    out = []
    for r in rows:
        item = {"role": r["role"], "content": r["content"]}
        if r["metadata"]:
            item["metadata"] = json.loads(r["metadata"])
        out.append(item)
    return out


def get_system_prompt(session_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return row["system_prompt"] if row else None


def save_turn(session_id: str, user_msg: str, reply: str, metadata: dict, system_prompt: str | None) -> None:
    """Persist user + assistant messages atomically (only called after a successful reply)."""
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        if system_prompt is not None:
            conn.execute(
                "INSERT INTO sessions(session_id, system_prompt) VALUES(?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt=excluded.system_prompt",
                (session_id, system_prompt),
            )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
            (session_id, "user", user_msg, None, now),
        )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
            (session_id, "assistant", reply, json.dumps(metadata), now),
        )
