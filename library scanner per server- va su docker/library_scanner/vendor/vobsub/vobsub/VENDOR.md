# vobsub (vendorizzato)

Parser VOBSUB (DVD `.idx`/`.sub`) → immagini + timestamp. Usato da `core/vobsub_ocr.py`.

## Origine
- Upstream: https://github.com/vincrichard/VobSub-ML-OCR (cartella `vob_sub/`)
- Estrazione **portata da Subtitle Edit** a Python.
- Licenza: **MIT** (vedi `LICENSE`).
- Vendorizzato il 2026-06-03 (non su PyPI; serve solo la parte di estrazione, non l'OCR ML).

## Cosa si usa / cosa NO
- USATO: `vob_sub_parser.VobSubParser` → `open_sub_idx(sub, idx)` → `merge_vob_sub_packs()`
  → pack con `.start_time`/`.end_time` (custom_timedelta, ha `total_seconds()`),
  `.get_bitmap()` (np array) e parser `.idx_palette`.
- NON usare `main.py` (importa `matplotlib`/`tqdm`). Il nostro `vobsub_ocr.py` chiama
  direttamente il parser e converte il bitmap in PIL.
- `__init__.py` è vuoto → importare i sottomoduli non tira dipendenze pesanti.

## Dipendenze runtime (solo estrazione)
- `numpy` (già nel progetto)
- `colour` (installato; `from colour import Color` in custom_color.py)

## Note
- `VobSubParser(is_pal)`: PAL=720x576, NTSC=720x480 (rilevabile dalla riga `size:` dell'.idx).
- Validato dallo spike 2026-06-03 su Duplex (2003): timing start/end corretti, OCR ita conf 89-95.
