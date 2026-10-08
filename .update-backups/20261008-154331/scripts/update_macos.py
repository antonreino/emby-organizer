#!/usr/bin/env python3
"""Actualiza una instalación existente conservando .env, .git y datos locales."""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
TARGET = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path('/Volumes/Datos/Proyectos/Scripts/emby-organizer')
FILES = [
    '.env.example',
    'README.md',
    'emby_organizer.py',
    'state_db.py',
    'torrent_utils.py',
    'scripts/log-viewer.py',
    'scripts/telegram_torrent_bot.py',
    'scripts/update_macos.py',
]
SERVICES = [
    'com.tone.emby-organizer',
    'com.tone.telegram-download-bot',
    'com.tone.emby-log-viewer',
]

if not TARGET.is_dir():
    raise SystemExit(f'No existe la instalación destino: {TARGET}')
if not (TARGET / '.env').is_file():
    raise SystemExit(f'No encuentro {TARGET / ".env"}; aborto para no actualizar una instalación equivocada.')

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = TARGET / '.update-backups' / stamp
backup.mkdir(parents=True, exist_ok=True)

for rel in FILES:
    src = SOURCE / rel
    if not src.is_file():
        raise SystemExit(f'Falta en el paquete: {src}')
    dst = TARGET / rel
    if dst.exists():
        old = backup / rel
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, old)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

# Validación usando el Python del entorno del proyecto si existe.
python = Path.home() / '.venvs' / 'emby-organizer' / 'bin' / 'python'
if not python.exists():
    python = Path(sys.executable)
subprocess.run([
    str(python), '-m', 'py_compile',
    str(TARGET / 'state_db.py'),
    str(TARGET / 'torrent_utils.py'),
    str(TARGET / 'emby_organizer.py'),
    str(TARGET / 'scripts/log-viewer.py'),
    str(TARGET / 'scripts/telegram_torrent_bot.py'),
], check=True)

uid = subprocess.check_output(['id', '-u'], text=True).strip()
for label in SERVICES:
    subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{uid}/{label}'], check=False)

print('✅ Emby Organizer actualizado.')
print(f'   Destino: {TARGET}')
print(f'   Copia de seguridad: {backup}')
print('   .env y datos persistentes se han conservado.')
print('   Servicios principales reiniciados.')
