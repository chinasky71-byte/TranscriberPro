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


def _run(tmp_path, selector):
    srt = tmp_path / 'a.srt'
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nCiao\n\n", encoding='utf-8')
    lines, got = [], _collect()
    c = g2.GenderCorrectorV2(log_callback=lines.append)
    c._run_selector = selector
    assert c.correct_file(srt, tmp_path / 'o.srt') is True
    return lines, [f['pct'] for k, f in got if k == 'bar']


def test_salto_senza_lavoro_chiude_la_card_ma_non_scrive_100_nel_log(tmp_path):
    lines, pcts = _run(tmp_path, lambda l: None)      # selettore fallito: SRT copiato
    assert pcts[-1] == 100
    assert not any(Translations.TEXTS['en']['g2_progress_done'] in l or Translations.TEXTS['it']['g2_progress_done'] in l
                   for l in lines)


def test_lavoro_completo_chiude_una_sola_volta(tmp_path):
    lines, pcts = _run(tmp_path, lambda l: ([[]], [[]]))   # nessuna riga candidata
    assert pcts == sorted(pcts) and pcts.count(100) == 1
