# -*- coding: utf-8 -*-
"""
VOBSUB OCR - Conversione sottotitoli bitmap DVD (VOBSUB .idx/.sub) → SRT.
File: core/vobsub_ocr.py

Stessa logica del modulo PGS (core/pgs_ocr.py), riusa il contratto OcrEvent e gli
helper condivisi (core/bitmap_ocr_common). Differenze:
  - estrazione via mkvextract → .idx/.sub
  - parsing via parser vendorizzato (core/vendor/vobsub, port di Subtitle Edit)
  - preprocess con auto-rilevamento polarità (VOBSUB ha colori variabili)
  - WRITE-BACK: rispetta CFG_WRITEBACK (mux o sidecar, default mux)

VERBATIM: il testo OCR non viene mai corretto. Nessun LLM.
Pipeline validata dallo spike 2026-06-03 (vedi memory/project_pgs_ocr_module.md).
"""
import os
import sys
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable, List, Tuple

from core.subtitle_extractor import SubtitleExtractor
from utils.platform_compat import find_tool
from core.bitmap_ocr_common import (
    preprocess_for_ocr, ocr_image_verbatim, ocr_images_parallel, pick_tesseract_lang,
    srt_track_title, refine_content_lang, available_tesseract_langs)
from core.subtitle_lang import tesseract_name
from core.pgs_types import (
    OcrEvent, events_to_srt, resolve_ocr_workers, lang_to_2,
    CFG_LANGUAGE, CFG_CONF_THRESHOLD, CFG_TESSERACT_PATH, CFG_OCR_WORKERS,
    CFG_WRITEBACK, WRITEBACK_MUX, WRITEBACK_SIDECAR, DEFAULT_WRITEBACK,
    DEFAULT_LANGUAGE, DEFAULT_CONF_THRESHOLD, DEFAULT_OCR_WORKERS,
    FLAG_LOW_CONF, FLAG_EMPTY,
    UnsupportedLanguage, ContentNotItalian,
)
from utils.translations import tr

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
    return find_tool("mkvextract")


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
    # Se impostato (es. dalla pipeline) vince sulla chiave CFG_WRITEBACK della config: 'sidecar' = scrive il
    # `.it.srt` accanto al video senza toccare l'MKV.
    writeback_override: Optional[str] = None

    def _cfg(self, key, default):
        if key == CFG_WRITEBACK and self.writeback_override:
            return self.writeback_override
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
        path = self._cfg(CFG_TESSERACT_PATH, "") or find_tool("tesseract")   # Impostazioni > PATH > cartelle standard
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
            raise BitmapNotSupported(tr('vob_no_bitmap_subtitle_found'))
        if sub["codec"].lower() not in VOBSUB_CODECS:
            raise BitmapNotSupported(
                tr('vob_codec_is_not_vobsub_use').format(codec=sub['codec']))
        return sub

    def select_all_vobsub_streams_ita(self) -> List[dict]:
        """Restituisce TUTTE le tracce VOBSUB italiane non-forced, ordinate per index."""
        subs = self.extractor.select_all_italian_bitmap_subtitles()
        return [s for s in subs if s["codec"].lower() in VOBSUB_CODECS]

    def extract_idx_sub(self, stream_index: int, out_base: Path) -> Tuple[Path, Path]:
        """
        Estrae VOBSUB in <out_base>.idx + <out_base>.sub via mkvextract.
        Nota: mkvextract usa i track ID di mkvmerge; per gli MKV standard coincidono
        con l'index di ffprobe. Ritorna (idx_path, sub_path).
        """
        mkvextract = _find_mkvextract()
        if not mkvextract:
            raise RuntimeError(tr('vob_mkvextract_not_found_install_mkvtoolnix'))
        out_base.parent.mkdir(parents=True, exist_ok=True)
        # mkvextract scrive out_base.idx e out_base.sub
        cmd = [mkvextract, "tracks", str(self.video_path),
               f"{stream_index}:{out_base}"]
        import re as _re
        self._active_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", creationflags=_CREATE_NO_WINDOW)
        tail = []
        self._progress(0, "Estrazione")
        for line in self._active_proc.stdout:
            if self._cancelled:
                break
            tail.append(line)
            if len(tail) > 20:
                tail.pop(0)
            m = _re.search(r'(\d+)\s*%', line)
            if m:
                self._progress(int(m.group(1)), "Estrazione")
        self._active_proc.wait()
        rc = self._active_proc.returncode
        err = "".join(tail)
        self._active_proc = None
        if self._cancelled:
            raise InterruptedError("Operazione annullata")
        self._progress(100, "Estrazione")
        idx = Path(str(out_base) + ".idx")
        sub = Path(str(out_base) + ".sub")
        if rc != 0 or not idx.exists() or not sub.exists():
            raise RuntimeError(tr('vob_mkvextract_failed_rc').format(rc=rc, err=err))
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
    def _ocr_single_stream(self, sub_info: dict) -> Tuple[List[OcrEvent], str]:
        """
        OCR di UNA traccia VOBSUB (helper condiviso da ocr_to_events e run_auto).
        Ritorna (eventi, lingua_contenuto 2-lettere). VERBATIM.
        """
        # lingua EFFETTIVA della traccia (tag normalizzato, completato dal titolo): i codici a 2 lettere o
        # non standard non diventano piu' "sconosciuti"; il tag grezzo resta solo come ripiego.
        lang2 = sub_info.get("lang") or lang_to_2(sub_info.get("language"))
        stream_lang3 = tesseract_name(lang2)
        if stream_lang3 == 'und':
            # lingua fuori tabella ma con traineddata installato (es. 'lat', 'tgl'): si usa il codice grezzo
            raw = (sub_info.get("language") or "").lower()
            if raw and raw in available_tesseract_langs():
                stream_lang3 = raw
        ocr_lang = pick_tesseract_lang(stream_lang3, fallback=self._cfg(CFG_LANGUAGE, DEFAULT_LANGUAGE))
        if stream_lang3 not in ('und', 'unk', '') and ocr_lang != stream_lang3:
            if stream_lang3 not in available_tesseract_langs():
                raise UnsupportedLanguage(
                    tr('vob_language_not_supported_by_tesseract').format(stream_lang3=stream_lang3))
        content_lang = lang2

        from utils.file_handler import FileHandler
        try:
            fh = FileHandler()
            out_base = Path(fh.get_temp_path(str(self.video_path), f"vobsub_{sub_info['index']}"))
        except Exception:
            import tempfile
            out_base = Path(tempfile.gettempdir()) / f"{self.video_path.stem}_vobsub_{sub_info['index']}"

        logger.info(f"Estrazione VOBSUB stream {sub_info['index']} ({stream_lang3}; OCR={ocr_lang})")
        self._log(tr('vob_ocr_extracting_vobsub_track'))
        idx, sub = self.extract_idx_sub(sub_info["index"], out_base)

        from utils.events import emit as _tp_emit
        _tp_emit('phase', name='ocr_read')
        self._log(tr('pgs_ocr_bitmap_analysis'))
        events = self._idxsub_to_events(idx, sub, ocr_lang)
        refined = refine_content_lang(events, content_lang, self._log)
        if refined != content_lang:
            better = tesseract_name(refined)
            if better != ocr_lang and better in available_tesseract_langs():
                self._log(tr('pgs_ocr_re_reading_the_track').format(better=better))
                events = self._idxsub_to_events(idx, sub, better)
            content_lang = refined

        for p in (idx, sub):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        n_flag = sum(1 for e in events if e.is_flagged)
        self._log(tr('pgs_lines_to_review').format(n=len(events), n_flag=n_flag))
        return events, content_lang

    def ocr_to_events(self) -> Tuple[List[OcrEvent], str]:
        """
        Esegue l'OCR sulla traccia VOBSUB migliore e ritorna (lista OcrEvent, lingua 2-lettere).
        Usato dal ramo review (singola traccia per UI di revisione).
        """
        sub_info = self.select_vobsub_stream()
        self._bitmap_stream_abs_idx = sub_info.get("index")
        return self._ocr_single_stream(sub_info)

    def _idxsub_to_events(self, idx: Path, sub: Path, language: str) -> List[OcrEvent]:
        import numpy as np
        from PIL import Image
        from vobsub.vob_sub_parser import VobSubParser
        from vobsub.sub_picture_fast import get_bitmap_fast

        threshold = int(self._cfg(CFG_CONF_THRESHOLD, DEFAULT_CONF_THRESHOLD))

        parser = VobSubParser(self._is_pal(idx))
        parser.open_sub_idx(str(sub), str(idx))
        packs = parser.merge_vob_sub_packs()
        palette = parser.idx_palette

        # 1) Decodifica i bitmap + timing con decoder NumPy vettorizzato.
        #    ~35-70x più veloce del loop pixel-per-pixel originale.
        decoded = []  # (start_ms, end_ms, pil)
        for i, pack in enumerate(packs, start=1):
            if self._cancelled:
                raise InterruptedError("Operazione annullata")
            try:
                arr = get_bitmap_fast(pack, palette)
                if arr.dtype != np.uint8:
                    arr = (arr * 255).astype("uint8")
                if arr.ndim == 3 and arr.shape[2] >= 3:
                    pil = Image.fromarray(arr[:, :, :3])
                else:
                    pil = Image.fromarray(arr).convert("RGB")
            except Exception as e:
                logger.warning(f"get_bitmap_fast fallito pack {i}: {e}")
                continue
            start_ms = int(pack.start_time.total_seconds() * 1000)
            end_ms   = int(pack.end_time.total_seconds() * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + 2000
            decoded.append((start_ms, end_ms, pil))

        # 2) OCR in PARALLELO.
        workers = resolve_ocr_workers(self._cfg(CFG_OCR_WORKERS, DEFAULT_OCR_WORKERS))
        ocr_results = ocr_images_parallel(
            [d[2] for d in decoded], language, upscale=3, auto_polarity=True,
            max_workers=workers, cancel_check=lambda: self._cancelled,
            progress_cb=self._progress)

        # 3) Assembla gli eventi.
        events: List[OcrEvent] = []
        for i, (start_ms, end_ms, pil) in enumerate(decoded, start=1):
            text, conf = ocr_results[i - 1]
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
        """
        Conversione automatica di TUTTE le tracce VOBSUB italiane.
        Singola traccia → writeback() normale.
        Più tracce → mux single-pass (rimuove tutti i bitmap + aggiunge tutti gli SRT).
        """
        streams = self.select_all_vobsub_streams_ita()
        if not streams:
            raise BitmapNotSupported(tr('vob_no_italian_vobsub_subtitle_found'))

        results: List[Tuple[dict, str, str]] = []  # (stream_dict, srt_text, lang2)
        for sub_info in streams:
            try:
                events, lang = self._ocr_single_stream(sub_info)
            except Exception as e:
                logger.warning(f"Stream {sub_info['index']}: errore OCR: {e}")
                self._log(tr('pgs_stream_ocr_failed_skipped').format(index=sub_info['index']))
                continue
            srt = events_to_srt(events)
            if srt.strip():
                results.append((sub_info, srt, lang))
            else:
                self._log(tr('pgs_stream_no_text_skipped').format(index=sub_info['index']))

        if not results:
            self._log(tr('pgs_no_ocr_text_produced'))
            return False

        # Tracce COMPLETE (non forced) date per italiane dal tag ma con testo di un'altra lingua: da
        # tradurre, non da salvare come italiano. Una forced (poche battute, nessun verdetto sulla lingua)
        # non decide: si traduce la traccia completa con piu' testo.
        full = [r for r in results if not r[0].get("forced")]
        if full and not any(lang == 'it' for _, _, lang in full):
            sub_x, srt_x, lang_x = max(full, key=lambda r: len(r[1]))
            self._bitmap_stream_abs_idx = sub_x["index"]
            raise ContentNotItalian(srt_x, lang_x, sub_x["index"])

        if len(results) == 1:
            sub_info, srt, lang = results[0]
            self._bitmap_stream_abs_idx = sub_info["index"]
            return self.writeback(srt, lang)

        return self._writeback_mux_multi(results)

    def _writeback_mux_multi(self, results: List[Tuple[dict, str, str]]) -> bool:
        """
        Mux single-pass: rimuove tutte le tracce VOBSUB OCR-ate e aggiunge gli SRT.
        results: [(stream_dict, srt_text, lang2), ...]
        """
        # Modalita' sidecar (sempre nella pipeline): l'MKV non si tocca e le tracce bitmap restano. Con piu' tracce
        # si scrive UN sidecar: la traccia completa (non forced) con piu' testo.
        if self._cfg(CFG_WRITEBACK, DEFAULT_WRITEBACK) == WRITEBACK_SIDECAR:
            full = [r for r in results if not r[0].get("forced")]
            pool = [r for r in full if r[2] == "it"] or full or results
            sub, srt, lang = max(pool, key=lambda r: len(r[1]))
            self._bitmap_stream_abs_idx = sub["index"]
            self._log(tr('vob_italian_vobsub_tracks_sidecar_from').format(n=len(results), index=sub['index']))
            return self.writeback(srt, lang)

        if self.video_path.suffix.lower() != ".mkv":
            logger.warning(f"Write-back mux multi salta {self.video_path.name}: non è MKV")
            return False

        if not self.extractor.subtitle_streams:
            self.extractor.detect_subtitles()
        all_subs = self.extractor.subtitle_streams
        n_subs = len(all_subs)
        N = len(results)

        bitmap_rel_indices = []
        for sub_info, _, _ in results:
            rel = next(
                (i for i, s in enumerate(all_subs) if s.get("index") == sub_info["index"]), None
            )
            if rel is not None:
                bitmap_rel_indices.append(rel)

        out_sub_start = n_subs - len(bitmap_rel_indices)

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
        for k, (sub_info, _, lang) in enumerate(results):
            out_idx = out_sub_start + k
            cmd += [f"-metadata:s:s:{out_idx}", f"language={lang}"]
            title = srt_track_title((sub_info.get("title") or "").strip())
            if title:
                cmd += [f"-metadata:s:s:{out_idx}", f"title={title}"]
            disposition = "forced" if sub_info.get("forced", False) else "0"
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
        self._log(tr('pgs_srt_tracks_embedded').format(N=N, langs=langs, name=self.video_path.name))
        return True

    # ── Write-back ────────────────────────────────────────────────────────
    def write_sidecar(self, srt_text: str, lang2: str) -> Path:
        """Scrive un sidecar <stem>.<lang2>.srt e ritorna il Path."""
        out = self.video_path.with_name(f"{self.video_path.stem}.{lang2}.srt")
        out.write_text(srt_text, encoding="utf-8")
        self._log(tr('pgs_srt_saved').format(name=out.name))
        return out

    def writeback(self, srt_text: str, language: str) -> bool:
        """Applica l'SRT secondo la strategia CFG_WRITEBACK (mux o sidecar)."""
        writeback = self._cfg(CFG_WRITEBACK, DEFAULT_WRITEBACK)
        if writeback == WRITEBACK_SIDECAR:
            out = self.video_path.with_name(f"{self.video_path.stem}.{language}.srt")
            try:
                out.write_text(srt_text, encoding="utf-8")
            except Exception as e:
                logger.error(f"Scrittura sidecar fallita: {e}")
                return False
            self._log(tr('pgs_srt_saved').format(name=out.name))
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
        Rimuxa l'SRT come nuova traccia testo nell'MKV, in-place, AL POSTO della
        traccia VOBSUB bitmap di origine: `-map "-0:s:{bitmap_rel_idx}"` la
        esclude esplicitamente dall'output, `-map 1:0` aggiunge il nuovo SRT.
        Tutte le altre tracce (video, audio, altri sottotitoli) restano intatte.
        """
        if self.video_path.suffix.lower() != ".mkv":
            logger.warning(f"Write-back mux salta {self.video_path.name}: non è MKV")
            return False

        if not self.extractor.subtitle_streams:
            self.extractor.detect_subtitles()
        subs = self.extractor.subtitle_streams
        n_subs = len(subs)

        # Individua la traccia bitmap da rimuovere
        if self._bitmap_stream_abs_idx is None:
            try:
                self._bitmap_stream_abs_idx = self.select_vobsub_stream().get("index")
            except Exception:
                pass
        orig = next((s for s in subs if s.get("index") == self._bitmap_stream_abs_idx), {})
        bitmap_rel_idx = next(
            (i for i, s in enumerate(subs) if s.get("index") == self._bitmap_stream_abs_idx),
            None,
        )
        new_sub_idx = n_subs - 1 if bitmap_rel_idx is not None else n_subs
        orig_title = srt_track_title((orig.get("title") or "").strip())
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
        self._log(tr('pgs_srt_embedded_in_the_file'))
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
