#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${EMBY_ORGANIZER_ENV_FILE:-$PROJECT_ROOT/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

WATCH_DIR="${EMBY_WATCH_DIR:-/media/Peliculas/Biblioteca/}"
EMBY_URL="${EMBY_URL:?EMBY_URL is required}"
EMBY_API_KEY="${EMBY_API_KEY:?EMBY_API_KEY is required}"
COOLDOWN=180 #tiempo sin eventos antes de refrescar
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_TOKEN:-}}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:?TELEGRAM_CHAT_ID is required}"

log() {
  echo "[$(date '+%F %T')] $*"
}

refresh_emby() {
  LAST_REFRESH_FILE="/tmp/emby-watch-last-refresh"
  MIN_REFRESH_INTERVAL=300

  now="$(date +%s)"
  last="$(cat "$LAST_REFRESH_FILE" 2>/dev/null || echo 0)"

  if [ $((now - last)) -lt "$MIN_REFRESH_INTERVAL" ]; then
    log "Refresh ignorado: ya se hizo uno hace menos de ${MIN_REFRESH_INTERVAL}s"
    return
  fi

  echo "$now" > "$LAST_REFRESH_FILE"

  log "Lanzando refresh de Emby..."
  curl -fsS -X POST \
    "${EMBY_URL}/Library/Refresh?api_key=${EMBY_API_KEY}" >/dev/null

  log "Refresh enviado a Emby"

  if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=📺 Emby actualizado
🎬 Nuevo contenido añadido" >/dev/null
  fi
}

last_event_time=0

inotifywait -m -r \
  -e close_write -e moved_to -e delete -e moved_from -e create \
  --format '%e|%w%f' \
  "$WATCH_DIR" | while IFS='|' read -r event file; do

  if [[ "$file" == *"/.Trash-"* ]] || [[ "$file" == *"/.Trash/"* ]]; then
    continue
  fi

  should_refresh=false

  # Si es carpeta, también refrescamos
  if [[ "$event" == *"ISDIR"* ]]; then
    log "Evento de carpeta detectado: $event -> $file"
    should_refresh=true
  fi

  # Si es vídeo, refrescamos
  case "${file,,}" in
    *.mkv|*.avi|*.mp4|*.m4v|*.ts)
      log "Evento de vídeo detectado: $event -> $file"
      should_refresh=true
      ;;
  esac

  if [ "$should_refresh" != true ]; then
    continue
  fi

  last_event_time=$(date +%s)

  (
    current_event_time=$last_event_time
    sleep "$COOLDOWN"

    if [ "$current_event_time" -eq "$last_event_time" ]; then
      refresh_emby
    else
      log "Eventos recientes detectados, se cancela refresh"
    fi
  ) &
done
