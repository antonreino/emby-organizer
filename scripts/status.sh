#!/usr/bin/env bash

PROJECT_ROOT="/home/tone/Documentos/Agentes/emby-organizer"
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

EMBY_HOST="${EMBY_HOST:?EMBY_HOST is required}"
EMBY_PORT="${EMBY_PORT:?EMBY_PORT is required}"

ORGANIZER_STATUS="$(systemctl --user is-active emby-organizer.service)"
TORRENT_STATUS="$(systemctl --user is-active openclaw-torrent-watch.service)"
EMBY_WATCHER_STATUS="$(ssh -p "$EMBY_PORT" "$EMBY_HOST" "systemctl is-active emby-watch-refresh.service" 2>/dev/null || echo unknown)"

echo "======================================"
echo "🎬 EMBY AUTOMATION DASHBOARD"
echo "======================================"
echo
echo "🧠 Organizer local:"
echo "$ORGANIZER_STATUS"
echo
echo "🧲 OpenClaw torrent watcher:"
echo "$TORRENT_STATUS"
echo
echo "📺 Emby watcher LXC:"
echo "$EMBY_WATCHER_STATUS"
echo "======================================"
