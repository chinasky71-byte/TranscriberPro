# -*- coding: utf-8 -*-
"""
Library Scanner - Scanner Filesystem
Scansiona le directory configurate, trova file video, verifica sottotitoli
e aggiorna il database.
"""
import json
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
from library_scanner.subtitle_checker import check_all_subtitles, detect_subtitle_streams_full

logger = logging.getLogger(__name__)


class LibraryScanner:
    """Scanner principale della libreria video."""

    def __init__(self):
        self._running = False
        self._cancelled = False
        self._progress_callback: Optional[Callable] = None
        self._files_total: int = 0
        self._files_processed: int = 0
        self._current_file: str = ""

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def progress(self) -> dict:
        total = self._files_total
        processed = self._files_processed
        percent = int(processed / total * 100) if total > 0 else 0
        return {
            "files_total": total,
            "files_processed": processed,
            "percent": percent,
            "current_file": self._current_file,
        }

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
        self._files_total = 0
        self._files_processed = 0
        self._current_file = ""

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

            # ── FASE 1: pre-conteggio globale su TUTTI i percorsi ──
            # Enumera i file di ogni directory abilitata PRIMA di elaborare, così
            # _files_total è il totale globale fin dall'inizio e la barra non si
            # "resetta" passando da un percorso al successivo. L'enumerazione è
            # fatta una sola volta: le liste raccolte vengono riusate in Fase 2.
            collected = []  # list[(scan_dir, [Path], [error_details])]
            for scan_dir in directories:
                if self._cancelled:
                    stats["status"] = "cancelled"
                    break
                self._current_file = f"Conteggio: {scan_dir.label}"
                self._notify(f"Conteggio file: {scan_dir.label}", 0)
                paths, errs = self._collect_video_files(scan_dir)
                collected.append((scan_dir, paths, errs))
                self._files_total += len(paths)
            logger.info(
                f"Totale file da scansionare su {len(collected)} percorsi: {self._files_total}"
            )

            # ── FASE 2: elaborazione con totale globale fisso ──
            for scan_dir, paths, errs in collected:
                if self._cancelled:
                    stats["status"] = "cancelled"
                    break

                self._notify(f"Scansione: {scan_dir.label}", self.progress["percent"])
                dir_stats = self._scan_directory(scan_dir, paths, errs)

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

    def _collect_video_files(self, scan_dir: ScanDirectory) -> tuple:
        """Enumera i file video di una directory SENZA elaborarli (Fase 1).

        Ritorna: (list[Path], list[str] error_details). L'elaborazione vera
        (ffprobe + DB) avviene poi in _scan_directory sulla lista qui raccolta.
        Separando conteggio ed elaborazione, _files_total può essere il totale
        globale di TUTTI i percorsi prima che la barra parta.
        """
        errors = []
        linux_path = Path(scan_dir.linux_path)
        if not linux_path.exists():
            msg = f"Directory non trovata: {scan_dir.linux_path}"
            logger.warning(msg)
            return [], [msg]

        if not linux_path.is_dir():
            msg = f"Non e' una directory: {scan_dir.linux_path}"
            logger.warning(msg)
            return [], [msg]

        logger.info(f"Conteggio directory: {scan_dir.label} ({scan_dir.linux_path})")

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
            errors.append(msg)

        logger.info(f"  Trovati {len(video_files)} file video in {scan_dir.label}")
        return video_files, errors

    def _scan_directory(self, scan_dir: ScanDirectory,
                        video_files: list, collect_errors: list) -> dict:
        """Elabora i file video GIÀ raccolti di una directory (Fase 2) e aggiorna il DB."""
        dir_stats = {
            "found": len(video_files), "new": 0, "updated": 0,
            "with_subs": 0, "without_subs": 0,
            "errors": len(collect_errors), "error_details": list(collect_errors)
        }

        if not video_files:
            return dir_stats

        logger.info(f"Elaborazione directory: {scan_dir.label} ({len(video_files)} file)")

        # Processa ogni file video
        with get_db() as db:
            for video_path in video_files:
                if self._cancelled:
                    break
                self._current_file = video_path.name
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
                finally:
                    self._files_processed += 1
                    self._notify(f"Scansione {scan_dir.label}", self.progress["percent"])

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

        # Verifica sottotitoli (presenza) + analisi formato codec
        sub_result    = check_all_subtitles(video_path)
        stream_result = detect_subtitle_streams_full(video_path)

        # has_any_italian_sub CORRETTO: solo sottotitoli testo (esclude bitmap PGS/VOBSUB)
        has_italian_text_sub = (
            sub_result["has_external"]
            or stream_result["has_italian_text_embedded"]
        )
        has_any_italian_sub = has_italian_text_sub

        # JSON stream info (solo se ci sono stream da segnalare)
        sub_formats_json = (
            json.dumps(stream_result["streams"], ensure_ascii=False)
            if stream_result["streams"] else None
        )

        # Errore combinato
        errors = [e for e in (sub_result["error"], stream_result["error"]) if e]
        combined_error = "; ".join(errors) or None

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
                has_any_italian_sub=has_any_italian_sub,
                has_italian_text_sub=has_italian_text_sub,
                has_italian_bitmap_sub=stream_result["has_italian_bitmap_sub"],
                has_convertible_subs=stream_result["has_convertible_subs"],
                has_italian_convertible_subs=stream_result["has_italian_convertible"],
                sub_formats_json=sub_formats_json,
                subtitle_check_error=combined_error,
                media_type=scan_dir.media_type,
                first_seen=now,
                last_scanned=now,
            )
            db.add(vf)
            db.flush()
            logger.debug(
                f"  Nuovo: {video_path.name} "
                f"(sub_testo={has_italian_text_sub}, "
                f"bitmap={stream_result['has_italian_bitmap_sub']}, "
                f"convertibile={stream_result['has_convertible_subs']})"
            )
            return "new"
        else:
            # File esistente — aggiorna (non tocca conversion_status/error/done_at)
            existing.last_scanned = now
            existing.file_size = file_stat.st_size
            existing.file_modified = file_modified
            existing.windows_path = windows_path
            existing.relative_path = relative_path
            existing.has_italian_srt = sub_result["has_external"]
            existing.has_italian_embedded = sub_result["has_embedded"]
            existing.has_any_italian_sub = has_any_italian_sub
            existing.has_italian_text_sub = has_italian_text_sub
            existing.has_italian_bitmap_sub = stream_result["has_italian_bitmap_sub"]
            existing.has_convertible_subs = stream_result["has_convertible_subs"]
            existing.has_italian_convertible_subs = stream_result["has_italian_convertible"]
            existing.sub_formats_json = sub_formats_json
            existing.subtitle_check_error = combined_error
            # Reset conversion_status solo se la sorgente non ha più ASS/SSA
            if not stream_result["has_convertible_subs"]:
                existing.conversion_status = None
                existing.conversion_error = None
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
