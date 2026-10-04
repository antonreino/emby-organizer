#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
UID_NOW="$(id -u)"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

INBOX_DIR="${INBOX_DIR:-$HOME/Documents/Torrent}"
TORRENT_DROP_DIR="${TORRENT_DROP_DIR:-$HOME/Downloads}"
GAME_DOWNLOAD_DIR="${GAME_DOWNLOAD_DIR:-$HOME/Downloads/Games}"

service_status() {
  local label="$1"
  local output

  if ! output="$(launchctl print "gui/${UID_NOW}/${label}" 2>/dev/null)"; then
    echo "❌ no cargado"
    return
  fi

  if printf '%s\n' "$output" | grep -Eq '^[[:space:]]*(job )?state = running$'; then
    echo "✅ ejecutándose"
  else
    local job_state
    job_state="$(printf '%s\n' "$output" | awk -F'= ' '/^[[:space:]]*job state = / {print $2; exit}')"
    if [ -z "$job_state" ]; then
      job_state="cargado pero no ejecutándose"
    fi
    echo "⚠️ ${job_state}"
  fi
}

echo "======================================"
echo "🎬 EMBY AUTOMATION - MAC"
echo "======================================"
echo

echo "🧠 Organizer:"
service_status "com.tone.emby-organizer"

echo
echo "🤖 Telegram descargas:"
service_status "com.tone.telegram-download-bot"

echo
echo "🖥️ Dashboard:"
service_status "com.tone.emby-log-viewer"

echo
echo "🚨 Alertas de errores:"
service_status "com.tone.emby-log-alerts"

echo
echo "📁 Media: $INBOX_DIR"
echo "🧲 .torrent: $TORRENT_DROP_DIR"
echo "🎮 /juego: $GAME_DOWNLOAD_DIR"
