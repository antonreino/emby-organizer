# 🎬 Emby Organizer

Proyecto completo de automatización para gestionar descargas,
clasificarlas y subirlas automáticamente a Emby.

## 🚀 Características

-   Integración con OpenClaw + Telegram
-   Clasificación automática (series, anime, películas)
-   TMDb fallback inteligente
-   Subida SFTP automática
-   Refresh automático de Emby
-   Notificaciones Telegram
-   Dashboard en terminal
-   Limpieza y cuarentena

## 📁 Estructura

emby-organizer/ ├── emby_organizer.py ├── scripts/ ├── systemd/ ├──
README.md └── .gitignore

## ▶️ Uso

python3 emby_organizer.py --daemon

## 📊 Logs

logsTorrent torrent logsTorrent emby embyDash

## 🔐 Seguridad

Usar variables de entorno para: - TMDB_API_KEY - TELEGRAM_BOT_TOKEN -
TELEGRAM_CHAT_ID

## 🧠 Flujo

Telegram → OpenClaw → Torrent → Organizer → SFTP → Emby → Refresh

------------------------------------------------------------------------

🚀 Automatización completa de tu biblioteca multimedia.
