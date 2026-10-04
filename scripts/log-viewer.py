#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
from state_db import dashboard_summary, init_db, recent_downloads, recent_history

load_dotenv(APP_DIR / ".env")

LOG_DIR = Path.home() / "Library" / "Logs"
GAME_DOWNLOAD_DIR = Path(os.getenv("GAME_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "Games"))).expanduser()
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

HTML = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Emby Automation · Dashboard</title>
<style>
:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif;background:Canvas;color:CanvasText}header{display:flex;justify-content:space-between;gap:18px;align-items:center;flex-wrap:wrap;margin-bottom:18px}h1{font-size:24px;margin:0}.muted{opacity:.65}.statusline{font-size:13px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}.card,.panel{border:1px solid color-mix(in srgb,CanvasText 14%,transparent);border-radius:14px;background:color-mix(in srgb,Canvas 96%,CanvasText 4%)}.card{padding:14px}.card b{font-size:22px;display:block;margin-top:7px}.services{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.service{padding:12px}.ok{color:#30d158}.bad{color:#ff453a}.warn{color:#ff9f0a}.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:14px}.panel{overflow:hidden;margin-bottom:14px}.panel h2{font-size:15px;margin:0;padding:11px 13px;border-bottom:1px solid color-mix(in srgb,CanvasText 12%,transparent)}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid color-mix(in srgb,CanvasText 8%,transparent);vertical-align:top}th{font-size:12px;opacity:.65}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.pill{display:inline-block;padding:2px 7px;border-radius:999px;background:color-mix(in srgb,CanvasText 10%,transparent);font-size:11px}.log-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}button,select{font:inherit;padding:7px 10px;border-radius:8px;border:1px solid color-mix(in srgb,CanvasText 20%,transparent);background:Canvas}.logs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.log pre{margin:0;padding:12px;min-height:220px;max-height:38vh;overflow:auto;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}.error h2{color:#ff453a}.empty{padding:18px;opacity:.6}@media(max-width:1050px){.cards,.services{grid-template-columns:repeat(2,1fr)}.grid,.logs{grid-template-columns:1fr}}@media(max-width:600px){body{padding:14px}.cards,.services{grid-template-columns:1fr}}
</style></head><body>
<header><div><h1>🎬 Emby Automation</h1><div class="statusline muted" id="updated">Cargando…</div></div><div class="log-controls"><label>Logs <select id="lines"><option>100</option><option selected>300</option><option>1000</option></select></label><button onclick="refreshAll()">Actualizar</button></div></header>
<section class="services" id="services"></section>
<section class="cards">
<div class="card"><span class="muted">Procesados 24 h</span><b id="hcount">0</b></div>
<div class="card"><span class="muted">Correctos 24 h</span><b id="hsuccess">0</b></div>
<div class="card"><span class="muted">Errores 24 h</span><b id="herrors">0</b></div>
<div class="card"><span class="muted">Datos 24 h</span><b id="hbytes">0 B</b></div>
</section>
<div class="grid">
<section class="panel"><h2>📥 Cola y descargas recientes</h2><div id="downloads"></div></section>
<section class="panel"><h2>💾 Almacenamiento</h2><div id="disk" style="padding:14px"></div></section>
</div>
<section class="panel"><h2>🕘 Historial reciente</h2><div id="history"></div></section>
<section class="logs">
<section class="panel log"><h2>Organizer</h2><pre id="organizer_out"></pre></section>
<section class="panel log error"><h2>Organizer · stderr</h2><pre id="organizer_err"></pre></section>
<section class="panel log"><h2>Telegram bot</h2><pre id="telegram_out"></pre></section>
<section class="panel log error"><h2>Telegram · stderr</h2><pre id="telegram_err"></pre></section>
</section>
<script>
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
function size(n){if(n==null)return "—";let v=Number(n),u=["B","KB","MB","GB","TB"],i=0;while(v>=1000&&i<u.length-1){v/=1000;i++}return `${v.toFixed(i?1:0)} ${u[i]}`}
function serviceLabel(k){return {organizer:"Organizer",telegram:"Telegram",viewer:"Dashboard",alerts:"Alertas"}[k]||k}
function table(rows, cols){if(!rows.length)return '<div class="empty">Sin datos todavía.</div>';return `<table><thead><tr>${cols.map(c=>`<th>${esc(c[0])}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${c[1](r)}</td>`).join("")}</tr>`).join("")}</tbody></table>`}
async function loadDashboard(){const r=await fetch('/api/dashboard',{cache:'no-store'});const d=await r.json();document.getElementById('services').innerHTML=Object.entries(d.services).map(([k,v])=>`<div class="card service"><span>${serviceLabel(k)}</span><b class="${v.running?'ok':'bad'}">${v.running?'● Activo':'● '+esc(v.state)}</b></div>`).join('');const h=d.summary.history_24h;document.getElementById('hcount').textContent=h.count;document.getElementById('hsuccess').textContent=h.success;document.getElementById('herrors').textContent=h.errors;document.getElementById('hbytes').textContent=size(h.bytes);document.getElementById('downloads').innerHTML=table(d.downloads,[['ID',r=>'#'+r.id],['Nombre',r=>esc(r.name)],['Estado',r=>`<span class="pill">${esc(r.status)}</span>`],['Tamaño',r=>size(r.size_bytes)],['Intento',r=>esc(r.attempt||0)]]);document.getElementById('history').innerHTML=table(d.history,[['Fecha',r=>esc((r.created_at||'').replace('T',' ').replace('+00:00',' UTC'))],['Tipo',r=>esc(r.kind)],['Estado',r=>`<span class="pill">${esc(r.status)}</span>`],['Título',r=>esc(r.title||'—')],['Categoría',r=>esc(r.category||'—')],['Detalle',r=>esc(r.details||'—')]]);document.getElementById('disk').innerHTML=`<b>${esc(d.disk.path)}</b><p>${size(d.disk.free)} libres de ${size(d.disk.total)} · ${d.disk.exists?'montado/disponible':'no disponible'}</p>`;document.getElementById('updated').textContent='Actualizado '+new Date().toLocaleTimeString()}
async function loadLogs(){const lines=linesEl.value;const r=await fetch(`/api/logs?lines=${lines}`,{cache:'no-store'});const d=await r.json();for(const[k,v]of Object.entries(d.logs)){const el=document.getElementById(k);const near=el.scrollHeight-el.scrollTop-el.clientHeight<80;el.textContent=v||'(vacío)';if(near)el.scrollTop=el.scrollHeight}}
const linesEl=document.getElementById('lines');linesEl.addEventListener('change',loadLogs);async function refreshAll(){try{await Promise.all([loadDashboard(),loadLogs()])}catch(e){document.getElementById('updated').textContent='Error: '+e}}refreshAll();setInterval(refreshAll,3000);
</script></body></html>'''


def tail(path: Path, lines: int) -> str:
    if not path.exists():
        return "(sin archivo de log)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=lines)).strip()
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


def disk_info(path: Path) -> dict:
    probe = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(probe)
        return {"path": str(path), "exists": path.exists(), "total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        return {"path": str(path), "exists": False, "total": 0, "used": 0, "free": 0}


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
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
        if parsed.path == "/api/dashboard":
            data = {
                "services": {name: service_state(label) for name, label in SERVICES.items()},
                "summary": dashboard_summary(),
                "downloads": recent_downloads(20),
                "history": recent_history(40),
                "disk": disk_info(GAME_DOWNLOAD_DIR),
            }
            self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Dashboard: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
