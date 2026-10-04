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
- La cola de `/juego` se guarda en SQLite y se recupera automáticamente tras reinicios.
- `/estado` (también `/status` y `/descargas`) muestra descargas activas y cola.
- `/logs`, `/logs bot` y `/logs todos` permiten consultar los logs desde Telegram.
- Dashboard local para macOS con servicios, almacenamiento, historial, cola y logs mediante `scripts/open-logs-macos.sh`.
- Historial persistente en SQLite de subidas, cuarentenas, descargas y errores.
- El visor y el watcher de errores arrancan automáticamente mediante LaunchAgents.
- Los errores nuevos de Organizer y Telegram se notifican automáticamente por Telegram. El watcher detecta `ERROR`/`CRITICAL` del Organizer en `stdout` y también vigila `stderr` de ambos procesos.
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

El instalador detecta automáticamente la ubicación del repositorio, crea/reutiliza `~/.venvs/emby-organizer`, instala dependencias, genera los LaunchAgents con las rutas correctas y arranca los cuatro servicios: Organizer, bot de Telegram, dashboard y watcher de alertas.

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

Dashboard local en macOS:

```bash
chmod +x scripts/open-logs-macos.sh
./scripts/open-logs-macos.sh
```

Abre `http://127.0.0.1:8765` en el navegador. Muestra el estado de los cuatro servicios, espacio de almacenamiento, cola y descargas recientes, historial persistente y los cuatro logs. Tras ejecutar `install-macos-services.sh`, el dashboard queda arrancado automáticamente al iniciar sesión.

## Telegram

Comandos:

```text
/help
/ping
/juego https://servidor/archivo
/estado
/logs
/logs bot
/logs todos
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

### Cola persistente e historial

El estado se guarda por defecto en:

```text
~/.local/share/emby_organizer/state.sqlite3
```

SQLite conserva las descargas directas pendientes/activas y el historial de actividad. Si el bot o el Mac se reinician, las descargas con estado `queued` o `active` vuelven a la cola y `curl -C -` intenta reanudarlas cuando el servidor lo permite.

El historial registra, entre otros eventos:

- contenido subido correctamente a Emby;
- archivos enviados a `NoClasificado`;
- errores del Organizer;
- descargas directas añadidas, completadas o fallidas.

El dashboard nunca muestra la URL de una descarga directa; únicamente nombre, estado, tamaño e intentos.

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
| `TELEGRAM_LOG_LINES` | Líneas de log devueltas por Telegram (30 por defecto) |
| `LOG_ALERT_POLL_SECONDS` | Intervalo de comprobación de errores (2 s por defecto) |
| `LOG_ALERT_DEDUP_SECONDS` | Ventana de deduplicación de alertas iguales (300 s) |
| `LOG_ALERT_MAX_CHARS` | Máximo de caracteres enviados por alerta (3000) |
| `EMBY_STATE_DB` | Ruta opcional de la base SQLite; por defecto `~/.local/share/emby_organizer/state.sqlite3` |
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
├── state_db.py
├── requirements.txt
├── README.md
├── MACOS_MIGRATION.md
├── launchd/
│   ├── com.tone.emby-organizer.plist.template
│   ├── com.tone.telegram-download-bot.plist.template
│   ├── com.tone.emby-log-viewer.plist.template
│   └── com.tone.emby-log-alerts.plist.template
├── scripts/
│   ├── emby-watch-refresh.sh
│   ├── install-macos-services.sh
│   ├── log-viewer.py
│   ├── log-error-watcher.py
│   ├── open-logs-macos.sh
│   ├── status-macos.sh
│   └── telegram_torrent_bot.py
└── systemd/
    └── emby-watch-refresh.service
```
