# -*- coding: utf-8 -*-
"""Compatibilita': il modulo e' stato spostato in core/services/settings_service.py (logica pura, senza Qt). Questo nome resta come ALIAS
dello stesso modulo (stesso oggetto: monkeypatch e import vecchi continuano a funzionare)."""
import sys

from core.services import settings_service as _moved

sys.modules[__name__] = _moved
