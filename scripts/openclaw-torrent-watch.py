#!/usr/bin/env python3
import shutil
import time
from pathlib import Path

INBOX = Path("/home/tone/.openclaw/media/inbound")
DEST = Path("/home/tone/Descargas")

def is_torrent(path: Path) -> bool:
    try:
        data = path.read_bytes()[:4096]
        return data.startswith(b"d") and b"announce" in data
    except Exception:
        return False

def unique_target(base: str) -> Path:
    if not base.endswith(".torrent"):
        base = base + ".torrent"

    target = DEST / base
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    counter = 1

    while True:
        candidate = DEST / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)

    while True:
        for item in INBOX.iterdir():
            if not item.is_file():
                continue

            if is_torrent(item):
                target = unique_target(item.name)
                shutil.move(str(item), str(target))
                print(f"Torrent movido: {item} -> {target}", flush=True)

        time.sleep(3)

if __name__ == "__main__":
    main()
