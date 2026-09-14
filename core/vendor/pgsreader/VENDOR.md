# pgsreader (vendorizzato)

Parser puro Python per sottotitoli Blu-ray PGS (`.sup`) → immagini + timestamp.
Usato dal ramo `review` di `core/pgs_ocr.py` (vedi `memory/project_pgs_ocr_module.md`).

## Origine
- Upstream: https://github.com/EzraBC/pgsreader.git
- Commit vendorizzato: `b4be94e972aa7fb4070e536ed1bfd8bb30862d81` (2023-10-13)
- Vendorizzato il 2026-06-03 perché **non è pubblicato su PyPI**.

## Licenza
L'upstream **non include un file di licenza**. Progetto piccolo, di pubblico dominio
de-facto, scelto esplicitamente come parser PGS di riferimento. Se in futuro serve
chiarezza legale, valutare la riscrittura del parser (formato PGS documentato:
brevetto US 2009/0185789).

## Patch locali applicate (NON presenti nell'upstream)
- `pgsreader.py` → `WindowDefinitionSegment.__init__`: reso difensivo. L'originale
  assumeva una sola finestra a offset fisso e andava in `IndexError` su file reali
  (riscontrato allo spike su "Prospect (2018)"). Ora itera `num_windows` con guardie
  e mantiene la compatibilità dell'API esponendo la prima finestra.
- `pgsreader.py` → `ObjectDefinitionSegment.__init__`: il warning "Image data length
  asserted does not match the length found" ora scatta solo se `in_sequence ==
  'First and last'`. Il controllo originale confrontava la lunghezza del singolo
  frammento ODS con `data_len` dell'oggetto completo, generando falsi warning su
  ogni bitmap frammentata su più segmenti (riassemblata correttamente a valle in
  `core/pgs_ocr.py`, non qui).

## API usata
```python
from pgsreader import PGSReader
from imagemaker import make_image
pgs = PGSReader(path)
for ds in pgs.displaysets:        # DisplaySet
    if ds.has_image:
        img = make_image(ds.ods[0], ds.pds[0])   # PIL.Image
        start_ms = ds.pcs[0].pts                  # già in millisecondi
```
La gestione di ODS frammentati/multipli e il calcolo dell'end-time (clear successivo)
sono in `core/pgs_ocr.py`, non qui.
