"""Link repository — SQLite today, interface portable to Postgres."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.errors import AppError

# token_urlsafe uses A-Za-z0-9_-, truncate for short codes
DEFAULT_CODE_LENGTH = 8
MAX_CODE_ATTEMPTS = 8


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def generate_code(length: int = DEFAULT_CODE_LENGTH) -> str:
    # token_urlsafe yields ~1.3 chars per byte; oversample then truncate
    raw = secrets.token_urlsafe(length + 4)
    # Keep only URL-safe alnum/_/- and truncate
    cleaned = "".join(c for c in raw if c.isalnum() or c in "_-")
    return cleaned[:length]


@dataclass(frozen=True)
class LinkRecord:
    code: str
    url: str
    created_at: str
    clicks: int
    active: bool


class LinkRepository(Protocol):
    def create(self, url: str, code: str | None = None) -> LinkRecord: ...
    def get(self, code: str, *, active_only: bool = False) -> LinkRecord | None: ...
    def increment_clicks(self, code: str) -> LinkRecord | None: ...
    def soft_delete(self, code: str) -> bool: ...


class SqliteLinkRepository:
    """SQLite implementation. SQL is intentionally simple for Postgres port."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, url: str, code: str | None = None) -> LinkRecord:
        if code is not None:
            return self._insert(code=code, url=url)

        last_err: Exception | None = None
        for _ in range(MAX_CODE_ATTEMPTS):
            candidate = generate_code()
            try:
                return self._insert(code=candidate, url=url)
            except AppError as exc:
                if exc.code != "alias_taken":
                    raise
                last_err = exc
        raise AppError(
            500,
            "Could not allocate a unique short code",
            code="code_generation_failed",
        ) from last_err

    def _insert(self, code: str, url: str) -> LinkRecord:
        created_at = utc_now_iso()
        try:
            self._conn.execute(
                "INSERT INTO links (code, url, created_at, clicks, active) "
                "VALUES (?, ?, ?, 0, 1)",
                (code, url, created_at),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise AppError(
                409,
                "Alias already in use",
                detail=f"code '{code}' is taken",
                code="alias_taken",
            ) from exc
        return LinkRecord(
            code=code, url=url, created_at=created_at, clicks=0, active=True
        )

    def get(self, code: str, *, active_only: bool = False) -> LinkRecord | None:
        if active_only:
            row = self._conn.execute(
                "SELECT code, url, created_at, clicks, active FROM links "
                "WHERE code = ? AND active = 1",
                (code,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT code, url, created_at, clicks, active FROM links WHERE code = ?",
                (code,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def increment_clicks(self, code: str) -> LinkRecord | None:
        cur = self._conn.execute(
            "UPDATE links SET clicks = clicks + 1 "
            "WHERE code = ? AND active = 1",
            (code,),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get(code, active_only=True)

    def soft_delete(self, code: str) -> bool:
        cur = self._conn.execute(
            "UPDATE links SET active = 0 WHERE code = ? AND active = 1",
            (code,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> LinkRecord:
        return LinkRecord(
            code=row["code"],
            url=row["url"],
            created_at=row["created_at"],
            clicks=int(row["clicks"]),
            active=bool(row["active"]),
        )
