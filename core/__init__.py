"""
Core Package Initialization
File: core/__init__.py

INTENZIONALMENTE VUOTO (come gui/__init__.py): i re-export storici
(`from .pipeline import ProcessingPipeline`, ecc.) caricavano l'INTERO
stack ML (torch + transformers, ~6-9s e ~2GB RAM) a ogni
`import core.qualcosa` — anche per moduli leggeri come core.pgs_types
usati dal thread GUI. Nessun modulo del repo usa `from core import X`
(verificato); importare sempre il modulo specifico:
    from core.pipeline import ProcessingPipeline
"""

# Cache bootstrap defensive: copre esecuzioni `python -m core.*` che
# bypassano main.py. Importa solo os/pathlib: costo ~0.
import utils.cache_bootstrap  # noqa: F401
