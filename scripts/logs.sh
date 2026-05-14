#!/bin/bash

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

case "$1" in
  torrent)
    journalctl --user -u emby-organizer.service -f -o cat
    ;;
  emby)
    ssh -t -p "$EMBY_PORT" "$EMBY_HOST" "sudo journalctl -u emby-watch-refresh.service -f -o cat"
    ;;
  all)
    echo "=== ORGANIZER ==="
    journalctl --user -u emby-organizer.service -f -o cat &
    PID1=$!

    echo "=== EMBY ==="
    ssh -t -p "$EMBY_PORT" "$EMBY_HOST" "sudo journalctl -u emby-watch-refresh.service -f -o cat" &
    PID2=$!

    wait $PID1 $PID2
    ;;
  *)
    echo "Uso: logs {torrent|emby|all}"
    ;;
esac
