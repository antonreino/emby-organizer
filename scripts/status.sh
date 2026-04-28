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

ORGANIZER_STATUS="$(systemctl --user is-active emby-organizer.service)"
TORRENT_STATUS="$(systemctl --user is-active openclaw-torrent-watch.service)"
EMBY_WATCH_STATUS="$(ssh -p "$EMBY_PORT" "$EMBY_HOST" "systemctl is-active emby-watch-refresh.service" 2>/dev/null)"

cat <<EOF
======================================
🎬 EMBY AUTOMATION DASHBOARD
======================================

🧠 Organizer local:
$ORGANIZER_STATUS

🧲 OpenClaw torrent watcher:
$TORRENT_STATUS

📺 Emby watcher LXC:
$EMBY_WATCH_STATUS
======================================
EOF
