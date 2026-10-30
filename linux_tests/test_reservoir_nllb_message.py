# -*- coding: utf-8 -*-
"""Il serbatoio NLLB-FT non deve annunciare un generico «NLLB fine-tuned scaricato»: sembrerebbe che NLLB abbia tradotto il file."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.translator as T  # noqa: E402
from utils.translations import tr  # noqa: E402


class _FakeFT:
    announced = []

    def __init__(self, log_callback=None, *a, **k):
        self.log_callback = log_callback

    def _run_translation(self, texts, src, tgt, add_context=False):
        return ['ciao' for _ in texts]

    def cleanup(self, announce=True):
        if announce:
            _FakeFT.announced.append('generico')


def test_serbatoio_nllb_scrive_il_messaggio_dedicato_e_non_quello_generico(monkeypatch):
    monkeypatch.setattr(T, 'NLLBFineTunedTranslator', _FakeFT)
    logs = []
    tr_obj = T.LLMSubtitleTranslator.__new__(T.LLMSubtitleTranslator)
    tr_obj.log = logs.append
    tr_obj.log_callback = None
    out = T.LLMSubtitleTranslator._reservoir_via_nllb(tr_obj, [{'id': 'k', 'text': 'Hi'}])
    assert out == {'k': 'ciao'}
    assert _FakeFT.announced == []                                  # il messaggio generico non c'e'
    assert logs == [tr('tl_reservoir_nllb_unloaded')]
    assert 'serbatoio' in logs[0].lower() or 'reservoir' in logs[0].lower()
