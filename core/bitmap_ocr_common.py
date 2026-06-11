# -*- coding: utf-8 -*-
"""
Helper OCR condivisi tra i moduli sottotitoli bitmap (PGS e VOBSUB).
File: core/bitmap_ocr_common.py

Estratti da core/pgs_ocr.py per riuso da core/vobsub_ocr.py.
VERBATIM: nessuna correzione del testo riconosciuto.
Validati dagli spike PGS (2026-06-03) e VOBSUB (2026-06-03).
"""
import re
from typing import Tuple


def srt_track_title(orig_title: str) -> str:
    """Converte il titolo di una traccia bitmap in titolo SRT.
    Rimuove le keyword codec (pgs/vobsub/ass/ssa) e aggiunge 'SRT' in coda.
    Es: 'Italian Regular PGS' → 'Italian Regular SRT'
    Ritorna stringa vuota se orig_title è vuoto (il chiamante omette il metadata).
    """
    if not orig_title:
        return ""
    cleaned = re.sub(r'\b(pgs|vobsub|ass|ssa)\b', '', orig_title, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return f"{cleaned} SRT" if cleaned else "SRT"


_AVAILABLE_LANGS = None


def available_tesseract_langs():
    """Lingue Tesseract installate (cache). Es. {'eng','ita','spa',...}."""
    global _AVAILABLE_LANGS
    if _AVAILABLE_LANGS is None:
        try:
            import pytesseract
            _AVAILABLE_LANGS = set(pytesseract.get_languages(config=''))
        except Exception:
            _AVAILABLE_LANGS = {'eng'}
    return _AVAILABLE_LANGS


def pick_tesseract_lang(stream_lang3: str, fallback: str = 'eng') -> str:
    """
    Sceglie il modello Tesseract per la lingua della traccia (ISO 639-2, 3 lettere).
    Se il traineddata di quella lingua non è installato, ripiega su `fallback` poi 'eng'.
    """
    avail = available_tesseract_langs()
    s = (stream_lang3 or '').lower()
    if s in avail:
        return s
    if fallback and fallback in avail:
        return fallback
    return 'eng' if 'eng' in avail else (next(iter(avail)) if avail else 'eng')


def preprocess_for_ocr(img, upscale: int = 2, auto_polarity: bool = False):
    """
    Prepara un'immagine bitmap di sottotitolo per Tesseract.
    Composito su nero → grigio → Otsu → (inversione) → upscale → bordo bianco.

    - PGS: testo chiaro su trasparenza → auto_polarity=False (inversione fissa).
    - VOBSUB: colori variabili → auto_polarity=True (sceglie la polarità con lo
      sfondo a maggioranza bianca).

    Ritorna un ndarray uint8 (grayscale) pronto per pytesseract.
    """
    import numpy as np
    import cv2
    from PIL import Image

    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    comp = Image.alpha_composite(bg, rgba).convert("L")
    arr = np.array(comp)
    _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if auto_polarity:
        # vogliamo testo scuro su sfondo bianco → lo sfondo dev'essere maggioranza
        if (th == 255).mean() < 0.5:
            th = 255 - th
    else:
        th = 255 - th  # testo chiaro su nero → inverti
    if th.shape[0] < 50:
        th = cv2.resize(th, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


def ocr_images_parallel(images, language: str, upscale: int, auto_polarity: bool,
                        max_workers: int, cancel_check=None, progress_cb=None):
    """
    Esegue preprocess + OCR verbatim su una lista di immagini IN PARALLELO
    (ThreadPool: ogni chiamata Tesseract è un subprocess che rilascia il GIL →
    usa più core). L'OCR è il collo di bottiglia, l'estrazione no.

    images:      lista di PIL.Image (ordine preservato nel risultato).
    Ritorna:     lista di (text, confidence) nello stesso ordine di `images`.
    cancel_check: callable() -> bool; se True interrompe.
    progress_cb:  callable(percent:int, label:str).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    n = len(images)
    results = [("", 0.0)] * n
    if n == 0:
        return results
    workers = max(1, int(max_workers))

    def _work(i, img):
        pre = preprocess_for_ocr(img, upscale=upscale, auto_polarity=auto_polarity)
        return i, ocr_image_verbatim(pre, language)

    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [ex.submit(_work, i, img) for i, img in enumerate(images)]
        done = 0
        for fut in as_completed(futures):
            if cancel_check and cancel_check():
                ex.shutdown(wait=False, cancel_futures=True)
                raise InterruptedError("Operazione annullata")
            i, res = fut.result()
            results[i] = res
            done += 1
            if progress_cb and (done % 5 == 0 or done == n):
                progress_cb(int(done / n * 100), "Tesseract")
    finally:
        ex.shutdown(wait=False)
    return results


def ocr_image_verbatim(pre, language: str) -> Tuple[str, float]:
    """
    Una passata `image_to_data`: ricostruisce il testo (con '\\n' per riga) e la
    confidenza media per-parola. NESSUNA modifica al testo riconosciuto (verbatim).

    Ritorna (testo, confidenza_media_0_100).
    """
    import pytesseract

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
