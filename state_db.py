#!/usr/bin/env python3
import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

STATE_DIR = Path.home() / ".local" / "share" / "emby_organizer"
DB_PATH = Path(os.getenv("EMBY_STATE_DB", str(STATE_DIR / "state.sqlite3"))).expanduser()
DB_BUSY_TIMEOUT_MS = int(os.getenv("EMBY_DB_BUSY_TIMEOUT_MS", "30000"))
DB_INIT_RETRIES = int(os.getenv("EMBY_DB_INIT_RETRIES", "10"))
DB_INIT_RETRY_DELAY = float(os.getenv("EMBY_DB_INIT_RETRY_DELAY", "0.25"))

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=DB_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
    return conn


def _initialize_once() -> None:
    """Configura SQLite y crea el esquema una vez por proceso.

    journal_mode=WAL puede requerir un bloqueo exclusivo durante unos instantes.
    Como Organizer, bot y dashboard arrancan casi simultáneamente mediante launchd,
    reintentamos únicamente la inicialización cuando otro proceso tiene ese bloqueo.
    """
    last_error = None
    for attempt in range(1, DB_INIT_RETRIES + 1):
        try:
            with closing(connect()) as conn, conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.executescript(
                    """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT,
                category TEXT,
                source_path TEXT,
                destination TEXT,
                details TEXT,
                size_bytes INTEGER,
                job_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_history_status ON history(status);

            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                url TEXT NOT NULL,
                name TEXT NOT NULL,
                target TEXT NOT NULL,
                size_bytes INTEGER,
                resume_supported INTEGER,
                status TEXT NOT NULL,
                queued_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
            CREATE INDEX IF NOT EXISTS idx_downloads_updated_at ON downloads(updated_at DESC);
                    """
                )
            return
        except sqlite3.OperationalError as exc:
            last_error = exc
            if "locked" not in str(exc).lower() or attempt >= DB_INIT_RETRIES:
                raise
            time.sleep(DB_INIT_RETRY_DELAY * attempt)

    if last_error is not None:
        raise last_error


def init_db() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        _initialize_once()
        _INITIALIZED = True


def add_history(
    kind: str,
    status: str,
    *,
    title: str | None = None,
    category: str | None = None,
    source_path: str | None = None,
    destination: str | None = None,
    details: str | None = None,
    size_bytes: int | None = None,
    job_id: int | None = None,
) -> int:
    init_db()
    with closing(connect()) as conn, conn:
        cur = conn.execute(
            """
            INSERT INTO history (
                created_at, kind, status, title, category,
                source_path, destination, details, size_bytes, job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now(), kind, status, title, category,
                source_path, destination, details, size_bytes, job_id,
            ),
        )
        return int(cur.lastrowid)


def create_download(
    *,
    chat_id: str,
    url: str,
    name: str,
    target: str,
    size_bytes: int | None,
    resume_supported: bool | None,
    queued_at: float,
) -> int:
    init_db()
    now = utc_now()
    resume_value = None if resume_supported is None else int(resume_supported)
    with closing(connect()) as conn, conn:
        cur = conn.execute(
            """
            INSERT INTO downloads (
                created_at, updated_at, chat_id, url, name, target,
                size_bytes, resume_supported, status, queued_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (now, now, str(chat_id), url, name, target, size_bytes, resume_value, queued_at),
        )
        return int(cur.lastrowid)


def update_download(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status", "started_at", "finished_at", "attempt", "error",
        "size_bytes", "resume_supported", "target", "name", "url", "chat_id",
    }
    clean = {key: value for key, value in fields.items() if key in allowed}
    if not clean:
        return
    clean["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in clean)
    values = list(clean.values()) + [job_id]
    with closing(connect()) as conn, conn:
        conn.execute(f"UPDATE downloads SET {assignments} WHERE id = ?", values)


def recover_pending_downloads() -> list[dict[str, Any]]:
    init_db()
    with closing(connect()) as conn, conn:
        rows = conn.execute(
            """
            SELECT * FROM downloads
            WHERE status IN ('queued', 'active')
            ORDER BY id ASC
            """
        ).fetchall()
        if rows:
            now = utc_now()
            conn.execute(
                """
                UPDATE downloads
                SET status = 'queued', started_at = NULL, updated_at = ?
                WHERE status = 'active'
                """,
                (now,),
            )
    result = []
    for row in rows:
        item = dict(row)
        item["status"] = "queued"
        if item["resume_supported"] is not None:
            item["resume_supported"] = bool(item["resume_supported"])
        result.append(item)
    return result


def recent_history(limit: int = 30) -> list[dict[str, Any]]:
    init_db()
    limit = max(1, min(int(limit), 500))
    with closing(connect()) as conn, conn:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_downloads(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    limit = max(1, min(int(limit), 500))
    with closing(connect()) as conn, conn:
        rows = conn.execute(
            """
            SELECT id, created_at, updated_at, name, target, size_bytes,
                   resume_supported, status, queued_at, started_at,
                   finished_at, attempt, error
            FROM downloads
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def dashboard_summary() -> dict[str, Any]:
    init_db()
    with closing(connect()) as conn, conn:
        counts = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS count FROM downloads GROUP BY status"
            ).fetchall()
        }
        history_24h = conn.execute(
            """
            SELECT COUNT(*) AS count,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                   SUM(CASE WHEN status IN ('error', 'failed') THEN 1 ELSE 0 END) AS errors,
                   COALESCE(SUM(CASE WHEN status = 'success' THEN size_bytes ELSE 0 END), 0) AS bytes
            FROM history
            WHERE datetime(created_at) >= datetime('now', '-1 day')
            """
        ).fetchone()
    return {
        "downloads": counts,
        "history_24h": {
            "count": int(history_24h["count"] or 0),
            "success": int(history_24h["success"] or 0),
            "errors": int(history_24h["errors"] or 0),
            "bytes": int(history_24h["bytes"] or 0),
        },
    }
