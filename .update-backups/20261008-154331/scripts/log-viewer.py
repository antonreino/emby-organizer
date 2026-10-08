#!/usr/bin/env python3
import argparse
import base64
import hmac
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
from state_db import (
    dashboard_statistics,
    dashboard_summary,
    emby_storage_snapshot,
    emby_system_snapshot,
    add_history,
    init_db,
    queue_download_request,
    recent_downloads,
    recent_history,
)
from torrent_utils import save_torrent_bytes

load_dotenv(APP_DIR / ".env")

LOG_DIR = Path.home() / "Library" / "Logs"
GAME_DOWNLOAD_DIR = Path(os.getenv("GAME_DOWNLOAD_DIR") or "/Volumes/Datos/Descargas").expanduser()
TORRENT_DROP_DIR = Path(os.getenv("TORRENT_DROP_DIR") or str(Path.home() / "Downloads")).expanduser()
TORRENT_UPLOAD_MAX_BYTES = int(os.getenv("TORRENT_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))
DASHBOARD_BIND = (os.getenv("DASHBOARD_BIND") or "127.0.0.1").strip()
DASHBOARD_USER = (os.getenv("DASHBOARD_USER") or "").strip()
DASHBOARD_PASSWORD = (os.getenv("DASHBOARD_PASSWORD") or "").strip()
PRICE_BOT_DIR = Path(os.getenv("PRICE_BOT_DIR") or str(APP_DIR.parent / "ps5-price-bot")).expanduser()
PRICE_BOT_DB = PRICE_BOT_DIR / "data" / "prices.sqlite3"
PRICE_BOT_LOG = PRICE_BOT_DIR / "logs" / "bot.log"
PRICE_BOT_CONFIG = PRICE_BOT_DIR / "config.json"
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
_DOWNLOAD_SPEED_SAMPLES = {}
_DOWNLOAD_SPEED_LOCK = threading.Lock()
_NET_SAMPLE = None
_METRICS_CACHE = {"at": 0.0, "value": None}
LOGS = {
    "organizer_out": LOG_DIR / "emby-organizer.out.log",
    "organizer_err": LOG_DIR / "emby-organizer.err.log",
    "telegram_out": LOG_DIR / "telegram-download-bot.out.log",
    "telegram_err": LOG_DIR / "telegram-download-bot.err.log",
}
SERVICES = {
    "organizer": "com.tone.emby-organizer",
    "telegram": "com.tone.telegram-download-bot",
    "viewer": "com.tone.emby-log-viewer",
    "alerts": "com.tone.emby-log-alerts",
}

LOG_TS_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2})(?:,\d+)?(?P<rest>.*)$")

HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Emby Automation · Dashboard</title>
<style>
:root{
  color-scheme: dark;
  --bg:#07111f;
  --panel:rgba(13,22,40,.82);
  --border:rgba(255,255,255,.08);
  --text:#eef4ff;
  --muted:#9db0ce;
  --accent:#6ea8ff;
  --accent-2:#8f7cff;
  --ok:#30d158;
  --warn:#ffb340;
  --bad:#ff5d73;
  --cyan:#49d6ff;
  --shadow:0 18px 60px rgba(0,0,0,.28);
  --radius:20px;
}
*{box-sizing:border-box}
html,body{min-height:100%}
body{
  margin:0;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;
  color:var(--text);
  background:
    radial-gradient(circle at top left, rgba(110,168,255,.18), transparent 28%),
    radial-gradient(circle at top right, rgba(143,124,255,.16), transparent 24%),
    radial-gradient(circle at bottom, rgba(73,214,255,.08), transparent 30%),
    linear-gradient(180deg, #050b16 0%, var(--bg) 52%, #050b16 100%);
}
body::before{
  content:"";
  position:fixed; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px);
  background-size:26px 26px;
  mask-image:linear-gradient(180deg, rgba(0,0,0,.5), transparent 88%);
  pointer-events:none;
}
.app{
  width:min(1500px, calc(100% - 32px));
  margin:26px auto 38px;
  position:relative;
  z-index:1;
}
.hero{
  display:flex;
  justify-content:space-between;
  gap:20px;
  align-items:flex-start;
  padding:28px;
  margin-bottom:18px;
  border:1px solid var(--border);
  border-radius:28px;
  background:linear-gradient(140deg, rgba(17,27,48,.96), rgba(8,16,30,.92));
  box-shadow:var(--shadow);
  backdrop-filter:blur(18px);
}
.eyebrow{
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding:8px 12px;
  border-radius:999px;
  background:rgba(110,168,255,.12);
  border:1px solid rgba(110,168,255,.2);
  color:#cfe1ff;
  font-size:12px;
  letter-spacing:.08em;
  text-transform:uppercase;
  font-weight:700;
}
.hero h1{
  margin:14px 0 8px;
  font-size:38px;
  line-height:1.05;
  letter-spacing:-.03em;
}
.hero p{
  margin:0;
  color:var(--muted);
  font-size:15px;
  max-width:640px;
}
.hero__side{
  width:min(430px, 100%);
  min-width:430px;
  display:grid;
  gap:12px;
}
.status-badge{
  display:flex;
  justify-content:space-between;
  gap:10px;
  align-items:center;
  padding:14px 16px;
  border-radius:18px;
  border:1px solid var(--border);
  background:rgba(255,255,255,.04);
}
.status-badge strong{font-size:15px}
.status-badge span{font-size:13px;color:var(--muted)}
.status-badge #updated{
  display:inline-block;
  min-width:190px;
  text-align:right;
  white-space:nowrap;
  font-variant-numeric:tabular-nums;
  font-feature-settings:"tnum" 1;
}
.controls{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}
.select-wrap,.button{
  display:inline-flex;align-items:center;gap:10px;min-height:48px;padding:0 16px;border-radius:16px;
  border:1px solid var(--border);background:rgba(255,255,255,.05);color:var(--text);font:inherit;
}
.select-wrap{
  color:var(--muted);
  position:relative;
  padding-right:38px;
  cursor:pointer;
  border-color:rgba(110,168,255,.28);
  background:rgba(110,168,255,.08);
}
.select-wrap::after{
  content:"⌄";
  position:absolute;
  right:14px;
  top:50%;
  transform:translateY(-54%);
  color:#dbe8ff;
  font-size:18px;
  font-weight:800;
  pointer-events:none;
}
.select-wrap:hover{
  background:rgba(110,168,255,.13);
  border-color:rgba(110,168,255,.42);
}
select{appearance:none;border:0;background:transparent;color:var(--text);font:inherit;outline:none;cursor:pointer;padding-right:8px}
.button{
  cursor:pointer;color:white;font-weight:700;background:linear-gradient(135deg, var(--accent), var(--accent-2));
  box-shadow:0 10px 22px rgba(110,168,255,.25);
}
.button:hover{filter:brightness(1.05)}
.github-link{
  display:inline-flex;
  align-items:center;
  gap:9px;
  min-height:48px;
  padding:0 16px;
  border-radius:16px;
  border:1px solid var(--border);
  background:rgba(255,255,255,.05);
  color:var(--text);
  font-weight:700;
  text-decoration:none;
  transition:background .18s ease, transform .18s ease, border-color .18s ease;
}
.github-link:hover{
  background:rgba(255,255,255,.09);
  border-color:rgba(255,255,255,.14);
  transform:translateY(-1px);
}
.github-link svg{
  width:19px;
  height:19px;
  fill:currentColor;
  flex:none;
}
.section-title{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0;font-size:16px;letter-spacing:-.01em}
.tabs{
  display:flex;
  gap:8px;
  margin:0 0 18px;
  padding:6px;
  width:max-content;
  border:1px solid var(--border);
  border-radius:16px;
  background:rgba(13,22,40,.72);
  box-shadow:var(--shadow);
  backdrop-filter:blur(14px);
}
.tab{
  border:0;
  border-radius:11px;
  padding:10px 16px;
  background:transparent;
  color:var(--muted);
  font:inherit;
  font-weight:700;
  cursor:pointer;
}
.tab:hover{color:var(--text);background:rgba(255,255,255,.04)}
.tab.active{
  color:#fff;
  background:linear-gradient(135deg,rgba(110,168,255,.28),rgba(143,124,255,.28));
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.08);
}
.view{display:none}
.view.active{display:block}
.stats-grid{
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:14px;
  margin-bottom:18px;
}
.stat-big{
  font-size:32px;
  font-weight:800;
  letter-spacing:-.04em;
  margin-top:10px;
}
.stat-sub{margin-top:8px;color:var(--muted);font-size:12px}

.section-title small{color:var(--muted);font-weight:500;font-size:12px}
.services{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}
.service-card,.metric-card,.panel{
  border:1px solid var(--border);border-radius:var(--radius);background:var(--panel);backdrop-filter:blur(14px);box-shadow:var(--shadow);
}
.service-card{padding:18px;position:relative;overflow:hidden}
.service-card::after{
  content:"";position:absolute;inset:auto -20% -40% auto;width:150px;height:150px;border-radius:50%;
  background:radial-gradient(circle, rgba(110,168,255,.20), transparent 68%);pointer-events:none;
}
.service-card__name{color:var(--muted);font-size:13px;margin-bottom:14px}
.service-card__state{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:700}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block;box-shadow:0 0 14px currentColor}
.ok{color:var(--ok)}
.warn{color:var(--warn)}
.bad{color:var(--bad)}
.muted{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-bottom:18px}
.metric-card{padding:18px;position:relative;overflow:hidden}
.metric-card::before{
  content:"";position:absolute;inset:0 auto auto 0;width:100%;height:2px;
  background:linear-gradient(90deg, var(--accent), var(--accent-2), var(--cyan));opacity:.85;
}
.metric-card__label{color:var(--muted);font-size:13px}
.metric-card__value{margin-top:12px;font-size:34px;font-weight:800;letter-spacing:-.04em}
.metric-card__hint{margin-top:8px;color:var(--muted);font-size:12px}
.layout{display:grid;grid-template-columns:1.15fr .85fr;gap:18px;margin-bottom:18px}
.panel{overflow:hidden}
.panel__head{
  display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px;
  border-bottom:1px solid rgba(255,255,255,.06);background:linear-gradient(180deg, rgba(255,255,255,.03), transparent);
}
.panel__body{padding:0}
.panel__body.pad{padding:20px}
.storage-grid{display:grid;gap:16px}
.storage-chip{
  padding:16px;border-radius:18px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06);
}
.storage-chip strong{display:block;margin-bottom:8px;font-size:14px}
.storage-bar{height:10px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:14px}
.storage-bar__fill{height:100%;border-radius:999px;background:linear-gradient(90deg, var(--accent), var(--cyan))}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{
  text-align:left;padding:13px 16px;color:var(--muted);font-size:12px;letter-spacing:.04em;
  text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,.06);
}
tbody td{padding:14px 16px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}
tbody tr:hover{background:rgba(255,255,255,.025)}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pill{
  display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:700;
  text-transform:uppercase;letter-spacing:.04em;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.06);
}
.pill.ok{background:rgba(48,209,88,.12);color:#b8ffca;border-color:rgba(48,209,88,.22)}
.pill.warn{background:rgba(255,179,64,.12);color:#ffe2aa;border-color:rgba(255,179,64,.24)}
.pill.bad{background:rgba(255,93,115,.12);color:#ffc1cb;border-color:rgba(255,93,115,.24)}
.progress{min-width:180px}
.progress-track{height:8px;border-radius:999px;background:rgba(255,255,255,.09);overflow:hidden;margin-bottom:6px}
.progress-fill{
  height:100%;border-radius:999px;background:linear-gradient(90deg, var(--accent), var(--cyan));box-shadow:0 0 18px rgba(73,214,255,.32);
}
.progress-label{font-size:11px;color:var(--muted);white-space:nowrap}
.logs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.log-panel pre{
  margin:0;padding:18px 20px 20px;min-height:240px;max-height:42vh;overflow:auto;white-space:pre-wrap;word-break:break-word;
  font:12px/1.58 ui-monospace,SFMono-Regular,Menlo,monospace;color:#dbe7ff;background:linear-gradient(180deg, rgba(6,10,18,.58), rgba(5,9,17,.92));
}
.log-panel.error pre{color:#ffd7dd}
.log-panel pre::-webkit-scrollbar{width:10px;height:10px}
.log-panel pre::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:999px}
.empty{padding:28px 20px;color:var(--muted)}
.deal-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.deal-card{display:flex;flex-direction:column;gap:10px;min-height:210px;padding:18px;border-radius:18px;border:1px solid rgba(255,255,255,.07);background:linear-gradient(145deg,rgba(255,255,255,.055),rgba(255,255,255,.025))}
.deal-card__top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.deal-card__family{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:#cfe1ff}
.deal-card__price{font-size:28px;font-weight:850;letter-spacing:-.04em}
.deal-card__title{font-size:14px;font-weight:700;line-height:1.35}
.deal-card__meta{font-size:12px;color:var(--muted);line-height:1.55}
.deal-card__link{margin-top:auto;display:inline-flex;width:max-content;text-decoration:none;color:#d9e8ff;font-size:12px;font-weight:800}
.deal-card__link:hover{text-decoration:underline}
.deal-status{font-size:12px;color:var(--muted)}
.download-form{display:flex;gap:10px;align-items:center;padding:16px 18px;border-bottom:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.025)}
.download-form input{flex:1;min-width:0;height:44px;border-radius:12px;border:1px solid var(--border);background:rgba(0,0,0,.18);color:var(--text);padding:0 14px;font:inherit;outline:none}
.download-form input:focus{border-color:rgba(110,168,255,.55);box-shadow:0 0 0 3px rgba(110,168,255,.10)}
.download-form button{height:44px;border:0;border-radius:12px;padding:0 16px;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:white;font:inherit;font-weight:800;cursor:pointer}
.download-form__status{padding:0 18px 12px;font-size:12px;color:var(--muted);min-height:18px}
.torrent-form{display:flex;gap:10px;align-items:center;padding:16px 18px;border-bottom:1px solid rgba(255,255,255,.06);background:rgba(73,214,255,.025)}
.torrent-form input[type=file]{flex:1;min-width:0;color:var(--muted);font:inherit}
.torrent-form input[type=file]::file-selector-button{margin-right:12px;height:40px;border:1px solid var(--border);border-radius:11px;padding:0 14px;background:rgba(255,255,255,.06);color:var(--text);font:inherit;font-weight:700;cursor:pointer}
.torrent-form button{height:44px;border:0;border-radius:12px;padding:0 16px;background:linear-gradient(135deg,var(--cyan),var(--accent));color:#04101d;font:inherit;font-weight:850;cursor:pointer}
.torrent-form__status{padding:0 18px 12px;font-size:12px;color:var(--muted);min-height:18px}
.system-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin-bottom:18px}
.system-card{padding:16px;border-radius:var(--radius);border:1px solid var(--border);background:var(--panel);box-shadow:var(--shadow)}
.system-card__label{color:var(--muted);font-size:12px}
.system-card__value{margin-top:8px;font-size:23px;font-weight:800;letter-spacing:-.03em}
.system-card__hint{margin-top:6px;color:var(--muted);font-size:11px;line-height:1.35}
.host-layout{display:grid;grid-template-columns:1.15fr .85fr;gap:18px;margin-bottom:18px}
.host-panel{border:1px solid var(--border);border-radius:var(--radius);background:var(--panel);box-shadow:var(--shadow);overflow:hidden}
.host-panel__head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 18px;border-bottom:1px solid rgba(255,255,255,.06)}
.host-panel__title{font-size:15px;font-weight:800}
.host-panel__sub{font-size:11px;color:var(--muted);margin-top:3px}
.host-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:16px}
.host-metric{padding:14px;border-radius:16px;border:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.025)}
.host-metric__label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.host-metric__value{font-size:21px;font-weight:800;margin-top:7px;letter-spacing:-.03em}
.host-metric__hint{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.35}
.host-storage{display:grid;gap:12px;padding:16px}
.host-storage .storage-chip{margin:0}
.host-note{padding:0 16px 16px;color:var(--muted);font-size:11px;line-height:1.45}
@media (max-width:1220px){.system-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.host-layout{grid-template-columns:1fr}}
@media (max-width:720px){.download-form,.torrent-form{flex-direction:column;align-items:stretch}.system-grid{grid-template-columns:1fr}}
@media (max-width:1220px){
  .services,.metrics,.stats-grid,.deal-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .layout,.logs{grid-template-columns:1fr}
  .hero{flex-direction:column}
  .hero__side{width:100%}
  .controls{justify-content:flex-start}
}
@media (max-width:720px){
  .app{width:min(100% - 18px, 1500px);margin:14px auto 28px}
  .hero{padding:20px}
  .hero h1{font-size:30px}
  .services,.metrics,.stats-grid,.deal-grid{grid-template-columns:1fr}
  thead{display:none}
  table,tbody,tr,td{display:block;width:100%}
  tbody tr{padding:10px 0}
  tbody td{display:flex;justify-content:space-between;gap:16px;padding:9px 16px}
  tbody td::before{
    content:attr(data-label);color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em;
  }
}
</style>
</head>
<body>
<div class="app">
  <header class="hero">
    <div class="hero__main">
      <div class="eyebrow">Emby Automation · Dashboard</div>
      <h1>Control total, limpio y moderno</h1>
      <p>Estado de servicios, descargas, historial y logs en tiempo real, con una interfaz más actual y cómoda para usar desde el Mac.</p>
    </div>
    <div class="hero__side">
      <div class="status-badge">
        <div>
          <strong>Estado del panel</strong><br>
          <span>Actualización automática cada 3 segundos</span>
        </div>
        <span id="updated">Cargando…</span>
      </div>
      <div class="controls">
        <a class="github-link"
           href="https://github.com/antonreino/emby-organizer"
           target="_blank"
           rel="noopener noreferrer"
           title="Abrir repositorio en GitHub"
           aria-label="Abrir repositorio emby-organizer en GitHub">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 .7a11.3 11.3 0 0 0-3.57 22c.57.1.78-.24.78-.55v-2.16c-3.18.69-3.85-1.35-3.85-1.35-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.68 1.25 3.34.96.1-.74.4-1.25.73-1.54-2.54-.29-5.21-1.27-5.21-5.65 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.46.11-3.03 0 0 .96-.31 3.12 1.17A10.85 10.85 0 0 1 12 5.91c.97 0 1.94.13 2.85.38 2.16-1.48 3.11-1.17 3.11-1.17.63 1.57.24 2.74.12 3.03.74.8 1.18 1.82 1.18 3.07 0 4.39-2.68 5.35-5.23 5.64.41.36.78 1.05.78 2.12v3.17c0 .31.2.66.79.55A11.3 11.3 0 0 0 12 .7Z"/>
          </svg>
          GitHub
        </a>
        <label class="select-wrap">Líneas de log
          <select id="lines">
            <option>100</option>
            <option selected>300</option>
            <option>1000</option>
          </select>
        </label>
        <button class="button" onclick="refreshAll()">Actualizar ahora</button>
      </div>
    </div>
  </header>


  <nav class="tabs" aria-label="Secciones del dashboard">
    <button class="tab active" data-view="inicio">Inicio</button>
    <button class="tab" data-view="estadisticas">Estadísticas</button>
    <button class="tab" data-view="chollos">Chollos</button>
  </nav>

  <div id="view-inicio" class="view active">
  <section class="services" id="services"></section>

  <section class="metrics">
    <div class="metric-card">
      <div class="metric-card__label">Procesados · 24 h</div>
      <div class="metric-card__value" id="hcount">0</div>
      <div class="metric-card__hint">Total de eventos recientes registrados</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label">Correctos · 24 h</div>
      <div class="metric-card__value" id="hsuccess">0</div>
      <div class="metric-card__hint">Eventos finalizados correctamente</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label">Errores · 24 h</div>
      <div class="metric-card__value" id="herrors">0</div>
      <div class="metric-card__hint">Fallos detectados en el último día</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label">Descargados · 24 h</div>
      <div class="metric-card__value" id="hdownloadbytes">0 B</div>
      <div class="metric-card__hint">Descargas directas completadas</div>
    </div>
    <div class="metric-card">
      <div class="metric-card__label">Movidos a Emby · 24 h</div>
      <div class="metric-card__value" id="hmovedbytes">0 B</div>
      <div class="metric-card__hint">Contenido enviado a las bibliotecas Emby</div>
    </div>
  </section>

  <section class="host-layout" aria-label="Estado de equipos">
    <section class="host-panel">
      <div class="host-panel__head">
        <div>
          <div class="host-panel__title">🖥️ Mac mini</div>
          <div class="host-panel__sub">Sistema local · Apple Silicon</div>
        </div>
      </div>
      <div class="host-metrics">
        <div class="host-metric">
          <div class="host-metric__label">CPU</div>
          <div class="host-metric__value" id="sysCpu">—</div>
          <div class="host-metric__hint">Uso total</div>
        </div>
        <div class="host-metric">
          <div class="host-metric__label">GPU</div>
          <div class="host-metric__value" id="sysGpu">—</div>
          <div class="host-metric__hint" id="sysGpuHint">Apple Silicon</div>
        </div>
        <div class="host-metric">
          <div class="host-metric__label">Memoria</div>
          <div class="host-metric__value" id="sysRam">—</div>
          <div class="host-metric__hint" id="sysRamHint">Memoria unificada</div>
        </div>
        <div class="host-metric">
          <div class="host-metric__label">Temperatura</div>
          <div class="host-metric__value" id="sysTemp">—</div>
          <div class="host-metric__hint" id="sysTempHint">Sensor térmico</div>
        </div>
        <div class="host-metric" style="grid-column:1/-1">
          <div class="host-metric__label">Red</div>
          <div class="host-metric__value" id="sysNet">—</div>
          <div class="host-metric__hint">Recepción y envío en tiempo real</div>
        </div>
      </div>
      <div class="host-storage" id="macStorage"></div>
      <div class="host-note" id="memoryNote"></div>
    </section>

    <section class="host-panel">
      <div class="host-panel__head">
        <div>
          <div class="host-panel__title">🗄️ Servidor Emby</div>
          <div class="host-panel__sub">Sistema Linux remoto · métricas vía SSH</div>
        </div>
      </div>
      <div class="host-metrics">
        <div class="host-metric">
          <div class="host-metric__label">CPU</div>
          <div class="host-metric__value" id="embyCpu">—</div>
          <div class="host-metric__hint">Uso total del servidor</div>
        </div>
        <div class="host-metric">
          <div class="host-metric__label">RAM</div>
          <div class="host-metric__value" id="embyRam">—</div>
          <div class="host-metric__hint" id="embyRamHint">Memoria del servidor</div>
        </div>
        <div class="host-metric" style="grid-column:1/-1">
          <div class="host-metric__label">Carga</div>
          <div class="host-metric__value" id="embyLoad">—</div>
          <div class="host-metric__hint" id="embySystemHint">1 · 5 · 15 minutos</div>
        </div>
      </div>
      <div class="host-storage" id="serverStorage"></div>
    </section>
  </section>

  <div class="layout">
    <section class="panel">
      <div class="panel__head">
        <h2 class="section-title">📥 Cola y descargas recientes <small>Estado y progreso en vivo</small></h2>
      </div>
      <form class="download-form" id="downloadForm">
        <input id="downloadUrl" type="url" autocomplete="off" placeholder="Pega aquí la URL directa del juego…" required>
        <button type="submit">Descargar</button>
      </form>
      <div class="download-form__status" id="downloadFormStatus"></div>
      <form class="torrent-form" id="torrentForm">
        <input id="torrentFile" type="file" accept=".torrent,application/x-bittorrent" required>
        <button type="submit">Añadir torrent</button>
      </form>
      <div class="torrent-form__status" id="torrentFormStatus">Se guardará en la misma carpeta que los torrents recibidos por Telegram.</div>
      <div class="panel__body" id="downloads"></div>
    </section>

    <section class="panel">
      <div class="panel__head">
        <h2 class="section-title">ℹ️ Estado de descarga <small>Detalles útiles</small></h2>
      </div>
      <div class="panel__body pad">
        <div class="muted" style="line-height:1.7">
          Las descargas directas usan el disco <strong style="color:var(--text)">Datos</strong>.
          El tiempo restante se calcula con la velocidad observada y puede fluctuar durante los primeros segundos.
          Telegram seguirá notificando inicio, reintentos, finalización y errores.
        </div>
      </div>
    </section>
  </div>

  <section class="panel" style="margin-bottom:18px;">
    <div class="panel__head">
      <h2 class="section-title">🕘 Historial reciente <small>Últimos eventos del sistema</small></h2>
      </div>
    <div class="panel__body" id="history"></div>
  </section>

  <section class="logs">
    <section class="panel log-panel">
      <div class="panel__head">
        <h2 class="section-title">Organizer <small>Salida estándar</small></h2>
      </div>
      <pre id="organizer_out"></pre>
    </section>

    <section class="panel log-panel error">
      <div class="panel__head">
        <h2 class="section-title">Organizer · stderr <small>Errores y trazas</small></h2>
      </div>
      <pre id="organizer_err"></pre>
    </section>

    <section class="panel log-panel">
      <div class="panel__head">
        <h2 class="section-title">Telegram bot <small>Actividad del bot</small></h2>
      </div>
      <pre id="telegram_out"></pre>
    </section>

    <section class="panel log-panel error">
      <div class="panel__head">
        <h2 class="section-title">Telegram · stderr <small>Errores del bot</small></h2>
      </div>
      <pre id="telegram_err"></pre>
    </section>
  </section>

  </div>

  <div id="view-estadisticas" class="view">
    <section class="stats-grid">
      <div class="metric-card">
        <div class="metric-card__label">Descargado · histórico</div>
        <div class="stat-big" id="statDownloaded">0 B</div>
        <div class="stat-sub" id="statDownloadCount">0 descargas completadas</div>
      </div>
      <div class="metric-card">
        <div class="metric-card__label">Movido a Emby · histórico</div>
        <div class="stat-big" id="statMoved">0 B</div>
        <div class="stat-sub" id="statMovedCount">0 archivos enviados</div>
      </div>
      <div class="metric-card">
        <div class="metric-card__label">Datos gestionados · histórico</div>
        <div class="stat-big" id="statTotal">0 B</div>
        <div class="stat-sub">Descargas + transferencias a Emby</div>
      </div>
      <div class="metric-card">
        <div class="metric-card__label">Historial disponible desde</div>
        <div class="stat-big" id="statSince" style="font-size:22px">—</div>
        <div class="stat-sub">Los totales empiezan cuando se activó SQLite</div>
      </div>
    </section>

    <div class="layout">
      <section class="panel">
        <div class="panel__head">
          <h2 class="section-title">📊 Datos por periodo <small>Descargado frente a movido</small></h2>
        </div>
        <div class="panel__body" id="periodStats"></div>
      </section>
      <section class="panel">
        <div class="panel__head">
          <h2 class="section-title">🎬 Bibliotecas Emby <small>Histórico por categoría</small></h2>
        </div>
        <div class="panel__body" id="categoryStats"></div>
      </section>
    </div>
  </div>

  <div id="view-chollos" class="view">
    <div class="panel__head" style="margin-bottom:12px;">
      <h2 class="section-title">🔥 Ofertas <small>datos del bot de precios</small></h2>
      <span class="deal-status" id="dealStatus">Cargando…</span>
    </div>
    <div class="layout" style="margin-bottom:18px;">
      <section class="panel">
        <div class="panel__head"><h2 class="section-title">🎮 PS5 <small>ofertas activas</small></h2></div>
        <div class="panel__body pad"><div class="deal-grid" id="activeDealsPs5"></div></div>
      </section>
      <section class="panel">
        <div class="panel__head"><h2 class="section-title">🗡️ Switch Zelda <small>ofertas activas</small></h2></div>
        <div class="panel__body pad"><div class="deal-grid" id="activeDealsSwitch"></div></div>
      </section>
    </div>
    <div class="layout">
      <section class="panel">
        <div class="panel__head"><h2 class="section-title">🧾 Historial <small>Avisos publicados</small></h2></div>
        <div class="panel__body" id="dealHistory"></div>
      </section>
      <section class="panel">
        <div class="panel__head"><h2 class="section-title">🛰 Eventos técnicos <small>Errores y recuperaciones</small></h2></div>
        <div class="panel__body" id="dealEvents"></div>
      </section>
    </div>
    <section class="panel log-panel">
      <div class="panel__head"><h2 class="section-title">🛍 Bot de precios · log <small>PS5 + Switch 2</small></h2></div>
      <pre id="dealLog">(cargando)</pre>
    </section>
  </div>
</div>

<script>
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
function size(n){if(n==null)return "—";let v=Number(n),u=["B","KB","MB","GB","TB"],i=0;while(v>=1000&&i<u.length-1){v/=1000;i++}return `${v.toFixed(i?1:0)} ${u[i]}`}
function serviceLabel(k){return {organizer:"Organizer",telegram:"Telegram bot",viewer:"Dashboard",alerts:"Alertas"}[k]||k}
function serviceTone(running,state){if(running)return "ok";const s=String(state||"").toLowerCase();if(s.includes("loaded")||s.includes("cargado")||s.includes("exited"))return "warn";return "bad"}
function statusTone(status){const s=String(status||"").toLowerCase();if(["completed","success","done","ok"].includes(s))return "ok";if(["queued","pending","active","running","processing","quarantined"].includes(s))return "warn";return "bad"}
function categoryLabel(category){
  const labels={anime:"Anime",series:"Series",movies:"Películas"};
  return labels[String(category||"").toLowerCase()]||category||"Sin categoría";
}
function statusLabel(status){
  const s=String(status||"").toLowerCase();
  const labels={
    queued:"En cola",
    active:"Descargando",
    completed:"Completada",
    failed:"Fallida",
    success:"Correcto",
    error:"Error",
    pending:"Pendiente",
    running:"En curso",
    processing:"Procesando",
    done:"Completada",
    ok:"Correcto",
    cancelled:"Cancelada",
    canceled:"Cancelada",
    paused:"Pausada",
    quarantined:"Cuarentena",
  };
  return labels[s]||status||"—";
}
function duration(seconds){
  if(seconds==null||!isFinite(Number(seconds))||Number(seconds)<0)return "—";
  let s=Math.round(Number(seconds)),h=Math.floor(s/3600);s%=3600;let m=Math.floor(s/60);s%=60;
  if(h)return `${h} h ${m} min`;
  if(m)return `${m} min ${s} s`;
  return `${s} s`;
}
function progress(r){
  if(r.progress_percent==null)return '<span class="muted">—</span>';
  const p=Math.max(0,Math.min(100,Number(r.progress_percent)));
  const active=String(r.status).toLowerCase()==='active';
  const speed=r.speed_bps!=null&&active?` · ${size(r.speed_bps)}/s`:'';
  const eta=r.eta_seconds!=null&&active?` · quedan ~${duration(r.eta_seconds)}`:'';
  return `<div class="progress"><div class="progress-track"><div class="progress-fill" style="width:${p}%"></div></div><div class="progress-label">${p.toFixed(1)}% · ${size(r.downloaded_bytes)} / ${size(r.size_bytes)}${speed}${eta}</div></div>`;
}
function table(rows, cols){
  if(!rows.length)return '<div class="empty">Sin datos todavía.</div>';
  const head=`<thead><tr>${cols.map(c=>`<th>${esc(c[0])}</th>`).join("")}</tr></thead>`;
  const body=`<tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td data-label="${esc(c[0])}">${c[1](r)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  return `<table>${head}${body}</table>`;
}
function embyStorageMeta(emby){
  if(!emby.updated_at)return 'Sin fecha de lectura';
  const d=new Date(emby.updated_at);
  const when=isNaN(d)?String(emby.updated_at):d.toLocaleString('es-ES');
  return `${emby.stale?'Último dato válido':'Última lectura'} · ${when}`;
}
function formatHistoryDate(value){
  if(!value)return "—";
  const d=new Date(value);
  if(isNaN(d))return esc(String(value).replace("T"," ").replace("+00:00"," UTC"));
  return esc(d.toLocaleString("es-ES"));
}
async function loadDashboard(){
  const r=await fetch('/api/dashboard',{cache:'no-store'});
  const d=await r.json();

  document.getElementById('services').innerHTML=Object.entries(d.services).map(([k,v])=>{
    const tone=serviceTone(v.running,v.state);
    const label=v.running?'Operativo':(v.state||'parado');
    return `<div class="service-card">
      <div class="service-card__name">${esc(serviceLabel(k))}</div>
      <div class="service-card__state ${tone}"><span class="dot"></span>${esc(label)}</div>
      <div class="muted" style="margin-top:10px;font-size:12px">${v.running?'Servicio en ejecución':'Estado detectado: '+esc(v.state||'desconocido')}</div>
    </div>`;
  }).join('');

  const h=d.summary.history_24h;
  document.getElementById('hcount').textContent=h.count;
  document.getElementById('hsuccess').textContent=h.success;
  document.getElementById('herrors').textContent=h.errors;
  document.getElementById('hdownloadbytes').textContent=size(h.downloaded_bytes);document.getElementById('hmovedbytes').textContent=size(h.moved_bytes);

  document.getElementById('downloads').innerHTML=table(d.downloads,[
    ['ID',r=>'<span class="mono">#'+r.id+'</span>'],
    ['Nombre',r=>esc(r.name)],
    ['Estado',r=>`<span class="pill ${statusTone(r.status)}">${esc(statusLabel(r.status))}</span>`],
    ['Progreso',r=>progress(r)],
    ['Tamaño',r=>size(r.size_bytes)],
    ['Intento',r=>esc(r.attempt||0)]
  ]);

  document.getElementById('history').innerHTML=table(d.history,[
    ['Fecha',r=>formatHistoryDate(r.created_at)],
    ['Tipo',r=>esc(r.kind)],
    ['Estado',r=>`<span class="pill ${statusTone(r.status)}">${esc(statusLabel(r.status))}</span>`],
    ['Título',r=>esc(r.title||'—')],
    ['Categoría',r=>esc(r.category||'—')],
    ['Detalle',r=>esc(r.details||'—')]
  ]);

  const total=Number(d.disk.total||0), free=Number(d.disk.free||0), used=Math.max(0,total-free);
  const usedPct=total>0 ? Math.min(100,(used*100/total)) : 0;
  const internal=d.internal_disk||{};
  const iTotal=Number(internal.total||0),iFree=Number(internal.free||0),iUsed=Math.max(0,iTotal-iFree);
  const iPct=iTotal>0?Math.min(100,iUsed*100/iTotal):0;
  const sys=d.system||{};
  document.getElementById('sysCpu').textContent=sys.cpu_percent!=null?`${Number(sys.cpu_percent).toFixed(1)}%`:'—';
  document.getElementById('sysGpu').textContent=sys.gpu_percent!=null?`${Number(sys.gpu_percent).toFixed(1)}%`:'N/D';
  document.getElementById('sysGpuHint').textContent=sys.gpu_percent!=null?'Residencia activa GPU':(sys.powermetrics_note||'GPU no accesible');
  document.getElementById('sysRam').textContent=sys.ram_percent!=null?`${Number(sys.ram_percent).toFixed(1)}%`:'—';
  const pressure=sys.memory_free_percent!=null?` · ${Number(sys.memory_free_percent).toFixed(0)}% libre por memory_pressure`:'';
  const swap=sys.swap_used?` · swap ${size(sys.swap_used)}`:'';
  document.getElementById('sysRamHint').textContent=sys.ram_used!=null?`${size(sys.ram_used)} de ${size(sys.ram_total)}${pressure}${swap}`:'Memoria unificada';
  document.getElementById('sysTemp').textContent=sys.temperature_c!=null?`${Number(sys.temperature_c).toFixed(1)} °C`:(sys.thermal_state||'N/D');
  document.getElementById('sysTempHint').textContent=
    sys.cpu_temperature_c!=null||sys.gpu_temperature_c!=null
      ? `CPU ${sys.cpu_temperature_c!=null?Number(sys.cpu_temperature_c).toFixed(1)+' °C':'—'} · GPU ${sys.gpu_temperature_c!=null?Number(sys.gpu_temperature_c).toFixed(1)+' °C':'—'}`
      : (sys.thermal_state?`Presión térmica: ${sys.thermal_state}`:(sys.powermetrics_note||'Sensor no accesible'));
  document.getElementById('sysNet').textContent=`↓ ${size(sys.net_rx_bps||0)}/s · ↑ ${size(sys.net_tx_bps||0)}/s`;
  document.getElementById('memoryNote').textContent=sys.memory_free_percent!=null
    ? `macOS utiliza RAM libre como caché. Que el porcentaje ocupado sea alto no implica por sí solo falta de memoria; fíjate también en memory_pressure y en el uso de swap.`
    : `macOS utiliza RAM libre como caché, por lo que un porcentaje ocupado alto no implica necesariamente falta de memoria.`;
  const embySystem=d.emby_system||{};
  document.getElementById('embyCpu').textContent=embySystem.cpu_percent!=null?`${Number(embySystem.cpu_percent).toFixed(1)}%`:'—';
  document.getElementById('embyRam').textContent=embySystem.ram_percent!=null?`${Number(embySystem.ram_percent).toFixed(1)}%`:'—';
  document.getElementById('embyRamHint').textContent=embySystem.ram_used!=null?`${size(embySystem.ram_used)} de ${size(embySystem.ram_total)}`:(embySystem.error||'Sin lectura');
  document.getElementById('embyLoad').textContent=embySystem.load_1!=null?`${Number(embySystem.load_1).toFixed(2)} · ${Number(embySystem.load_5).toFixed(2)} · ${Number(embySystem.load_15).toFixed(2)}`:'—';
  document.getElementById('embySystemHint').textContent=embySystem.updated_at?`${embySystem.stale?'Último dato válido':'Última lectura'} · ${new Date(embySystem.updated_at).toLocaleString('es-ES')}`:(embySystem.error||'1 · 5 · 15 minutos');
  const emby=d.emby_disk||{};
  let embyHtml='';
  if(emby.available){
    const eTotal=Number(emby.total||0),eFree=Number(emby.free||0),eUsed=Number(emby.used||0);
    const ePct=eTotal>0?Math.min(100,eUsed*100/eTotal):0;
    embyHtml=`<div class="storage-chip">
      <strong>Servidor Emby</strong>
      <div>${size(eFree)} libres de ${size(eTotal)}</div>
      <div class="storage-bar"><div class="storage-bar__fill" style="width:${ePct}%"></div></div>
      <div class="muted" style="margin-top:10px;font-size:12px">${ePct.toFixed(1)}% usado · ${size(eUsed)} ocupados</div>
      <div class="muted" style="margin-top:6px;font-size:12px">${esc(embyStorageMeta(emby))}</div>
      ${emby.stale&&emby.last_error?`<div class="warn" style="margin-top:6px;font-size:12px">Última actualización fallida: ${esc(emby.last_error)}</div>`:''}
    </div>`;
  }else{
    embyHtml=`<div class="storage-chip">
      <strong>Servidor Emby</strong>
      <div class="warn">No se pudo consultar el espacio remoto</div>
      <div class="muted" style="margin-top:8px;font-size:12px">${esc(emby.error||'Sin información')}</div>
    </div>`;
  }
  document.getElementById('macStorage').innerHTML=`
    <div class="storage-chip">
      <strong>Disco interno · macOS</strong>
      <div class="mono">${esc(internal.path||'/')}</div>
      <div style="margin-top:8px">${size(iFree)} libres de ${size(iTotal)}</div>
      <div class="storage-bar"><div class="storage-bar__fill" style="width:${iPct}%"></div></div>
      <div class="muted" style="margin-top:10px;font-size:12px">${iPct.toFixed(1)}% usado · ${size(iUsed)} ocupados</div>
    </div>
    <div class="storage-chip">
      <strong>Disco Datos · descargas</strong>
      <div class="mono">${esc(d.disk.path)}</div>
      <div style="margin-top:8px">${size(free)} libres de ${size(total)}</div>
      <div class="storage-bar"><div class="storage-bar__fill" style="width:${usedPct}%"></div></div>
      <div class="muted" style="margin-top:10px;font-size:12px">${usedPct.toFixed(1)}% usado · ${size(used)} ocupados</div>
    </div>`;

  document.getElementById('serverStorage').innerHTML=embyHtml;


  const st=d.statistics||{};
  document.getElementById('statDownloaded').textContent=size(st.downloaded_bytes||0);
  document.getElementById('statMoved').textContent=size(st.moved_bytes||0);
  document.getElementById('statTotal').textContent=size(st.total_bytes||0);
  document.getElementById('statDownloadCount').textContent=`${st.download_count||0} descargas completadas`;
  document.getElementById('statMovedCount').textContent=`${st.moved_count||0} archivos enviados`;
  document.getElementById('statSince').textContent=st.first_event?new Date(st.first_event).toLocaleDateString('es-ES'):'—';

  document.getElementById('periodStats').innerHTML=table(st.periods||[],[
    ['Periodo',r=>esc(r.label)],
    ['Descargado',r=>size(r.downloaded_bytes)],
    ['Movido a Emby',r=>size(r.moved_bytes)],
    ['Descargas',r=>esc(r.download_count)],
    ['Archivos Emby',r=>esc(r.moved_count)]
  ]);

  document.getElementById('categoryStats').innerHTML=table(st.categories||[],[
    ['Biblioteca',r=>esc(categoryLabel(r.category))],
    ['Datos',r=>size(r.bytes)],
    ['Archivos',r=>esc(r.count)]
  ]);
  document.getElementById('updated').textContent='Actualizado · '+new Date().toLocaleTimeString('es-ES');
}

function euroPrice(cents){if(cents==null)return "—";return new Intl.NumberFormat("es-ES",{style:"currency",currency:"EUR"}).format(Number(cents)/100)}
function familyLabel(family){return family==="switch2"?"Switch 2 Zelda":"PS5"}
function availabilityLabel(v){return {in_stock:"En stock",preorder:"Preventa / reserva",out_of_stock:"Agotado",unknown:"Stock por confirmar"}[v]||v||"—"}
function kindLabel(v){return {retailer:"Tienda",comparison:"Comparador",deal:"Chollo"}[v]||v||"—"}
function renderActiveDeals(rows,emptyText="No hay ofertas activas disponibles."){
  if(!rows.length)return `<div class="empty" style="grid-column:1/-1">${esc(emptyText)}</div>`;
  return rows.map(o=>`<article class="deal-card">
    <div class="deal-card__top"><div><div class="deal-card__family">${esc(familyLabel(o.family))} · ${esc(kindLabel(o.kind))}</div><div class="deal-card__price">${esc(euroPrice(o.price))}</div></div><span class="pill ${o.availability==='unknown'?'warn':'ok'}">${esc(availabilityLabel(o.availability))}</span></div>
    <div class="deal-card__title">${esc(o.title||'Sin título')}</div>
    <div class="deal-card__meta">${esc(o.source||'—')}${o.seller?' · '+esc(o.seller):''}<br>${o.shipping!=null?'Envío: '+esc(euroPrice(o.shipping)):'Envío por confirmar'}<br>Última lectura: ${formatHistoryDate(o.seen_iso)}</div>
    <a class="deal-card__link" href="${esc(o.url||'#')}" target="_blank" rel="noopener noreferrer">Abrir oferta ↗</a>
  </article>`).join('');
}
async function loadDeals(){
  const r=await fetch(`/api/deals?lines=${linesEl.value}`,{cache:'no-store'}),d=await r.json();
  const status=document.getElementById('dealStatus'),ps5=document.getElementById('activeDealsPs5'),sw=document.getElementById('activeDealsSwitch'),history=document.getElementById('dealHistory'),events=document.getElementById('dealEvents'),log=document.getElementById('dealLog');
  if(!d.available){
    status.textContent='Bot no disponible';
    const msg=`<div class="empty" style="grid-column:1/-1">${esc(d.error||'No se encuentra el bot de precios.')}</div>`;
    ps5.innerHTML=msg;
    sw.innerHTML=msg;
    history.innerHTML='<div class="empty">Sin datos.</div>';
    events.innerHTML='<div class="empty">Sin datos.</div>';
    log.textContent=d.log||'(sin log)';
    return;
  }
  const ps5Offers=d.active_offers.filter(o=>o.family==='ps5');
  const switchOffers=d.active_offers.filter(o=>o.family==='switch2');
  status.textContent=`${ps5Offers.length} PS5 · ${switchOffers.length} Switch Zelda`;
  ps5.innerHTML=renderActiveDeals(ps5Offers,'No hay ofertas activas de PS5.');
  sw.innerHTML=renderActiveDeals(switchOffers,'No hay ofertas activas de Switch Zelda.');
  history.innerHTML=table(d.history,[['Fecha',r=>formatHistoryDate(r.created_iso)],['Aviso',r=>esc(r.body)]]);
  events.innerHTML=table(d.events,[['Fecha',r=>formatHistoryDate(r.created_iso)],['Fuente',r=>esc(r.name)],['Estado',r=>`<span class="pill ${r.level==='error'?'bad':'ok'}">${esc(r.level==='error'?'Error':'Recuperada')}</span>`],['Detalle',r=>esc(r.detail)]]);
  const near=log.scrollHeight-log.scrollTop-log.clientHeight<80;log.textContent=d.log||'(vacío)';if(near)log.scrollTop=log.scrollHeight;
}

async function loadLogs(){
  const lines=linesEl.value;
  const r=await fetch(`/api/logs?lines=${lines}`,{cache:'no-store'});
  const d=await r.json();
  for(const [k,v] of Object.entries(d.logs)){
    const el=document.getElementById(k);
    const near=el.scrollHeight-el.scrollTop-el.clientHeight<80;
    el.textContent=v||'(vacío)';
    if(near)el.scrollTop=el.scrollHeight;
  }
}
const downloadForm=document.getElementById('downloadForm');
downloadForm.addEventListener('submit',async e=>{
  e.preventDefault();
  const input=document.getElementById('downloadUrl');
  const status=document.getElementById('downloadFormStatus');
  const url=input.value.trim();
  if(!url)return;
  status.textContent='Enviando solicitud al bot…';
  try{
    const r=await fetch('/api/download',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url})
    });
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);
    status.textContent=`Solicitud #${d.request_id} enviada. El bot la procesará y notificará por Telegram.`;
    input.value='';
    setTimeout(loadDashboard,1200);
  }catch(err){
    status.textContent='Error: '+err.message;
  }
});

const torrentForm=document.getElementById('torrentForm');
torrentForm.addEventListener('submit',async e=>{
  e.preventDefault();
  const input=document.getElementById('torrentFile');
  const status=document.getElementById('torrentFormStatus');
  const file=input.files&&input.files[0];
  if(!file){status.textContent='Selecciona un archivo .torrent.';return;}
  status.textContent='Subiendo torrent…';
  try{
    const r=await fetch('/api/torrent',{
      method:'POST',
      headers:{'Content-Type':'application/x-bittorrent','X-Torrent-Filename':encodeURIComponent(file.name)},
      body:file
    });
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);
    status.textContent=`✅ Torrent añadido: ${d.name}`;
    input.value='';
    setTimeout(loadDashboard,800);
  }catch(err){
    status.textContent='❌ '+(err.message||err);
  }
});

document.querySelectorAll('.tab').forEach(tab=>{
  tab.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t===tab));
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    const target=document.getElementById(`view-${tab.dataset.view}`);
    if(target)target.classList.add('active');
  });
});
const linesEl=document.getElementById('lines');
linesEl.addEventListener('change',()=>{loadLogs();loadDeals();});
async function refreshAll(){
  try{
    await Promise.all([loadDashboard(),loadLogs(),loadDeals()]);
  }catch(e){
    document.getElementById('updated').textContent='Error de actualización';
    console.error(e);
  }
}
refreshAll();
setInterval(refreshAll, 3000);
</script>
</body>
</html>'''



def format_log_timestamps(text: str) -> str:
    result = []
    last_stamp = None
    for line in text.splitlines():
        match = LOG_TS_RE.match(line)
        if match:
            year, month, day = match.group("date").split("-")
            last_stamp = f"{day}/{month}/{year} {match.group('time')}"
            result.append(f"{last_stamp}{match.group('rest')}")
        elif last_stamp and line.strip():
            result.append(f"{last_stamp} | {line}")
        else:
            result.append(line)
    return "\n".join(result)


def tail(path: Path, lines: int) -> str:
    if not path.exists():
        return "(sin archivo de log)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            raw = "".join(deque(handle, maxlen=lines)).strip()
        return format_log_timestamps(raw)
    except Exception as exc:
        return f"(error leyendo {path.name}: {exc})"


def service_state(label: str) -> dict:
    if sys.platform != "darwin":
        return {"running": False, "state": "no disponible"}
    try:
        proc = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=3,
        )
        if proc.returncode != 0:
            return {"running": False, "state": "no cargado"}
        output = proc.stdout
        running = any(line.strip() in {"state = running", "job state = running"} for line in output.splitlines())
        if running:
            return {"running": True, "state": "running"}
        state = "cargado"
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("state = ") or stripped.startswith("job state = "):
                state = stripped.split("=", 1)[1].strip()
                break
        return {"running": False, "state": state}
    except Exception as exc:
        return {"running": False, "state": f"error: {exc}"}


def download_progress(rows: list[dict]) -> list[dict]:
    result = []
    now = time.monotonic()
    active_ids = set()
    for row in rows:
        item = dict(row)
        total = item.get("size_bytes")
        target = Path(item.get("target") or "")
        try:
            downloaded = target.stat().st_size if target.is_file() else 0
        except OSError:
            downloaded = 0

        status = str(item.get("status") or "").lower()
        if status == "completed" and total:
            downloaded = max(downloaded, int(total))

        speed_bps = None
        job_id = item.get("id")
        if status == "active" and job_id is not None:
            active_ids.add(job_id)
            with _DOWNLOAD_SPEED_LOCK:
                previous = _DOWNLOAD_SPEED_SAMPLES.get(job_id)
                if previous is not None:
                    previous_bytes, previous_at = previous
                    elapsed = now - previous_at
                    delta = downloaded - previous_bytes
                    if elapsed >= 0.5 and delta >= 0:
                        speed_bps = delta / elapsed
                _DOWNLOAD_SPEED_SAMPLES[job_id] = (downloaded, now)
        elif job_id is not None:
            with _DOWNLOAD_SPEED_LOCK:
                _DOWNLOAD_SPEED_SAMPLES.pop(job_id, None)

        item["downloaded_bytes"] = downloaded
        item["speed_bps"] = round(speed_bps, 1) if speed_bps is not None else None
        item["progress_percent"] = round(min(100.0, downloaded * 100.0 / int(total)), 1) if total and int(total) > 0 else None
        item["eta_seconds"] = (
            round(max(0, int(total) - downloaded) / speed_bps)
            if total and speed_bps is not None and speed_bps > 1 and downloaded < int(total)
            else None
        )
        result.append(item)

    with _DOWNLOAD_SPEED_LOCK:
        for job_id in list(_DOWNLOAD_SPEED_SAMPLES):
            if job_id not in active_ids:
                _DOWNLOAD_SPEED_SAMPLES.pop(job_id, None)
    return result




def _plain_telegram_html(value: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", value or "")).strip()

def _epoch_iso(value) -> str | None:
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")

def _price_bot_policy() -> tuple[set[str] | None, float | None]:
    try:
        cfg = json.loads(PRICE_BOT_CONFIG.read_text(encoding="utf-8"))
        enabled = {
            str(source.get("name"))
            for source in cfg.get("sources", [])
            if source.get("enabled", True)
        }
        stale = float(cfg.get("stale_after_seconds", 0) or 0)
        return enabled, stale if stale > 0 else None
    except Exception:
        return None, None


def _parse_bytes(value: str) -> int | None:
    match = re.match(r"\s*([0-9.]+)\s*([KMGT]?)(?:B)?\s*$", str(value), re.I)
    if not match:
        return None
    factor = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[match.group(2).upper()]
    return int(float(match.group(1)) * factor)


def _network_totals() -> tuple[int, int]:
    proc = subprocess.run(
        ["/usr/sbin/netstat", "-ibn"],
        capture_output=True, text=True, timeout=2,
    )
    if proc.returncode != 0:
        return 0, 0
    lines = proc.stdout.splitlines()
    if not lines:
        return 0, 0
    header = re.split(r"\s+", lines[0].strip())
    try:
        name_i, ibytes_i, obytes_i = header.index("Name"), header.index("Ibytes"), header.index("Obytes")
    except ValueError:
        return 0, 0
    per_iface = {}
    for line in lines[1:]:
        cols = re.split(r"\s+", line.strip())
        if len(cols) <= max(name_i, ibytes_i, obytes_i):
            continue
        name = cols[name_i]
        if name == "lo0":
            continue
        try:
            ibytes, obytes = int(cols[ibytes_i]), int(cols[obytes_i])
        except ValueError:
            continue
        previous = per_iface.get(name, (0, 0))
        per_iface[name] = (max(previous[0], ibytes), max(previous[1], obytes))
    return sum(v[0] for v in per_iface.values()), sum(v[1] for v in per_iface.values())


def _apple_silicon_metrics() -> dict:
    """GPU y temperaturas en Apple Silicon.

    Prioriza macmon porque expone GPU y temperaturas reales sin sudo.
    Si no está instalado, cae a powermetrics para GPU + presión térmica.
    """
    macmon_candidates = [
        Path("/opt/homebrew/bin/macmon"),
        Path("/usr/local/bin/macmon"),
    ]
    macmon = next((path for path in macmon_candidates if path.exists()), None)

    if macmon is not None:
        try:
            proc = subprocess.run(
                [str(macmon), "pipe", "-s", "1", "-i", "250"],
                capture_output=True, text=True, timeout=4,
            )
            lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            if proc.returncode == 0 and lines:
                data = json.loads(lines[-1])
                temp = data.get("temp") or {}
                cpu_temp = temp.get("cpu_temp_avg")
                gpu_temp = temp.get("gpu_temp_avg")

                gpu_active = data.get("gpu_active_ratio")
                if gpu_active is None:
                    gpu_usage = data.get("gpu_usage")
                    if isinstance(gpu_usage, list) and len(gpu_usage) >= 2:
                        gpu_active = gpu_usage[1]

                return {
                    "gpu_percent": float(gpu_active) * 100 if gpu_active is not None else None,
                    "cpu_temperature_c": float(cpu_temp) if cpu_temp is not None else None,
                    "gpu_temperature_c": float(gpu_temp) if gpu_temp is not None else None,
                    "thermal_state": None,
                    "note": "macmon",
                }
        except Exception:
            pass

    gpu_percent = None
    thermal_state = None
    note = "macmon no instalado"

    try:
        gpu_proc = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/bin/powermetrics",
             "--samplers", "gpu_power", "-n", "1", "-i", "250"],
            capture_output=True, text=True, timeout=4,
        )
        if gpu_proc.returncode == 0:
            match = re.search(
                r"GPU HW active residency:\s*([0-9.]+)%",
                gpu_proc.stdout,
                re.I,
            )
            if match:
                gpu_percent = float(match.group(1))
            note = "powermetrics"
    except Exception:
        pass

    try:
        thermal_proc = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/bin/powermetrics",
             "--samplers", "thermal", "-n", "1", "-i", "250"],
            capture_output=True, text=True, timeout=4,
        )
        if thermal_proc.returncode == 0:
            match = re.search(
                r"Current pressure level:\s*([A-Za-z]+)",
                thermal_proc.stdout,
                re.I,
            )
            if match:
                thermal_state = match.group(1)
    except Exception:
        pass

    return {
        "gpu_percent": gpu_percent,
        "cpu_temperature_c": None,
        "gpu_temperature_c": None,
        "thermal_state": thermal_state,
        "note": note,
    }

def mac_system_snapshot() -> dict:
    global _NET_SAMPLE, _METRICS_CACHE

    now = time.monotonic()
    cpu_percent = None
    ram_total = None
    ram_used = None

    try:
        proc = subprocess.run(
            ["/usr/bin/top", "-l", "1", "-n", "0"],
            capture_output=True, text=True, timeout=3,
        )
        cpu = re.search(r"CPU usage:\s*([0-9.]+)% user,\s*([0-9.]+)% sys", proc.stdout)
        if cpu:
            cpu_percent = float(cpu.group(1)) + float(cpu.group(2))
        phys = re.search(r"PhysMem:\s*([^ ]+) used.*?,\s*([^ ]+) unused", proc.stdout)
        if phys:
            ram_used = _parse_bytes(phys.group(1))
            ram_free = _parse_bytes(phys.group(2))
            if ram_used is not None and ram_free is not None:
                ram_total = ram_used + ram_free
    except Exception:
        pass

    memory_free_percent = None
    swap_used = None
    try:
        mp = subprocess.run(
            ["/usr/bin/memory_pressure", "-Q"],
            capture_output=True, text=True, timeout=2,
        )
        m = re.search(r"free percentage:\s*([0-9.]+)%", mp.stdout, re.I)
        if m:
            memory_free_percent = float(m.group(1))
    except Exception:
        pass

    try:
        sw = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
            capture_output=True, text=True, timeout=2,
        )
        m = re.search(r"used\s*=\s*([0-9.]+)([MGT])", sw.stdout, re.I)
        if m:
            factor = {"M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2).upper()]
            swap_used = int(float(m.group(1)) * factor)
    except Exception:
        pass

    rx, tx = _network_totals()
    rx_bps = tx_bps = 0.0
    if _NET_SAMPLE is not None:
        old_at, old_rx, old_tx = _NET_SAMPLE
        elapsed = now - old_at
        if elapsed > 0:
            rx_bps = max(0.0, (rx - old_rx) / elapsed)
            tx_bps = max(0.0, (tx - old_tx) / elapsed)
    _NET_SAMPLE = (now, rx, tx)

    if now - float(_METRICS_CACHE.get("at") or 0) >= 10 or _METRICS_CACHE.get("value") is None:
        _METRICS_CACHE = {"at": now, "value": _apple_silicon_metrics()}
    apple = _METRICS_CACHE["value"]

    return {
        "cpu_percent": round(cpu_percent, 1) if cpu_percent is not None else None,
        "gpu_percent": round(apple.get("gpu_percent"), 1) if apple.get("gpu_percent") is not None else None,
        "temperature_c": (
            round(max(
                x for x in (
                    apple.get("cpu_temperature_c"),
                    apple.get("gpu_temperature_c"),
                ) if x is not None
            ), 1)
            if any(x is not None for x in (
                apple.get("cpu_temperature_c"),
                apple.get("gpu_temperature_c"),
            ))
            else None
        ),
        "cpu_temperature_c": round(apple.get("cpu_temperature_c"), 1) if apple.get("cpu_temperature_c") is not None else None,
        "gpu_temperature_c": round(apple.get("gpu_temperature_c"), 1) if apple.get("gpu_temperature_c") is not None else None,
        "thermal_state": apple.get("thermal_state"),
        "ram_total": ram_total,
        "ram_used": ram_used,
        "ram_percent": round(ram_used * 100 / ram_total, 1) if ram_used is not None and ram_total else None,
        "memory_free_percent": round(memory_free_percent, 1) if memory_free_percent is not None else None,
        "swap_used": swap_used,
        "net_rx_bps": round(rx_bps, 1),
        "net_tx_bps": round(tx_bps, 1),
        "powermetrics_note": apple.get("note"),
    }


def price_bot_snapshot(log_lines: int = 300) -> dict:
    log_text = tail(PRICE_BOT_LOG, log_lines)
    if not PRICE_BOT_DB.is_file():
        return {"available": False, "error": f"No se encuentra la base de datos: {PRICE_BOT_DB}", "active_offers": [], "history": [], "events": [], "log": log_text}
    conn = None
    try:
        conn = sqlite3.connect(PRICE_BOT_DB, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute("SELECT o.source,o.payload,o.seen FROM offers o JOIN sources s ON s.name=o.source WHERE o.active=1 AND s.ok=1 ORDER BY o.seen DESC LIMIT 250").fetchall()
        enabled_sources, stale_after = _price_bot_policy()
        cutoff = time.time() - stale_after if stale_after else None
        active = []
        for row in rows:
            if enabled_sources is not None and row["source"] not in enabled_sources:
                continue
            if cutoff is not None and float(row["seen"] or 0) < cutoff:
                continue
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            payload["family"] = "switch2" if str(payload.get("model") or "").startswith("switch2") else "ps5"
            payload["seen_iso"] = _epoch_iso(row["seen"])
            active.append(payload)
        history = [{"body": _plain_telegram_html(r["body"]), "created_iso": _epoch_iso(r["created"])} for r in conn.execute("SELECT body,created FROM published_notifications ORDER BY created DESC LIMIT 120")]
        events = [{"name": r["name"], "level": r["level"], "detail": r["detail"], "created_iso": _epoch_iso(r["created"])} for r in conn.execute("SELECT name,level,detail,created FROM source_events ORDER BY id DESC LIMIT 100")]
        return {"available": True, "active_offers": active, "history": history, "events": events, "log": log_text}
    except sqlite3.Error as exc:
        return {"available": False, "error": f"No se pudo leer SQLite del bot de precios: {exc}", "active_offers": [], "history": [], "events": [], "log": log_text}
    finally:
        if conn is not None:
            conn.close()

def disk_info(path: Path) -> dict:
    probe = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(probe)
        return {"path": str(path), "exists": path.exists(), "total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        return {"path": str(path), "exists": False, "total": 0, "used": 0, "free": 0}


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        if not DASHBOARD_USER and not DASHBOARD_PASSWORD:
            return True
        raw = self.headers.get("Authorization", "")
        if not raw.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(raw[6:], validate=True).decode("utf-8")
            user, password = decoded.split(":", 1)
        except Exception:
            return False
        return hmac.compare_digest(user, DASHBOARD_USER) and hmac.compare_digest(password, DASHBOARD_PASSWORD)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        body = b"Authentication required"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Emby Dashboard", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def send_bytes(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/health":
            self.send_bytes(b"ok", "text/plain")
            return
        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query)
            try:
                lines = int(query.get("lines", ["300"])[0])
            except ValueError:
                lines = 300
            lines = max(10, min(lines, 2000))
            body = json.dumps({"logs": {name: tail(path, lines) for name, path in LOGS.items()}}, ensure_ascii=False).encode("utf-8")
            self.send_bytes(body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/deals":
            query = parse_qs(parsed.query)
            try:
                lines = int(query.get("lines", ["300"])[0])
            except ValueError:
                lines = 300
            lines = max(10, min(lines, 2000))
            data = price_bot_snapshot(lines)
            self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/dashboard":
            data = {
                "services": {name: service_state(label) for name, label in SERVICES.items()},
                "summary": dashboard_summary(),
                "statistics": dashboard_statistics(),
                "downloads": download_progress(recent_downloads(20)),
                "history": recent_history(40),
                "disk": disk_info(GAME_DOWNLOAD_DIR),
                "internal_disk": disk_info(Path("/")),
                "emby_disk": emby_storage_snapshot(),
                "emby_system": emby_system_snapshot(),
                "system": mac_system_snapshot(),
            }
            self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        self.send_error(404)

    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)

        if parsed.path == "/api/torrent":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > TORRENT_UPLOAD_MAX_BYTES:
                self.send_bytes(
                    json.dumps({"error": f"Torrent vacío o demasiado grande; máximo {TORRENT_UPLOAD_MAX_BYTES // (1024*1024)} MB"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 413 if length > TORRENT_UPLOAD_MAX_BYTES else 400,
                )
                return
            filename = unquote(self.headers.get("X-Torrent-Filename", "")).strip()
            if not filename.lower().endswith(".torrent"):
                self.send_bytes(
                    json.dumps({"error": "Selecciona un archivo con extensión .torrent"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 400,
                )
                return
            try:
                data = self.rfile.read(length)
                target = save_torrent_bytes(data, filename, TORRENT_DROP_DIR, prefix="dashboard")
                add_history(
                    "torrent", "success", title=target.name, source_path="dashboard",
                    destination=str(target.parent), details="Torrent añadido desde el Dashboard", size_bytes=len(data),
                )
            except ValueError as exc:
                self.send_bytes(
                    json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 400,
                )
                return
            except OSError as exc:
                self.send_bytes(
                    json.dumps({"error": f"No se pudo guardar el torrent: {exc}"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 500,
                )
                return
            self.send_bytes(
                json.dumps({"ok": True, "name": target.name}, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8", 201,
            )
            return

        if parsed.path == "/api/download":
            if not TELEGRAM_CHAT_ID:
                self.send_bytes(
                    json.dumps({"error": "TELEGRAM_CHAT_ID no configurado"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 503,
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 65536:
                self.send_bytes(
                    json.dumps({"error": "Petición inválida"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 400,
                )
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                url = str(payload.get("url") or "").strip()
            except Exception:
                url = ""
            parsed_url = urlparse(url)
            if len(url) > 8192 or parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
                self.send_bytes(
                    json.dumps({"error": "URL no válida"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", 400,
                )
                return
            request_id = queue_download_request(chat_id=TELEGRAM_CHAT_ID, url=url)
            self.send_bytes(
                json.dumps({"ok": True, "request_id": request_id}, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8", 202,
            )
            return

        self.send_error(404)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DASHBOARD_BIND)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    host = str(args.host or "127.0.0.1").strip()
    if host not in ("127.0.0.1", "localhost", "::1") and (not DASHBOARD_USER or not DASHBOARD_PASSWORD):
        raise SystemExit("Para exponer el Dashboard fuera de localhost configura DASHBOARD_USER y DASHBOARD_PASSWORD en .env")
    init_db()
    TORRENT_DROP_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, args.port), Handler)
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"Dashboard: http://{shown_host}:{args.port} (bind {host})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
