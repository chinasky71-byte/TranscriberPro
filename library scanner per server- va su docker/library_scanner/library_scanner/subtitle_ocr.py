# -*- coding: utf-8 -*-
"""
Library Scanner - Subtitle OCR
Converte sottotitoli bitmap PGS embedded nei file MKV in SRT testuale via pgsrip.
Richiede: tesseract-ocr, tesseract-ocr-ita, mkvtoolnix in PATH (installati nel Dockerfile).
Opera solo su file con has_italian_bitmap_sub=True AND has_italian_text_sub=False.
Output: sidecar <stem>.it.srt accanto al video (nessun remux).
"""
import json
import logging
import shutil
import subprocess
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from sqlalchemy import select, or_

from library_scanner.config import Config
from library_scanner.database import get_db
from library_scanner.models import VideoFile, OcrLog

logger = logging.getLogger(__name__)

_PGS_CODECS   = {'hdmv_pgs_subtitle', 'pgssub'}
_VOBSUB_CODECS = {'dvd_subtitle', 'dvdsub'}
_ITALIAN_CODES = {'ita', 'it', 'italian', 'italiano'}
_LANG_PRIORITY = ['ita', 'eng', 'spa', 'fra', 'deu', 'por', 'rus', 'jpn']


class SubtitleOcr:
    """
    Converte sottotitoli bitmap PGS → SRT testuale via pgsrip + Tesseract.
    Stessa interfaccia di SubtitleConverter per facile integrazione con API e scheduler.
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
        logger.info("SubtitleOcr: cancellazione richiesta")

    def run_ocr(self, video_ids: Optional[list] = None,
                progress_callback: Optional[Callable] = None) -> dict:
        """
        Avvia OCR in batch.
        Se video_ids è None elabora tutti i file con has_italian_bitmap_sub=True
        e has_italian_text_sub=False e ocr_status non 'done'/'skipped'.
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
                q = (
                    select(VideoFile)
                    .where(VideoFile.has_italian_bitmap_sub == True)
                    .where(VideoFile.has_italian_text_sub == False)
                )
                if video_ids:
                    q = q.where(VideoFile.id.in_(video_ids))
                else:
                    q = q.where(
                        or_(
                            VideoFile.ocr_status == None,
                            VideoFile.ocr_status == "pending",
                            VideoFile.ocr_status == "failed",
                        )
                    )
                files = db.execute(q).scalars().all()

            self._total_count = len(files)
            stats["total"] = self._total_count
            logger.info(f"SubtitleOcr: {self._total_count} file da elaborare")

            for i, vf in enumerate(files):
                if self._cancelled:
                    stats["status"] = "cancelled"
                    break

                self._current_file = vf.filename
                self._notify(
                    f"OCR {i + 1}/{self._total_count}: {vf.filename}",
                    int(i / max(self._total_count, 1) * 100),
                )

                result = self._ocr_file(vf)
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
            logger.error(f"SubtitleOcr batch error: {e}", exc_info=True)
            stats["status"] = "failed"
        finally:
            self._running = False
            self._cancelled = False
            self._current_proc = None
            self._current_file = ""

        return stats

    # ── File singolo ──────────────────────────────────────────────────────────

    def _ocr_file(self, vf: VideoFile) -> str:
        """
        Elabora un singolo file.
        Returns: 'done' | 'skipped' | 'failed'
        """
        video_path = Path(vf.linux_path)

        if video_path.suffix.lower() != ".mkv":
            logger.info(f"  Skip {vf.filename}: non è MKV")
            self._update_status(vf.id, "skipped", "Non è un file MKV")
            return "skipped"

        if not video_path.exists():
            logger.warning(f"  File non trovato: {video_path}")
            self._update_status(vf.id, "failed", "File non trovato su disco")
            return "failed"

        stream = self._find_best_bitmap_stream(vf.sub_formats_json)
        if not stream:
            logger.info(f"  {vf.filename}: nessun bitmap italiano trovato nel JSON, skip")
            self._update_status(vf.id, "skipped", "Nessun bitmap italiano in sub_formats_json")
            return "skipped"

        codec = stream.get("codec", "").lower()
        if codec in _PGS_CODECS:
            return self._ocr_pgs(vf, video_path)
        elif codec in _VOBSUB_CODECS:
            return self._ocr_vobsub(vf, video_path, stream["index"])
        else:
            msg = f"Codec bitmap non supportato: {codec}"
            logger.warning(f"  {vf.filename}: {msg}")
            self._update_status(vf.id, "skipped", msg)
            return "skipped"

    def _find_best_bitmap_stream(self, sub_formats_json: Optional[str]) -> Optional[dict]:
        """
        Restituisce il miglior stream bitmap italiano, o None.
        Priorità lingua: ita > eng > spa > ...
        Preferisce PGS su VOBSUB a parità di lingua.
        """
        try:
            streams = json.loads(sub_formats_json or "[]")
        except Exception:
            return None

        bitmap = [
            s for s in streams
            if isinstance(s, dict) and
            s.get("codec", "").lower() in (_PGS_CODECS | _VOBSUB_CODECS)
        ]
        if not bitmap:
            return None

        def _lang(s):
            return str(s.get("language", s.get("lang", "")) or "").lower()

        # Cerca prima ita, poi per priorità
        for target in _LANG_PRIORITY:
            for s in bitmap:
                if _lang(s) in _ITALIAN_CODES if target == "ita" else _lang(s) == target:
                    return s

        return bitmap[0]  # fallback: primo bitmap disponibile

    # ── PGS via pgsrip ───────────────────────────────────────────────────────

    def _ocr_pgs(self, vf: VideoFile, video_path: Path) -> str:
        """
        OCR sottotitoli PGS italiani via pgsrip.
        pgsrip usa mkvextract + Tesseract e produce <stem>.ita.srt accanto al video.
        """
        log_id = self._create_log(vf.id, "pgs")
        self._update_status(vf.id, "ocring")
        start = time.time()

        # pgsrip output: <video_stem>.ita.srt nella stessa directory del video
        pgsrip_out = video_path.with_name(f"{video_path.stem}.ita.srt")
        it_srt     = video_path.with_name(f"{video_path.stem}.it.srt")

        # Rimuovi output precedente se esiste (--overwrite non sempre sufficiente)
        if pgsrip_out.exists():
            pgsrip_out.unlink()

        cmd = [
            "python", "-m", "pgsrip",
            "-l", Config.OCR_LANGUAGE,
            "--overwrite",
            str(video_path),
        ]

        logger.info(f"  pgsrip PGS: {vf.filename}")
        try:
            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = self._current_proc.communicate(timeout=Config.OCR_TIMEOUT_S)
            rc = self._current_proc.returncode
            self._current_proc = None

            if self._cancelled:
                if pgsrip_out.exists():
                    pgsrip_out.unlink()
                return "failed"

            if rc != 0:
                msg = (stderr.strip()[-400:] or f"pgsrip exit {rc}")
                logger.error(f"  pgsrip fallito (rc={rc}): {msg}")
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                return "failed"

            # Verifica output
            if not pgsrip_out.exists() or pgsrip_out.stat().st_size < 10:
                if pgsrip_out.exists():
                    pgsrip_out.unlink()
                msg = "pgsrip non ha prodotto output (nessuna traccia ita?)"
                logger.warning(f"  {vf.filename}: {msg}")
                self._update_status(vf.id, "skipped", msg)
                self._finish_log(log_id, "skipped", msg, time.time() - start)
                return "skipped"

            # Rinomina .ita.srt → .it.srt
            pgsrip_out.replace(it_srt)
            duration = time.time() - start
            logger.info(f"  ✓ PGS OCR in {duration:.1f}s: {it_srt.name}")

            self._update_status(vf.id, "done", conversion_done_at=datetime.now(timezone.utc))
            self._finish_log(log_id, "done", None, duration)
            self._post_ocr_update(vf.id)
            return "done"

        except subprocess.TimeoutExpired:
            if self._current_proc:
                self._current_proc.kill()
            self._current_proc = None
            if pgsrip_out.exists():
                pgsrip_out.unlink()
            msg = f"Timeout pgsrip ({Config.OCR_TIMEOUT_S}s)"
            self._update_status(vf.id, "failed", msg)
            self._finish_log(log_id, "failed", msg, time.time() - start)
            return "failed"

        except Exception as e:
            self._current_proc = None
            if pgsrip_out.exists():
                pgsrip_out.unlink()
            msg = str(e)
            self._update_status(vf.id, "failed", msg)
            self._finish_log(log_id, "failed", msg, time.time() - start)
            logger.error(f"  Errore PGS OCR: {e}", exc_info=True)
            return "failed"

    # ── VOBSUB via mkvextract + vobsub2srt ───────────────────────────────────

    def _ocr_vobsub(self, vf: VideoFile, video_path: Path, stream_idx: int) -> str:
        """
        OCR sottotitoli VOBSUB italiani: mkvextract → .idx/.sub → vobsub2srt.
        Richiede 'vobsub2srt' installato (apt).
        """
        log_id = self._create_log(vf.id, "vobsub")
        self._update_status(vf.id, "ocring")
        start = time.time()

        it_srt = video_path.with_name(f"{video_path.stem}.it.srt")

        # vobsub2srt è opzionale (non disponibile in tutti i repo Debian)
        if not shutil.which("vobsub2srt"):
            msg = "vobsub2srt non trovato nel PATH — installa il pacchetto sul server"
            logger.warning(f"  {vf.filename}: {msg}")
            self._update_status(vf.id, "skipped", msg)
            self._finish_log(log_id, "skipped", msg, time.time() - start)
            return "skipped"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_base = Path(tmpdir) / "vobsub"

            # Step 1: estrazione .idx/.sub con mkvextract
            extract_cmd = [
                "mkvextract", "tracks", str(video_path),
                f"{stream_idx}:{tmp_base}",
            ]
            logger.info(f"  mkvextract VOBSUB stream {stream_idx}: {vf.filename}")
            try:
                self._current_proc = subprocess.Popen(
                    extract_cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace",
                )
                _, stderr = self._current_proc.communicate(timeout=Config.OCR_TIMEOUT_S)
                rc = self._current_proc.returncode
                self._current_proc = None

                if rc != 0 or self._cancelled:
                    msg = f"mkvextract fallito (rc={rc})" if rc != 0 else "Annullato"
                    self._update_status(vf.id, "failed", msg)
                    self._finish_log(log_id, "failed", msg, time.time() - start)
                    return "failed"

                idx_file = tmp_base.with_suffix(".idx")
                if not idx_file.exists():
                    msg = "mkvextract non ha prodotto .idx"
                    self._update_status(vf.id, "failed", msg)
                    self._finish_log(log_id, "failed", msg, time.time() - start)
                    return "failed"

            except subprocess.TimeoutExpired:
                if self._current_proc:
                    self._current_proc.kill()
                self._current_proc = None
                msg = f"Timeout mkvextract ({Config.OCR_TIMEOUT_S}s)"
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                return "failed"

            # Step 2: OCR con vobsub2srt
            vobsub2srt_cmd = [
                "vobsub2srt",
                "--language", Config.OCR_LANGUAGE,
                str(tmp_base),
            ]
            logger.info(f"  vobsub2srt: {vf.filename}")
            try:
                self._current_proc = subprocess.Popen(
                    vobsub2srt_cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace",
                )
                _, stderr = self._current_proc.communicate(timeout=Config.OCR_TIMEOUT_S)
                rc = self._current_proc.returncode
                self._current_proc = None

                if self._cancelled:
                    return "failed"

                out_srt = tmp_base.with_suffix(".srt")
                if rc != 0 or not out_srt.exists() or out_srt.stat().st_size < 10:
                    msg = (stderr.strip()[-400:] or f"vobsub2srt exit {rc}") if rc != 0 else \
                          "vobsub2srt non ha prodotto output"
                    logger.warning(f"  {vf.filename}: {msg}")
                    self._update_status(vf.id, "failed", msg)
                    self._finish_log(log_id, "failed", msg, time.time() - start)
                    return "failed"

                # Copia in destinazione finale
                shutil.copy2(out_srt, it_srt)

            except subprocess.TimeoutExpired:
                if self._current_proc:
                    self._current_proc.kill()
                self._current_proc = None
                msg = f"Timeout vobsub2srt ({Config.OCR_TIMEOUT_S}s)"
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                return "failed"

            except Exception as e:
                self._current_proc = None
                msg = str(e)
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                logger.error(f"  Errore VOBSUB OCR: {e}", exc_info=True)
                return "failed"

        duration = time.time() - start
        logger.info(f"  ✓ VOBSUB OCR in {duration:.1f}s: {it_srt.name}")
        self._update_status(vf.id, "done", conversion_done_at=datetime.now(timezone.utc))
        self._finish_log(log_id, "done", None, duration)
        self._post_ocr_update(vf.id)
        return "done"

    # ── Helpers DB ─────────────────────────────────────────────────────────────

    def _update_status(self, video_id: int, status: str,
                       error: str = None,
                       conversion_done_at: Optional[datetime] = None):
        try:
            with get_db() as db:
                vf = db.get(VideoFile, video_id)
                if vf:
                    vf.ocr_status = status
                    if error is not None:
                        vf.ocr_error = error
                    if conversion_done_at:
                        vf.ocr_done_at = conversion_done_at
        except Exception as e:
            logger.error(f"_update_status OCR error: {e}")

    def _create_log(self, video_id: int, codec_type: str) -> Optional[int]:
        try:
            with get_db() as db:
                entry = OcrLog(
                    video_id=video_id,
                    codec_type=codec_type,
                    started_at=datetime.now(timezone.utc),
                    status="running",
                )
                db.add(entry)
                db.flush()
                return entry.id
        except Exception as e:
            logger.error(f"_create_log OCR error: {e}")
            return None

    def _finish_log(self, log_id: Optional[int], status: str,
                    error: Optional[str], duration: float):
        if not log_id:
            return
        try:
            with get_db() as db:
                entry = db.get(OcrLog, log_id)
                if entry:
                    entry.finished_at = datetime.now(timezone.utc)
                    entry.status = status
                    entry.error = error
                    entry.duration_seconds = round(duration, 1)
        except Exception as e:
            logger.error(f"_finish_log OCR error: {e}")

    def _post_ocr_update(self, video_id: int):
        """Dopo OCR riuscito: segna il file come avente sottotitolo testo italiano."""
        try:
            with get_db() as db:
                vf = db.get(VideoFile, video_id)
                if vf:
                    vf.has_italian_text_sub = True
                    vf.has_any_italian_sub = True
                    vf.has_italian_srt = True
        except Exception as e:
            logger.error(f"_post_ocr_update error: {e}")

    def _notify(self, message: str, percent: int):
        if self._progress_callback:
            try:
                self._progress_callback(message, percent)
            except Exception:
                pass


# Singleton
_ocr_instance: Optional[SubtitleOcr] = None


def get_ocr() -> SubtitleOcr:
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = SubtitleOcr()
    return _ocr_instance
