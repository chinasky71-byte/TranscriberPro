# -*- coding: utf-8 -*-
"""
Library Scanner - Subtitle Converter
Converte sottotitoli ASS/SSA embedded nei file MKV in formato SRT via FFmpeg.
Opera solo su .mkv; i formati bitmap (PGS/VOBSUB) vengono ignorati.
"""
import json
import logging
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from sqlalchemy import select, or_

import re

from library_scanner.config import Config
from library_scanner.database import get_db
from library_scanner.models import VideoFile, ConversionLog


def _srt_track_title(orig_title: str) -> str:
    """Converte il titolo di una traccia ASS/SSA in titolo SRT.
    Es: 'Italiano ASS' → 'Italiano SRT'
    """
    if not orig_title:
        return ""
    cleaned = re.sub(r'\b(pgs|vobsub|ass|ssa)\b', '', orig_title, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return f"{cleaned} SRT" if cleaned else "SRT"

logger = logging.getLogger(__name__)


class SubtitleConverter:
    """
    Converte sottotitoli ASS/SSA → SRT nei file MKV via FFmpeg.
    Video e audio vengono copiati (nessuna ricodifica).
    Il file originale viene sostituito atomicamente solo su successo.
    """

    def __init__(self):
        self._running = False
        self._cancelled = False
        self._progress_callback: Optional[Callable] = None
        self._current_proc: Optional[subprocess.Popen] = None
        self._current_file: str = ""
        self._done_count: int = 0
        self._total_count: int = 0
        self._error_count: int = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def progress(self) -> dict:
        return {
            "running": self._running,
            "current_file": self._current_file,
            "done": self._done_count,
            "total": self._total_count,
            "errors": self._error_count,
        }

    def cancel(self):
        self._cancelled = True
        if self._current_proc:
            try:
                self._current_proc.kill()
            except Exception:
                pass
        logger.info("SubtitleConverter: cancellazione richiesta")

    def run_conversion(self, video_ids: Optional[list] = None,
                       progress_callback: Optional[Callable] = None) -> dict:
        """
        Avvia conversione in batch.
        Se video_ids è None converte tutti i file con has_italian_convertible_subs=True
        e conversion_status non 'done'/'skipped'.
        """
        if self._running:
            return {"status": "already_running"}

        self._running = True
        self._cancelled = False
        self._progress_callback = progress_callback
        self._done_count = 0
        self._error_count = 0

        stats = {"status": "running", "total": 0, "done": 0, "failed": 0, "skipped": 0}

        try:
            with get_db() as db:
                q = select(VideoFile).where(VideoFile.has_italian_convertible_subs == True)
                if video_ids:
                    q = q.where(VideoFile.id.in_(video_ids))
                else:
                    q = q.where(
                        or_(
                            VideoFile.conversion_status == None,
                            VideoFile.conversion_status == "pending",
                            VideoFile.conversion_status == "failed",
                        )
                    )
                files = db.execute(q).scalars().all()

            self._total_count = len(files)
            stats["total"] = self._total_count
            logger.info(f"SubtitleConverter: {self._total_count} file da convertire")

            for i, vf in enumerate(files):
                if self._cancelled:
                    stats["status"] = "cancelled"
                    break

                self._current_file = vf.filename
                self._notify(
                    f"Conversione {i + 1}/{self._total_count}: {vf.filename}",
                    int(i / max(self._total_count, 1) * 100),
                )

                result = self._convert_file(vf)
                if result == "done":
                    stats["done"] += 1
                    self._done_count += 1
                elif result == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
                    self._error_count += 1

            if not self._cancelled:
                stats["status"] = "completed"

        except Exception as e:
            logger.error(f"SubtitleConverter batch error: {e}", exc_info=True)
            stats["status"] = "failed"
        finally:
            self._running = False
            self._cancelled = False
            self._current_proc = None
            self._current_file = ""

        return stats

    def _convert_file(self, vf: VideoFile) -> str:
        """
        Converte un singolo file.
        Returns: 'done' | 'skipped' | 'failed'
        """
        video_path = Path(vf.linux_path)

        # Solo MKV: mp4/avi hanno supporto limitato ai codec subtitle
        if video_path.suffix.lower() != ".mkv":
            logger.info(f"  Skip {vf.filename}: non è MKV ({video_path.suffix})")
            self._update_status(vf.id, "skipped", "Non è un file MKV")
            return "skipped"

        if not video_path.exists():
            logger.warning(f"  File non trovato su disco: {video_path}")
            self._update_status(vf.id, "failed", "File non trovato su disco")
            return "failed"

        # Controlla spazio disco (105% del file per sicurezza)
        required_bytes = int(video_path.stat().st_size * 1.05)
        free_bytes = shutil.disk_usage(video_path.parent).free
        if free_bytes < required_bytes:
            msg = (
                f"Spazio insufficiente: {free_bytes / (1024**3):.1f} GB liberi, "
                f"{required_bytes / (1024**3):.1f} GB richiesti"
            )
            logger.warning(f"  {msg}")
            self._update_status(vf.id, "failed", msg)
            return "failed"

        # Legge stream info
        try:
            streams = json.loads(vf.sub_formats_json or "[]")
        except Exception:
            streams = []

        if not streams:
            logger.warning(f"  {vf.filename}: sub_formats_json vuoto, skip")
            self._update_status(vf.id, "skipped", "sub_formats_json vuoto")
            return "skipped"

        # Elaboriamo SOLO le tracce ASS/SSA italiane (stessa regola dei bitmap PGS/VOBSUB).
        ita_conv = self._italian_convertible(streams)
        if not ita_conv:
            logger.info(f"  Skip {vf.filename}: nessun ASS/SSA italiano da convertire")
            self._update_status(vf.id, "skipped", "Nessun ASS/SSA italiano")
            return "skipped"

        cmd = self._build_ffmpeg_cmd(video_path, streams)
        temp_path = Path(str(video_path) + ".converting")

        logger.info(f"  Avvio conversione: {vf.filename}")
        self._update_status(vf.id, "converting")
        log_id = self._create_log_entry(vf.id)
        start = time.time()

        try:
            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            _, stderr = self._current_proc.communicate(
                timeout=Config.CONVERSION_TIMEOUT_S
            )
            rc = self._current_proc.returncode
            self._current_proc = None

            if self._cancelled:
                if temp_path.exists():
                    temp_path.unlink()
                return "failed"

            if rc != 0:
                if temp_path.exists():
                    temp_path.unlink()
                error_msg = (stderr.strip()[-400:] if stderr else "FFmpeg errore sconosciuto")
                logger.error(f"  FFmpeg fallito (rc={rc}): {error_msg}")
                self._update_status(vf.id, "failed", error_msg)
                self._finish_log(log_id, "failed", error_msg, time.time() - start)
                return "failed"

            if not temp_path.exists() or temp_path.stat().st_size < 1024:
                if temp_path.exists():
                    temp_path.unlink()
                msg = "File di output non valido o troppo piccolo"
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                return "failed"

            # Sostituisce l'originale
            temp_path.replace(video_path)
            duration = time.time() - start
            logger.info(f"  ✓ Convertito in {duration:.1f}s: {vf.filename}")

            self._update_status(
                vf.id, "done",
                conversion_done_at=datetime.now(timezone.utc)
            )
            self._finish_log(log_id, "done", None, duration)
            # Restano sub convertibili se c'è ancora ASS/SSA NON italiano (non lo tocchiamo).
            remaining_conv = any(
                isinstance(s, dict)
                and s.get("convertible")
                and (s.get("codec") or "").lower() in Config.CONVERTIBLE_SUB_CODECS
                and (s.get("language") or "").lower().strip() not in Config.ITALIAN_LANG_CODES
                for s in streams
            )
            self._post_conversion_update(vf.id, remaining_conv)
            return "done"

        except subprocess.TimeoutExpired:
            if self._current_proc:
                self._current_proc.kill()
            self._current_proc = None
            if temp_path.exists():
                temp_path.unlink()
            msg = f"Timeout FFmpeg ({Config.CONVERSION_TIMEOUT_S}s)"
            self._update_status(vf.id, "failed", msg)
            self._finish_log(log_id, "failed", msg, time.time() - start)
            return "failed"

        except Exception as e:
            self._current_proc = None
            if temp_path.exists():
                temp_path.unlink()
            msg = str(e)
            self._update_status(vf.id, "failed", msg)
            self._finish_log(log_id, "failed", msg, time.time() - start)
            logger.error(f"  Errore inatteso: {e}", exc_info=True)
            return "failed"

    @staticmethod
    def _italian_convertible(streams: list) -> list:
        """Restituisce le tracce ASS/SSA italiane (le sole da convertire)."""
        out = []
        for s in streams:
            if not isinstance(s, dict):
                continue
            codec = (s.get("codec") or "").lower()
            lang = (s.get("language") or "").lower().strip()
            if (s.get("convertible")
                    and codec in Config.CONVERTIBLE_SUB_CODECS
                    and lang in Config.ITALIAN_LANG_CODES):
                out.append(s)
        return out

    def _build_ffmpeg_cmd(self, video_path: Path, streams: list) -> list:
        """
        Costruisce il comando FFmpeg (conversione in-place, stesse regole dei PGS/VOBSUB).

        Mantiene TUTTI gli stream del file (`-map 0 -c copy`: video, audio, altri
        sottotitoli — testo e bitmap —, allegati/font, capitoli) e transcodifica in
        SRT SOLO le tracce ASS/SSA ITALIANE, sovrascrivendole nella stessa posizione.
        Il titolo originale viene copiato con suffisso 'SRT'; lingua e disposition
        (forced) sono preservate automaticamente da `-c copy`.
        """
        # Ordiniamo per index: con `-map 0` l'indice subtitle-relative (s:N) di output
        # coincide con questa posizione, così `-c:s:N` colpisce la traccia giusta.
        all_subs = sorted(
            [s for s in streams if isinstance(s, dict)],
            key=lambda s: s.get("index") if s.get("index") is not None else 0,
        )

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-map", "0",
            "-c", "copy",
        ]

        for rel_idx, stream in enumerate(all_subs):
            codec = (stream.get("codec") or "").lower()
            lang = (stream.get("language") or "").lower().strip()
            if (stream.get("convertible")
                    and codec in Config.CONVERTIBLE_SUB_CODECS
                    and lang in Config.ITALIAN_LANG_CODES):
                cmd += [f"-c:s:{rel_idx}", "srt"]
                srt_title = _srt_track_title((stream.get("title") or "").strip())
                if srt_title:
                    cmd += [f"-metadata:s:s:{rel_idx}", f"title={srt_title}"]

        cmd += ["-f", "matroska", str(video_path) + ".converting"]
        return cmd

    def _update_status(self, video_id: int, status: str,
                       error: str = None,
                       conversion_done_at: Optional[datetime] = None):
        try:
            with get_db() as db:
                vf = db.get(VideoFile, video_id)
                if vf:
                    vf.conversion_status = status
                    if error is not None:
                        vf.conversion_error = error
                    if conversion_done_at:
                        vf.conversion_done_at = conversion_done_at
        except Exception as e:
            logger.error(f"_update_status error: {e}")

    def _create_log_entry(self, video_id: int) -> Optional[int]:
        try:
            with get_db() as db:
                entry = ConversionLog(
                    video_id=video_id,
                    started_at=datetime.now(timezone.utc),
                    status="running",
                )
                db.add(entry)
                db.flush()
                return entry.id
        except Exception as e:
            logger.error(f"_create_log_entry error: {e}")
            return None

    def _finish_log(self, log_id: Optional[int], status: str,
                    error: Optional[str], duration: float):
        if not log_id:
            return
        try:
            with get_db() as db:
                entry = db.get(ConversionLog, log_id)
                if entry:
                    entry.finished_at = datetime.now(timezone.utc)
                    entry.status = status
                    entry.error = error
                    entry.duration_seconds = round(duration, 1)
        except Exception as e:
            logger.error(f"_finish_log error: {e}")

    def _post_conversion_update(self, video_id: int, remaining_convertible: bool = False):
        """Dopo conversione riuscita: aggiorna i flag del file nel DB.

        `remaining_convertible`: True se restano tracce ASS/SSA NON italiane (non
        convertite di proposito) → il flag has_convertible_subs resta acceso.
        """
        try:
            with get_db() as db:
                vf = db.get(VideoFile, video_id)
                if vf:
                    vf.has_convertible_subs = remaining_convertible
                    # L'ASS/SSA italiano è stato convertito in SRT → esce dalla lista.
                    vf.has_italian_convertible_subs = False
                    vf.has_italian_text_sub = True
                    vf.has_any_italian_sub = True
        except Exception as e:
            logger.error(f"_post_conversion_update error: {e}")

    def _notify(self, message: str, percent: int):
        if self._progress_callback:
            try:
                self._progress_callback(message, percent)
            except Exception:
                pass


# Singleton
_converter_instance: Optional[SubtitleConverter] = None


def get_converter() -> SubtitleConverter:
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = SubtitleConverter()
    return _converter_instance