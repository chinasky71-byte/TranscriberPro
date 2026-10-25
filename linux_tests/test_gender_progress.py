# -*- coding: utf-8 -*-
"""Barra di avanzamento ed ETA della correzione di genere v2 (card del log sintetico)."""
import pytest

from core import gender_corrector_v2 as g2
from gui.file_progress import FileProgress
from gui.services.log_filter import LogFilter
from gui.services.step_plan import PlanOptions, StepTracker
from utils import events
from utils.translations import Translations


def _collect():
    got = []
    events.set_sink(lambda k, f: got.append((k, f)))
    return got


@pytest.fixture(autouse=True)
def _no_sink():
    yield
    events.set_sink(None)


def test_barra_monotona_emette_eventi_bar_e_righe_aggiornabili():
    got, lines = _collect(), []
    bar = g2._GenderBar(lines.append)
    for f in (0.0, 0.05, 0.05, 0.10, 0.5, 1.0):
        bar.set(f)
    pcts = [f['pct'] for k, f in got if k == 'bar' and f['phase'] == 'gender']
    assert pcts == [0, 5, 10, 50, 100]
    assert len(lines) == len(pcts)
    assert all(LogFilter().decide(l).action == 'progress' for l in lines[:-1])


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_chiavi_g2_progress_in_entrambe_le_lingue(lang):
    tx = Translations.TEXTS[lang]
    line = tx['g2_progress_eta'].format(bar='█' * 4 + '░' * 6, progress=40, eta_str='30s')
    assert LogFilter().decide(line).action == 'progress'
    assert '100%' in tx['g2_progress_done']
    fp = FileProgress('ita')
    fp.feed('6.5. gender')
    assert fp.phase == 'gender'
    fp.feed(line)
    assert fp.fraction['gender'] == pytest.approx(0.4)


def test_la_card_mostra_percentuale_ed_eta_dalla_barra():
    tr = StepTracker('/x/film.mkv', PlanOptions(gender=True))
    tr.feed_event('phase', {'name': 'gender'})
    tr.feed_event('bar', {'phase': 'gender', 'pct': 40, 'eta_s': 90})
    step = next(st for st in tr.snapshot().steps if st.key == 'gender')
    assert (step.status, step.pct, step.eta) == ('active', 40, '~2m')
