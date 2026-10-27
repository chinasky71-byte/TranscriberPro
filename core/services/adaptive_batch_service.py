# -*- coding: utf-8 -*-
"""Impostazioni del batch adattivo, senza Qt.

Trasposizione fedele di gui/adaptive_batch_settings_widget.py: valori di default di "Ripristina", testo di stato, scrittura delle
sette chiavi di config con un solo salvataggio finale. Il widget resta la vista."""
from dataclasses import dataclass

from utils.translations import tr


@dataclass(frozen=True)
class AdaptiveBatchValues:
    enabled: bool = True
    initial_size: int = 0          # 0 = rilevamento automatico
    min_size: int = 1
    max_size: int = 24
    warmup_batches: int = 5
    high_threshold: float = 0.85
    low_threshold: float = 0.60


DEFAULTS = AdaptiveBatchValues()
_KEYS = ('adaptive_batch_enabled', 'adaptive_batch_initial_size', 'adaptive_batch_min_size', 'adaptive_batch_max_size',
         'adaptive_batch_warmup_batches', 'adaptive_batch_high_threshold', 'adaptive_batch_low_threshold')


class AdaptiveBatchService:
    def __init__(self, config):
        self._config = config

    def load(self) -> AdaptiveBatchValues:
        cfg = self._config.get_adaptive_batch_config()
        return AdaptiveBatchValues(
            enabled=cfg['enabled'], initial_size=self._config.get('adaptive_batch_initial_size', 0),
            min_size=cfg['min_size'], max_size=cfg['max_size'], warmup_batches=cfg['warmup_batches'],
            high_threshold=cfg['high_threshold'], low_threshold=cfg['low_threshold'])

    def status_text(self, enabled: bool) -> str:
        if not enabled:
            return tr('abs_disabled_status')
        cfg = self._config.get_adaptive_batch_config()
        initial_txt = tr('abs_autodetect') if not cfg['initial_size'] else str(cfg['initial_size'])
        return tr('abs_active_status').format(
            initial=initial_txt, min=cfg['min_size'], max=cfg['max_size'], warmup=cfg['warmup_batches'])

    def save(self, v: AdaptiveBatchValues) -> None:
        """Scrive le sette chiavi senza salvare e poi salva UNA volta."""
        for key, value in zip(_KEYS, (v.enabled, v.initial_size, v.min_size, v.max_size, v.warmup_batches,
                                      v.high_threshold, v.low_threshold)):
            self._config.set(key, value, save=False)
        self._config.save()
