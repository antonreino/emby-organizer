# 🧠 COMANDOS DEL SISTEMA – GUÍA COMPLETA ACTUALIZADA

---

# 🎬 1. EMBY (Automatización multimedia)

### 📊 Estado del sistema

```bash
embyStatus
```

---

### 📊 Dashboard completo

```bash
/bash /home/tone/Documentos/Agentes/emby-organizer/scripts/dashboard.sh
```

---

### 🔄 Refrescar Emby manualmente

```bash
curl -X POST "http://IP_EMBY:8096/emby/Library/Refresh?api_key=TU_API_KEY"
```

---

### 📡 Estado del watcher en LXC

```bash
systemctl status emby-watch-refresh.service
```

---

### ⚙️ Configuración

Copia `.env.example` a `.env` y configura las variables necesarias:

- `TMDB_API_KEY`: Clave de API de TMDb para metadatos de películas/series.
- `TELEGRAM_BOT_TOKEN`: Token del bot de Telegram para notificaciones.
- `TELEGRAM_CHAT_ID`: ID del chat de Telegram.
- `EMBY_API_KEY`: Clave de API de Emby.
- `EMBY_URL`: URL del servidor Emby.
- `INBOX_DIR`: Directorio donde se descargan los archivos (opcional, por defecto `/home/tone/Documentos/Torrent/Descargas`).
- Otras variables SFTP para conexión remota.

---

# 📦 2. SHIPMENT TRACKER (Seguimiento de paquetes)

## ➕ Añadir envío

### Automático (detecta carrier)

```bash
envio_add TRACKING
```

Ejemplo:

```bash
envio_add ES2504564636
```

---

### Manual (forzando carrier)

```bash
envio_add CARRIER TRACKING
```

Ejemplo:

```bash
envio_add correos_express 63806680081074701369605
```

---

## 📋 Listar envíos activos

```bash
envios
```

---

## 🔄 Actualizar estados

```bash
envios_check
```

Hace automáticamente:

```text
- Register en 17track
- Consulta estado
- Fallback email (Amazon / Correos / CTT)
- Detecta estados (Entregado, En reparto, Enviado)
- Notifica por Telegram
- Elimina entregados automáticamente
```

---

## 🧠 Comportamiento del sistema

```text
1. Intenta 17track
2. Si falla → fallback por email
3. Detecta estado real desde correos
4. Actualiza DB
5. Notifica
6. Limpia entregados
```

---

# 🤖 3. COMANDOS DESDE TELEGRAM (OpenClaw)

## 📦 Añadir envío

```text
/bash envio_add TRACKING
```

Ejemplo:

```text
/bash envio_add ES2504564636
```

---

## 📋 Ver envíos

```text
/bash envios
```

---

## 🔄 Actualizar estados

```text
/bash envios_check
```

---

# 🧠 4. DASHBOARD GLOBAL (EMBY + PAQUETES)

## 🚀 Comando principal

```text
/bash /home/tone/bin/status_telegram
```

---

## 📊 Qué hace

```text
🎬 Muestra estado de Emby
📦 Refresca tracking (17track + fallback)
📋 Lista envíos activos
⚠️ Muestra errores (429, etc.)
```

---

## 🛠️ Características técnicas

```text
✔ Script limpio (sin errores de bash)
✔ Rutas absolutas (compatibles con OpenClaw)
✔ Uso de timeout (evita bloqueos)
✔ Logs filtrados (salida limpia)
✔ Compatible con Telegram
```

---

# ⚠️ IMPORTANTE (BUENAS PRÁCTICAS)

```text
- No ejecutar /bash status muchas veces seguidas → evita 429
- 17track puede tardar en actualizar estados
- Amazon NO funciona con 17track → usa fallback email
- Correos/CTT a veces necesitan fallback
```

---

# 🚀 RESUMEN RÁPIDO

```text
📦 envios            → ver envíos
➕ envio_add         → añadir tracking
🔄 envios_check      → refrescar estados

🎬 embyStatus        → estado Emby

🧠 status_telegram   → dashboard completo
```

---

# 🧩 SISTEMA COMPLETO

```text
✔ Tracking multi-carrier automático
✔ 17track + fallback inteligente
✔ Detección automática de carrier
✔ Notificaciones Telegram
✔ Limpieza automática de entregados
✔ Integración OpenClaw
✔ Dashboard unificado
✔ Automatización Emby
```

---

👉 Esto ya es tu **asistente personal automatizado real** 😄
