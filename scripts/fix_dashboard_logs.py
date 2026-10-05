#!/usr/bin/env python3
from pathlib import Path

ROOT = Path.cwd()
STATE = ROOT / "state_db.py"
VIEWER = ROOT / "scripts" / "log-viewer.py"
BOT = ROOT / "scripts" / "telegram_torrent_bot.py"

for path in (STATE, VIEWER, BOT):
    if not path.exists():
        raise SystemExit(f"ERROR: no encuentro {path}. Ejecuta este patcher desde la raíz de emby-organizer.")

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ERROR en {label}: esperaba 1 coincidencia y encontré {count}.")
    return text.replace(old, new, 1)

# 1) Cerrar siempre las conexiones SQLite.
text = STATE.read_text(encoding="utf-8")
if "from contextlib import closing" not in text:
    text = replace_once(
        text,
        "import time\nfrom datetime import datetime, timezone\n",
        "import time\nfrom contextlib import closing\nfrom datetime import datetime, timezone\n",
        "import closing",
    )
count = text.count("with connect() as conn:")
if count:
    text = text.replace("with connect() as conn:", "with closing(connect()) as conn, conn:")
elif "with closing(connect()) as conn, conn:" not in text:
    raise SystemExit("ERROR: no encuentro conexiones SQLite que parchear.")
STATE.write_text(text, encoding="utf-8")
print(f"OK state_db.py: {count} conexiones ajustadas.")

# 2) Formato DD/MM/YYYY HH:MM:SS en el dashboard.
text = VIEWER.read_text(encoding="utf-8")
if "\nimport re\n" not in text:
    text = replace_once(text, "import os\nimport shutil\n", "import os\nimport re\nimport shutil\n", "import re")

services_block = '''SERVICES = {
    "organizer": "com.tone.emby-organizer",
    "telegram": "com.tone.telegram-download-bot",
    "viewer": "com.tone.emby-log-viewer",
    "alerts": "com.tone.emby-log-alerts",
}
'''
if "LOG_TS_RE =" not in text:
    text = replace_once(
        text,
        services_block,
        services_block + '\nLOG_TS_RE = re.compile(r"^(?P<date>\\d{4}-\\d{2}-\\d{2}) (?P<time>\\d{2}:\\d{2}:\\d{2})(?:,\\d+)?(?P<rest>.*)$")\n',
        "regex timestamps",
    )

old_tail = '''def tail(path: Path, lines: int) -> str:
    if not path.exists():
        return "(sin archivo de log)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=lines)).strip()
    except Exception as exc:
        return f"(error leyendo {path.name}: {exc})"
'''
new_tail = '''def format_log_timestamps(text: str) -> str:
    result = []
    last_stamp = None
    for line in text.splitlines():
        match = LOG_TS_RE.match(line)
        if match:
            year, month, day = match.group("date").split("-")
            last_stamp = f"{day}/{month}/{year} {match.group('time')}"
            result.append(f"{last_stamp}{match.group('rest')}")
        elif last_stamp and line.strip():
            result.append(f"{last_stamp} | {line}")
        else:
            result.append(line)
    return "\\n".join(result)


def tail(path: Path, lines: int) -> str:
    if not path.exists():
        return "(sin archivo de log)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            raw = "".join(deque(handle, maxlen=lines)).strip()
        return format_log_timestamps(raw)
    except Exception as exc:
        return f"(error leyendo {path.name}: {exc})"
'''
if "def format_log_timestamps(" not in text:
    text = replace_once(text, old_tail, new_tail, "tail del dashboard")
VIEWER.write_text(text, encoding="utf-8")
print("OK log-viewer.py: formato español añadido.")

# 3) Timestamp real en los logs nuevos del bot.
text = BOT.read_text(encoding="utf-8")
if "from datetime import datetime\n" not in text:
    text = replace_once(
        text,
        "from collections import deque\nfrom email.message import Message\n",
        "from collections import deque\nfrom datetime import datetime\nfrom email.message import Message\n",
        "datetime bot",
    )

anchor = '''KNOWN_TARGETS = set()      # target paths active or queued


'''
helper = '''KNOWN_TARGETS = set()      # target paths active or queued


def log(message: str) -> None:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} | {message}", flush=True)


'''
if "def log(message: str)" not in text:
    text = replace_once(text, anchor, helper, "helper log bot")

replacements = {
    'print(f"Error enviando mensaje Telegram: {exc}", flush=True)': 'log(f"Error enviando mensaje Telegram: {exc}")',
    'print(f"Juego #{job[\'id\']}: {name}\\nDestino: {target}", flush=True)': 'log(f"Juego #{job[\'id\']}: {name} | Destino: {target}")',
    'print(f"Descarga completada #{job[\'id\']}: {target}", flush=True)': 'log(f"Descarga completada #{job[\'id\']}: {target}")',
    'print(f"Descarga #{job[\'id\']} intento {attempt}/{GAME_MAX_RETRIES} falló: {error}", flush=True)': 'log(f"Descarga #{job[\'id\']} intento {attempt}/{GAME_MAX_RETRIES} falló: {error}")',
    'print(f"Error inesperado en descarga #{job[\'id\']}: {exc}", flush=True)': 'log(f"Error inesperado en descarga #{job[\'id\']}: {exc}")',
    'print(f"Chat no autorizado: {chat_id}", flush=True)': 'log(f"Chat no autorizado: {chat_id}")',
    'print(f"Recibido documento: {filename}", flush=True)': 'log(f"Recibido documento: {filename}")',
    'print(f"Error descargando archivo: {exc}", flush=True)': 'log(f"Error descargando archivo: {exc}")',
    'print(f"Archivo rechazado: {rejected}", flush=True)': 'log(f"Archivo rechazado: {rejected}")',
    'print(f"Torrent guardado: {target}", flush=True)': 'log(f"Torrent guardado: {target}")',
    'print("Bot Telegram iniciado.", flush=True)': 'log("Bot Telegram iniciado.")',
    'print(f"Torrents -> {TORRENT_DROP_DIR}", flush=True)': 'log(f"Torrents -> {TORRENT_DROP_DIR}")',
    'print(f"/juego -> {GAME_DOWNLOAD_DIR}", flush=True)': 'log(f"/juego -> {GAME_DOWNLOAD_DIR}")',
    'print(f"Descargas simultáneas -> {GAME_MAX_CONCURRENT}", flush=True)': 'log(f"Descargas simultáneas -> {GAME_MAX_CONCURRENT}")',
    'print(f"Cola persistente recuperada -> {recovered}", flush=True)': 'log(f"Cola persistente recuperada -> {recovered}")',
    'print(f"Error loop Telegram: {exc}", flush=True)': 'log(f"Error loop Telegram: {exc}")',
}
changed = 0
for old, new in replacements.items():
    if old in text:
        text = text.replace(old, new)
        changed += 1
BOT.write_text(text, encoding="utf-8")
print(f"OK telegram_torrent_bot.py: {changed} prints convertidos.")

print("\nListo. Ejecuta ahora:")
print("python3 -m py_compile state_db.py scripts/log-viewer.py scripts/telegram_torrent_bot.py")
print("git diff --check")
