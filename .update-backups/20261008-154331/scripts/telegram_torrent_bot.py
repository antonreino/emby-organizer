#!/usr/bin/env python3
import os
import re
import subprocess
import threading
import sys
import time
from collections import deque
from datetime import datetime
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
from torrent_utils import is_torrent_file, safe_torrent_name, unique_target
from state_db import (
    add_history,
    claim_download_requests,
    create_download,
    finish_download_request,
    init_db,
    recover_download_requests,
    recover_pending_downloads,
    update_download,
)

ENV_FILE = APP_DIR / ".env"
load_dotenv(ENV_FILE)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TORRENT_DROP_DIR = Path(os.getenv("TORRENT_DROP_DIR", str(Path.home() / "Downloads"))).expanduser()
GAME_DOWNLOAD_DIR = Path(os.getenv("GAME_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "Games"))).expanduser()
GAME_MAX_RETRIES = int(os.getenv("GAME_MAX_RETRIES", "20"))
GAME_RETRY_DELAY = int(os.getenv("GAME_RETRY_DELAY", "5"))
GAME_MAX_CONCURRENT = int(os.getenv("GAME_MAX_CONCURRENT", "2"))
TELEGRAM_LOG_LINES = int(os.getenv("TELEGRAM_LOG_LINES", "30"))

LOG_DIR = Path.home() / "Library" / "Logs"
ORGANIZER_OUT_LOG = LOG_DIR / "emby-organizer.out.log"
ORGANIZER_ERR_LOG = LOG_DIR / "emby-organizer.err.log"
BOT_OUT_LOG = LOG_DIR / "telegram-download-bot.out.log"
BOT_ERR_LOG = LOG_DIR / "telegram-download-bot.err.log"

if not TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")
if not ALLOWED_CHAT_ID:
    raise SystemExit("Falta TELEGRAM_CHAT_ID en .env")

API = f"https://api.telegram.org/bot{TOKEN}"

DOWNLOAD_LOCK = threading.Lock()
ACTIVE_DOWNLOADS = {}      # job_id -> job dict
QUEUED_DOWNLOADS = deque() # job dicts
KNOWN_TARGETS = set()      # target paths active or queued


def log(message: str) -> None:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} | {message}", flush=True)


def tg(method, **params):
    r = requests.get(f"{API}/{method}", params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data["result"]


def send_message(chat_id, text):
    try:
        requests.post(
            f"{API}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=15,
        ).raise_for_status()
    except Exception as exc:
        log(f"Error enviando mensaje Telegram: {exc}")


def is_allowed(chat_id):
    return str(chat_id) == str(ALLOWED_CHAT_ID)


def redact_secrets(text: str) -> str:
    secrets = [
        TOKEN,
        os.getenv("EMBY_SFTP_PASSWORD", ""),
        os.getenv("TMDB_API_KEY", ""),
        os.getenv("EMBY_API_KEY", ""),
    ]
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "[REDACTADO]")
    return text


def tail_log(path: Path, lines: int = TELEGRAM_LOG_LINES) -> str:
    if not path.exists():
        return "(sin archivo de log)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail = deque(handle, maxlen=max(1, lines))
        text = "".join(tail).strip()
        return redact_secrets(text) if text else "(vacío)"
    except Exception as exc:
        return f"(error leyendo {path.name}: {exc})"


def logs_message(target: str = "organizer") -> str:
    target = (target or "organizer").lower().strip()
    if target in ("organizer", "organizador", "emby"):
        sections = [("🎬 Organizer", ORGANIZER_OUT_LOG), ("🚨 Organizer errores", ORGANIZER_ERR_LOG)]
    elif target in ("bot", "telegram"):
        sections = [("🤖 Telegram bot", BOT_OUT_LOG), ("🚨 Telegram errores", BOT_ERR_LOG)]
    elif target in ("todos", "all"):
        sections = [
            ("🎬 Organizer", ORGANIZER_OUT_LOG), ("🚨 Organizer errores", ORGANIZER_ERR_LOG),
            ("🤖 Telegram bot", BOT_OUT_LOG), ("🚨 Telegram errores", BOT_ERR_LOG),
        ]
    else:
        return "Uso: /logs, /logs bot o /logs todos"

    chunks = [f"📋 Últimas {TELEGRAM_LOG_LINES} líneas"]
    for title, path in sections:
        chunks.append(f"\n{title}\n{tail_log(path)}")
    message = "\n".join(chunks)
    if len(message) > 3900:
        message = "… salida recortada …\n" + message[-3875:]
    return message



def safe_filename(name: str) -> str:
    name = unquote(name or "").strip().strip('"').strip("'")
    name = Path(name).name.replace("/", "_").replace("\\", "_")
    return name or f"descarga-{int(time.time())}"



def download_torrent_file(file_id, filename):
    info = tg("getFile", file_id=file_id)
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

    target = unique_target(TORRENT_DROP_DIR, safe_torrent_name(filename))
    tmp = target.with_suffix(target.suffix + ".part")

    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 512):
                if chunk:
                    handle.write(chunk)

    tmp.rename(target)

    if not is_torrent_file(target):
        bad = target.with_suffix(target.suffix + ".rechazado")
        target.rename(bad)
        return None, bad

    return target, None


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    match = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)]+)\)", raw, flags=re.DOTALL)
    if match:
        raw = match.group(2)
    raw = raw.replace("\\&", "&").replace("\\_", "_")
    return raw.strip()


def filename_from_content_disposition(disposition: str) -> str:
    if not disposition:
        return ""
    try:
        msg = Message()
        msg["Content-Disposition"] = disposition
        return safe_filename(msg.get_filename() or "") if msg.get_filename() else ""
    except Exception:
        return ""


def filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    disposition = unquote(params.get("response-content-disposition", [""])[0])
    name = filename_from_content_disposition(disposition)
    if name:
        return name
    return safe_filename(Path(parsed.path).name)


def probe_game_url(url: str) -> dict:
    headers = {"User-Agent": "curl/8 (ps5-telegram-download-bot)", "Accept": "*/*"}
    response = None
    try:
        response = requests.head(url, allow_redirects=True, timeout=(15, 30), headers=headers)
        if response.status_code >= 400 or not (
            response.headers.get("Content-Disposition")
            or response.headers.get("Content-Length")
            or response.headers.get("Accept-Ranges")
        ):
            response.close()
            response = requests.get(
                url,
                allow_redirects=True,
                stream=True,
                timeout=(15, 30),
                headers={**headers, "Range": "bytes=0-0"},
            )

        response.raise_for_status()
        h = response.headers
        name = filename_from_content_disposition(h.get("Content-Disposition", "")) or filename_from_url(url)

        total_size = None
        content_length = h.get("Content-Length", "")
        if content_length.isdigit():
            total_size = int(content_length)
        content_range = h.get("Content-Range", "")
        m = re.search(r"/(\d+)$", content_range)
        if m:
            total_size = int(m.group(1))

        accept_ranges = h.get("Accept-Ranges", "").lower()
        resume_supported = "bytes" in accept_ranges or response.status_code == 206

        return {
            "name": safe_filename(name),
            "size": total_size,
            "resume": resume_supported,
            "status": response.status_code,
            "final_url": str(response.url),
        }
    except Exception as exc:
        return {
            "name": filename_from_url(url),
            "size": None,
            "resume": None,
            "status": None,
            "final_url": url,
            "probe_error": str(exc),
        }
    finally:
        if response is not None:
            response.close()


def human_size(size_bytes):
    if size_bytes is None:
        return "desconocido"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    i = 0
    while value >= 1000 and i < len(units) - 1:
        value /= 1000
        i += 1
    return f"{value:.2f} {units[i]}"


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def progress_text(job: dict) -> str:
    downloaded = file_size(job["target"])
    total = job.get("size")
    if total and total > 0:
        pct = min(100.0, downloaded * 100.0 / total)
        return f"{pct:.1f}% · {human_size(downloaded)} / {human_size(total)}"
    return f"{human_size(downloaded)} descargados"


def queue_position(job_id: int):
    with DOWNLOAD_LOCK:
        for i, job in enumerate(QUEUED_DOWNLOADS, start=1):
            if job["id"] == job_id:
                return i
    return None


def start_queued_downloads():
    to_start = []
    with DOWNLOAD_LOCK:
        while len(ACTIVE_DOWNLOADS) < GAME_MAX_CONCURRENT and QUEUED_DOWNLOADS:
            job = QUEUED_DOWNLOADS.popleft()
            job["status"] = "active"
            job["started_at"] = time.time()
            update_download(job["id"], status="active", started_at=job["started_at"], error=None)
            ACTIVE_DOWNLOADS[job["id"]] = job
            to_start.append(job)

    for job in to_start:
        thread = threading.Thread(target=run_game_download, args=(job,), daemon=True)
        thread.start()


def finish_job(job: dict):
    with DOWNLOAD_LOCK:
        ACTIVE_DOWNLOADS.pop(job["id"], None)
        KNOWN_TARGETS.discard(str(job["target"]))
    start_queued_downloads()


def run_game_download(job: dict):
    chat_id = job["chat_id"]
    url = job["url"]
    name = job["name"]
    target = job["target"]
    resume = job.get("resume")

    try:
        if not GAME_DOWNLOAD_DIR.parent.exists():
            error = f"No está montado el volumen de destino: {GAME_DOWNLOAD_DIR.parent}"
            update_download(job["id"], status="failed", finished_at=time.time(), error=error)
            add_history("download", "failed", title=name, destination=str(target), details=error, job_id=job["id"])
            send_message(chat_id, f"❌ No está montado el volumen de destino:\n{GAME_DOWNLOAD_DIR.parent}")
            return

        GAME_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        resume_text = "Sí" if resume is True else "No" if resume is False else "No se pudo comprobar"
        start_text = (
            f"⬇️ Descarga iniciada #{job['id']}:\n{name}\n"
            f"📦 Tamaño: {human_size(job.get('size'))}\n"
            f"♻️ Reanudación: {resume_text}"
        )
        if job.get("probe_error"):
            start_text += "\n⚠️ No pude leer todas las cabeceras; curl lo intentará igualmente."
        send_message(chat_id, start_text)
        log(f"Juego #{job['id']}: {name} | Destino: {target}")

        for attempt in range(1, GAME_MAX_RETRIES + 1):
            job["attempt"] = attempt
            update_download(job["id"], attempt=attempt)
            cmd = [
                "/usr/bin/caffeinate",
                "/usr/bin/curl",
                "-L",
                "--fail",
                "--show-error",
                "--silent",
                "--connect-timeout", "30",
                "-o", str(target),
            ]
            if resume is not False:
                cmd += ["-C", "-"]
            cmd.append(url)

            process = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            job["pid"] = process.pid
            stdout, stderr = process.communicate()
            job["pid"] = None

            if process.returncode == 0:
                final_size = file_size(target)
                update_download(
                    job["id"], status="completed", finished_at=time.time(),
                    error=None, size_bytes=final_size,
                )
                add_history(
                    "download", "success", title=name, destination=str(target),
                    details="Descarga directa completada", size_bytes=final_size,
                    job_id=job["id"],
                )
                send_message(
                    chat_id,
                    f"✅ Descarga completada #{job['id']}:\n{name}\n📦 {human_size(final_size)}",
                )
                log(f"Descarga completada #{job['id']}: {target}")
                return

            error = (stderr or stdout or "Error desconocido").strip()[-500:]
            update_download(job["id"], error=error, attempt=attempt)
            log(f"Descarga #{job['id']} intento {attempt}/{GAME_MAX_RETRIES} falló: {error}")
            send_message(
                chat_id,
                f"⚠️ Descarga interrumpida #{job['id']}\n\n🎮 {name}\n"
                f"📊 {progress_text(job)}\n"
                f"🔁 Intento: {attempt}/{GAME_MAX_RETRIES}\n"
                f"⚙️ curl: {process.returncode}\n\n"
                f"Reintento en {GAME_RETRY_DELAY} s.",
            )
            if attempt < GAME_MAX_RETRIES:
                time.sleep(GAME_RETRY_DELAY)

        final_error = f"Se agotaron los {GAME_MAX_RETRIES} intentos"
        update_download(job["id"], status="failed", finished_at=time.time(), error=final_error)
        add_history(
            "download", "failed", title=name, destination=str(target),
            details=final_error, size_bytes=file_size(target), job_id=job["id"],
        )
        send_message(
            chat_id,
            f"❌ DESCARGA FALLIDA #{job['id']}\n\n🎮 {name}\n"
            f"Se agotaron los {GAME_MAX_RETRIES} intentos.",
        )
    except Exception as exc:
        update_download(job["id"], status="failed", finished_at=time.time(), error=str(exc))
        add_history(
            "download", "failed", title=name, destination=str(target),
            details=str(exc), size_bytes=file_size(target), job_id=job["id"],
        )
        log(f"Error inesperado en descarga #{job['id']}: {exc}")
        send_message(chat_id, f"❌ Error inesperado en descarga #{job['id']}:\n{name}\n{exc}")
    finally:
        finish_job(job)


def enqueue_game_download(chat_id, raw_url: str):
    url = normalize_url(raw_url)
    if not url.lower().startswith(("http://", "https://")):
        send_message(chat_id, "❌ URL no válida.\nUso: /juego https://...")
        return None

    probe = probe_game_url(url)
    name = probe["name"]
    target = GAME_DOWNLOAD_DIR / name
    key = str(target)

    with DOWNLOAD_LOCK:
        if key in KNOWN_TARGETS:
            send_message(chat_id, f"⚠️ Esa descarga ya está activa o en cola:\n{name}")
            return None

        queued_at = time.time()
        job_id = create_download(
            chat_id=str(chat_id), url=url, name=name, target=str(target),
            size_bytes=probe.get("size"), resume_supported=probe.get("resume"),
            queued_at=queued_at,
        )
        job = {
            "id": job_id,
            "chat_id": chat_id,
            "url": url,
            "name": name,
            "target": target,
            "size": probe.get("size"),
            "resume": probe.get("resume"),
            "probe_error": probe.get("probe_error"),
            "queued_at": queued_at,
            "started_at": None,
            "attempt": 0,
            "pid": None,
            "status": "queued",
        }
        KNOWN_TARGETS.add(key)
        QUEUED_DOWNLOADS.append(job)
        position = len(QUEUED_DOWNLOADS)
        can_start_now = len(ACTIVE_DOWNLOADS) < GAME_MAX_CONCURRENT

    add_history(
        "download", "queued", title=name, destination=str(target),
        details="Descarga añadida a la cola", size_bytes=probe.get("size"),
        job_id=job_id,
    )

    if can_start_now:
        send_message(chat_id, f"🆕 Descarga añadida #{job_id}:\n{name}\n▶️ Preparando inicio...")
    else:
        send_message(chat_id, f"🕒 Descarga en cola #{job_id}:\n{name}\n📋 Posición: {position}")

    start_queued_downloads()
    return job_id


def dashboard_request_loop():
    recover_download_requests()
    while True:
        try:
            requests_to_process = claim_download_requests(5)
            if not requests_to_process:
                time.sleep(1)
                continue
            for request in requests_to_process:
                try:
                    job_id = enqueue_game_download(request["chat_id"], request["url"])
                    if job_id is None:
                        finish_download_request(
                            request["id"], status="rejected",
                            error="URL rechazada o descarga duplicada",
                        )
                    else:
                        finish_download_request(request["id"], status="accepted")
                        log(f"Dashboard -> descarga #{job_id} aceptada")
                except Exception as exc:
                    finish_download_request(request["id"], status="error", error=str(exc))
                    log(f"Error procesando solicitud del dashboard #{request['id']}: {exc}")
        except Exception as exc:
            log(f"Error leyendo solicitudes del dashboard: {exc}")
            time.sleep(3)


def restore_persistent_queue():
    recovered = recover_pending_downloads()
    if not recovered:
        return 0

    with DOWNLOAD_LOCK:
        for row in recovered:
            target = Path(row["target"])
            key = str(target)
            if key in KNOWN_TARGETS:
                continue
            job = {
                "id": row["id"],
                "chat_id": row["chat_id"],
                "url": row["url"],
                "name": row["name"],
                "target": target,
                "size": row["size_bytes"],
                "resume": row["resume_supported"],
                "probe_error": None,
                "queued_at": row["queued_at"],
                "started_at": None,
                "attempt": row["attempt"] or 0,
                "pid": None,
                "status": "queued",
            }
            KNOWN_TARGETS.add(key)
            QUEUED_DOWNLOADS.append(job)

    return len(recovered)


def downloads_status(chat_id):
    with DOWNLOAD_LOCK:
        active = list(ACTIVE_DOWNLOADS.values())
        queued = list(QUEUED_DOWNLOADS)

    if not active and not queued:
        send_message(chat_id, "📭 No hay descargas activas ni en cola.")
        return

    lines = [f"📥 Descargas ({len(active)} activas · {len(queued)} en cola)"]

    if active:
        lines.append("\n▶️ ACTIVAS")
        for job in active:
            lines.append(
                f"#{job['id']} {job['name']}\n"
                f"   📊 {progress_text(job)}\n"
                f"   🔁 Intento {max(job.get('attempt', 1), 1)}/{GAME_MAX_RETRIES}"
            )

    if queued:
        lines.append("\n🕒 EN COLA")
        for i, job in enumerate(queued, start=1):
            size = human_size(job.get("size"))
            lines.append(f"{i}. #{job['id']} {job['name']} · {size}")

    send_message(chat_id, "\n".join(lines))


def handle_message(msg):
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return

    if not is_allowed(chat_id):
        send_message(chat_id, "⛔ Chat no autorizado.")
        log(f"Chat no autorizado: {chat_id}")
        return

    text = (msg.get("text") or "").strip()

    if text in ("/start", "/help"):
        send_message(
            chat_id,
            "🎬 Bot de descargas\n\n"
            "• Envíame un .torrent y lo guardaré en ~/Downloads.\n"
            "• /juego URL añade una descarga directa.\n"
            f"• Máximo {GAME_MAX_CONCURRENT} descargas simultáneas; el resto queda en cola.\n"
            "• /estado muestra progreso y cola.\n"
            "• /logs muestra los logs del Organizer.\n"
            "• /logs bot muestra los logs del bot.\n"
            "• /logs todos muestra ambos.\n"
            "• /ping comprueba que el bot responde.",
        )
        return

    if text == "/ping":
        send_message(chat_id, "pong")
        return

    if text in ("/estado", "/status", "/descargas"):
        downloads_status(chat_id)
        return

    if text == "/logs" or text.startswith("/logs "):
        parts = text.split(maxsplit=1)
        target = parts[1] if len(parts) == 2 else "organizer"
        send_message(chat_id, logs_message(target))
        return

    if text.startswith("/juego"):
        parts = text.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            send_message(chat_id, "Uso: /juego https://servidor/archivo")
            return
        enqueue_game_download(chat_id, parts[1].strip())
        return

    doc = msg.get("document")
    if not doc:
        return

    filename = doc.get("file_name", f"telegram-{int(time.time())}.torrent")
    file_id = doc.get("file_id")
    if not file_id:
        send_message(chat_id, "❌ No pude leer el archivo.")
        return

    log(f"Recibido documento: {filename}")
    try:
        target, rejected = download_torrent_file(file_id, filename)
    except Exception as exc:
        send_message(chat_id, f"❌ Error descargando archivo: {exc}")
        log(f"Error descargando archivo: {exc}")
        return

    if rejected:
        send_message(chat_id, f"⚠️ Archivo rechazado, no parece torrent: {rejected.name}")
        log(f"Archivo rechazado: {rejected}")
        return

    add_history(
        "torrent", "success", title=target.name, source_path="telegram",
        destination=str(target.parent), details="Torrent recibido por Telegram", size_bytes=target.stat().st_size,
    )
    send_message(chat_id, f"✅ Torrent recibido:\n{target.name}\n📁 {target.parent}")
    log(f"Torrent guardado: {target}")


def main():
    init_db()
    TORRENT_DROP_DIR.mkdir(parents=True, exist_ok=True)
    recovered = restore_persistent_queue()
    log("Bot Telegram iniciado.")
    log(f"Torrents -> {TORRENT_DROP_DIR}")
    log(f"/juego -> {GAME_DOWNLOAD_DIR}")
    log(f"Descargas simultáneas -> {GAME_MAX_CONCURRENT}")
    if recovered:
        log(f"Cola persistente recuperada -> {recovered}")
        start_queued_downloads()

    request_thread = threading.Thread(target=dashboard_request_loop, daemon=True)
    request_thread.start()
    log("Cola de solicitudes del dashboard -> activa")

    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset

            updates = tg("getUpdates", **params)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if msg:
                    handle_message(msg)
        except Exception as exc:
            log(f"Error loop Telegram: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
