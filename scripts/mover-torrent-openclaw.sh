#!/usr/bin/env bash
set -euo pipefail

INBOX="/home/tone/.openclaw/media/inbound"
DEST="/home/tone/Descargas"

mkdir -p "$DEST"

latest="$(find "$INBOX" -maxdepth 1 -type f -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"

if [ -z "${latest:-}" ]; then
  echo "No hay archivos recibidos."
  exit 1
fi

if ! file "$latest" | grep -qi "BitTorrent"; then
  echo "El archivo más reciente no parece un torrent: $latest"
  exit 1
fi

base="$(basename "$latest")"

if [[ "$base" != *.torrent ]]; then
  base="$base.torrent"
fi

target="$DEST/$base"

if [ -e "$target" ]; then
  target="$DEST/${base%.torrent}-$(date +%Y%m%d-%H%M%S).torrent"
fi

mv "$latest" "$target"
echo "Torrent movido a Descargas: $target"
