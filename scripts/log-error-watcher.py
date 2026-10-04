#!/usr/bin/env python3
import hashlib
import os
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
    "Organizer": LOG_DIR / "emby-organizer.err.log",
    "Telegram bot": LOG_DIR / "telegram-download-bot.err.log",
}

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
        data={
            "chat_id": CHAT_ID,
            "text": f"🚨 Error en {source}\n\n{text}",
        },
        timeout=15,
    )
    response.raise_for_status()


def current_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def main():
    offsets = {name: current_size(path) for name, path in WATCHED.items()}
    recent = {}

    print("Watcher de errores iniciado.", flush=True)
    for name, path in WATCHED.items():
        print(f"{name}: {path}", flush=True)

    while True:
        for name, path in WATCHED.items():
            try:
                size = current_size(path)
                offset = offsets[name]

                if size < offset:
                    offset = 0

                if size > offset:
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        handle.seek(offset)
                        chunk = handle.read()
                        offsets[name] = handle.tell()

                    chunk = chunk.strip()
                    if chunk:
                        fingerprint = hashlib.sha256(
                            f"{name}\0{chunk}".encode("utf-8", errors="replace")
                        ).hexdigest()
                        now = time.time()
                        last_sent = recent.get(fingerprint, 0)

                        if now - last_sent >= DEDUP_SECONDS:
                            try:
                                send_alert(name, chunk)
                                recent[fingerprint] = now
                                print(f"Alerta enviada: {name}", flush=True)
                            except Exception as exc:
                                print(f"Error enviando alerta: {exc}", flush=True)

                # Limpia huellas antiguas para que el diccionario no crezca sin límite.
                now = time.time()
                recent = {
                    key: sent_at
                    for key, sent_at in recent.items()
                    if now - sent_at < DEDUP_SECONDS
                }

            except Exception as exc:
                print(f"Error vigilando {name}: {exc}", flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
