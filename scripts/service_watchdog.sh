#!/bin/bash

ENV_FILE="/home/tone/Documentos/Agentes/emby-organizer/.env"
STATE_DIR="/home/tone/.cache/openclaw-watchdog"
mkdir -p "$STATE_DIR"

source "$ENV_FILE"

send_telegram() {
  local msg="$1"
  echo "$msg"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    --data-urlencode text="$msg" >/dev/null
}

check_local_service() {
  local service="$1"
  local label="$2"
  local down_file="$STATE_DIR/${service}.down"
  local restart_file="$STATE_DIR/${service}.restart_attempted"

  if systemctl --user is-active --quiet "$service"; then
    if [ -f "$down_file" ]; then
      rm -f "$down_file" "$restart_file"
      send_telegram "✅ Servicio recuperado: ${label}"
    fi
    return
  fi

  if [ ! -f "$down_file" ]; then
    touch "$down_file"
    send_telegram "🚨 Servicio caído: ${label}"
  fi

  if [ ! -f "$restart_file" ]; then
    touch "$restart_file"
    send_telegram "🔁 Intentando reiniciar: ${label}"

    systemctl --user restart "$service"

    sleep 5

    if systemctl --user is-active --quiet "$service"; then
      rm -f "$down_file" "$restart_file"
      send_telegram "✅ Servicio reiniciado correctamente: ${label}"
    else
      send_telegram "❌ No se pudo reiniciar: ${label}. No lo reintentaré hasta que cambie el estado."
    fi
  fi
}

check_lxc_service() {
  local service="emby-watch-refresh.service"
  local label="Emby watcher LXC"
  local host="tonecas@192.168.1.177"
  local port="2222"

  local down_file="$STATE_DIR/emby-watch-refresh-lxc.down"
  local restart_file="$STATE_DIR/emby-watch-refresh-lxc.restart_attempted"
  local unreachable_file="$STATE_DIR/emby-lxc.unreachable"

  ssh -p "$port" -o BatchMode=yes -o ConnectTimeout=10 "$host" "true" >/dev/null 2>&1
  if [ $? -ne 0 ]; then
    if [ ! -f "$unreachable_file" ]; then
      touch "$unreachable_file"
      send_telegram "🚨 No puedo conectar con el servidor Emby LXC. Posible caída o timeout."
    fi
    return
  fi

  if [ -f "$unreachable_file" ]; then
    rm -f "$unreachable_file"
    send_telegram "✅ Conexión recuperada con Emby LXC"
  fi

  ssh -p "$port" -o BatchMode=yes -o ConnectTimeout=10 "$host" "systemctl is-active --quiet $service"
  if [ $? -eq 0 ]; then
    if [ -f "$down_file" ]; then
      rm -f "$down_file" "$restart_file"
      send_telegram "✅ Servicio recuperado: ${label}"
    fi
    return
  fi

  if [ ! -f "$down_file" ]; then
    touch "$down_file"
    send_telegram "🚨 Servicio caído: ${label}"
  fi

  if [ ! -f "$restart_file" ]; then
    touch "$restart_file"
    send_telegram "🔁 Intentando reiniciar: ${label}"

    ssh -p "$port" -o BatchMode=yes -o ConnectTimeout=10 "$host" "sudo -n systemctl restart $service"

    sleep 5

    ssh -p "$port" -o BatchMode=yes -o ConnectTimeout=10 "$host" "systemctl is-active --quiet $service"
    if [ $? -eq 0 ]; then
      rm -f "$down_file" "$restart_file"
      send_telegram "✅ Servicio reiniciado correctamente: ${label}"
    else
      send_telegram "❌ No se pudo reiniciar: ${label}. No lo reintentaré hasta que cambie el estado."
    fi
  fi
}

check_local_service "emby-organizer.service" "Emby Organizer local"
check_local_service "openclaw-torrent-watch.service" "OpenClaw torrent watcher"
check_lxc_service
