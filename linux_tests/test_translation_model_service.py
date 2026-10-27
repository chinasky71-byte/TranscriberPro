# -*- coding: utf-8 -*-
"""core/services/translation_model_service.py: cio' che il dialogo non rende osservabile (nome di ripiego)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services.translation_model_service import DISPLAY_NAMES, MODEL_IDS, TranslationModelService


class Cfg:
    saved = None

    def set_translation_model(self, m):
        self.saved = m


def test_nome_di_ripiego_in_maiuscolo():
    c = Cfg()
    s = TranslationModelService(c)
    assert s.commit_selection('qualcosa') == 'QUALCOSA' and c.saved == 'qualcosa'
    assert all(s.commit_selection(m) == DISPLAY_NAMES[m] for m in MODEL_IDS)


class Cfg2:
    def __init__(self, **kw):
        self.kw = kw

    def get(self, k, d=None):
        return self.kw.get(k, d)


def test_prerequisiti_genere_percorsi_candidati(tmp_path):
    from utils.platform_compat import venv_python
    s = TranslationModelService(Cfg2(huggingface_token='hf_x'))
    assert s.gender_prerequisites(tmp_path) == ['tmd_gender_missing_nlp']
    for rel in (('venv_nlp',), ('gender_eval', '.venv_spacy')):
        root = tmp_path.joinpath(*rel[:1]) if False else tmp_path
        py = venv_python(tmp_path.joinpath(*rel))
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text('x')
        assert s.gender_prerequisites(tmp_path) == []
        py.unlink()
        assert s.gender_prerequisites(tmp_path) == ['tmd_gender_missing_nlp']
    assert TranslationModelService(Cfg2()).gender_prerequisites(tmp_path) == ['tmd_gender_missing_nlp', 'tmd_gender_missing_hf']
