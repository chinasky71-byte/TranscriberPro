# -*- coding: utf-8 -*-
"""Nome storico: il modello della riga della coda vive in core/services/job_model.py (senza Qt)."""
import sys

from core.services import job_model as _moved

sys.modules[__name__] = _moved
