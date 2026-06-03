# -*- coding: utf-8 -*-
"""
VOBSUB OCR - Conversione sottotitoli bitmap DVD (VOBSUB .idx/.sub) → SRT.
File: core/vobsub_ocr.py

Stessa logica del modulo PGS (core/pgs_ocr.py), riusa il contratto OcrEvent e gli
helper condivisi (core/bitmap_ocr_common). Differenze:
  - estrazione via mkvextract → .idx/.sub
  - parsing via parser vendorizzato (core/vendor/vobsub, port di Subtitle Edit)
  - preprocess con auto-rilevamento polarità (VOBSUB ha colori variabili)
  - WRITE-BACK SEMPRE SIDECAR (decisione utente per VOBSUB)

VERBATIM: il testo OCR non viene mai corretto. Nessun LLM.
Pipeline validata dallo spike 2026-06-03 (vedi memory/project_pgs_ocr_module.md).
"""
import os
import sys
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable, List, Tuple

from core.subtitle_extractor import SubtitleExtractor
from core.bitmap_ocr_common import preprocess_for_ocr, ocr_image_verbatim
from core.pgs_types import (
    OcrEvent, events_to_srt,
    CFG_LANGUAGE, CFG_CONF_THRESHOLD, CFG_TESSERACT_PATH,
    DEFAULT_LANGUAGE, DEFAULT_CONF_THRESHOLD,
    FLAG_LOW_CONF, FLAG_EMPTY,
)

logger = logging.getLogger(__name__)

# Vendor: parser VOBSUB (port di Subtitle Edit), non su PyPI.
_VENDOR = Path(__file__).parent / "vendor" / "vobsub"
if str(_VENDOR.parent) not in sys.path:
    sys.path.insert(0, str(_VENDOR.parent))

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

VOBSUB_CODECS = {"dvd_subtitle", "dvdsub"}


class BitmapNotSupported(Exception):
    """Sollevata quando il bitmap selezionato non è VOBSUB."""


def _find_mkvextract() -> Optional[str]:
    exe = shutil.which("mkvextract")
    if exe:
        return exe
    candidate = Path.home() / "scoop" / "shims" / "mkvextract.exe"
    return str(candidate) if candidate.exists() else None


class VobSubOcr:
    """
    Converte i sottotitoli VOBSUB di un video in SRT (sidecar).

    Uso (ramo review, orchestrato dalla GUI):
        ocr = VobSubOcr(video_path, config)
        events, lang = ocr.ocr_to_events()
        # ... revisione utente ...
        ocr.writeback(srt_text, lang)     # sempre sidecar

    Uso (ramo auto):
        ocr = VobSubOcr(video_path, config)
        ocr.run_auto()
    """

    def __init__(self, video_path: str, config=None,
                 log_callback: Optional[Callable] = None):
        self.video_path = Path(video_path)
        self.config = config
        self.log_callback = log_callback
        self.extractor = SubtitleExtractor(str(video_path))
        self._cancelled = False
        self._active_proc: Optional[subprocess.Popen] = None
        self._configure_tesseract()

    # ── Config helpers ────────────────────────────────────────────────────
    def _cfg(self, key, default):
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:
            try:
                return self.config[key]
            except Exception:
                return default

    def _configure_tesseract(self):
        path = self._cfg(CFG_TESSERACT_PATH, "")
        if path:
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = path
            except Exception as e:
                logger.warning(f"Impossibile impostare tesseract_cmd={path}: {e}")

    def cancel(self):
        self._cancelled = True
        if self._active_proc:
            try:
                self._active_proc.kill()
            except Exception:
                pass

    def _log(self, msg: str):
        logger.info(msg)
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass

    # ── Selezione stream + estrazione idx/sub ─────────────────────────────
    def select_vobsub_stream(self) -> dict:
        sub = self.extractor.select_best_bitmap_subtitle()
        if not sub:
            raise BitmapNotSupported("Nessun sottotitolo bitmap trovato")
        if sub["codec"].lower() not in VOBSUB_CODECS:
            raise BitmapNotSupported(
                f"Codec {sub['codec']} non è VOBSUB (usa il modulo PGS)")
        return sub

    def extract_idx_sub(self, stream_index: int, out_base: Path) -> Tuple[Path, Path]:
        """
        Estrae VOBSUB in <out_base>.idx + <out_base>.sub via mkvextract.
        Nota: mkvextract usa i track ID di mkvmerge; per gli MKV standard coincidono
        con l'index di ffprobe. Ritorna (idx_path, sub_path).
        """
        mkvextract = _find_mkvextract()
        if not mkvextract:
            raise RuntimeError("mkvextract non trovato (installa MKVToolNix)")
        out_base.parent.mkdir(parents=True, exist_ok=True)
        # mkvextract scrive out_base.idx e out_base.sub
        cmd = [mkvextract, "tracks", str(self.video_path),
               f"{stream_index}:{out_base}"]
        self._active_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW)
        _, err = self._active_proc.communicate()
        rc = self._active_proc.returncode
        self._active_proc = None
        if self._cancelled:
            raise InterruptedError("Operazione annullata")
        idx = Path(str(out_base) + ".idx")
        sub = Path(str(out_base) + ".sub")
        if rc != 0 or not idx.exists() or not sub.exists():
            raise RuntimeError(f"mkvextract fallito (rc={rc}): {err}")
        return idx, sub

    @staticmethod
    def _is_pal(idx_path: Path) -> bool:
        """Rileva PAL (720x576) vs NTSC (720x480) dalla riga 'size:' dell'.idx."""
        try:
            for line in idx_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("size:") and "x480" in line:
                    return False
        except Exception:
            pass
        return True  # default PAL

    # ── Ramo REVIEW ───────────────────────────────────────────────────────
    def ocr_to_events(self) -> Tuple[List[OcrEvent], str]:
        sub_info = self.select_vobsub_stream()
        language = self._cfg(CFG_LANGUAGE, DEFAULT_LANGUAGE)

        from utils.file_handler import FileHandler  # lazy
        try:
            fh = FileHandler()
            out_base = Path(fh.get_temp_path(str(self.video_path), "vobsub_ocr"))
        except Exception:
            import tempfile
            out_base = Path(tempfile.gettempdir()) / f"{self.video_path.stem}_vobsub_ocr"

        self._log(f"Estrazione VOBSUB (stream {sub_info['index']}, {sub_info['language']})...")
        idx, sub = self.extract_idx_sub(sub_info["index"], out_base)

        self._log("Parsing VOBSUB + OCR Tesseract...")
        events = self._idxsub_to_events(idx, sub, language)

        for p in (idx, sub):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        n_flag = sum(1 for e in events if e.is_flagged)
        self._log(f"OCR completato: {len(events)} eventi, {n_flag} da rivedere")
        return events, language

    def _idxsub_to_events(self, idx: Path, sub: Path, language: str) -> List[OcrEvent]:
        import numpy as np
        from PIL import Image
        from vobsub.vob_sub_parser import VobSubParser

        threshold = int(self._cfg(CFG_CONF_THRESHOLD, DEFAULT_CONF_THRESHOLD))

        parser = VobSubParser(self._is_pal(idx))
        parser.open_sub_idx(str(sub), str(idx))
        packs = parser.merge_vob_sub_packs()
        palette = parser.idx_palette

        events: List[OcrEvent] = []
        for i, pack in enumerate(packs, start=1):
            if self._cancelled:
                raise InterruptedError("Operazione annullata")
            try:
                pack.palette = palette
                arr = pack.get_bitmap()
                if arr.dtype != np.uint8:
                    arr = (arr * 255).astype("uint8")
                if arr.ndim == 3 and arr.shape[2] >= 3:
                    pil = Image.fromarray(arr[:, :, :3], "RGB")
                else:
                    pil = Image.fromarray(arr).convert("RGB")
            except Exception as e:
                logger.warning(f"get_bitmap fallito pack {i}: {e}")
                continue

            start_ms = int(pack.start_time.total_seconds() * 1000)
            end_ms = int(pack.end_time.total_seconds() * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 2000

            pre = preprocess_for_ocr(pil, upscale=3, auto_polarity=True)
            text, conf = ocr_image_verbatim(pre, language)

            flags = set()
            if not text.strip():
                flags.add(FLAG_EMPTY)
            elif conf < threshold:
                flags.add(FLAG_LOW_CONF)

            events.append(OcrEvent(
                index=i, start_ms=start_ms, end_ms=end_ms,
                text=text, confidence=conf, image=pil, flags=flags,
            ))
        return events

    # ── Ramo AUTO ─────────────────────────────────────────────────────────
    def run_auto(self) -> bool:
        events, language = self.ocr_to_events()
        srt = events_to_srt(events)
        if not srt.strip():
            self._log("Nessun testo OCR prodotto")
            return False
        return self.writeback(srt, language)

    # ── Write-back: SEMPRE sidecar per VOBSUB ─────────────────────────────
    def writeback(self, srt_text: str, language: str) -> bool:
        out = self.video_path.with_name(f"{self.video_path.stem}.{language}.srt")
        try:
            out.write_text(srt_text, encoding="utf-8")
        except Exception as e:
            logger.error(f"Scrittura sidecar fallita: {e}")
            return False
        self._log(f"SRT sidecar scritto: {out.name}")
        return True


# ── CLI di test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Test VOBSUB OCR")
    ap.add_argument("video")
    ap.add_argument("--out", help="scrivi SRT su file (default: stdout)")
    args = ap.parse_args()

    ocr = VobSubOcr(args.video)
    evs, lang = ocr.ocr_to_events()
    srt = events_to_srt(evs)
    if args.out:
        Path(args.out).write_text(srt, encoding="utf-8")
        print(f"Scritto {args.out} ({len(evs)} eventi, lingua {lang})")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(srt[:2000])
