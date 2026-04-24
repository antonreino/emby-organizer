#!/bin/bash

case "$1" in
  torrent)
    journalctl --user -u emby-organizer.service -f -o cat
    ;;
  emby)
    ssh -t -p 2222 tonecas@192.168.1.177 "sudo journalctl -u emby-watch-refresh.service -f -o cat"
    ;;
  all)
    echo "=== ORGANIZER ==="
    journalctl --user -u emby-organizer.service -f -o cat &
    PID1=$!

    echo "=== EMBY ==="
    ssh -t -p 2222 tonecas@192.168.1.177 "sudo journalctl -u emby-watch-refresh.service -f -o cat" &
    PID2=$!

    wait $PID1 $PID2
    ;;
  *)
    echo "Uso: logs {torrent|emby|all}"
    ;;
esac
