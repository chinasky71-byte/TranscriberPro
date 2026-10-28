# -*- coding: utf-8 -*-
"""Spegnimento del PC a fine coda (casella 'Spegni'), senza Qt: comando per sistema e ritardo."""
import os
from typing import List


class ShutdownPolicy:
    DELAY_MS = 5000

    @staticmethod
    def command() -> List[str]:
        return ['shutdown', '/s', '/t', '60'] if os.name == 'nt' else ['shutdown', '-h', '+1']
