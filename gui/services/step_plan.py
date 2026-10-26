# -*- coding: utf-8 -*-
"""Compatibilita': il modulo e' stato spostato in core/jobs/step_plan.py (classe pura, senza Qt). Questo nome resta come ALIAS
dello stesso modulo (stesso oggetto: monkeypatch e import vecchi continuano a funzionare)."""
import sys

from core.jobs import step_plan as _moved

sys.modules[__name__] = _moved
