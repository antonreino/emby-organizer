#!/usr/bin/env python3
import json
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
            CREATE TABLE IF NOT EXISTS runtime_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS download_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_download_requests_status
                ON download_requests(status, id);
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



def set_runtime_state(key: str, value: dict[str, Any]) -> None:
    init_db()
    now = utc_now()
    payload = json.dumps(value, ensure_ascii=False)
    with closing(connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO runtime_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, payload, now),
        )


def get_runtime_state(key: str) -> dict[str, Any] | None:
    init_db()
    with closing(connect()) as conn, conn:
        row = conn.execute(
            "SELECT value, updated_at FROM runtime_state WHERE key = ?",
            (key,),
        ).fetchone()

    if row is None:
        return None

    try:
        value = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return None

    if isinstance(value, dict):
        value.setdefault("stored_at", row["updated_at"])
        return value
    return None


def save_emby_storage(*, path: str, total: int, used: int, free: int) -> None:
    set_runtime_state(
        "emby_storage",
        {
            "available": True,
            "path": path,
            "total": int(total),
            "used": int(used),
            "free": int(free),
            "used_percent": round((int(used) * 100 / int(total)), 1) if total else 0.0,
            "updated_at": utc_now(),
            "stale": False,
        },
    )


def mark_emby_storage_error(error: str) -> None:
    current = get_runtime_state("emby_storage") or {
        "available": False,
        "path": None,
        "total": 0,
        "used": 0,
        "free": 0,
        "used_percent": 0.0,
    }
    current["last_error"] = str(error)
    current["last_error_at"] = utc_now()
    current["stale"] = bool(current.get("available"))
    set_runtime_state("emby_storage", current)


def emby_storage_snapshot() -> dict[str, Any]:
    current = get_runtime_state("emby_storage")
    if current is None:
        return {
            "available": False,
            "error": "Todavía no hay una lectura del almacenamiento de Emby",
            "stale": False,
        }

    if not current.get("available"):
        current["error"] = current.get("last_error") or "Sin información de almacenamiento"
    return current



def save_emby_system(*, cpu_percent: float, ram_total: int, ram_used: int, ram_available: int, load_1: float, load_5: float, load_15: float) -> None:
    set_runtime_state(
        "emby_system",
        {
            "available": True,
            "cpu_percent": round(float(cpu_percent), 1),
            "ram_total": int(ram_total),
            "ram_used": int(ram_used),
            "ram_available": int(ram_available),
            "ram_percent": round((int(ram_used) * 100 / int(ram_total)), 1) if ram_total else 0.0,
            "load_1": round(float(load_1), 2),
            "load_5": round(float(load_5), 2),
            "load_15": round(float(load_15), 2),
            "updated_at": utc_now(),
            "stale": False,
        },
    )


def mark_emby_system_error(error: str) -> None:
    current = get_runtime_state("emby_system") or {
        "available": False,
        "cpu_percent": None,
        "ram_total": 0,
        "ram_used": 0,
        "ram_available": 0,
        "ram_percent": None,
        "load_1": None,
        "load_5": None,
        "load_15": None,
    }
    current["last_error"] = str(error)
    current["last_error_at"] = utc_now()
    current["stale"] = bool(current.get("available"))
    set_runtime_state("emby_system", current)


def emby_system_snapshot() -> dict[str, Any]:
    current = get_runtime_state("emby_system")
    if current is None:
        return {
            "available": False,
            "error": "Todavía no hay una lectura de CPU/RAM del servidor Emby",
            "stale": False,
        }
    if not current.get("available"):
        current["error"] = current.get("last_error") or "Sin información de CPU/RAM"
    return current

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



def queue_download_request(*, chat_id: str, url: str) -> int:
    init_db()
    now = utc_now()
    with closing(connect()) as conn, conn:
        cur = conn.execute(
            """
            INSERT INTO download_requests (created_at, updated_at, chat_id, url, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (now, now, str(chat_id), str(url)),
        )
        return int(cur.lastrowid)


def recover_download_requests() -> None:
    init_db()
    now = utc_now()
    with closing(connect()) as conn, conn:
        conn.execute(
            """
            UPDATE download_requests
            SET status='pending', updated_at=?, error=NULL
            WHERE status='processing'
            """,
            (now,),
        )


def claim_download_requests(limit: int = 5) -> list[dict[str, Any]]:
    init_db()
    limit = max(1, min(int(limit), 20))
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id, chat_id, url
            FROM download_requests
            WHERE status='pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if rows:
            now = utc_now()
            conn.executemany(
                "UPDATE download_requests SET status='processing', updated_at=? WHERE id=?",
                [(now, int(row["id"])) for row in rows],
            )
        conn.commit()
    return [dict(row) for row in rows]


def finish_download_request(request_id: int, *, status: str, error: str | None = None) -> None:
    init_db()
    with closing(connect()) as conn, conn:
        conn.execute(
            """
            UPDATE download_requests
            SET status=?, error=?, updated_at=?
            WHERE id=?
            """,
            (str(status), error, utc_now(), int(request_id)),
        )

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



def dashboard_statistics() -> dict[str, Any]:
    """Estadísticas del historial persistente desde que existe la base SQLite."""
    init_db()

    def aggregate(conn: sqlite3.Connection, modifier: str | None = None) -> dict[str, int]:
        where = ""
        params: tuple[Any, ...] = ()
        if modifier is not None:
            where = "WHERE datetime(created_at) >= datetime('now', ?)"
            params = (modifier,)

        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE
                    WHEN kind = 'download' AND status = 'success'
                    THEN COALESCE(size_bytes, 0) ELSE 0 END), 0) AS downloaded_bytes,
                COALESCE(SUM(CASE
                    WHEN kind = 'organizer' AND status = 'success'
                    THEN COALESCE(size_bytes, 0) ELSE 0 END), 0) AS moved_bytes,
                SUM(CASE WHEN kind = 'download' AND status = 'success' THEN 1 ELSE 0 END) AS download_count,
                SUM(CASE WHEN kind = 'organizer' AND status = 'success' THEN 1 ELSE 0 END) AS moved_count
            FROM history
            {where}
            """,
            params,
        ).fetchone()

        return {
            "downloaded_bytes": int(row["downloaded_bytes"] or 0),
            "moved_bytes": int(row["moved_bytes"] or 0),
            "download_count": int(row["download_count"] or 0),
            "moved_count": int(row["moved_count"] or 0),
        }

    with closing(connect()) as conn, conn:
        periods = [
            {"label": "Últimas 24 horas", **aggregate(conn, "-1 day")},
            {"label": "Últimos 7 días", **aggregate(conn, "-7 days")},
            {"label": "Últimos 30 días", **aggregate(conn, "-30 days")},
            {"label": "Todo el historial", **aggregate(conn)},
        ]

        categories = [
            {
                "category": row["category"] or "Sin categoría",
                "bytes": int(row["bytes"] or 0),
                "count": int(row["count"] or 0),
            }
            for row in conn.execute(
                """
                SELECT category,
                       COALESCE(SUM(size_bytes), 0) AS bytes,
                       COUNT(*) AS count
                FROM history
                WHERE kind = 'organizer' AND status = 'success'
                GROUP BY category
                ORDER BY bytes DESC
                """
            ).fetchall()
        ]

        bounds = conn.execute(
            """
            SELECT MIN(created_at) AS first_event,
                   MAX(created_at) AS last_event
            FROM history
            """
        ).fetchone()

    total = periods[-1]
    return {
        "downloaded_bytes": total["downloaded_bytes"],
        "moved_bytes": total["moved_bytes"],
        "total_bytes": total["downloaded_bytes"] + total["moved_bytes"],
        "download_count": total["download_count"],
        "moved_count": total["moved_count"],
        "periods": periods,
        "categories": categories,
        "first_event": bounds["first_event"],
        "last_event": bounds["last_event"],
    }


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
                   COALESCE(SUM(CASE WHEN status = 'success' THEN size_bytes ELSE 0 END), 0) AS bytes,
                   COALESCE(SUM(CASE WHEN kind = 'download' AND status = 'success' THEN size_bytes ELSE 0 END), 0) AS downloaded_bytes,
                   COALESCE(SUM(CASE WHEN kind = 'organizer' AND status = 'success' THEN size_bytes ELSE 0 END), 0) AS moved_bytes
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
            "downloaded_bytes": int(history_24h["downloaded_bytes"] or 0),
            "moved_bytes": int(history_24h["moved_bytes"] or 0),
        },
    }
