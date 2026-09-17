"""SQLite connection helpers (Postgres-portable SQL dialect where practical)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code TEXT PRIMARY KEY NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    clicks INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_links_active ON links(active);
"""


def _ensure_parent(path: str) -> None:
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def connect(path: str | None = None) -> sqlite3.Connection:
    db_path = path or get_settings().sqlite_path
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def get_connection(path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()
