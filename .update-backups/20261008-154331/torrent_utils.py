#!/usr/bin/env python3
import time
from pathlib import Path


def is_torrent_data(data: bytes) -> bool:
    """Validación ligera del metainfo BitTorrent sin ejecutar contenido."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 16:
        return False
    sample = bytes(data[:65536])
    return sample.startswith(b"d") and b"4:info" in sample and (
        b"8:announce" in sample or b"13:announce-list" in sample
    )


def is_torrent_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return is_torrent_data(handle.read(65536))
    except OSError:
        return False


def safe_torrent_name(name: str, prefix: str = "torrent") -> str:
    name = Path(str(name or "")).name.replace("/", "_").replace("\\", "_").strip()
    if not name:
        name = f"{prefix}-{int(time.time())}.torrent"
    if not name.lower().endswith(".torrent"):
        name += ".torrent"
    return name


def unique_target(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    i = 1
    while True:
        candidate = directory / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def save_torrent_bytes(data: bytes, filename: str, directory: Path, *, prefix: str = "dashboard") -> Path:
    if not is_torrent_data(data):
        raise ValueError("El archivo no parece un .torrent válido")
    target = unique_target(directory, safe_torrent_name(filename, prefix=prefix))
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target
