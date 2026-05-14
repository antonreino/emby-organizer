#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${EMBY_ORGANIZER_ENV_FILE:-$PROJECT_ROOT/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

EMBY_HOST="${EMBY_HOST:?EMBY_HOST is required}"
EMBY_PORT="${EMBY_PORT:?EMBY_PORT is required}"

clear

echo "======================================"
echo "🎬 EMBY AUTOMATION DASHBOARD"
echo "======================================"
echo ""

echo "🧠 Organizer local:"
systemctl --user is-active emby-organizer.service

echo ""
echo "🧲 OpenClaw torrent watcher:"
systemctl --user is-active openclaw-torrent-watch.service

echo ""
echo "📺 Emby watcher LXC:"
ssh -p "$EMBY_PORT" "$EMBY_HOST" "systemctl is-active emby-watch-refresh.service"

echo ""
echo "======================================"
echo "📡 Logs en vivo"
echo "Ctrl+C para salir"
echo "======================================"
echo ""

(
  journalctl --user -u openclaw-torrent-watch.service -f -o cat | sed 's/^/[TORRENT] /'
) &

PID1=$!

(
  journalctl --user -u emby-organizer.service -f -o cat | sed 's/^/[ORGANIZER] /'
) &

PID2=$!

(
  ssh -tt -p "$EMBY_PORT" "$EMBY_HOST" "sudo journalctl -u emby-watch-refresh.service -f -o cat" | sed 's/^/[EMBY] /'
) &

PID3=$!

trap "kill $PID1 $PID2 $PID3 2>/dev/null; exit" INT TERM

wait
