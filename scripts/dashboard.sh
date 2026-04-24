#!/usr/bin/env bash

EMBY_HOST="tonecas@192.168.1.177"
EMBY_PORT="2222"

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
