# 🎬 Emby Organizer

Automatización personal para macOS que organiza contenido multimedia, lo envía por SFTP a un servidor Emby y gestiona descargas directas y archivos `.torrent` desde Telegram.

El proyecto incluye un dashboard web local con estado de servicios, progreso de descargas, almacenamiento local y remoto, historial persistente, estadísticas y logs en tiempo real.

## Funciones principales

### Organizer

- Vigila `INBOX_DIR` y procesa archivos cuando llevan el tiempo suficiente estables.
- Clasifica películas, series y anime.
- Normaliza títulos y nombres de episodios.
- Consulta TMDb de forma opcional para mejorar la clasificación.
- Sube el contenido al servidor Emby mediante SFTP.
- Elimina el archivo local después de una subida correcta.
- Envía archivos no clasificables a `NoClasificado`.
- Registra subidas, errores y cuarentenas en SQLite.
- Envía notificaciones por Telegram.
- Actualiza periódicamente el espacio disponible del servidor Emby y guarda el último dato válido en SQLite.

### Telegram

El bot acepta:

```text
/help
/ping
/juego URL
/estado
/status
/descargas
/logs
/logs bot
/logs todos
```

También acepta archivos `.torrent` enviados como documentos.

`/juego URL`:

- descarga mediante `curl`;
- soporta redirecciones;
- intenta reanudar descargas con `curl -C -`;
- realiza reintentos automáticos;
- admite varias descargas simultáneas;
- mantiene una cola persistente en SQLite;
- recupera descargas pendientes después de un reinicio;
- informa del progreso desde Telegram;
- nunca registra la URL firmada de la descarga en los logs.

### Dashboard

Disponible por defecto en:

```text
http://127.0.0.1:8765
```

Incluye:

- estado de Organizer, bot de Telegram, dashboard y watcher de alertas;
- resumen de las últimas 24 horas;
- GB descargados en las últimas 24 horas;
- GB movidos a Emby en las últimas 24 horas;
- cola y descargas recientes;
- porcentaje de progreso de cada descarga;
- almacenamiento local de descargas;
- almacenamiento del servidor Emby;
- historial reciente;
- logs de Organizer y Telegram;
- acceso directo al repositorio de GitHub;
- interfaz responsive y en castellano.

El selector de líneas permite mostrar:

```text
100
300
1000
```

líneas de log.

## Estadísticas

La pestaña **Estadísticas** muestra datos acumulados desde que se activó el historial SQLite:

- total descargado;
- total movido a Emby;
- total de datos gestionados;
- número de descargas completadas;
- número de archivos enviados a Emby;
- estadísticas de las últimas 24 horas;
- estadísticas de los últimos 7 días;
- estadísticas de los últimos 30 días;
- total histórico;
- desglose por biblioteca: Anime, Series y Películas.

Los valores históricos solo incluyen eventos registrados desde que existe la base SQLite. No se reconstruyen datos anteriores.

## Almacenamiento de Emby

El Organizer consulta periódicamente el espacio del servidor remoto usando la misma conexión SFTP utilizada para subir contenido.

El flujo es:

```text
Servidor Emby
     │
     │ SFTP
     ▼
Organizer
     │
     │ guarda snapshot
     ▼
SQLite
     │
     ▼
Dashboard
```

El dashboard no necesita conectarse directamente por SSH/SFTP al servidor Emby.

Esto permite:

- evitar conexiones remotas cada pocos segundos;
- reducir carga;
- evitar problemas de red de procesos `launchd`;
- conservar el último dato válido si Emby no responde temporalmente.

Por defecto, el Organizer actualiza el almacenamiento remoto cada:

```text
300 segundos
```

mediante:

```dotenv
EMBY_STORAGE_REFRESH_SECONDS=300
```

Si una actualización falla, el dashboard conserva el último dato correcto y lo marca como último valor válido.

## Persistencia SQLite

Por defecto:

```text
~/.local/share/emby_organizer/state.sqlite3
```

SQLite almacena:

- historial de actividad;
- descargas directas;
- cola persistente;
- estados de descargas;
- tamaño de archivos;
- errores;
- estadísticas;
- último estado conocido del almacenamiento Emby.

La base se ejecuta en modo WAL y utiliza `busy_timeout` para reducir problemas cuando Organizer, Telegram y Dashboard acceden simultáneamente.

## Flujo multimedia

```text
Telegram (.torrent)
        │
        ▼
TORRENT_DROP_DIR
        │
        ▼
qBittorrent
        │
        ▼
INBOX_DIR
        │
        ▼
Emby Organizer
        │
       SFTP
        ▼
Servidor Emby
```

Descarga directa:

```text
Telegram
  │
  └── /juego URL
          │
          ▼
        curl
          │
          ▼
GAME_DOWNLOAD_DIR
```

## Requisitos

- Python 3.10+
- macOS para los LaunchAgents incluidos
- `curl`
- `caffeinate`
- acceso SSH/SFTP al servidor Emby
- bot de Telegram
- TMDb opcional

Dependencias Python:

```text
paramiko
python-dotenv
requests
```

## Instalación en macOS

```bash
git clone https://github.com/antonreino/emby-organizer.git
cd emby-organizer

cp .env.example .env
```

Edita `.env` con tus datos reales.

Después:

```bash
chmod +x scripts/install-macos-services.sh
chmod +x scripts/status-macos.sh
chmod +x scripts/open-logs-macos.sh

./scripts/install-macos-services.sh
```

El instalador:

- crea o reutiliza `~/.venvs/emby-organizer`;
- instala las dependencias;
- genera los LaunchAgents;
- configura las rutas reales del repositorio;
- arranca los cuatro servicios.

## Servicios macOS

Se instalan cuatro LaunchAgents:

```text
com.tone.emby-organizer
com.tone.telegram-download-bot
com.tone.emby-log-viewer
com.tone.emby-log-alerts
```

Consultar estado:

```bash
./scripts/status-macos.sh
```

Reiniciar manualmente:

```bash
launchctl kickstart -k gui/$(id -u)/com.tone.emby-organizer
launchctl kickstart -k gui/$(id -u)/com.tone.telegram-download-bot
launchctl kickstart -k gui/$(id -u)/com.tone.emby-log-viewer
launchctl kickstart -k gui/$(id -u)/com.tone.emby-log-alerts
```

## Logs

```bash
tail -f ~/Library/Logs/emby-organizer.out.log
tail -f ~/Library/Logs/emby-organizer.err.log

tail -f ~/Library/Logs/telegram-download-bot.out.log
tail -f ~/Library/Logs/telegram-download-bot.err.log

tail -f ~/Library/Logs/emby-log-viewer.out.log
tail -f ~/Library/Logs/emby-log-viewer.err.log
```

El dashboard también muestra estos logs y permite seleccionar cuántas líneas visualizar.

## Variables principales

| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram |
| `TELEGRAM_CHAT_ID` | Chat autorizado |
| `TMDB_API_KEY` | API de TMDb opcional |
| `INBOX_DIR` | Carpeta vigilada por Organizer |
| `TORRENT_DROP_DIR` | Destino de `.torrent` recibidos |
| `GAME_DOWNLOAD_DIR` | Destino de `/juego` |
| `GAME_MAX_CONCURRENT` | Número máximo de descargas simultáneas |
| `GAME_MAX_RETRIES` | Reintentos máximos por descarga |
| `GAME_RETRY_DELAY` | Segundos entre reintentos |
| `TELEGRAM_LOG_LINES` | Líneas de logs enviadas por Telegram |
| `LOG_ALERT_POLL_SECONDS` | Intervalo del watcher de errores |
| `LOG_ALERT_DEDUP_SECONDS` | Ventana de deduplicación |
| `LOG_ALERT_MAX_CHARS` | Tamaño máximo de alertas |
| `EMBY_STATE_DB` | Ruta opcional de SQLite |
| `EMBY_STORAGE_REFRESH_SECONDS` | Intervalo de actualización del almacenamiento Emby |
| `EMBY_SFTP_ANIME_URL` | Biblioteca Anime por SFTP |
| `EMBY_SFTP_SERIES_URL` | Biblioteca Series por SFTP |
| `EMBY_SFTP_MOVIES_URL` | Biblioteca Películas por SFTP |
| `EMBY_SFTP_PASSWORD` | Contraseña SFTP opcional |
| `EMBY_URL` | URL local de Emby para el watcher |
| `EMBY_API_KEY` | API key de Emby |
| `EMBY_WATCH_DIR` | Directorio vigilado en el servidor |

Consulta `.env.example` para ver todos los valores disponibles.

## Seguridad

- `.env` está excluido de Git.
- Las bases SQLite están excluidas de Git.
- Los logs están excluidos de Git.
- Las descargas y archivos multimedia están excluidos.
- El bot solo responde al `TELEGRAM_CHAT_ID` configurado.
- Las URLs de descargas directas no se muestran en el dashboard.
- Las URLs firmadas no se escriben en los logs.
- Los secretos se redactan al enviar logs por Telegram.
- Los nombres de archivos recibidos se saneán antes de escribirlos.
- Se recomienda autenticación SFTP mediante clave SSH siempre que sea posible.

Nunca subas `.env` al repositorio.

## Watcher de Emby en Linux/LXC

El proyecto incluye:

```text
scripts/emby-watch-refresh.sh
systemd/emby-watch-refresh.service
```

Sirve para refrescar automáticamente la biblioteca de Emby cuando llegan nuevos archivos.

Ejemplo:

```bash
sudo cp scripts/emby-watch-refresh.sh /usr/local/bin/emby-watch-refresh.sh
sudo chmod +x /usr/local/bin/emby-watch-refresh.sh

sudo cp systemd/emby-watch-refresh.service /etc/systemd/system/
sudo nano /etc/emby-watch-refresh.env

sudo systemctl daemon-reload
sudo systemctl enable --now emby-watch-refresh.service
```

Configuración mínima:

```dotenv
EMBY_WATCH_DIR=/ruta/a/la/biblioteca
EMBY_URL=http://127.0.0.1:8096
EMBY_API_KEY=tu_api_key
```

## Estructura

```text
emby-organizer/
├── .env.example
├── .gitignore
├── LICENSE
├── MACOS_MIGRATION.md
├── README.md
├── emby_organizer.py
├── requirements.txt
├── state_db.py
├── launchd/
│   ├── com.tone.emby-log-alerts.plist.template
│   ├── com.tone.emby-log-viewer.plist.template
│   ├── com.tone.emby-organizer.plist.template
│   └── com.tone.telegram-download-bot.plist.template
├── scripts/
│   ├── emby-watch-refresh.sh
│   ├── install-macos-services.sh
│   ├── log-error-watcher.py
│   ├── log-viewer.py
│   ├── open-logs-macos.sh
│   ├── status-macos.sh
│   └── telegram_torrent_bot.py
└── systemd/
    └── emby-watch-refresh.service
```

## Comprobación rápida

Validar sintaxis:

```bash
python3 -m py_compile \
  state_db.py \
  emby_organizer.py \
  scripts/log-viewer.py \
  scripts/telegram_torrent_bot.py
```

Comprobar espacios o errores de diff:

```bash
git diff --check
```

Abrir dashboard:

```bash
http://127.0.0.1:8765
```

## Licencia

Consulta `LICENSE`.
