#!/usr/bin/env python3
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

APP_DIR = Path("/home/tone/Documentos/Agentes/emby-organizer")
ENV_FILE = APP_DIR / ".env"
INBOX = Path("/home/tone/.openclaw/media/inbound")

load_dotenv(ENV_FILE)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

if not TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")

API = f"https://api.telegram.org/bot{TOKEN}"


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
        )
    except Exception as e:
        print(f"Error enviando mensaje Telegram: {e}", flush=True)


def is_allowed(chat_id):
    if not ALLOWED_CHAT_ID:
        return True
    return str(chat_id) == str(ALLOWED_CHAT_ID)


def is_torrent_bytes(path: Path) -> bool:
    try:
        data = path.read_bytes()[:4096]
        return data.startswith(b"d") and b"announce" in data
    except Exception:
        return False


def safe_name(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_").strip()
    if not name:
        name = f"telegram-{int(time.time())}.torrent"
    if not name.endswith(".torrent"):
        name += ".torrent"
    return name


def unique_target(filename: str) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    target = INBOX / safe_name(filename)

    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    i = 1

    while True:
        candidate = INBOX / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def download_file(file_id, filename):
    info = tg("getFile", file_id=file_id)
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

    target = unique_target(filename)
    tmp = target.with_suffix(target.suffix + ".part")

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)

    tmp.rename(target)

    if not is_torrent_bytes(target):
        bad = target.with_suffix(target.suffix + ".rechazado")
        target.rename(bad)
        return None, bad

    return target, None


def handle_message(msg):
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return

    if not is_allowed(chat_id):
        send_message(chat_id, "⛔ Chat no autorizado.")
        print(f"Chat no autorizado: {chat_id}", flush=True)
        return

    text = msg.get("text", "")

    if text in ("/start", "/help"):
        send_message(
            chat_id,
            "Envíame un archivo .torrent y lo dejaré listo para descargar.",
        )
        return

    if text == "/ping":
        send_message(chat_id, "pong")
        return

    doc = msg.get("document")
    if not doc:
        return

    filename = doc.get("file_name", f"telegram-{int(time.time())}.torrent")
    file_id = doc.get("file_id")

    if not file_id:
        send_message(chat_id, "❌ No pude leer el archivo.")
        return

    print(f"Recibido documento: {filename}", flush=True)

    try:
        target, rejected = download_file(file_id, filename)
    except Exception as e:
        send_message(chat_id, f"❌ Error descargando archivo: {e}")
        print(f"Error descargando archivo: {e}", flush=True)
        return

    if rejected:
        send_message(chat_id, f"⚠️ Archivo rechazado, no parece torrent: {rejected.name}")
        print(f"Archivo rechazado: {rejected}", flush=True)
        return

    send_message(chat_id, f"✅ Torrent recibido: {target.name}")
    print(f"Torrent guardado en inbound: {target}", flush=True)


def main():
    INBOX.mkdir(parents=True, exist_ok=True)

    print("Bot Telegram torrent iniciado.", flush=True)
    print(f"Inbox: {INBOX}", flush=True)

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

        except Exception as e:
            print(f"Error loop Telegram: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
