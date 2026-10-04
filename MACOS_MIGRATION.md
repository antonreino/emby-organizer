# Instalación / migración a macOS

El proyecto ya no depende de una ruta fija. Puede estar en el disco interno o en un volumen externo.

## 1. Configurar

```bash
cp .env.example .env
```

Edita `.env`. En tu instalación actual puedes usar, por ejemplo:

```dotenv
INBOX_DIR=/Users/tuusuario/Documents/Torrent
TORRENT_DROP_DIR=/Users/tuusuario/Downloads
GAME_DOWNLOAD_DIR=/Volumes/Datos/Descargas
GAME_MAX_RETRIES=20
GAME_RETRY_DELAY=5
GAME_MAX_CONCURRENT=2
```

Añade también las credenciales reales de Telegram, TMDb y SFTP. `.env` está ignorado por Git.

## 2. Instalar servicios

Desde la raíz del proyecto:

```bash
chmod +x scripts/install-macos-services.sh scripts/status-macos.sh
./scripts/install-macos-services.sh
```

El instalador obtiene automáticamente `PROJECT_ROOT`, crea/reutiliza `~/.venvs/emby-organizer`, instala dependencias y genera los dos LaunchAgents con las rutas reales del equipo.

## 3. Telegram

```text
/ping
/help
/juego URL
/estado
```

- `.torrent` se guarda en `TORRENT_DROP_DIR`.
- `/juego` descarga en `GAME_DOWNLOAD_DIR`.
- Se detecta nombre/tamaño/reanudación cuando el servidor lo permite.
- `curl` negocia HTTP/2 o HTTP/1.1 automáticamente.
- Hay hasta `GAME_MAX_CONCURRENT` descargas simultáneas y cola para el resto.
- `/estado` muestra progreso y cola.

## 4. Comprobar

```bash
./scripts/status-macos.sh
```

Logs:

```bash
tail -f ~/Library/Logs/telegram-download-bot.out.log
tail -f ~/Library/Logs/telegram-download-bot.err.log
tail -f ~/Library/Logs/emby-organizer.out.log
tail -f ~/Library/Logs/emby-organizer.err.log
```
