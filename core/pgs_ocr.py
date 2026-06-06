# -*- coding: utf-8 -*-
"""
PGS OCR - Conversione sottotitoli bitmap (PGS) → SRT.
File: core/pgs_ocr.py

Due rami, selezionati dalla strategia in Opzioni (vedi core/pgs_types.py):
  - STRATEGY_REVIEW: pgsreader (vendor) + Tesseract pilotato da noi → produce OcrEvent
    con immagine + testo VERBATIM + confidenza per la UI di revisione mirata.
  - STRATEGY_AUTO:   stesso motore del review (pgsreader+Tesseract via ffmpeg), senza dialog.

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
from core.bitmap_ocr_common import (
    preprocess_for_ocr, ocr_image_verbatim, ocr_images_parallel, pick_tesseract_lang)
from core.pgs_types import (
    OcrEvent, events_to_srt, resolve_ocr_workers, lang_to_2, is_italian,
    CFG_LANGUAGE, CFG_CONF_THRESHOLD, CFG_TESSERACT_PATH, CFG_WRITEBACK, CFG_OCR_WORKERS,
    DEFAULT_LANGUAGE, DEFAULT_CONF_THRESHOLD, DEFAULT_WRITEBACK, DEFAULT_OCR_WORKERS,
    WRITEBACK_MUX, WRITEBACK_SIDECAR,
    FLAG_LOW_CONF, FLAG_EMPTY, FLAG_MULTI_ODS,
    UnsupportedLanguage,
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
        ocr.run_auto()                          # OCR senza dialog + write-back
    """

    def __init__(self, video_path: str, config=None,
                 log_callback: Optional[Callable] = None,
                 progress_callback: Optional[Callable] = None):
        self.video_path = Path(video_path)
        self.config = config
        self.log_callback = log_callback
        # progress_callback(percent: int, label: str)
        self.progress_callback = progress_callback
        self.extractor = SubtitleExtractor(str(video_path))
        self._cancelled = False
        self._active_proc: Optional[subprocess.Popen] = None
        self._bitmap_stream_abs_idx: Optional[int] = None
        self._configure_tesseract()

    def _progress(self, percent: int, label: str):
        if self.progress_callback:
            try:
                self.progress_callback(int(percent), label)
            except Exception:
                pass

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

    def select_all_pgs_streams_ita(self) -> List[dict]:
        """Restituisce TUTTE le tracce PGS italiane non-forced, ordinate per index."""
        subs = self.extractor.select_all_italian_bitmap_subtitles()
        return [s for s in subs if s["codec"].lower() in PGS_CODECS]

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
    def _ocr_single_stream(self, sub: dict) -> Tuple[List[OcrEvent], str]:
        """
        OCR di UNA traccia PGS (helper condiviso da ocr_to_events e run_auto).
        Ritorna (eventi, lingua_contenuto 2-lettere). VERBATIM.
        """
        stream_lang3 = (sub.get("language") or "und").lower()
        ocr_lang = pick_tesseract_lang(stream_lang3, fallback=self._cfg(CFG_LANGUAGE, DEFAULT_LANGUAGE))
        if stream_lang3 not in ('und', 'unk', '') and ocr_lang != stream_lang3:
            from core.bitmap_ocr_common import available_tesseract_langs
            if stream_lang3 not in available_tesseract_langs():
                raise UnsupportedLanguage(
                    f"Lingua '{stream_lang3}' non supportata da Tesseract (traineddata mancante)")
        content_lang = lang_to_2(stream_lang3)

        from utils.file_handler import FileHandler
        try:
            fh = FileHandler()
            sup_path = Path(fh.get_temp_path(str(self.video_path), f"pgs_{sub['index']}.sup"))
        except Exception:
            import tempfile
            sup_path = Path(tempfile.gettempdir()) / f"{self.video_path.stem}_pgs_{sub['index']}.sup"

        self._log(f"Estrazione PGS (stream {sub['index']}, {stream_lang3}; OCR={ocr_lang})...")
        if not self.extract_sup(sub["index"], sup_path):
            raise RuntimeError(f"Estrazione .sup fallita (stream {sub['index']})")

        self._log("Parsing PGS + OCR Tesseract...")
        events = self._sup_to_events(sup_path, ocr_lang)

        try:
            sup_path.unlink(missing_ok=True)
        except Exception:
            pass

        n_flag = sum(1 for e in events if e.is_flagged)
        self._log(f"OCR completato: {len(events)} eventi, {n_flag} da rivedere")
        return events, content_lang

    def ocr_to_events(self) -> Tuple[List[OcrEvent], str]:
        """
        Esegue l'OCR sulla traccia PGS migliore e ritorna (lista di OcrEvent, lingua 2-lettere).
        Usato dal ramo review (singola traccia per UI di revisione).
        """
        sub = self.select_pgs_stream()
        self._bitmap_stream_abs_idx = sub.get("index")
        return self._ocr_single_stream(sub)

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

        # 2) OCR in PARALLELO (preprocess + Tesseract su più core).
        workers = resolve_ocr_workers(self._cfg(CFG_OCR_WORKERS, DEFAULT_OCR_WORKERS))
        images = [r[2] for r in raw]
        ocr_results = ocr_images_parallel(
            images, language, upscale=2, auto_polarity=False,
            max_workers=workers, cancel_check=lambda: self._cancelled,
            progress_cb=self._progress)

        # 3) Assembla gli OcrEvent (ordine preservato).
        events: List[OcrEvent] = []
        for i, (start_ms, end_ms, img, multi) in enumerate(raw, start=1):
            text, conf = ocr_results[i - 1]
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
        """Wrapper: preprocess PGS (composito nero, inversione fissa, upscale 2×)."""
        return preprocess_for_ocr(img, upscale=2, auto_polarity=False)

    @staticmethod
    def _ocr_image(pre, language, pytesseract) -> Tuple[str, float]:
        """Wrapper: OCR verbatim condiviso (single-pass image_to_data)."""
        return ocr_image_verbatim(pre, language)

    # ── Ramo AUTO ─────────────────────────────────────────────────────────
    def run_auto(self) -> bool:
        """
        Conversione automatica di TUTTE le tracce PGS italiane.
        Singola traccia → writeback() normale.
        Più tracce → mux single-pass (rimuove tutti i bitmap + aggiunge tutti gli SRT).
        """
        streams = self.select_all_pgs_streams_ita()
        if not streams:
            raise BitmapNotSupported("Nessun sottotitolo PGS italiano trovato")

        results: List[Tuple[dict, str, str]] = []  # (stream_dict, srt_text, lang2)
        for sub in streams:
            try:
                events, lang = self._ocr_single_stream(sub)
            except Exception as e:
                self._log(f"Stream {sub['index']}: errore OCR, skip: {e}")
                continue
            srt = events_to_srt(events)
            if srt.strip():
                results.append((sub, srt, lang))
            else:
                self._log(f"Stream {sub['index']}: OCR non ha prodotto testo, skip")

        if not results:
            self._log("Nessun testo OCR prodotto")
            return False

        if len(results) == 1:
            sub, srt, lang = results[0]
            self._bitmap_stream_abs_idx = sub["index"]
            return self.writeback(srt, lang)

        return self._writeback_mux_multi(results)

    def _writeback_mux_multi(self, results: List[Tuple[dict, str, str]]) -> bool:
        """
        Mux single-pass: rimuove tutte le tracce PGS OCR-ate e aggiunge gli SRT.
        results: [(stream_dict, srt_text, lang2), ...]
        """
        if self.video_path.suffix.lower() != ".mkv":
            logger.warning(f"Write-back mux multi salta {self.video_path.name}: non è MKV")
            return False

        if not self.extractor.subtitle_streams:
            self.extractor.detect_subtitles()
        all_subs = self.extractor.subtitle_streams
        n_subs = len(all_subs)
        N = len(results)

        # Indici relativi (nell'array subtitle) delle tracce bitmap da rimuovere
        bitmap_rel_indices = []
        for sub, _, _ in results:
            rel = next(
                (i for i, s in enumerate(all_subs) if s.get("index") == sub["index"]), None
            )
            if rel is not None:
                bitmap_rel_indices.append(rel)

        out_sub_start = n_subs - len(bitmap_rel_indices)

        # Scrivi SRT temporanei accanto al video
        tmp_srts: List[Path] = []
        temp = Path(str(self.video_path) + ".converting")
        try:
            for k, (_, srt_text, _) in enumerate(results):
                srt_p = self.video_path.with_suffix(f".ocr_tmp_{k}.srt")
                srt_p.write_text(srt_text, encoding="utf-8")
                tmp_srts.append(srt_p)
        except Exception as e:
            logger.error(f"Scrittura SRT temp fallita: {e}")
            for p in tmp_srts:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            return False

        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(self.video_path)]
        for srt_p in tmp_srts:
            cmd += ["-i", str(srt_p)]
        cmd += ["-map", "0"]
        for rel_idx in sorted(bitmap_rel_indices, reverse=True):
            cmd += ["-map", f"-0:s:{rel_idx}"]
        for k in range(N):
            cmd += ["-map", f"{k + 1}:0"]
        cmd += ["-c", "copy"]
        for k, (sub, _, lang) in enumerate(results):
            out_idx = out_sub_start + k
            cmd += [f"-metadata:s:s:{out_idx}", f"language={lang}"]
            title = (sub.get("title") or "").strip()
            if title:
                cmd += [f"-metadata:s:s:{out_idx}", f"title={title}"]
            # Preserva il flag forced dell'originale sul SRT di output
            disposition = "forced" if sub.get("forced", False) else "0"
            cmd += [f"-disposition:s:{out_idx}", disposition]
        cmd += ["-f", "matroska", str(temp)]

        self._active_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW)
        _, err = self._active_proc.communicate()
        rc = self._active_proc.returncode
        self._active_proc = None

        for p in tmp_srts:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        if self._cancelled:
            if temp.exists():
                temp.unlink()
            raise InterruptedError("Operazione annullata")
        if rc != 0 or not temp.exists() or temp.stat().st_size < 1024:
            logger.error(f"Write-back mux multi fallito (rc={rc}): {err}")
            if temp.exists():
                temp.unlink()
            return False
        temp.replace(self.video_path)
        langs = ", ".join(l for _, _, l in results)
        self._log(f"{N} tracce SRT ({langs}) aggiunte in-place: {self.video_path.name}")
        return True

    # ── Write-back ────────────────────────────────────────────────────────
    def write_sidecar(self, srt_text: str, lang2: str) -> Path:
        """Scrive sempre un sidecar <stem>.<lang2>.srt e ritorna il Path."""
        out = self.video_path.with_name(f"{self.video_path.stem}.{lang2}.srt")
        out.write_text(srt_text, encoding="utf-8")
        self._log(f"SRT sidecar scritto: {out.name}")
        return out

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
        subs = self.extractor.subtitle_streams
        n_subs = len(subs)

        # Individua la traccia bitmap da rimuovere
        if self._bitmap_stream_abs_idx is None:
            try:
                self._bitmap_stream_abs_idx = self.select_pgs_stream().get("index")
            except Exception:
                pass
        orig = next((s for s in subs if s.get("index") == self._bitmap_stream_abs_idx), {})
        bitmap_rel_idx = next(
            (i for i, s in enumerate(subs) if s.get("index") == self._bitmap_stream_abs_idx),
            None,
        )
        # Se rimuoviamo 1 e aggiungiamo 1 il conteggio resta invariato → indice = n_subs-1
        new_sub_idx = n_subs - 1 if bitmap_rel_idx is not None else n_subs
        orig_title = (orig.get("title") or "").strip()
        orig_forced = orig.get("forced", False)

        temp = Path(str(self.video_path) + ".converting")
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-i", str(self.video_path), "-i", str(srt_file),
               "-map", "0"]
        if bitmap_rel_idx is not None:
            cmd += ["-map", f"-0:s:{bitmap_rel_idx}"]
        cmd += ["-map", "1:0", "-c", "copy",
                f"-metadata:s:s:{new_sub_idx}", f"language={language}"]
        if orig_title:
            cmd += [f"-metadata:s:s:{new_sub_idx}", f"title={orig_title}"]
        disposition = "forced" if orig_forced else "0"
        cmd += [f"-disposition:s:{new_sub_idx}", disposition,
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
