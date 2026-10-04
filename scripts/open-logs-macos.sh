#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$HOME/.venvs/emby-organizer/bin/python"
PORT="${LOG_VIEWER_PORT:-8765}"
URL="http://127.0.0.1:${PORT}"
VIEWER_LOG="$HOME/Library/Logs/emby-log-viewer.log"
if [ -x "$VENV_PYTHON" ]; then PYTHON="$VENV_PYTHON"; else PYTHON="$(command -v python3)"; fi
if ! /usr/bin/curl -fsS "$URL/health" >/dev/null 2>&1; then
  nohup "$PYTHON" "$SCRIPT_DIR/log-viewer.py" --port "$PORT" >"$VIEWER_LOG" 2>&1 </dev/null &
  for _ in {1..20}; do
    if /usr/bin/curl -fsS "$URL/health" >/dev/null 2>&1; then break; fi
    sleep 0.1
  done
fi
open "$URL"
