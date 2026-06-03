# -*- coding: utf-8 -*-
"""
PGS OCR - Conversione sottotitoli bitmap (PGS) → SRT.
File: core/pgs_ocr.py

Due rami, selezionati dalla strategia in Opzioni (vedi core/pgs_types.py):
  - STRATEGY_REVIEW: pgsreader (vendor) + Tesseract pilotato da noi → produce OcrEvent
    con immagine + testo VERBATIM + confidenza per la UI di revisione mirata.
  - STRATEGY_AUTO:   pgsrip (turnkey MKVToolNix+Tesseract) → SRT, nessuna revisione.

Pipeline ramo review validata dallo spike 2026-06-03 (vedi memory/project_pgs_ocr_module.md):
  estrai .sup → parse display set → preprocess (composito nero, Otsu, invert, upscale 2×,
  border) → Tesseract --psm 6 (preserva \n, accenti UTF-8 corretti) → confidenza media parole.

VERBATIM: il testo OCR NON viene mai corretto/normalizzato. Nessun LLM.
"""
import os
import sys
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable, List, Tuple

from core.subtitle_extractor import SubtitleExtractor
from core.pgs_types import (
    OcrEvent, events_to_srt,
    CFG_LANGUAGE, CFG_CONF_THRESHOLD, CFG_TESSERACT_PATH, CFG_WRITEBACK,
    DEFAULT_LANGUAGE, DEFAULT_CONF_THRESHOLD, DEFAULT_WRITEBACK,
    WRITEBACK_MUX, WRITEBACK_SIDECAR,
    FLAG_LOW_CONF, FLAG_EMPTY, FLAG_MULTI_ODS,
)

logger = logging.getLogger(__name__)

# Vendor: pgsreader non è su PyPI, è vendorizzato (con patch WDS difensiva).
_VENDOR = Path(__file__).parent / "vendor" / "pgsreader"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

# Codec PGS gestiti dal ramo review (gli unici supportati da pgsreader).
PGS_CODECS = {"hdmv_pgs_subtitle", "pgssub"}


class BitmapNotSupported(Exception):
    """Sollevata quando il bitmap selezionato non è PGS (es. VOBSUB → fase 2)."""


class PgsOcr:
    """
    Converte i sottotitoli PGS di un video in SRT.

    Uso (ramo review, orchestrato dalla GUI):
        ocr = PgsOcr(video_path, config)
        events, lang = ocr.ocr_to_events()      # lista OcrEvent per la revisione
        # ... revisione utente ...
        ocr.writeback(srt_text, lang)

    Uso (ramo auto):
        ocr = PgsOcr(video_path, config)
        ocr.run_auto()                          # pgsrip end-to-end + write-back
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

    # ── Selezione stream + estrazione .sup ────────────────────────────────
    def select_pgs_stream(self) -> dict:
        """Seleziona il miglior sottotitolo PGS. Solleva BitmapNotSupported se VOBSUB/assente."""
        sub = self.extractor.select_best_bitmap_subtitle()
        if not sub:
            raise BitmapNotSupported("Nessun sottotitolo bitmap trovato")
        if sub["codec"].lower() not in PGS_CODECS:
            raise BitmapNotSupported(
                f"Codec {sub['codec']} non supportato dal ramo review "
                f"(solo PGS; VOBSUB/DVD è fase 2)"
            )
        return sub

    def extract_sup(self, stream_index: int, out_sup: Path) -> bool:
        out_sup.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-i", str(self.video_path),
               "-map", f"0:{stream_index}", "-c", "copy", str(out_sup)]
        self._active_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW)
        _, err = self._active_proc.communicate()
        rc = self._active_proc.returncode
        self._active_proc = None
        if self._cancelled:
            raise InterruptedError("Operazione annullata")
        if rc != 0 or not out_sup.exists() or out_sup.stat().st_size == 0:
            logger.error(f"Estrazione .sup fallita (rc={rc}): {err}")
            return False
        return True

    # ── Ramo REVIEW: pgsreader + Tesseract ────────────────────────────────
    def ocr_to_events(self) -> Tuple[List[OcrEvent], str]:
        """
        Esegue l'OCR PGS e ritorna (lista di OcrEvent, lingua).
        VERBATIM: nessuna correzione del testo.
        """
        sub = self.select_pgs_stream()
        language = self._cfg(CFG_LANGUAGE, DEFAULT_LANGUAGE)

        from utils.file_handler import FileHandler  # lazy
        try:
            fh = FileHandler()
            sup_path = Path(fh.get_temp_path(str(self.video_path), "pgs_ocr.sup"))
        except Exception:
            import tempfile
            sup_path = Path(tempfile.gettempdir()) / f"{self.video_path.stem}_pgs_ocr.sup"

        self._log(f"Estrazione PGS (stream {sub['index']}, {sub['language']})...")
        if not self.extract_sup(sub["index"], sup_path):
            raise RuntimeError("Estrazione .sup fallita")

        self._log("Parsing PGS + OCR Tesseract...")
        events = self._sup_to_events(sup_path, language)

        try:
            sup_path.unlink(missing_ok=True)
        except Exception:
            pass

        n_flag = sum(1 for e in events if e.is_flagged)
        self._log(f"OCR completato: {len(events)} eventi, {n_flag} da rivedere")
        return events, language

    def _sup_to_events(self, sup_path: Path, language: str) -> List[OcrEvent]:
        import numpy as np
        import cv2
        import pytesseract
        from PIL import Image
        from pgsreader import PGSReader
        from imagemaker import make_image

        threshold = int(self._cfg(CFG_CONF_THRESHOLD, DEFAULT_CONF_THRESHOLD))

        pgs = PGSReader(str(sup_path))
        dsets = pgs.displaysets

        # 1) Ricostruisci coppie (start_ms, end_ms, immagine) dai display set.
        raw: List[Tuple[int, int, "Image.Image", bool]] = []
        pending = None  # (start_ms, image, multi)
        for ds in dsets:
            if self._cancelled:
                raise InterruptedError("Operazione annullata")
            pts = ds.pcs[0].pts if ds.pcs else (ds.segments[0].pts if ds.segments else 0)
            if ds.has_image:
                if pending is not None:
                    raw.append((pending[0], int(pts), pending[1], pending[2]))
                img, multi = self._build_image(ds, make_image, np)
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

        # 2) OCR di ogni immagine (un'unica passata image_to_data → testo+confidenza).
        events: List[OcrEvent] = []
        for i, (start_ms, end_ms, img, multi) in enumerate(raw, start=1):
            if self._cancelled:
                raise InterruptedError("Operazione annullata")
            pre = self._preprocess(img, np, cv2, Image)
            text, conf = self._ocr_image(pre, language, pytesseract)
            flags = set()
            if multi:
                flags.add(FLAG_MULTI_ODS)
            if not text.strip():
                flags.add(FLAG_EMPTY)
            elif conf < threshold:
                flags.add(FLAG_LOW_CONF)
            events.append(OcrEvent(
                index=i, start_ms=start_ms, end_ms=end_ms,
                text=text, confidence=conf, image=img, flags=flags,
            ))
        return events

    @staticmethod
    def _build_image(ds, make_image, np):
        """
        Costruisce l'immagine del display set gestendo ODS frammentati/multipli.
        Ritorna (PIL.Image|None, multi: bool).
        """
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
            logger.warning(f"make_image fallito su un display set: {e}")
            return None, multi

    @staticmethod
    def _preprocess(img, np, cv2, Image):
        """Composito su nero → grigio → Otsu → invert (testo scuro su chiaro) → upscale 2× → border."""
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        comp = Image.alpha_composite(bg, rgba).convert("L")
        arr = np.array(comp)
        _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        th = 255 - th
        th = cv2.resize(th, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        th = cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        return th

    @staticmethod
    def _ocr_image(pre, language, pytesseract) -> Tuple[str, float]:
        """
        Una passata image_to_data: ricostruisce testo (con \n per riga) e confidenza media.
        VERBATIM: nessuna modifica al testo riconosciuto.
        """
        data = pytesseract.image_to_data(
            pre, lang=language, config="--psm 6",
            output_type=pytesseract.Output.DICT)
        lines = {}
        confs = []
        for i in range(len(data["text"])):
            w = data["text"][i].strip()
            if not w:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(w)
            try:
                c = float(data["conf"][i])
            except (ValueError, TypeError):
                c = -1
            if c >= 0:
                confs.append(c)
        text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
        mean = sum(confs) / len(confs) if confs else 0.0
        return text, mean

    # ── Ramo AUTO: pgsrip ─────────────────────────────────────────────────
    def run_auto(self) -> bool:
        """
        Conversione turnkey via pgsrip (richiede MKVToolNix + Tesseract).
        pgsrip scrive l'SRT accanto; poi applichiamo il write-back configurato.
        """
        language = self._cfg(CFG_LANGUAGE, DEFAULT_LANGUAGE)
        try:
            from pgsrip import pgsrip, Mkv, Options
            from babelfish import Language
        except Exception as e:
            logger.error(f"pgsrip non disponibile: {e}")
            return False

        self._log("Conversione automatica con pgsrip...")
        try:
            media = Mkv(str(self.video_path))
            options = Options(languages={Language(language)}, overwrite=True)
            pgsrip.rip(media, options)
        except Exception as e:
            logger.error(f"pgsrip fallito: {e}", exc_info=True)
            return False

        # pgsrip crea <video>.<lang>.srt accanto al file.
        produced = self.video_path.with_suffix("")  # base
        candidates = list(self.video_path.parent.glob(f"{self.video_path.stem}*.srt"))
        if not candidates:
            logger.error("pgsrip non ha prodotto alcun SRT")
            return False
        srt_file = max(candidates, key=lambda p: p.stat().st_mtime)

        writeback = self._cfg(CFG_WRITEBACK, DEFAULT_WRITEBACK)
        if writeback == WRITEBACK_MUX:
            ok = self._writeback_mux(srt_file, language)
            if ok:
                try:
                    srt_file.unlink(missing_ok=True)  # rimosso dopo il mux
                except Exception:
                    pass
            return ok
        # sidecar: l'SRT prodotto da pgsrip è già accanto al video
        return True

    # ── Write-back ────────────────────────────────────────────────────────
    def writeback(self, srt_text: str, language: str) -> bool:
        """Applica l'SRT (testo) secondo la strategia di write-back configurata."""
        writeback = self._cfg(CFG_WRITEBACK, DEFAULT_WRITEBACK)
        if writeback == WRITEBACK_SIDECAR:
            out = self.video_path.with_name(f"{self.video_path.stem}.{language}.srt")
            out.write_text(srt_text, encoding="utf-8")
            self._log(f"SRT scritto: {out.name}")
            return True
        # MUX: scrivi un SRT temporaneo e rimuxalo nell'MKV in-place.
        tmp_srt = self.video_path.with_suffix(".ocr_tmp.srt")
        tmp_srt.write_text(srt_text, encoding="utf-8")
        ok = self._writeback_mux(tmp_srt, language)
        try:
            tmp_srt.unlink(missing_ok=True)
        except Exception:
            pass
        return ok

    def _writeback_mux(self, srt_file: Path, language: str) -> bool:
        """
        Aggiunge l'SRT come nuova traccia testo nell'MKV, in-place.
        Pattern Library Scanner: -map 0 -map 1:0 -c copy -f matroska + temp .converting + replace.
        Tutte le tracce esistenti (incluso il PGS originale) restano intatte (copy).
        """
        if self.video_path.suffix.lower() != ".mkv":
            logger.warning(f"Write-back mux salta {self.video_path.name}: non è MKV")
            return False

        # Indice della nuova traccia sottotitolo = numero di sub esistenti.
        if not self.extractor.subtitle_streams:
            self.extractor.detect_subtitles()
        n_subs = len(self.extractor.subtitle_streams)

        temp = Path(str(self.video_path) + ".converting")
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-i", str(self.video_path), "-i", str(srt_file),
               "-map", "0", "-map", "1:0", "-c", "copy",
               f"-metadata:s:s:{n_subs}", f"language={language}",
               f"-disposition:s:{n_subs}", "0",
               "-f", "matroska", str(temp)]
        self._active_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW)
        _, err = self._active_proc.communicate()
        rc = self._active_proc.returncode
        self._active_proc = None
        if self._cancelled:
            if temp.exists():
                temp.unlink()
            raise InterruptedError("Operazione annullata")
        if rc != 0 or not temp.exists() or temp.stat().st_size < 1024:
            logger.error(f"Write-back mux fallito (rc={rc}): {err}")
            if temp.exists():
                temp.unlink()
            return False
        temp.replace(self.video_path)
        self._log(f"Traccia SRT ({language}) aggiunta in-place: {self.video_path.name}")
        return True


# ── CLI di test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Test PGS OCR (ramo review)")
    ap.add_argument("video")
    ap.add_argument("--out", help="scrivi SRT su file (default: stdout)")
    args = ap.parse_args()

    ocr = PgsOcr(args.video)
    evs, lang = ocr.ocr_to_events()
    srt = events_to_srt(evs)
    if args.out:
        Path(args.out).write_text(srt, encoding="utf-8")
        print(f"Scritto {args.out} ({len(evs)} eventi, lingua {lang})")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(srt[:2000])
