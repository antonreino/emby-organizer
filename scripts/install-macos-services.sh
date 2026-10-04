#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
ENV_FILE="$PROJECT_ROOT/.env"
VENV_DIR="$HOME/.venvs/emby-organizer"
PYTHON="$VENV_DIR/bin/python"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Falta $ENV_FILE"
  echo "   Copia .env.example a .env y rellena tus credenciales."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

INBOX_DIR="${INBOX_DIR:-$HOME/Documents/Torrent}"
TORRENT_DROP_DIR="${TORRENT_DROP_DIR:-$HOME/Downloads}"
GAME_DOWNLOAD_DIR="${GAME_DOWNLOAD_DIR:-$HOME/Downloads/Games}"

mkdir -p "$LAUNCH_AGENTS" "$HOME/Library/Logs" "$INBOX_DIR" "$TORRENT_DROP_DIR" "$GAME_DOWNLOAD_DIR" "$(dirname "$VENV_DIR")"

if [ ! -x "$PYTHON" ]; then
  echo "📦 Creando entorno virtual..."
  /usr/bin/python3 -m venv "$VENV_DIR"
fi

"$PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"

render_plist() {
  local template="$1"
  local output="$2"

  /usr/bin/python3 - "$template" "$output" "$PROJECT_ROOT" "$HOME" "$PYTHON" <<'PY2'
from pathlib import Path
import sys

src, dst, project, home, python = sys.argv[1:]

text = Path(src).read_text(encoding="utf-8")
text = (
    text
    .replace("__PROJECT_ROOT__", project)
    .replace("__HOME__", home)
    .replace("__PYTHON__", python)
)

Path(dst).write_text(text, encoding="utf-8")
PY2
}

render_plist "$PROJECT_ROOT/launchd/com.tone.emby-organizer.plist.template" \
  "$LAUNCH_AGENTS/com.tone.emby-organizer.plist"
render_plist "$PROJECT_ROOT/launchd/com.tone.telegram-download-bot.plist.template" \
  "$LAUNCH_AGENTS/com.tone.telegram-download-bot.plist"

for label in com.tone.emby-organizer com.tone.telegram-download-bot; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
done

launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/com.tone.emby-organizer.plist"
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/com.tone.telegram-download-bot.plist"

echo "✅ Servicios instalados y arrancados."
echo "   Organizer: launchctl print gui/$(id -u)/com.tone.emby-organizer"
echo "   Telegram:  launchctl print gui/$(id -u)/com.tone.telegram-download-bot"
