# -*- coding: utf-8 -*-
"""
Library Scanner - Scanner Filesystem
Scansiona le directory configurate, trova file video, verifica sottotitoli
e aggiorna il database.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from library_scanner.config import Config
from library_scanner.database import get_db
from library_scanner.models import ScanDirectory, VideoFile, ScanLog
from library_scanner.subtitle_checker import check_all_subtitles

logger = logging.getLogger(__name__)


class LibraryScanner:
    """Scanner principale della libreria video."""

    def __init__(self):
        self._running = False
        self._cancelled = False
        self._progress_callback: Optional[Callable] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def cancel(self):
        """Richiede cancellazione della scansione in corso."""
        if self._running:
            self._cancelled = True
            logger.info("Cancellazione scansione richiesta")

    def run_full_scan(self, progress_callback: Optional[Callable] = None) -> dict:
        """
        Esegue una scansione completa di tutte le directory abilitate.

        Args:
            progress_callback: funzione opzionale chiamata con (message, percent)

        Returns:
            dict con statistiche della scansione
        """
        if self._running:
            logger.warning("Scansione gia' in corso, richiesta ignorata")
            return {"status": "already_running"}

        self._running = True
        self._cancelled = False
        self._progress_callback = progress_callback

        scan_log = None
        start_time = time.time()

        stats = {
            "status": "running",
            "directories_scanned": 0,
            "files_found": 0,
            "files_new": 0,
            "files_updated": 0,
            "files_removed": 0,
            "files_with_subs": 0,
            "files_without_subs": 0,
            "errors": 0,
            "error_details": []
        }

        try:
            # Crea log della scansione
            with get_db() as db:
                scan_log = ScanLog(status="running")
                db.add(scan_log)
                db.flush()
                scan_log_id = scan_log.id

            # Recupera directory abilitate
            with get_db() as db:
                directories = db.execute(
                    select(ScanDirectory).where(ScanDirectory.enabled == True)
                ).scalars().all()

                if not directories:
                    logger.info("Nessuna directory abilitata per la scansione")
                    stats["status"] = "no_directories"
                    return stats

                total_dirs = len(directories)
                logger.info(f"Inizio scansione di {total_dirs} directory")

            # Scansiona ogni directory
            for idx, scan_dir in enumerate(directories):
                if self._cancelled:
                    stats["status"] = "cancelled"
                    break

                self._notify(f"Scansione: {scan_dir.label}", int((idx / total_dirs) * 100))
                dir_stats = self._scan_directory(scan_dir)

                stats["directories_scanned"] += 1
                stats["files_found"] += dir_stats["found"]
                stats["files_new"] += dir_stats["new"]
                stats["files_updated"] += dir_stats["updated"]
                stats["files_with_subs"] += dir_stats["with_subs"]
                stats["files_without_subs"] += dir_stats["without_subs"]
                stats["errors"] += dir_stats["errors"]
                stats["error_details"].extend(dir_stats["error_details"])

            # Rimuovi file che non esistono piu'
            removed = self._cleanup_missing_files()
            stats["files_removed"] = removed

            if not self._cancelled:
                stats["status"] = "completed"

            duration = time.time() - start_time
            stats["duration_seconds"] = round(duration, 1)

            # Aggiorna log della scansione
            with get_db() as db:
                log = db.get(ScanLog, scan_log_id)
                if log:
                    log.finished_at = datetime.now(timezone.utc)
                    log.status = stats["status"]
                    log.directories_scanned = stats["directories_scanned"]
                    log.files_found = stats["files_found"]
                    log.files_new = stats["files_new"]
                    log.files_updated = stats["files_updated"]
                    log.files_removed = stats["files_removed"]
                    log.files_with_subs = stats["files_with_subs"]
                    log.files_without_subs = stats["files_without_subs"]
                    log.errors = stats["errors"]
                    log.duration_seconds = stats["duration_seconds"]
                    if stats["error_details"]:
                        log.error_details = "\n".join(stats["error_details"][:50])

            logger.info(
                f"Scansione completata in {stats['duration_seconds']}s: "
                f"{stats['files_found']} trovati, {stats['files_new']} nuovi, "
                f"{stats['files_removed']} rimossi, "
                f"{stats['files_with_subs']} con sub, {stats['files_without_subs']} senza sub"
            )
            self._notify("Scansione completata", 100)
            return stats

        except Exception as e:
            logger.error(f"Errore durante scansione: {e}", exc_info=True)
            stats["status"] = "failed"
            stats["error_details"].append(str(e))

            # Aggiorna log
            try:
                with get_db() as db:
                    log = db.get(ScanLog, scan_log_id)
                    if log:
                        log.finished_at = datetime.now(timezone.utc)
                        log.status = "failed"
                        log.error_details = str(e)
                        log.duration_seconds = time.time() - start_time
            except Exception:
                pass

            return stats
        finally:
            self._running = False
            self._cancelled = False

    def _scan_directory(self, scan_dir: ScanDirectory) -> dict:
        """Scansiona una singola directory e aggiorna il database."""
        dir_stats = {
            "found": 0, "new": 0, "updated": 0,
            "with_subs": 0, "without_subs": 0,
            "errors": 0, "error_details": []
        }

        linux_path = Path(scan_dir.linux_path)
        if not linux_path.exists():
            msg = f"Directory non trovata: {scan_dir.linux_path}"
            logger.warning(msg)
            dir_stats["errors"] += 1
            dir_stats["error_details"].append(msg)
            return dir_stats

        if not linux_path.is_dir():
            msg = f"Non e' una directory: {scan_dir.linux_path}"
            logger.warning(msg)
            dir_stats["errors"] += 1
            dir_stats["error_details"].append(msg)
            return dir_stats

        logger.info(f"Scansione directory: {scan_dir.label} ({scan_dir.linux_path})")

        # Raccogli tutti i file video
        video_files = []
        try:
            iterator = linux_path.rglob("*") if scan_dir.recursive else linux_path.glob("*")
            for item in iterator:
                if self._cancelled:
                    break
                if not item.is_file():
                    continue
                if item.suffix.lower() not in Config.VIDEO_EXTENSIONS:
                    continue
                if item.stat().st_size < Config.MIN_FILE_SIZE_MB * 1024 * 1024:
                    continue
                # Escludi directory particolari
                if self._is_excluded_path(item):
                    continue
                video_files.append(item)
        except PermissionError as e:
            msg = f"Permesso negato: {e}"
            logger.warning(msg)
            dir_stats["errors"] += 1
            dir_stats["error_details"].append(msg)

        logger.info(f"  Trovati {len(video_files)} file video in {scan_dir.label}")
        dir_stats["found"] = len(video_files)

        # Processa ogni file video
        with get_db() as db:
            for video_path in video_files:
                if self._cancelled:
                    break
                try:
                    result = self._process_video_file(db, scan_dir, video_path)
                    if result == "new":
                        dir_stats["new"] += 1
                    elif result == "updated":
                        dir_stats["updated"] += 1

                    # Conta sub
                    vf = db.execute(
                        select(VideoFile).where(VideoFile.linux_path == str(video_path))
                    ).scalar_one_or_none()
                    if vf:
                        if vf.has_any_italian_sub:
                            dir_stats["with_subs"] += 1
                        else:
                            dir_stats["without_subs"] += 1

                except Exception as e:
                    dir_stats["errors"] += 1
                    dir_stats["error_details"].append(f"{video_path.name}: {e}")
                    logger.error(f"  Errore processando {video_path.name}: {e}")

        return dir_stats

    def _process_video_file(self, db: Session, scan_dir: ScanDirectory, video_path: Path) -> str:
        """
        Processa un singolo file video: verifica sottotitoli e aggiorna DB.

        Returns:
            "new" se file nuovo, "updated" se aggiornato, "unchanged" se invariato
        """
        linux_path_str = str(video_path)
        relative_path = str(video_path.relative_to(scan_dir.linux_path))

        # Calcola il path Windows
        windows_path = scan_dir.windows_path.rstrip("\\") + "\\" + relative_path.replace("/", "\\")

        # Cerca file esistente nel DB
        existing = db.execute(
            select(VideoFile).where(VideoFile.linux_path == linux_path_str)
        ).scalar_one_or_none()

        # Verifica sottotitoli
        sub_result = check_all_subtitles(video_path)

        file_stat = video_path.stat()
        file_modified = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc)
        now = datetime.now(timezone.utc)

        if existing is None:
            # Nuovo file
            vf = VideoFile(
                directory_id=scan_dir.id,
                filename=video_path.name,
                linux_path=linux_path_str,
                windows_path=windows_path,
                relative_path=relative_path,
                file_size=file_stat.st_size,
                file_modified=file_modified,
                has_italian_srt=sub_result["has_external"],
                has_italian_embedded=sub_result["has_embedded"],
                has_any_italian_sub=sub_result["has_any"],
                subtitle_check_error=sub_result["error"] or None,
                media_type=scan_dir.media_type,
                first_seen=now,
                last_scanned=now
            )
            db.add(vf)
            db.flush()
            logger.debug(f"  Nuovo: {video_path.name} (sub_ita={sub_result['has_any']})")
            return "new"
        else:
            # File esistente - aggiorna
            existing.last_scanned = now
            existing.file_size = file_stat.st_size
            existing.file_modified = file_modified
            existing.windows_path = windows_path
            existing.relative_path = relative_path
            existing.has_italian_srt = sub_result["has_external"]
            existing.has_italian_embedded = sub_result["has_embedded"]
            existing.has_any_italian_sub = sub_result["has_any"]
            existing.subtitle_check_error = sub_result["error"] or None
            db.flush()
            return "updated"

    def _cleanup_missing_files(self) -> int:
        """Rimuove dal database i file che non esistono piu' su disco."""
        removed = 0
        with get_db() as db:
            all_videos = db.execute(select(VideoFile)).scalars().all()
            for vf in all_videos:
                if not Path(vf.linux_path).exists():
                    logger.debug(f"  Rimosso (non trovato): {vf.filename}")
                    db.delete(vf)
                    removed += 1
        if removed:
            logger.info(f"  Rimossi {removed} file non piu' presenti su disco")
        return removed

    def _is_excluded_path(self, path: Path) -> bool:
        """Verifica se il path contiene directory escluse."""
        parts_lower = {p.lower() for p in path.parts}
        return bool(parts_lower & Config.EXCLUDED_DIR_NAMES)

    def _notify(self, message: str, percent: int):
        """Invia notifica di progresso."""
        if self._progress_callback:
            try:
                self._progress_callback(message, percent)
            except Exception:
                pass


# Istanza singleton
_scanner_instance = None


def get_scanner() -> LibraryScanner:
    """Restituisce l'istanza singleton dello scanner."""
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = LibraryScanner()
    return _scanner_instance
