# -*- coding: utf-8 -*-
"""G3 (fase 0 della web UI): CARATTERIZZAZIONE di gui/ocr_review_dialog.py::OcrReviewDialog.

Passa identica sul codice vecchio e su quello con la logica in core/services/ocr_review_service.py: etichette della lista, contatore,
filtro "solo dubbi", navigazione (precedente/successivo/prossimo dubbio con giro completo), salvataggio del testo, "verificato",
corsivo, riga di info, SRT finale. Qt offscreen, eventi senza immagine."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def qt(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    for w in app.topLevelWidgets():
        w.deleteLater()
    app.processEvents()


def evs():
    from core.pgs_types import OcrEvent
    return [
        OcrEvent(index=1, start_ms=1000, end_ms=2500, text='Ciao a tutti', confidence=95.0),
        OcrEvent(index=2, start_ms=3_600_000 + 5, end_ms=3_700_000, text='Dubbio uno\nsecondo rigo', confidence=60.0, flags={'low_conf'}),
        OcrEvent(index=3, start_ms=4000, end_ms=5000, text='', confidence=80.0, flags={'empty'}),
        OcrEvent(index=4, start_ms=6000, end_ms=7000, text='x' * 60, confidence=75.0),
        OcrEvent(index=5, start_ms=8000, end_ms=9000, text='Altro dubbio', confidence=40.0, flags={'low_conf'}, verified=False),
        OcrEvent(index=6, start_ms=9500, end_ms=9900, text='Gia verificato', confidence=30.0, flags={'low_conf'}, verified=True),
    ]


def make(events=None):
    from gui.ocr_review_dialog import OcrReviewDialog
    return OcrReviewDialog(evs() if events is None else events)


def labels(d):
    return [d.list_widget.item(i).text() for i in range(d.list_widget.count())]


def test_etichette_e_contatore(qt):
    from utils.translations import tr
    d = make()
    assert labels(d) == [
        '🟢 #1  Ciao a tutti',
        '🔴 #2  Dubbio uno secondo rigo',
        f"🟡 #3  {tr('ocr_empty_text')}".replace('🟡', '🟡'),
        '🟡 #4  ' + 'x' * 40 + '…',
        '🔴 #5  Altro dubbio',
        '🔴 #6  ✓ Gia verificato',
    ]
    assert d.counter_label.text() == tr('ocr_counter').format(total=6, flagged=3)       # il verificato non conta


def test_selezione_iniziale_e_info(qt):
    from utils.translations import tr
    d = make()
    assert d._current == 1 and d.list_widget.currentRow() == 1
    assert d.event_info.text() == (f"#2  01:00:00,005 → 01:01:40,000  ·  {tr('ocr_confidence')}: 60  ·  {tr('ocr_state_flagged')}")
    assert d.text_edit.toPlainText() == 'Dubbio uno\nsecondo rigo'
    assert d.text_edit.isEnabled() and d.prev_btn.isEnabled() and d.next_btn.isEnabled()
    d._select_index(0)
    assert d.event_info.text().endswith(tr('ocr_state_ok')) and not d.prev_btn.isEnabled()
    d._select_index(5)
    assert d.event_info.text().endswith(tr('ocr_state_verified')) and not d.next_btn.isEnabled()


def test_senza_dubbi_parte_dal_primo(qt):
    from core.pgs_types import OcrEvent
    d = make([OcrEvent(index=1, start_ms=0, end_ms=1, text='a', confidence=90.0)])
    assert d._current == 0


def test_lista_vuota(qt):
    d = make([])
    assert d._current == -1 and not d.text_edit.isEnabled() and not d.verify_btn.isEnabled() and d.event_info.text() == ''
    assert d.get_srt() == '' or isinstance(d.get_srt(), str)


def test_filtro_solo_dubbi(qt):
    d = make()
    d.only_flagged_cb.setChecked(True)
    assert labels(d) == [l for l in labels(make()) if l.startswith(('🔴 #2', '🟡 #3', '🔴 #5'))]
    assert d._current == 1 and d.list_widget.currentRow() == 0
    d._select_index(0)                              # evento filtrato fuori: il filtro si disattiva da solo
    assert not d.only_flagged_cb.isChecked() and d.list_widget.count() == 6 and d._current == 0


def test_navigazione(qt):
    d = make()
    d._go_next()
    assert d._current == 2
    d._go_prev()
    d._go_prev()
    assert d._current == 0
    d._go_prev()
    assert d._current == 0
    d._select_index(5)
    d._go_next()
    assert d._current == 5


def test_prossimo_dubbio_con_giro(qt):
    d = make()
    assert d._next_flagged_from(1) == 2 and d._next_flagged_from(2) == 4
    assert d._next_flagged_from(4) == 1                      # giro completo: il #6 e' verificato
    assert d._next_flagged_from(-1) == 1
    d.events[1].flags = set()
    d.events[2].flags = set()
    d.events[4].flags = set()
    assert d._next_flagged_from(0) is None


def test_invio_salva_e_salta(qt):
    d = make()
    d.text_edit.setPlainText('Corretto uno')
    d._on_enter_save_next()
    assert d.events[1].text == 'Corretto uno' and d._current == 2
    assert labels(d)[1] == '🔴 #2  Corretto uno'
    d._select_index(4)
    d.events[1].flags = set()
    d.events[2].flags = set()
    d._on_enter_save_next()
    assert d._current == 4                                   # unico dubbio rimasto: nessun salto


def test_verificato(qt):
    from utils.translations import tr
    d = make()
    d.text_edit.setPlainText('Testo verificato')
    d._mark_verified()
    ev = d.events[1]
    assert ev.verified and ev.flags == set() and ev.text == 'Testo verificato' and d._current == 2
    assert labels(d)[1] == '🔴 #2  ✓ Testo verificato'
    assert d.counter_label.text() == tr('ocr_counter').format(total=6, flagged=2)
    d.only_flagged_cb.setChecked(True)
    d._select_index(4)
    d._mark_verified()
    assert d.events[4].verified
    # c'e' ancora il #3: si salta li' e la lista NON si ripopola (l'item verificato resta, con la spunta)
    assert d._current == 2 and labels(d)[1].startswith('🔴 #5  ✓ ')
    d._select_index(2)
    d.events[2].flags = set()
    d._select_index(4)
    d._mark_verified()
    # nessun altro dubbio: con il filtro attivo la lista si ripopola e il verificato sparisce
    assert labels(d) == []


def test_verificato_senza_selezione(qt):
    d = make([])
    d._mark_verified()
    d._save_current_text()
    assert d.events == []


def test_corsivo(qt):
    d = make()
    d.text_edit.setPlainText('  uno due  ')
    d._toggle_italic()
    assert d.text_edit.toPlainText() == '  <i>uno due</i>  ' and d.events[1].text == '  <i>uno due</i>  '
    d._toggle_italic()
    assert d.text_edit.toPlainText() == '  uno due  '
    d.text_edit.setPlainText('')
    d._toggle_italic()
    assert d.text_edit.toPlainText() == ''
    d.text_edit.setPlainText('alfa beta gamma')
    cur = d.text_edit.textCursor()
    cur.setPosition(5)
    cur.setPosition(9, cur.MoveMode.KeepAnchor)
    d.text_edit.setTextCursor(cur)
    d._toggle_italic()
    assert d.text_edit.toPlainText() == 'alfa <i>beta</i> gamma'
    assert d.text_edit.textCursor().selectedText() == '<i>beta</i>'


@pytest.mark.parametrize('text,exp', [('a', '<i>a</i>'), ('<i>a</i>', 'a'), (' <i>a b</i>\n', ' a b\n'), ('   ', '   '),
                                      ('<i>a', '<i><i>a</i>'), ('a</i>', '<i>a</i></i>')])
def test_corsivo_statico(qt, text, exp):
    from gui.ocr_review_dialog import OcrReviewDialog
    assert OcrReviewDialog._toggle_italic_on(text) == exp


def test_srt_finale_e_chiusura(qt):
    d = make()
    d.text_edit.setPlainText('Modificato')
    srt = d.get_srt()
    assert 'Modificato' in srt and 'Ciao a tutti' in srt and '00:00:01,000 --> 00:00:02,500' in srt
    assert srt.count('-->') == 5                              # l'evento vuoto e' saltato
    assert d.get_events() is d.events
    d.text_edit.setPlainText('Alla chiusura')
    d._on_done()
    assert d.events[1].text == 'Alla chiusura' and d.result() == d.DialogCode.Accepted


@pytest.mark.parametrize('conf,dot', [(85.0, '🟢'), (84.9, '🟡'), (70.0, '🟡'), (69.9, '🔴'), (0.0, '🔴')])
def test_soglie_pallino(qt, conf, dot):
    from core.pgs_types import OcrEvent
    d = make([OcrEvent(index=1, start_ms=0, end_ms=1, text='a', confidence=conf)])
    assert labels(d)[0].startswith(dot)


def test_lunghezza_massima_etichetta(qt):
    from core.pgs_types import OcrEvent
    d = make([OcrEvent(index=1, start_ms=0, end_ms=1, text='y' * 40), OcrEvent(index=2, start_ms=0, end_ms=1, text='y' * 41)])
    assert labels(d)[0].endswith('y' * 40) and labels(d)[1].endswith('y' * 40 + '…')


def test_giro_completo_include_l_indice_di_partenza(qt):
    from core.pgs_types import OcrEvent
    evs2 = [OcrEvent(index=1, start_ms=0, end_ms=1, text='a', flags={'f'}), OcrEvent(index=2, start_ms=0, end_ms=1, text='b')]
    d = make(evs2)
    assert d._next_flagged_from(0) == 0 and d._next_flagged_from(1) == 0


def test_testo_invariato_non_cambia_etichetta(qt):
    d = make()
    before = labels(d)
    d._save_current_text()
    assert labels(d) == before
