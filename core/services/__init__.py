# -*- coding: utf-8 -*-
"""Servizi dell'applicazione senza Qt e senza GUI (fase 0 della web UI: docs/WEBUI_PIANO.md).

Qui sta la LOGICA che prima viveva dentro i widget Qt: la GUI Qt e, piu' avanti, la web UI usano gli stessi servizi.
REGOLA: nessun modulo di questo pacchetto importa PyQt6 ne' `gui` (test: linux_tests/test_core_jobs_pure.py)."""
