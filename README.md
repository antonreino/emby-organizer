# 🎬 Emby Organizer

Automatización personal para organizar películas, series y anime, moverlos por SFTP a una biblioteca Emby y gestionar descargas desde Telegram.

## Funciones

- Vigila `INBOX_DIR` y espera a que los archivos sean estables antes de procesarlos.
- Clasifica películas, series y anime y normaliza sus nombres.
- Consulta TMDb de forma opcional para mejorar metadatos.
- Sube el contenido a las bibliotecas remotas mediante SFTP.
- Envía notificaciones por Telegram.
- Recibe archivos `.torrent` por Telegram.
- `/juego URL` realiza descargas directas con `curl`, reanudación y reintentos.
- Hasta `GAME_MAX_CONCURRENT` descargas directas simultáneas; el resto queda en cola.
- `/estado` (también `/status` y `/descargas`) muestra descargas activas y cola.
- Incluye LaunchAgents para macOS y un watcher systemd opcional para refrescar Emby en Linux/LXC.

## Requisitos

- Python 3.10+
- `curl` y, en macOS, `caffeinate`
- Acceso SSH/SFTP al servidor de Emby
- Bot de Telegram para las funciones de Telegram
- TMDb opcional

## Instalación en macOS

```bash
git clone https://github.com/antonreino/emby-organizer.git
cd emby-organizer
cp .env.example .env
# Edita .env con tus datos reales
chmod +x scripts/install-macos-services.sh scripts/status-macos.sh
./scripts/install-macos-services.sh
```

El instalador detecta automáticamente la ubicación del repositorio, crea/reutiliza `~/.venvs/emby-organizer`, instala dependencias, genera los LaunchAgents con las rutas correctas y arranca ambos servicios.

Consulta el estado con:

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

## Telegram

Comandos:

```text
/help
/ping
/juego https://servidor/archivo
/estado
```

Los `.torrent` pueden enviarse directamente como documentos. El bot solo acepta el chat configurado mediante `TELEGRAM_CHAT_ID`; si falta esa variable, no arranca.

Flujo multimedia:

```text
Telegram (.torrent) -> TORRENT_DROP_DIR -> qBittorrent -> INBOX_DIR
                                              |
                                              v
                                      Emby Organizer -> SFTP -> Emby
```

Descarga directa:

```text
/juego URL -> curl -> GAME_DOWNLOAD_DIR
```

El bot intenta obtener `Content-Disposition`, tamaño y soporte de rangos. No fuerza HTTP/1.1: deja que `curl` negocie el protocolo con el servidor.

## Variables principales

| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot |
| `TELEGRAM_CHAT_ID` | Único chat autorizado |
| `TMDB_API_KEY` | Metadatos opcionales |
| `INBOX_DIR` | Carpeta procesada por el organizador |
| `TORRENT_DROP_DIR` | Destino de `.torrent` recibidos |
| `GAME_DOWNLOAD_DIR` | Descargas de `/juego` |
| `GAME_MAX_CONCURRENT` | Descargas simultáneas (2 por defecto) |
| `GAME_MAX_RETRIES` | Reintentos por descarga |
| `EMBY_SFTP_*_URL` | Destinos SFTP por biblioteca |
| `EMBY_SFTP_PASSWORD` | Opcional; se recomienda clave SSH |

Consulta `.env.example` para la lista completa. Nunca subas `.env` al repositorio.

## Watcher de Emby en Linux/LXC

El repositorio conserva `scripts/emby-watch-refresh.sh` y `systemd/emby-watch-refresh.service` para refrescar la biblioteca cuando llegan archivos al servidor.

Instalación de ejemplo en el servidor Emby:

```bash
sudo cp scripts/emby-watch-refresh.sh /usr/local/bin/emby-watch-refresh.sh
sudo chmod +x /usr/local/bin/emby-watch-refresh.sh
sudo cp systemd/emby-watch-refresh.service /etc/systemd/system/
sudo nano /etc/emby-watch-refresh.env
sudo systemctl daemon-reload
sudo systemctl enable --now emby-watch-refresh.service
```

`/etc/emby-watch-refresh.env` debe contener, al menos:

```dotenv
EMBY_WATCH_DIR=/ruta/a/la/biblioteca
EMBY_URL=http://127.0.0.1:8096
EMBY_API_KEY=tu_api_key
```

## Seguridad

- `.env`, bases de datos, logs, cachés, entornos virtuales y descargas están ignorados por Git.
- El bot de Telegram funciona en modo *fail closed*: requiere `TELEGRAM_CHAT_ID`.
- Los nombres recibidos se saneán antes de escribir archivos.
- Se recomienda autenticación SFTP mediante clave SSH.
- No se incluyen credenciales reales en el repositorio.

## Estructura

```text
emby-organizer/
├── .env.example
├── .gitignore
├── emby_organizer.py
├── requirements.txt
├── README.md
├── MACOS_MIGRATION.md
├── launchd/
│   ├── com.tone.emby-organizer.plist.template
│   └── com.tone.telegram-download-bot.plist.template
├── scripts/
│   ├── emby-watch-refresh.sh
│   ├── install-macos-services.sh
│   ├── status-macos.sh
│   └── telegram_torrent_bot.py
└── systemd/
    └── emby-watch-refresh.service
```
