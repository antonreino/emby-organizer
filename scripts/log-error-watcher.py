#!/usr/bin/env python3
import hashlib
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
POLL_SECONDS = float(os.getenv("LOG_ALERT_POLL_SECONDS", "2"))
DEDUP_SECONDS = int(os.getenv("LOG_ALERT_DEDUP_SECONDS", "300"))
MAX_CHARS = int(os.getenv("LOG_ALERT_MAX_CHARS", "3000"))

LOG_DIR = Path.home() / "Library" / "Logs"
WATCHED = {
    "organizer_stdout": {
        "label": "Organizer",
        "path": LOG_DIR / "emby-organizer.out.log",
        "mode": "logging",
    },
    "organizer_stderr": {
        "label": "Organizer",
        "path": LOG_DIR / "emby-organizer.err.log",
        "mode": "raw",
    },
    "telegram_stderr": {
        "label": "Telegram bot",
        "path": LOG_DIR / "telegram-download-bot.err.log",
        "mode": "raw",
    },
}

LOG_RECORD_RE = re.compile(r"^\d{4}-\d{2}-\d{2} .*? \| ([A-Z]+) \| ")

if not TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")
if not CHAT_ID:
    raise SystemExit("Falta TELEGRAM_CHAT_ID en .env")

API = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def redact(text: str) -> str:
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


def send_alert(source: str, text: str) -> None:
    text = redact(text.strip())
    if not text:
        return
    if len(text) > MAX_CHARS:
        text = "… contenido recortado …\n" + text[-MAX_CHARS:]

    response = requests.post(
        API,
        data={"chat_id": CHAT_ID, "text": f"🚨 Error en {source}\n\n{text}"},
        timeout=15,
    )
    response.raise_for_status()


def current_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def extract_logging_errors(chunk: str) -> list[str]:
    """Extrae ERROR/CRITICAL y sus traceback asociados de un StreamHandler."""
    blocks = []
    current = []
    current_is_error = False

    for line in chunk.splitlines():
        match = LOG_RECORD_RE.match(line)
        if match:
            if current and current_is_error:
                blocks.append("\n".join(current))
            current = [line]
            current_is_error = match.group(1) in {"ERROR", "CRITICAL"}
        elif current:
            current.append(line)
        elif line.strip():
            # Fragmento de traceback partido entre dos lecturas: mejor conservarlo.
            current = [line]
            current_is_error = True

    if current and current_is_error:
        blocks.append("\n".join(current))
    return blocks


def messages_for(entry: dict, chunk: str) -> list[str]:
    if entry["mode"] == "logging":
        return extract_logging_errors(chunk)
    chunk = chunk.strip()
    return [chunk] if chunk else []


def main():
    offsets = {key: current_size(entry["path"]) for key, entry in WATCHED.items()}
    recent = {}

    print("Watcher de errores iniciado.", flush=True)
    for entry in WATCHED.values():
        print(f"{entry['label']}: {entry['path']} ({entry['mode']})", flush=True)

    while True:
        for key, entry in WATCHED.items():
            path = entry["path"]
            try:
                size = current_size(path)
                offset = offsets[key]
                if size < offset:
                    offset = 0

                if size > offset:
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        handle.seek(offset)
                        chunk = handle.read()
                        offsets[key] = handle.tell()

                    for message in messages_for(entry, chunk):
                        fingerprint = hashlib.sha256(
                            f"{entry['label']}\0{message}".encode("utf-8", errors="replace")
                        ).hexdigest()
                        now = time.time()
                        if now - recent.get(fingerprint, 0) >= DEDUP_SECONDS:
                            try:
                                send_alert(entry["label"], message)
                                recent[fingerprint] = now
                                print(f"Alerta enviada: {entry['label']}", flush=True)
                            except Exception as exc:
                                print(f"Error enviando alerta: {exc}", flush=True)

                now = time.time()
                recent = {
                    fingerprint: sent_at
                    for fingerprint, sent_at in recent.items()
                    if now - sent_at < DEDUP_SECONDS
                }
            except Exception as exc:
                print(f"Error vigilando {entry['label']}: {exc}", flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
