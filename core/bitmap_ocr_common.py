# -*- coding: utf-8 -*-
"""
Helper OCR condivisi tra i moduli sottotitoli bitmap (PGS e VOBSUB).
File: core/bitmap_ocr_common.py

Estratti da core/pgs_ocr.py per riuso da core/vobsub_ocr.py.
VERBATIM: nessuna correzione del testo riconosciuto.
Validati dagli spike PGS (2026-06-03) e VOBSUB (2026-06-03).
"""
from typing import Tuple


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
    th = cv2.resize(th, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


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
