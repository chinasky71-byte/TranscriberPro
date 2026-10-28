# -*- coding: utf-8 -*-
"""Compatibilita': il modulo e' stato spostato in core/services/log_filter.py (senza Qt). Questo nome resta come ALIAS dello stesso
modulo (stesso oggetto: monkeypatch e import vecchi continuano a funzionare)."""
import sys

from core.services import log_filter as _moved

sys.modules[__name__] = _moved
