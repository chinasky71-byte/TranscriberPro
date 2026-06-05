# -*- coding: utf-8 -*-
"""
Library Scanner - Subtitle OCR
Converte sottotitoli bitmap PGS/VOBSUB → SRT via Tesseract.

PGS:    estrazione .sup (mkvextract) → pgsreader → OCR parallelo (ThreadPoolExecutor)
VOBSUB: mkvextract → .idx/.sub → VobSubParser (vendor) → OCR parallelo (ThreadPoolExecutor)

Priorità bassa garantita: i worker OCR chiamano os.nice(10) per thread + ionice
best-effort -n 4 per il processo all'avvio del batch.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, List, Tuple

from sqlalchemy import select, or_

from library_scanner.config import Config
from library_scanner.database import get_db
from library_scanner.models import VideoFile, OcrLog

logger = logging.getLogger(__name__)

_PGS_CODECS    = {'hdmv_pgs_subtitle', 'pgssub'}
_VOBSUB_CODECS = {'dvd_subtitle', 'dvdsub'}
_ITALIAN_CODES = {'ita', 'it', 'italian', 'italiano'}
_LANG_PRIORITY = ['ita', 'eng', 'spa', 'fra', 'deu', 'por', 'rus', 'jpn']

# Vendor pgsreader e vobsub nel package locale
_VENDOR_DIR = Path(__file__).parent / "vendor" / "pgsreader"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

_VOBSUB_VENDOR = Path(__file__).parent / "vendor"
if str(_VOBSUB_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VOBSUB_VENDOR))


# ── Priorità processo ─────────────────────────────────────────────────────────

def _set_low_priority():
    """
    Abbassa la priorità CPU e I/O per il thread/processo chiamante.
    Chiamato all'avvio di ogni batch OCR e dentro i worker Tesseract.

    - os.nice(10): su Linux/NPTL agisce per thread; CPU priority background (cede ai processi attivi).
    - ionice -c 2 -n 7: best-effort, livello 7 (minimo). Il disco serve le code
      normalmente ma gli altri processi vengono prima. Applicato al processo una
      volta sola per batch (non idle class -c 3 che causa starvation su server attivo).
    """
    try:
        os.nice(10)          # best-effort background: cede ai processi attivi ma non affama se il server è parzialmente libero
    except (PermissionError, OSError):
        pass
    try:
        subprocess.run(
            ["ionice", "-c", "2", "-n", "4", "-p", str(os.getpid())],  # metà scala best-effort invece del minimo
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass


# ── OCR helpers (inlined da bitmap_ocr_common) ────────────────────────────────

def _preprocess(img, upscale: int = 2):
    """Prepara immagine PGS per Tesseract: composito nero → Otsu → invert → upscale → bordo."""
    import cv2
    import numpy as np
    from PIL import Image

    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    comp = Image.alpha_composite(bg, rgba).convert("L")
    arr = np.array(comp)
    _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = 255 - th  # testo chiaro su nero → inverti
    th = cv2.resize(th, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


def _ocr_image(pre, language: str) -> str:
    """OCR verbatim single-pass: image_to_data TSV → testo ricostruito."""
    import pytesseract

    data = pytesseract.image_to_data(
        pre, lang=language, config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )
    lines = {}
    for i in range(len(data["text"])):
        w = data["text"][i].strip()
        if not w:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(w)
    return "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))


def _ms_to_srt_ts(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms_ = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_:03d}"


def _events_to_srt(events: List[Tuple[int, int, str]]) -> str:
    """events = [(start_ms, end_ms, text), ...]"""
    parts = []
    for idx, (start, end, text) in enumerate(events, 1):
        if text.strip():
            parts.append(f"{idx}\n{_ms_to_srt_ts(start)} --> {_ms_to_srt_ts(end)}\n{text}\n")
    return "\n".join(parts)


def _ocr_images_parallel(
    images: list,
    language: str,
    workers: int,
    cancel_check=None,
) -> List[str]:
    """OCR in parallelo su lista di PIL.Image. Ogni worker abbassa la propria priorità."""
    n = len(images)
    results = [""] * n
    if n == 0:
        return results

    def _work(i, img):
        _set_low_priority()          # priorità minima per questo worker thread
        pre = _preprocess(img)
        return i, _ocr_image(pre, language)

    ex = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures = [ex.submit(_work, i, img) for i, img in enumerate(images)]
        for fut in as_completed(futures):
            if cancel_check and cancel_check():
                ex.shutdown(wait=False, cancel_futures=True)
                raise InterruptedError("OCR annullato")
            i, text = fut.result()
            results[i] = text
    finally:
        ex.shutdown(wait=False)
    return results


# ── SubtitleOcr ───────────────────────────────────────────────────────────────

class SubtitleOcr:
    """
    Converte sottotitoli bitmap PGS → SRT via pgsreader + Tesseract (parallelo).
    VOBSUB: mkvextract + vobsub2srt (se disponibile in apt, altrimenti skip).
    Stessa interfaccia di SubtitleConverter per integrazione con API e scheduler.
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
        self._skipped_count: int = 0

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
            "skipped": self._skipped_count,
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
        Avvia OCR in batch. Abbassa subito priorità CPU e I/O del processo per
        non interferire con gli altri container durante l'elaborazione.
        """
        if self._running:
            return {"status": "already_running"}

        self._running = True
        self._cancelled = False
        self._progress_callback = progress_callback
        self._done_count = 0
        self._error_count = 0
        self._skipped_count = 0

        # ── Abbassa priorità per l'intero batch ─────────────────────────────
        _set_low_priority()

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
            logger.info(
                f"SubtitleOcr: {self._total_count} file da elaborare "
                f"(nice=10, ionice=best-effort-4, workers={_ocr_workers()})"
            )

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
                    self._skipped_count += 1
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
        video_path = Path(vf.linux_path)

        if video_path.suffix.lower() != ".mkv":
            self._update_status(vf.id, "skipped", "Non è un file MKV")
            return "skipped"

        if not video_path.exists():
            self._update_status(vf.id, "failed", "File non trovato su disco")
            return "failed"

        stream = self._find_best_bitmap_stream(vf.sub_formats_json)
        if not stream:
            self._update_status(vf.id, "skipped", "Nessun bitmap italiano in sub_formats_json")
            return "skipped"

        codec = stream.get("codec", "").lower()
        if codec in _PGS_CODECS:
            return self._ocr_pgs(vf, video_path, stream["index"])
        elif codec in _VOBSUB_CODECS:
            return self._ocr_vobsub(vf, video_path, stream["index"])
        else:
            self._update_status(vf.id, "skipped", f"Codec non supportato: {codec}")
            return "skipped"

    def _find_best_bitmap_stream(self, sub_formats_json: Optional[str]) -> Optional[dict]:
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

        for target in _LANG_PRIORITY:
            for s in bitmap:
                lang = _lang(s)
                match = lang in _ITALIAN_CODES if target == "ita" else lang == target
                if match:
                    return s
        return bitmap[0]

    # ── PGS: mkvextract + pgsreader + Tesseract parallelo ────────────────────

    def _ocr_pgs(self, vf: VideoFile, video_path: Path, stream_idx: int) -> str:
        log_id = self._create_log(vf.id, "pgs")
        self._update_status(vf.id, "ocring")
        start = time.time()

        it_srt = video_path.with_name(f"{video_path.stem}.it.srt")

        with tempfile.TemporaryDirectory() as tmpdir:
            sup_path = Path(tmpdir) / "track.sup"

            # Step 1: estrai .sup con mkvextract
            cmd = ["mkvextract", "tracks", str(video_path),
                   f"{stream_idx}:{sup_path}"]
            logger.info(f"  mkvextract PGS stream {stream_idx}: {vf.filename}")
            try:
                self._current_proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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

                if not sup_path.exists() or sup_path.stat().st_size < 100:
                    msg = "mkvextract non ha prodotto il file .sup"
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

            # Step 2: parsing PGS + OCR parallelo
            logger.info(f"  pgsreader + Tesseract parallelo ({_ocr_workers()} worker): {vf.filename}")
            try:
                srt_text = self._sup_to_srt(sup_path, Config.OCR_LANGUAGE)
            except Exception as e:
                msg = f"OCR PGS fallito: {e}"
                logger.error(f"  {vf.filename}: {msg}", exc_info=True)
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                return "failed"

        if not srt_text.strip():
            msg = "OCR non ha prodotto testo"
            self._update_status(vf.id, "skipped", msg)
            self._finish_log(log_id, "skipped", msg, time.time() - start)
            return "skipped"

        mux_ok = self._writeback_mux(video_path, srt_text, "ita", stream_idx, vf.sub_formats_json)
        duration = time.time() - start
        if mux_ok:
            logger.info(f"  ✓ PGS OCR + mux in {duration:.1f}s: {video_path.name}")
        else:
            it_srt.write_text(srt_text, encoding="utf-8")
            logger.warning(f"  Mux fallito, sidecar: {it_srt.name}")

        self._update_status(vf.id, "done", conversion_done_at=datetime.now(timezone.utc))
        self._finish_log(log_id, "done", None, duration)
        self._post_ocr_update(vf.id)
        return "done"

    def _sup_to_srt(self, sup_path: Path, language: str) -> str:
        """Parsifica .sup con pgsreader, esegue OCR in parallelo, costruisce SRT."""
        from pgsreader import PGSReader
        from imagemaker import make_image

        pgs = PGSReader(str(sup_path))
        raw: List[Tuple[int, int, object, bool]] = []  # (start_ms, end_ms, image, multi_ods)

        pending = None
        for ds in pgs.displaysets:
            if self._cancelled:
                raise InterruptedError("Annullato")
            pts = ds.pcs[0].pts if ds.pcs else (
                ds.segments[0].pts if ds.segments else 0)
            if ds.has_image:
                if pending is not None:
                    raw.append((pending[0], int(pts), pending[1], pending[2]))
                img, multi = self._build_pgs_image(ds, make_image)
                if img is None:
                    pending = None
                    continue
                pending = (int(pts), img, multi)
            else:
                if pending is not None:
                    raw.append((pending[0], int(pts), pending[1], pending[2]))
                    pending = None
        if pending is not None:
            raw.append((pending[0], pending[0] + 2000, pending[1], pending[2]))

        if not raw:
            return ""

        images = [r[2] for r in raw]
        texts = _ocr_images_parallel(
            images, language, _ocr_workers(),
            cancel_check=lambda: self._cancelled,
        )

        events = [
            (start, end, txt)
            for (start, end, _img, _multi), txt in zip(raw, texts)
            if txt.strip()
        ]
        return _events_to_srt(events)

    @staticmethod
    def _build_pgs_image(ds, make_image):
        """Costruisce PIL.Image da un PGS display set (con patch multi-ODS)."""
        ods_list = ds.ods
        pds_list = ds.pds
        if not ods_list or not pds_list:
            return None, False
        multi = len(ods_list) > 1
        try:
            if multi:
                first = ods_list[0]
                combined = b"".join(o.img_data for o in ods_list)

                class _ODSShim:
                    pass
                shim = _ODSShim()
                shim.width = first.width
                shim.height = first.height
                shim.img_data = combined
                img = make_image(shim, pds_list[0])
            else:
                img = make_image(ods_list[0], pds_list[0])
            return img.convert("RGBA"), multi
        except Exception as e:
            logger.debug(f"_build_pgs_image: {e}")
            return None, multi

    # ── VOBSUB: mkvextract + VobSubParser + Tesseract parallelo ─────────────

    def _ocr_vobsub(self, vf: VideoFile, video_path: Path, stream_idx: int) -> str:
        """OCR VOBSUB via VobSubParser (vendor) + pytesseract — stessa pipeline PGS."""
        log_id = self._create_log(vf.id, "vobsub")
        self._update_status(vf.id, "ocring")
        start = time.time()
        it_srt = video_path.with_name(f"{video_path.stem}.it.srt")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_base = Path(tmpdir) / "vobsub"

            # Step 1: mkvextract → .idx + .sub
            extract_cmd = ["mkvextract", "tracks", str(video_path),
                           f"{stream_idx}:{tmp_base}"]
            logger.info(f"  mkvextract VOBSUB stream {stream_idx}: {vf.filename}")
            try:
                self._current_proc = subprocess.Popen(
                    extract_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace",
                )
                _, _ = self._current_proc.communicate(timeout=Config.OCR_TIMEOUT_S)
                rc = self._current_proc.returncode
                self._current_proc = None

                if rc != 0 or self._cancelled:
                    msg = f"mkvextract fallito (rc={rc})" if rc != 0 else "Annullato"
                    self._update_status(vf.id, "failed", msg)
                    self._finish_log(log_id, "failed", msg, time.time() - start)
                    return "failed"

                idx_path = Path(str(tmp_base) + ".idx")
                sub_path = Path(str(tmp_base) + ".sub")
                if not idx_path.exists() or not sub_path.exists():
                    msg = "mkvextract non ha prodotto .idx/.sub"
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

            # Step 2: parsing + OCR parallelo via VobSubParser (vendor)
            logger.info(f"  VobSubParser + Tesseract parallelo ({_ocr_workers()} worker): {vf.filename}")
            try:
                srt_text = self._idxsub_to_srt(idx_path, sub_path, Config.OCR_LANGUAGE)
            except Exception as e:
                msg = f"OCR VOBSUB fallito: {e}"
                logger.error(f"  {vf.filename}: {msg}", exc_info=True)
                self._update_status(vf.id, "failed", msg)
                self._finish_log(log_id, "failed", msg, time.time() - start)
                return "failed"

        if not srt_text.strip():
            msg = "OCR non ha prodotto testo"
            self._update_status(vf.id, "skipped", msg)
            self._finish_log(log_id, "skipped", msg, time.time() - start)
            return "skipped"

        mux_ok = self._writeback_mux(video_path, srt_text, "ita", stream_idx, vf.sub_formats_json)
        duration = time.time() - start
        if mux_ok:
            logger.info(f"  ✓ VOBSUB OCR + mux in {duration:.1f}s: {video_path.name}")
        else:
            it_srt.write_text(srt_text, encoding="utf-8")
            logger.warning(f"  Mux fallito, sidecar: {it_srt.name}")

        self._update_status(vf.id, "done", conversion_done_at=datetime.now(timezone.utc))
        self._finish_log(log_id, "done", None, duration)
        self._post_ocr_update(vf.id)
        return "done"

    def _idxsub_to_srt(self, idx_path: Path, sub_path: Path, language: str) -> str:
        """Parsifica .idx/.sub con VobSubParser, OCR in parallelo, restituisce SRT."""
        import numpy as np
        from PIL import Image
        from vobsub.vob_sub_parser import VobSubParser
        from vobsub.sub_picture_fast import get_bitmap_fast

        # Rileva PAL/NTSC da 'size:' nell'.idx
        is_pal = True
        try:
            for line in idx_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("size:") and "x480" in line:
                    is_pal = False
                    break
        except Exception:
            pass

        parser = VobSubParser(is_pal)
        parser.open_sub_idx(str(sub_path), str(idx_path))
        packs = parser.merge_vob_sub_packs()
        palette = parser.idx_palette

        # Decodifica bitmap + timing con decoder NumPy vettorizzato (~35-70x più veloce).
        decoded: List[Tuple[int, int, object]] = []
        for pack in packs:
            if self._cancelled:
                raise InterruptedError("Annullato")
            try:
                arr = get_bitmap_fast(pack, palette)
                if arr.dtype != np.uint8:
                    arr = (arr * 255).astype("uint8")
                if arr.ndim == 3 and arr.shape[2] >= 3:
                    pil = Image.fromarray(arr[:, :, :3])
                else:
                    pil = Image.fromarray(arr).convert("RGB")
            except Exception as e:
                logger.debug(f"get_bitmap_fast fallito: {e}")
                continue
            start_ms = int(pack.start_time.total_seconds() * 1000)
            end_ms   = int(pack.end_time.total_seconds() * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 2000
            decoded.append((start_ms, end_ms, pil))

        if not decoded:
            return ""

        images = [d[2] for d in decoded]
        texts = _ocr_images_parallel(
            images, language, _ocr_workers(),
            cancel_check=lambda: self._cancelled,
        )

        events = [
            (start, end, txt)
            for (start, end, _pil), txt in zip(decoded, texts)
            if txt.strip()
        ]
        return _events_to_srt(events)

    # ── Helpers DB ────────────────────────────────────────────────────────────

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
        try:
            with get_db() as db:
                vf = db.get(VideoFile, video_id)
                if vf:
                    vf.has_italian_text_sub = True
                    vf.has_any_italian_sub = True
                    vf.has_italian_srt = True
        except Exception as e:
            logger.error(f"_post_ocr_update error: {e}")

    def _writeback_mux(self, video_path: Path, srt_text: str, language: str,
                       bitmap_abs_idx: int, sub_formats_json: Optional[str]) -> bool:
        """
        Aggiunge l'SRT come nuova traccia testo nell'MKV in-place e rimuove
        la traccia bitmap originale (PGS o VOBSUB).
        Fallback automatico a sidecar se il mux fallisce.
        """
        # Individua subtitle-relative index della traccia bitmap
        try:
            all_subs = sorted(json.loads(sub_formats_json or "[]"),
                              key=lambda s: s.get("index", 0))
        except Exception:
            all_subs = []

        n_subs = len(all_subs)
        orig = next((s for s in all_subs if s.get("index") == bitmap_abs_idx), {})
        bitmap_rel_idx = next(
            (i for i, s in enumerate(all_subs) if s.get("index") == bitmap_abs_idx),
            None,
        )
        new_sub_idx = n_subs - 1 if bitmap_rel_idx is not None else n_subs
        orig_title = (orig.get("title") or "").strip()

        tmp_srt = video_path.with_suffix(".ocr_tmp.srt")
        temp    = Path(str(video_path) + ".converting")
        try:
            tmp_srt.write_text(srt_text, encoding="utf-8")
        except Exception as e:
            logger.error(f"_writeback_mux: scrittura tmp SRT fallita: {e}")
            return False

        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-i", str(video_path), "-i", str(tmp_srt),
               "-map", "0"]
        if bitmap_rel_idx is not None:
            cmd += ["-map", f"-0:s:{bitmap_rel_idx}"]
        cmd += ["-map", "1:0", "-c", "copy",
                f"-metadata:s:s:{new_sub_idx}", f"language={language}"]
        if orig_title:
            cmd += [f"-metadata:s:s:{new_sub_idx}", f"title={orig_title}"]
        cmd += [f"-disposition:s:{new_sub_idx}", "0",
                "-f", "matroska", str(temp)]

        try:
            self._current_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace",
            )
            _, err = self._current_proc.communicate(timeout=Config.OCR_TIMEOUT_S)
            rc = self._current_proc.returncode
            self._current_proc = None
        except subprocess.TimeoutExpired:
            if self._current_proc:
                self._current_proc.kill()
            self._current_proc = None
            if temp.exists():
                temp.unlink()
            return False
        finally:
            try:
                tmp_srt.unlink(missing_ok=True)
            except Exception:
                pass

        if self._cancelled:
            if temp.exists():
                temp.unlink()
            return False

        if rc != 0 or not temp.exists() or temp.stat().st_size < 1024:
            logger.error(f"_writeback_mux ffmpeg fallito (rc={rc}): {(err or '')[-300:]}")
            if temp.exists():
                temp.unlink()
            return False

        temp.replace(video_path)
        return True

    def _notify(self, message: str, percent: int):
        if self._progress_callback:
            try:
                self._progress_callback(message, percent)
            except Exception:
                pass


def _ocr_workers() -> int:
    """Numero di thread OCR paralleli: min(cpu_count, 8), stesso di Transcriber Pro."""
    return min(os.cpu_count() or 4, 8)


# Singleton
_ocr_instance: Optional[SubtitleOcr] = None


def get_ocr() -> SubtitleOcr:
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = SubtitleOcr()
    return _ocr_instance
