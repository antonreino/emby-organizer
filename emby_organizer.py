#!/usr/bin/env python3
import argparse
import getpass
import json
import logging
import os
import re
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

try:
    import paramiko
except ImportError:
    paramiko = None


# =========================
# CONFIGURACIÓN
# =========================
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

INBOX_DIR = Path("/home/tone/Documentos/Torrent/Descargas")
STABLE_SECONDS = 180
SCAN_INTERVAL_SECONDS = 30
LOG_FILE = Path.home() / ".local" / "share" / "emby_organizer" / "organizer.log"
STATE_DIR = Path.home() / ".local" / "share" / "emby_organizer"
QUARANTINE_LOCAL_DIR = INBOX_DIR / "NoClasificado"

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_CACHE_FILE = STATE_DIR / "tmdb_cache.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts"}
IGNORE_EXTENSIONS = {".part", ".tmp", ".crdownload", ".!qB", ".aria2"}
IGNORE_FILENAMES = {"canal telegram oficial.url"}
IGNORE_DIR_NAMES = {"NoClasificado", ".staging", ".git"}

LIBRARIES = {
    "anime": os.environ.get("EMBY_SFTP_ANIME_URL", ""),
    "series": os.environ.get("EMBY_SFTP_SERIES_URL", ""),
    "movies": os.environ.get("EMBY_SFTP_MOVIES_URL", ""),
}

ANIME_HINTS = {
    "anime",
    "ova",
    "ona",
    "fansub",
    "sub esp",
    "subspa",
    "japanese",
    "japones",
    "japonés",
}

SERIES_EPISODE_PATTERNS = [
    re.compile(r"(?i)(?<!\w)S(?P<season>\d{1,2})E(?P<episode>\d{1,3})(?!\w)"),
    re.compile(r"(?i)(?<!\d)(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?!\d)"),
    re.compile(r"(?i)\bSeason[ ._-]?(?P<season>\d{1,2})[ ._-]*Episode[ ._-]?(?P<episode>\d{1,3})\b"),
]

SPANISH_EPISODE_PATTERNS = [
    re.compile(r"(?i)\[Cap[ ._-]?(?P<episode>\d{1,4})\]"),
    re.compile(r"(?i)\bCap[íi]?tulo[ ._-]?(?P<episode>\d{1,4})\b"),
    re.compile(r"(?i)\bCap[ ._-]?(?P<episode>\d{1,4})\b"),
]

QUALITY_TOKENS = re.compile(
    r"(?i)\b(2160p|1080p|720p|480p|x264|x265|h\.264|h\.265|hevc|bluray|bdrip|webrip|web-dl|hdrip|dvdrip|aac|dts|10bit|8bit|multi|multi-audio|dual audio|subbed|proper|repack|hdtv|microhd)\b"
)
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")


@dataclass
class SftpTarget:
    username: str
    host: str
    port: int
    path: str


@dataclass
class MediaInfo:
    source_path: Path
    title: str
    category: str  # anime | series | movies | unknown
    season: Optional[int] = None
    episode: Optional[int] = None
    year: Optional[int] = None
    extension: str = ""


class OrganizerError(Exception):
    pass


class SftpUploader:
    def __init__(self, targets: dict[str, str]):
        if paramiko is None:
            raise OrganizerError(
                "Falta la librería 'paramiko'. Instálala con: python3 -m pip install paramiko"
            )
        self.targets = {name: self._parse_sftp_url(url) for name, url in targets.items()}
        self._transport = None
        self._sftp = None
        self._active_key = None
        self._password = os.environ.get("EMBY_SFTP_PASSWORD") or None

    @staticmethod
    def _parse_sftp_url(url: str) -> SftpTarget:
        parsed = urlparse(url)
        if parsed.scheme != "sftp":
            raise OrganizerError(f"URL SFTP inválida: {url}")
        if not parsed.hostname or not parsed.username or not parsed.path:
            raise OrganizerError(f"URL SFTP incompleta: {url}")
        return SftpTarget(
            username=parsed.username,
            host=parsed.hostname,
            port=parsed.port or 22,
            path=parsed.path,
        )

    @staticmethod
    def safe_component(value: str) -> str:
        value = value.strip()
        value = value.replace("/", "-").replace("\\", "-")
        value = re.sub(r"\s+", " ", value)
        return value.strip(" .-_") or "Unknown"

    def _connect(self, category: str):
        target = self.targets[category]
        key = (target.username, target.host, target.port)
        if self._sftp and self._active_key == key:
            return self._sftp, target

        self.close()

        ssh_dir = Path.home() / ".ssh"
        private_key_candidates = [
            ssh_dir / "id_ed25519",
            ssh_dir / "id_rsa",
        ]

        last_error = None

        for key_path in private_key_candidates:
            if not key_path.exists():
                continue

            transport = paramiko.Transport((target.host, target.port))
            try:
                if key_path.name == "id_ed25519":
                    pkey = paramiko.Ed25519Key.from_private_key_file(str(key_path))
                else:
                    pkey = paramiko.RSAKey.from_private_key_file(str(key_path))

                transport.connect(username=target.username, pkey=pkey)
                self._transport = transport
                self._sftp = paramiko.SFTPClient.from_transport(transport)
                self._active_key = key
                return self._sftp, target

            except Exception as exc:
                last_error = exc
                try:
                    transport.close()
                except Exception:
                    pass

        if self._password is None:
            self._password = getpass.getpass(
                f"Contraseña SFTP para {target.username}@{target.host}:{target.port}: "
            )

        transport = paramiko.Transport((target.host, target.port))
        try:
            transport.connect(username=target.username, password=self._password)
            self._transport = transport
            self._sftp = paramiko.SFTPClient.from_transport(transport)
            self._active_key = key
            return self._sftp, target
        except Exception as exc:
            last_error = exc
            try:
                transport.close()
            except Exception:
                pass

        raise OrganizerError(
            "No se pudo abrir la conexión SFTP ni por clave ni por contraseña. "
            f"Último error: {last_error}"
        )

    def close(self):
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
        self._sftp = None
        self._transport = None
        self._active_key = None

    def ensure_remote_dir(self, category: str, remote_dir: str):
        sftp, _ = self._connect(category)
        parts = [p for p in remote_dir.strip("/").split("/") if p]
        current = ""
        for part in parts:
            current += "/" + part
            try:
                sftp.stat(current)
            except FileNotFoundError:
                sftp.mkdir(current)

    def upload_file(self, local_path: Path, category: str, remote_path: str):
        sftp, _ = self._connect(category)
        remote_dir = str(Path(remote_path).parent).replace("\\", "/")
        self.ensure_remote_dir(category, remote_dir)
        temp_remote_path = remote_path + ".uploading"
        sftp.put(str(local_path), temp_remote_path)
        sftp.rename(temp_remote_path, remote_path)

    def exists(self, category: str, remote_path: str) -> bool:
        sftp, _ = self._connect(category)
        try:
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False

    def list_remote_dirs(self, category: str) -> list[str]:
        sftp, target = self._connect(category)
        try:
            entries = sftp.listdir_attr(target.path)
        except FileNotFoundError:
            return []

        result = []
        for entry in entries:
            if entry.filename.startswith("."):
                continue
            if entry.st_mode and (entry.st_mode & 0o170000) == 0o040000:
                result.append(entry.filename)
        return result

    def build_remote_path(self, media: MediaInfo) -> str:
        target = self.targets[media.category]
        safe_title = self.safe_component(media.title)
        safe_title = re.sub(r"\s+", " ", safe_title).strip()

        # Series normales o anime episódico.
        if media.category in {"series", "anime"} and media.episode is not None:
            season = media.season or 1
            filename = f"S{season:02d}E{media.episode:02d}{media.extension}"
            return f"{target.path}/{safe_title}/Season {season}/{filename}"

        # Películas SIN carpeta (estructura plana)
        filename = safe_title if media.year is None else f"{safe_title} ({media.year})"
        filename = f"{filename}{media.extension}"
        return f"{target.path}/{filename}"


class MediaOrganizer:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.uploader = SftpUploader(LIBRARIES)
        self._ensure_dirs()

    def _ensure_dirs(self):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        QUARANTINE_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    def shutdown(self):
        self.uploader.close()

    def should_ignore(self, path: Path) -> bool:
        if not path.is_file():
            return True
        if path.parent.name in IGNORE_DIR_NAMES:
            return True
        if path.name.lower() in IGNORE_FILENAMES:
            return True
        if path.suffix.lower() in IGNORE_EXTENSIONS:
            return True
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            return True
        return False

    def is_stable(self, path: Path) -> bool:
        try:
            stat1 = path.stat()
            time.sleep(2)
            stat2 = path.stat()
            if stat1.st_size != stat2.st_size:
                return False
            age = time.time() - stat2.st_mtime
            return age >= STABLE_SECONDS
        except FileNotFoundError:
            return False

    def clean_title(self, raw_name: str) -> str:
        name = raw_name.replace(".", " ").replace("_", " ")
        name = re.sub(r"\[[A-F0-9]{6,8}\]", "", name, flags=re.IGNORECASE)
        name = re.sub(r"^\[[^\]]+\]\s*", "", name)
        name = re.sub(r"(?i)\[Cap[ ._-]?\d{1,4}\]", "", name)
        name = re.sub(r"(?i)\bCap[íi]?tulo[ ._-]?\d{1,4}\b", "", name)
        name = re.sub(r"(?i)\bCap[ ._-]?\d{1,4}\b", "", name)
        name = QUALITY_TOKENS.sub("", name)
        name = re.sub(r"(?i)www\..*$", "", name)
        name = re.sub(r"(?i)newpct\d*.*$", "", name)
        name = re.sub(r"\[\s*\]", "", name)
        name = re.sub(r"\s+", " ", name).strip(" -_.[]")
        return name

    def clean_title_for_tmdb(self, raw_name: str) -> str:
        name = raw_name

        name = re.sub(r"(?i)www\..*$", " ", name)
        name = re.sub(r"(?i)newpct\d*.*$", " ", name)

        name = name.replace(".", " ").replace("_", " ")

        name = re.sub(r"\[[^\]]*\]", " ", name)
        name = re.sub(r"\([^\)]*\)", " ", name)

        name = re.sub(r"(?i)\b(mkv|mp4|avi|mov|m4v|ts)\b", " ", name)

        name = QUALITY_TOKENS.sub(" ", name)
        name = re.sub(
            r"(?i)\b(BD1080|BD720|MicroHD|Castellano|Japones|Japonés|Japanese|Subs?|AC3|DTS|5\.1|5 1|ES|EN)\b",
            " ",
            name,
        )

        name = re.sub(r"\s+", " ", name).strip(" -_.[]")
        logging.info("TMDb query limpia: raw=%s -> query=%s", raw_name, name)
        return name

    def detect_episode(self, name: str) -> Tuple[Optional[int], Optional[int]]:
        for pattern in SERIES_EPISODE_PATTERNS:
            match = pattern.search(name)
            if match:
                return int(match.group("season")), int(match.group("episode"))
        return None, None

    def detect_spanish_episode(self, name: str) -> Tuple[Optional[int], Optional[int]]:
        for pattern in SPANISH_EPISODE_PATTERNS:
            match = pattern.search(name)
            if match:
                raw = match.group("episode")
                if len(raw) >= 3:
                    season = int(raw[:-2])
                    episode = int(raw[-2:])
                else:
                    season = 1
                    episode = int(raw)
                return season, episode
        return None, None

    def detect_year(self, name: str) -> Optional[int]:
        match = YEAR_PATTERN.search(name)
        return int(match.group(1)) if match else None

    def normalize_name(self, value: str) -> str:
        value = value.lower()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"(?i)\b(the|tv|serie|series|season)\b", " ", value)
        value = re.sub(r"[^a-z0-9]+", "", value)
        return value

    def resolve_existing_series(self, parsed_title: str, preferred_category: str) -> Tuple[str, str]:
        candidates = []
        for category in [preferred_category, "series", "anime"]:
            try:
                for remote_dir in self.uploader.list_remote_dirs(category):
                    candidates.append((category, remote_dir))
            except Exception:
                continue

        normalized_target = self.normalize_name(parsed_title)
        for category, remote_dir in candidates:
            if self.normalize_name(remote_dir) == normalized_target:
                return category, remote_dir

        return preferred_category, parsed_title

    def load_tmdb_cache(self) -> dict:
        try:
            if TMDB_CACHE_FILE.exists():
                return json.loads(TMDB_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("No se pudo leer caché TMDb")
        return {}

    def save_tmdb_cache(self, cache: dict):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            TMDB_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logging.exception("No se pudo guardar caché TMDb")

    def tmdb_search_multi(self, query: str) -> Optional[dict]:
        if not TMDB_API_KEY:
            logging.info("TMDb no configurado: falta TMDB_API_KEY")
            return None

        query = query.strip()
        if not query:
            return None

        cache = self.load_tmdb_cache()
        cache_key = self.normalize_name(query)

        if cache_key in cache:
            return cache[cache_key]

        url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "api_key": TMDB_API_KEY,
            "query": query,
            "language": "es-ES",
            "include_adult": "false",
        }

        try:
            response = requests.get(url, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()
            results = [
                r for r in data.get("results", [])
                if r.get("media_type") in {"movie", "tv"}
            ]

            if not results:
                cache[cache_key] = None
                self.save_tmdb_cache(cache)
                logging.info("TMDb sin resultados para query=%s", query)
                return None

            result = sorted(
                results,
                key=lambda r: (
                    self.normalize_name(r.get("title") or r.get("name") or "") == self.normalize_name(query),
                    r.get("popularity", 0),
                    r.get("vote_count", 0),
                ),
                reverse=True,
            )[0]

            cache[cache_key] = result
            self.save_tmdb_cache(cache)
            return result

        except Exception:
            logging.exception("Error consultando TMDb para query=%s", query)
            return None

    def classify_with_tmdb(self, path: Path) -> Optional[MediaInfo]:
        raw_candidates = [
            path.parent.name if path.parent != INBOX_DIR else "",
            path.stem,
        ]

        extension = path.suffix.lower()

        for raw in raw_candidates:
            query = self.clean_title_for_tmdb(raw)
            if not query:
                continue

            result = self.tmdb_search_multi(query)
            if not result:
                continue

            media_type = result.get("media_type")
            genre_ids = result.get("genre_ids", [])
            original_language = result.get("original_language")
            origin_country = result.get("origin_country") or []

            if media_type == "movie":
                title = result.get("title") or result.get("original_title") or query

                year = None
                release_date = result.get("release_date")
                if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
                    year = int(release_date[:4])

                is_animation = 16 in genre_ids
                is_japanese = original_language == "ja" or "JP" in origin_country
                category = "anime" if is_animation and is_japanese else "movies"

                logging.info(
                    "TMDb fallback: %s -> %s | title=%s | year=%s | media_type=%s | genres=%s | lang=%s | country=%s",
                    path.name,
                    category,
                    title,
                    year,
                    media_type,
                    genre_ids,
                    original_language,
                    origin_country,
                )

                return MediaInfo(
                    source_path=path,
                    title=title,
                    category=category,
                    year=year,
                    extension=extension,
                )

            if media_type == "tv":
                title = result.get("name") or result.get("original_name") or query
                is_animation = 16 in genre_ids
                is_japanese = original_language == "ja" or "JP" in origin_country
                category = "anime" if is_animation and is_japanese else "series"

                logging.info(
                    "TMDb fallback detectó TV sin episodio: %s -> %s | title=%s. Se ignora porque no hay episodio.",
                    path.name,
                    category,
                    title,
                )

                return None

        return None

    def classify(self, path: Path) -> MediaInfo:
        stem = path.stem
        lower = stem.lower()
        parent_stem = path.parent.name
        parent_lower = parent_stem.lower()
        extension = path.suffix.lower()

        season, episode = self.detect_episode(stem)
        if season is None or episode is None:
            season, episode = self.detect_episode(parent_stem)

        year = self.detect_year(stem)
        title = self.clean_title(stem)
        parent_title = self.clean_title(parent_stem)

        anime_context = any(hint in lower for hint in ANIME_HINTS) or any(hint in parent_lower for hint in ANIME_HINTS)

        if season is not None and episode is not None:
            category = "anime" if anime_context else "series"
            final_title = parent_title or title
            category, final_title = self.resolve_existing_series(final_title, category)
            return MediaInfo(
                source_path=path,
                title=final_title,
                category=category,
                season=season,
                episode=episode,
                extension=extension,
            )

        spanish_season, spanish_episode = self.detect_spanish_episode(stem)
        if spanish_season is None or spanish_episode is None:
            spanish_season, spanish_episode = self.detect_spanish_episode(parent_stem)

        if spanish_season is not None and spanish_episode is not None:
            final_title = parent_title or title
            category = "anime" if anime_context else "series"
            category, final_title = self.resolve_existing_series(final_title, category)
            return MediaInfo(
                source_path=path,
                title=final_title,
                category=category,
                season=spanish_season,
                episode=spanish_episode,
                extension=extension,
            )

        # Antes de asumir película normal por año/calidad, probamos TMDb.
        # Esto evita que películas anime con año o calidad acaben en Peliculas.
        tmdb_media = self.classify_with_tmdb(path)
        if tmdb_media:
            return tmdb_media

        movie_like = year is not None or any(token in lower for token in ["movie", "film", "part ", "part-"])
        if movie_like:
            return MediaInfo(
                source_path=path,
                title=title,
                category="movies",
                year=year,
                extension=extension,
            )

        return MediaInfo(
            source_path=path,
            title=title or path.stem,
            category="unknown",
            extension=extension,
        )

    def quarantine(self, path: Path, reason: str):
        destination = QUARANTINE_LOCAL_DIR / path.name
        if destination.exists():
            destination = QUARANTINE_LOCAL_DIR / self._dedupe_name(path.name, QUARANTINE_LOCAL_DIR)

        if self.dry_run:
            logging.warning("[DRY-RUN] Cuarentena: %s -> %s | Motivo: %s", path, destination, reason)
            return

        shutil.move(str(path), str(destination))
        logging.warning("Cuarentena: %s -> %s | Motivo: %s", path, destination, reason)

    def _dedupe_name(self, filename: str, folder: Path) -> str:
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while True:
            candidate = f"{stem} ({counter}){suffix}"
            if not (folder / candidate).exists():
                return candidate
            counter += 1

    def cleanup_download_folder(self, source_path: Path):
        folder = source_path.parent

        if folder == INBOX_DIR:
            return

        try:
            folder.relative_to(INBOX_DIR)
        except ValueError:
            return

        remaining_video_files = [
            p for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ]
        if remaining_video_files:
            logging.info("Se conserva la carpeta porque aún contiene vídeos: %s", folder)
            return

        if self.dry_run:
            logging.info("[DRY-RUN] Se eliminaría la carpeta contenedora: %s", folder)
            return

        shutil.rmtree(folder, ignore_errors=False)
        logging.info("Carpeta contenedora eliminada: %s", folder)

    def cleanup_empty_folders(self):
        folders = [p for p in INBOX_DIR.rglob("*") if p.is_dir()]
        folders.sort(key=lambda p: len(p.parts), reverse=True)

        for folder in folders:
            if folder == INBOX_DIR:
                continue
            if folder.name in IGNORE_DIR_NAMES:
                continue

            has_video = any(
                f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
                for f in folder.rglob("*")
            )

            if has_video:
                continue

            if self.dry_run:
                logging.info("[DRY-RUN] Se eliminaría carpeta sin vídeos: %s", folder)
            else:
                shutil.rmtree(folder, ignore_errors=True)
                logging.info("Carpeta sin vídeos eliminada: %s", folder)

    def notify_telegram(self, media: MediaInfo, remote_path: str):
        if not TELEGRAM_BOT_TOKEN:
            logging.info("Telegram no configurado: falta TELEGRAM_BOT_TOKEN")
            return

        category_names = {
            "anime": "Anime",
            "series": "Series",
            "movies": "Películas",
        }

        category = category_names.get(media.category, media.category)

        if media.episode is not None:
            detail = f"{media.title} - S{media.season or 1:02d}E{media.episode:02d}"
        else:
            detail = media.title if media.year is None else f"{media.title} ({media.year})"

        text = (
            "✅ Contenido añadido a Emby\n"
            f"📚 Biblioteca: {category}\n"
            f"🎬 Título: {detail}\n"
            f"📁 Ruta: {remote_path}"
        )

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                },
                timeout=8,
            )
            response.raise_for_status()
            logging.info("Notificación Telegram enviada")
        except Exception:
            logging.exception("Error enviando notificación Telegram")

    def process_file(self, path: Path):
        if self.should_ignore(path):
            logging.debug("Ignorado: %s", path)
            return

        if not self.is_stable(path):
            logging.info("Archivo aún en copia o demasiado reciente: %s", path)
            return

        media = self.classify(path)
        if media.category == "unknown":
            self.quarantine(path, "No se pudo clasificar con suficiente confianza")
            return

        remote_path = self.uploader.build_remote_path(media)
        logging.info("Clasificado: %s -> %s | Título=%s", path.name, media.category, media.title)
        logging.info("Destino remoto: %s", remote_path)

        if self.dry_run:
            logging.info("[DRY-RUN] Se subiría: %s -> %s", path, remote_path)
            return

        if self.uploader.exists(media.category, remote_path):
            self.quarantine(path, f"El archivo remoto ya existe: {remote_path}")
            return

        self.uploader.upload_file(path, media.category, remote_path)
        path.unlink()
        logging.info("Subido y eliminado localmente: %s", path)

        self.notify_telegram(media, remote_path)

        self.cleanup_download_folder(path)

    def scan_once(self):
        found_any = False
        for item in sorted(INBOX_DIR.rglob("*")):
            if item.is_dir():
                continue
            found_any = True
            self.process_file(item)

        if not found_any:
            logging.info("No se encontraron archivos dentro de %s", INBOX_DIR)

        self.cleanup_empty_folders()

    def run_daemon(self):
        logging.info("Modo daemon iniciado. Escaneando %s cada %s segundos.", INBOX_DIR, SCAN_INTERVAL_SECONDS)
        while True:
            try:
                self.scan_once()
            except Exception:
                logging.exception("Error durante el escaneo")
            time.sleep(SCAN_INTERVAL_SECONDS)


def setup_logging(verbose: bool = False):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Organizador local para Emby con subida SFTP")
    parser.add_argument("--scan-once", action="store_true", help="Ejecuta un único escaneo")
    parser.add_argument("--daemon", action="store_true", help="Modo continuo")
    parser.add_argument("--dry-run", action="store_true", help="No mueve ni sube archivos")
    parser.add_argument("--verbose", action="store_true", help="Más detalle en logs")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.scan_once and not args.daemon:
        args.scan_once = True

    setup_logging(args.verbose)
    organizer = MediaOrganizer(dry_run=args.dry_run)

    try:
        if args.scan_once:
            organizer.scan_once()
        elif args.daemon:
            organizer.run_daemon()
    finally:
        organizer.shutdown()


if __name__ == "__main__":
    main()
