# -*- coding: utf-8 -*-
"""Compatibilita': il modulo e' stato spostato in core/jobs/file_progress.py (classe pura, senza Qt, usata anche dalla coda
headless). Questo nome resta come ALIAS dello stesso modulo (stesso oggetto: monkeypatch e import vecchi continuano a funzionare)."""
import sys

from core.jobs import file_progress as _moved

sys.modules[__name__] = _moved
