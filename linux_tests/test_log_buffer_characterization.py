# -*- coding: utf-8 -*-
"""LogBuffer (core/services/log_buffer.py) contro il log VERO della GUI Qt (`MainWindow.log_message`): le stesse sequenze di messaggi
producono lo stesso elenco di righe (testo, ordine, barre riscritte sul posto) e gli stessi colori."""
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
from core.services.log_buffer import LogBuffer, kind_of, pct_of  # noqa: E402

T0 = datetime(2026, 10, 28, 6, 15, 52)


@pytest.fixture(scope='module')
def mw(tmp_path_factory):
    import os
    tmp = tmp_path_factory.mktemp('home')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['HOME'] = os.environ['USERPROFILE'] = str(tmp)
    from utils import config as cfg
    cfg.Config.CONFIG_DIR = tmp / '.transcriberpro'
    cfg.Config.CONFIG_FILE = cfg.Config.CONFIG_DIR / 'config.json'
    cfg.reset_config()
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.history_widget import HistoryWidget
    HistoryWidget.HISTORY_FILE = tmp / '.transcriberpro' / 'history.json'
    import gui.main_window as mwmod
    from gui.main_window import MainWindow

    class FakeDT:
        @staticmethod
        def now():
            return T0
    mwmod.datetime = FakeDT
    w = MainWindow()
    yield w
    w.close()
    cfg.reset_config()


def gui_lines(mw):
    doc = mw.log_text.document()
    out = []
    b = doc.begin()
    while b.isValid():
        out.append(b.text().replace(' ', '\n').replace('\xa0', ' '))
        b = b.next()
    return [] if out == [''] else out          # un documento vuoto ha comunque un blocco vuoto


def gui_colors(mw):
    """Colore di ogni riga, letto dall'HTML del documento (primo `color:` di ciascun blocco)."""
    html = mw.log_text.toHtml()
    return re.findall(r'<p [^>]*>.*?</p>', html, flags=re.S)


def run(mw, steps):
    """steps: [(messaggio, compact, hide_progress)]. Dopo OGNI messaggio le righe della GUI e del LogBuffer coincidono."""
    mw.log_text.clear()
    buf = LogBuffer()
    for msg, compact, hide in steps:
        mw.compact_log_enabled = compact
        mw._hide_log_bars = lambda h=hide: h
        mw.log_message(msg)
        buf.add(msg, T0, compact, hide)
        assert [l['text'] for l in buf.lines] == gui_lines(mw), msg
    return buf


BAR = lambda name, pct: f'{name}: [{"#" * (pct // 10)}{"-" * (10 - pct // 10)}] {pct}%'      # noqa: E731


def test_righe_normali_colori_e_testo_su_piu_righe(mw):
    steps = [(m, False, False) for m in ('🎬 Inizio', '✅ Fatto', '❌ Errore grave', '⚠️ Attenzione', '➕ Aggiunto', 'riga muta',
                                         '\n' + '=' * 20 + '\nFile 1/3: a.mkv\n' + '=' * 20, '  due  spazi  ', '🎉 Finito', '--- sep ---')]
    buf = run(mw, steps)
    assert [l['kind'] for l in buf.lines] == ['info', 'success', 'danger', 'warn', 'info', 'muted', 'info', 'muted', 'success', 'info']


@pytest.mark.parametrize('compact,hide', [(False, False), (True, False), (True, True), (False, True)])
def test_barre_riscritte_sul_posto(mw, compact, hide):
    steps = [(m, compact, hide) for m in (
        BAR('Trascrizione', 10), BAR('Trascrizione', 40),                      # aggiornata sull'ultima riga
        '⚠️ avviso in mezzo', BAR('Trascrizione', 60),                          # tolta e riscritta in fondo
        BAR('Demucs', 20), BAR('Trascrizione', 70), BAR('Demucs', 50),          # due barre alternate
        '✅ Trascrizione: [##########] 100%', BAR('Trascrizione', 5),           # completata: la nuova si accoda
        BAR('Trascrizione', 3),                                                 # percentuale piu' bassa dell'ultima: si accoda? (vedi regola)
        '⚙️ OCR 1/10', '⚙️ OCR 2/10', 'x', '⚙️ OCR 3/10',                      # stato senza %: solo se e' l'ultima
        'Progresso: 10%', 'Progress: 20%', 'Warm-up: [#---] 5%', 'Warm-up: [##--] 25%',
        'Traduzione: [#####-----] 50%', 'Translation: [######----] 60%', 'Riconoscimento parlanti: [#-] 10%')]
    run(mw, steps)


def test_barra_con_percentuale_piu_bassa_si_accoda_e_la_ricerca_si_ferma_a_40_righe(mw):
    steps = [(m, False, False) for m in (BAR('Trascrizione', 50), BAR('Trascrizione', 20), BAR('Trascrizione', 20), BAR('Trascrizione', 30))]
    steps += [(BAR('Demucs', 10), False, False)] + [(f'riga {i}', False, False) for i in range(39)] + [(BAR('Demucs', 20), False, False)]
    steps += [(f'altra {i}', False, False) for i in range(41)] + [(BAR('Demucs', 30), False, False)]      # la barra e' oltre le 40 righe: si accoda
    buf = run(mw, steps)
    assert sum('Demucs' in l['text'] for l in buf.lines) == 2
    run(mw, [('✅ Demucs: [##########] 80%', False, False), (BAR('Demucs', 90), False, False), (BAR('Demucs', 95), False, False)])   # completata: si accoda anche se la % non cala


def test_rumore_compatto_e_ram_non_vanno_a_schermo(mw):
    noise = ['📊 VRAM 1.2 GB', 'Parametri profilo caricati', '[DIAG-RAM] 1. x', '❌ 📊 VRAM errore', 'Modello trascrizione: whisper-large']
    steps = [(m, c, False) for c in (False, True) for m in noise + ['riga senza marcatori', '✅ con marcatore', '📥 download']]
    run(mw, steps)


def test_nome_del_modello_nella_tessera(mw):
    buf = LogBuffer()
    for msg, name in (('Modello trascrizione: whisper-large-v3', 'whisper-large-v3'), ('Transcription model: qwen3', 'qwen3'),
                      ('Modello trascrizione:   ', None), ('altro', None)):
        mw.compact_log_enabled = False
        mw._hide_log_bars = lambda: False
        r = buf.add(msg, T0, False, False)
        assert r.model_name == name
    mw.log_message('Modello trascrizione: faster-x')
    assert mw._diag_modello._val.text() == 'faster-x'                      # la tessera «Modello» della GUI mostra il nome


def test_mojibake_riparato_come_nella_gui(mw):
    broken = 'âœ… Fatto'
    run(mw, [(broken, False, False), ('ðŸŽ¬ Titolo', False, False)])


def test_colori_come_nel_log_della_gui(mw):
    for text in ('[06:15:52] ✅ ok', '[06:15:52] 🎉 x', '[06:15:52] ❌ e', '[06:15:52] ⚠️ w', '[06:15:52] 🎬 i', '[06:15:52] ⚙️ i', '[06:15:52] ➕ i',
                 '[06:15:52] === i', '[06:15:52] --- i', '[06:15:52] muta', '[06:15:52] ✅ ❌ misto', '[06:15:52] ❌ ⚠'):
        html = mw._log_color_html(text)
        color = re.search(r'color:(#[0-9a-fA-F]{6})', html).group(1)
        from gui.design_tokens import T
        assert color == T.LOG_COLORS[kind_of(text)], text


def test_massimo_5000_righe(mw):
    mw.log_text.clear()
    buf = LogBuffer()
    for i in range(5003):
        mw.compact_log_enabled = False
        mw.log_message(f'riga {i}')
        buf.add(f'riga {i}', T0)
    assert len(buf.lines) == 5000 and buf.lines[0]['text'].endswith('riga 3') and buf.lines[-1]['text'].endswith('riga 5002')
    assert [l['text'] for l in buf.lines] == gui_lines(mw)


def test_operazioni_per_i_client(mw):
    b = LogBuffer()
    r = b.add('uno', T0)
    assert r.op['op'] == 'append' and r.op['line']['id'] == 1
    r = b.add(BAR('Trascrizione', 10), T0)
    assert r.op['op'] == 'append' and r.op['line']['id'] == 2
    r = b.add(BAR('Trascrizione', 20), T0)
    assert r.op['op'] == 'update_last' and r.op['line']['id'] == 2 and len(b.lines) == 2
    b.add('avviso', T0)
    r = b.add(BAR('Trascrizione', 30), T0)
    assert r.op['op'] == 'replace' and r.op['remove_id'] == 2 and r.op['line']['id'] == 4
    assert [l['id'] for l in b.lines] == [1, 3, 4]
    assert b.add('[DIAG-RAM] x', T0).action == 'drop_ram' and b.add('[DIAG-RAM] x', T0).op is None
    assert pct_of('abc 45% x') == 45 and pct_of('niente') is None
