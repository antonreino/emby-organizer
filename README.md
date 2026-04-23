# 🎬 Emby Organizer

![Emby Organizer Banner](https://github.com/antonreino/emby-organizer)

## 📌 Descripción

**Emby Organizer** es un agente automatizado que gestiona descargas de contenido multimedia y las organiza directamente en tu servidor Emby.

El sistema detecta archivos descargados (series, anime y películas), los clasifica, los renombra correctamente y los sube mediante SFTP a las bibliotecas correspondientes en Emby.

Además, limpia automáticamente las carpetas de descarga y gestiona errores mediante un sistema de cuarentena.

---

## 🚀 Características principales

- 📥 Monitorización automática de descargas
- 🧠 Clasificación inteligente (series, anime, películas)
- 🏷️ Renombrado automático (formato Emby: `S01E05.mkv`)
- 📤 Subida automática vía SFTP
- 🧹 Limpieza de carpetas tras procesar archivos
- 🚫 Sistema de cuarentena para archivos no reconocidos
- 🔐 Autenticación por clave SSH (sin contraseñas)
- 🔄 Ejecución como servicio (daemon con systemd)

---

## 📁 Estructura del flujo

```text
Torrent Download Folder
        ↓
Emby Organizer
        ↓
Clasificación + Renombrado
        ↓
Subida SFTP
        ↓
Servidor Emby
```

---

## ⚙️ Configuración

### 📍 Carpeta de entrada

```bash
/home/tone/Documentos/Torrent/Descargas
```

### 📚 Bibliotecas Emby

```python
LIBRARIES = {
    "anime": "sftp://tonecas@192.168.1.177:2222/media/Peliculas/Biblioteca/Anime",
    "series": "sftp://tonecas@192.168.1.177:2222/media/Peliculas/Biblioteca/Series",
    "movies": "sftp://tonecas@192.168.1.177:2222/media/Peliculas/Biblioteca/Peliculas",
}
```

---

## 🔐 Configuración SSH (recomendado)

Generar clave:

```bash
ssh-keygen -t ed25519
```

Copiar al servidor:

```bash
ssh-copy-id -p 2222 tonecas@192.168.1.177
```

---

## ▶️ Uso

### Ejecutar una vez

```bash
python3 emby_organizer.py --scan-once --verbose
```

### Modo daemon (continuo)

```bash
python3 emby_organizer.py --daemon
```

### Simulación (dry-run)

```bash
python3 emby_organizer.py --scan-once --dry-run --verbose
```

---

## 🧹 Limpieza automática

Después de subir un archivo:

- Se elimina el archivo local
- Se elimina la carpeta contenedora si queda vacía

---

## ⚠️ Cuarentena

Los archivos que no se pueden clasificar se mueven a:

```bash
/home/tone/Documentos/Torrent/Descargas/NoClasificado
```

---

## 🧠 Lógica de clasificación

### Series / Anime

Detecta formatos como:

- `S01E05`
- `1x05`
- `Cap.105` → interpretado como `S01E05`

### Películas

Basado en:

- Año (ej: 2023)
- Palabras clave (movie, film...)

---

## 🧾 Logs

Ubicación:

```bash
~/.local/share/emby_organizer/organizer.log
```

---

## 🔧 Servicio systemd (user)

Ejemplo de servicio:

```ini
[Unit]
Description=Emby Organizer

[Service]
ExecStart=/usr/bin/python3 /home/tone/Documentos/Agentes/emby-organizer/emby_organizer.py --daemon
Restart=always

[Install]
WantedBy=default.target
```

Activar:

```bash
systemctl --user enable emby-organizer
systemctl --user start emby-organizer
```

---

## 🔮 Próximas mejoras

- 📲 Integración con Telegram (OpenClaw)
- 🔔 Notificaciones de subida
- 🎯 Reprocesado automático de errores
- 📊 Dashboard de actividad

---

## 👨‍💻 Autor

Proyecto desarrollado para automatizar flujos multimedia en entornos self-hosted con Emby + Proxmox.

---

## ⭐ Licencia

Uso personal / privado

---

## 💡 Nota

Este proyecto está optimizado para entornos locales (homelab) y pensado para integrarse con herramientas como:

- qBittorrent
- Emby
- Proxmox
- OpenClaw (futuro)

---

🚀 *Automatiza tu biblioteca multimedia sin tocar nada.*
