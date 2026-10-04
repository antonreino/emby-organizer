#!/usr/bin/env python3
import argparse
import json
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LOG_DIR = Path.home() / "Library" / "Logs"
LOGS = {
    "organizer_out": LOG_DIR / "emby-organizer.out.log",
    "organizer_err": LOG_DIR / "emby-organizer.err.log",
    "telegram_out": LOG_DIR / "telegram-download-bot.out.log",
    "telegram_err": LOG_DIR / "telegram-download-bot.err.log",
}

HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Emby Organizer · Logs</title>
<style>
:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif;background:Canvas;color:CanvasText}
header{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:18px}h1{font-size:22px;margin:0}.controls{display:flex;gap:8px;align-items:center}
button,select{font:inherit;padding:7px 10px;border-radius:8px;border:1px solid color-mix(in srgb,CanvasText 20%,transparent);background:Canvas}.status{font-size:13px;opacity:.7}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{border:1px solid color-mix(in srgb,CanvasText 14%,transparent);border-radius:12px;overflow:hidden;background:color-mix(in srgb,Canvas 96%,CanvasText 4%)}
.card h2{margin:0;padding:10px 12px;font-size:14px;border-bottom:1px solid color-mix(in srgb,CanvasText 12%,transparent)}pre{margin:0;padding:12px;min-height:270px;max-height:42vh;overflow:auto;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}.error h2{color:#ff453a}@media(max-width:900px){.grid{grid-template-columns:1fr}}
</style></head>
<body>
<header><div><h1>🎬 Emby Organizer · Logs</h1><div class="status" id="status">Cargando…</div></div>
<div class="controls"><label>Líneas <select id="lines"><option>100</option><option selected>300</option><option>1000</option></select></label><button onclick="loadLogs()">Actualizar</button></div></header>
<main class="grid">
<section class="card"><h2>Organizer</h2><pre id="organizer_out"></pre></section>
<section class="card error"><h2>Organizer · errores</h2><pre id="organizer_err"></pre></section>
<section class="card"><h2>Telegram bot</h2><pre id="telegram_out"></pre></section>
<section class="card error"><h2>Telegram · errores</h2><pre id="telegram_err"></pre></section>
</main>
<script>
async function loadLogs(){const lines=document.getElementById("lines").value;try{const r=await fetch(`/api/logs?lines=${lines}`,{cache:"no-store"});const data=await r.json();for(const [key,value] of Object.entries(data.logs)){const el=document.getElementById(key);const nearBottom=el.scrollHeight-el.scrollTop-el.clientHeight<80;el.textContent=value||"(vacío)";if(nearBottom)el.scrollTop=el.scrollHeight}document.getElementById("status").textContent="Actualizado "+new Date().toLocaleTimeString()}catch(e){document.getElementById("status").textContent="Error: "+e}}
document.getElementById("lines").addEventListener("change",loadLogs);loadLogs();setInterval(loadLogs,3000);
</script></body></html>"""

def tail(path: Path, lines: int) -> str:
    if not path.exists():
        return "(sin archivo de log)"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=lines)).strip()
    except Exception as exc:
        return f"(error leyendo {path.name}: {exc})"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/health":
            body = b"ok"
            self.send_response(200); self.send_header("Content-Type","text/plain"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query)
            try: lines = int(query.get("lines",["300"])[0])
            except ValueError: lines = 300
            lines = max(10,min(lines,2000))
            body = json.dumps({"logs":{name:tail(path,lines) for name,path in LOGS.items()}},ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_error(404)
    def log_message(self, fmt, *args):
        pass

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--port",type=int,default=8765); args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    print(f"Visor de logs: http://127.0.0.1:{args.port}",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == "__main__":
    main()
