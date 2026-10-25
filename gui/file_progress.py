# -*- coding: utf-8 -*-
"""Backwards-compatible re-export.

The implementation moved to core/jobs/progress.py (Qt-free). Importing from
here keeps the legacy GUI and old code working while core stops depending on
the gui package.
"""
from core.jobs.progress import *  # noqa: F401,F403
from core.jobs.progress import FileProgress  # noqa: F401
