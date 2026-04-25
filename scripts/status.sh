#!/usr/bin/env bash

EMBY_HOST="tonecas@192.168.1.177"
EMBY_PORT="2222"

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
