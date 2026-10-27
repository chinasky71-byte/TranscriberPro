# -*- coding: utf-8 -*-
"""G2 (fase 0 della web UI): CARATTERIZZAZIONE di gui/glossary_dialog.py.

Passa identica sul codice vecchio e su quello con la logica in core/services/glossary_service.py: funzioni di nome/slug/candidati
(usate con i NOMI VECCHI del modulo), costruzione dell'args.json dell'avvio, lettura del report, salvataggio dei termini approvati.
Qt offscreen, worker finto, config e glossari su cartelle temporanee."""
import json
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
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    yield app
    cfg.reset_config()


@pytest.fixture
def boxes(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    class Seen(list):
        pass
    seen = Seen()
    answer = {'q': QMessageBox.StandardButton.Yes}
    for kind in ('warning', 'information', 'critical'):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda p, t, m, *a, _k=kind, **k: seen.append((_k, t, m)) or 0))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda p, t, m, *a, **k: seen.append(('question', t, m)) or answer['q']))
    seen.answer = answer
    return seen


# --------------------------------------------------------------------------------------------------- funzioni pure
def test_slugify():
    from gui.glossary_dialog import _slugify
    assert _slugify('  The Walking Dead! (2010) ') == 'the_walking_dead_2010'
    assert _slugify('Àèì  ') == 'show' and _slugify('') == 'show' and _slugify('A--B') == 'a_b'


@pytest.mark.parametrize('name,is_season', [('Season 2', True), ('stagione 10', True), ('S3', True), ('Staffel_4', True),
                                            ('Specials', True), ('Extras', True), ('Special Features', True),
                                            ('Season of the Witch', False), ('Show', False), ('Season 2 extra', False)])
def test_cartella_stagione(name, is_season):
    from gui.glossary_dialog import _SEASON_DIR_RE
    assert bool(_SEASON_DIR_RE.match(name)) is is_season


def touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'x')


def test_titolo_dai_file(tmp_path):
    from gui.glossary_dialog import _title_from_episode_files
    touch(tmp_path / 'The.Show.Name.S01E02.1080p.mkv')
    assert _title_from_episode_files(tmp_path) == 'The Show Name'
    d = tmp_path / 'x'
    touch(d / 'Altro_Titolo - 2x05.srt')
    assert _title_from_episode_files(d) == 'Altro Titolo'
    assert _title_from_episode_files(tmp_path / 'inesistente') is None
    touch(tmp_path / 'y' / 'Solo.Testo.S01E01.txt')                      # estensione non ammessa: ignorato
    assert _title_from_episode_files(tmp_path / 'y') is None
    empty = tmp_path / 'e'
    empty.mkdir()
    touch(empty / 'nota.txt')
    touch(empty / 'S01E01.mkv')                      # niente titolo prima del codice
    assert _title_from_episode_files(empty) is None


def test_titolo_profondita(tmp_path):
    from gui.glossary_dialog import _title_from_episode_files
    touch(tmp_path / 'sub' / 'Ep.Show.S02E03.mkv')
    assert _title_from_episode_files(tmp_path) == 'Ep Show'              # un livello di sottocartelle
    touch(tmp_path / 'a' / 'b' / 'Deep.S01E01.mkv')
    (tmp_path / 'sub' / 'Ep.Show.S02E03.mkv').unlink()
    assert _title_from_episode_files(tmp_path) is None                   # due livelli: troppo in profondita'
    assert _title_from_episode_files(tmp_path, depth=2) == 'Deep'


def test_candidati_nome(tmp_path):
    from gui.glossary_dialog import _name_candidates
    show = tmp_path / 'My Show'
    touch(show / 'My.Show.S01E01.mkv')
    assert _name_candidates(str(show)) == ['My Show', tmp_path.name]
    season = tmp_path / 'Plex Show' / 'Season 2'
    touch(season / 'Titolo.Dal.File.S02E01.mkv')
    assert _name_candidates(str(season)) == ['Plex Show', 'Titolo Dal File']      # la cartella padre per prima; 'Season 2' mai fra i candidati
    film = tmp_path / 'Film (2020)'
    film.mkdir()
    assert _name_candidates(str(film)) == ['Film (2020)', tmp_path.name]
    touch(tmp_path / 'My Show2' / 'my show2.S01E01.mkv')
    assert _name_candidates(str(tmp_path / 'My Show2')) == ['My Show2', tmp_path.name]      # doppioni (senza maiuscole) scartati


# ------------------------------------------------------------------------------------------------------ il dialogo
class FakeWorker:
    instances = []

    def __init__(self, payload, work_dir, parent=None):
        from PyQt6.QtCore import QObject, pyqtSignal
        self.payload, self.work_dir, self.started, self.cancelled = payload, work_dir, False, False
        FakeWorker.instances.append(self)
        sigs = type('S', (QObject,), {'gate': pyqtSignal(dict), 'progress': pyqtSignal(str, int, int, str),
                                      'log_line': pyqtSignal(str), 'finished_ok': pyqtSignal(str), 'failed': pyqtSignal(str)})
        self.s = sigs()
        for n in ('gate', 'progress', 'log_line', 'finished_ok', 'failed'):
            setattr(self, n, getattr(self.s, n))

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started and not self.cancelled

    def cancel(self):
        self.cancelled = True

    def wait(self, ms=0):
        return True


@pytest.fixture
def dlg(qt, boxes, monkeypatch, tmp_path):
    import gui.glossary_dialog as gd
    FakeWorker.instances.clear()
    monkeypatch.setattr(gd, 'GlossaryBuilderWorker', FakeWorker)
    monkeypatch.setattr(gd, 'venv_glossary_available', lambda: True)
    from utils.config import get_config
    monkeypatch.setattr(type(get_config()), 'resolve_llm_model', lambda self, key='x', preference=None: ('', 0))
    d = gd.GlossaryDialog()
    d.show_dir = tmp_path / 'My Show'
    d.show_dir.mkdir()
    return d


def test_avvio_senza_cartella(dlg, boxes):
    from utils.translations import tr
    dlg._on_run()
    assert boxes == [('warning', tr('glossary_dialog_title'), tr('glossary_error_no_folder'))] and FakeWorker.instances == []


def test_avvio_senza_tmdb_chiede_conferma(dlg, boxes):
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    dlg.folder_edit.setText(str(dlg.show_dir))
    boxes.answer['q'] = QMessageBox.StandardButton.No
    dlg._on_run()
    assert boxes == [('question', tr('glossary_dialog_title'), tr('glossary_confirm_no_tmdb'))] and FakeWorker.instances == []


def test_payload_senza_tmdb(dlg, boxes, monkeypatch):
    import gui.glossary_dialog as gd
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('My Show: la serie!')
    dlg._on_run()
    w = FakeWorker.instances[0]
    assert w.started and w.payload == {
        'show_dir': str(dlg.show_dir), 'name': 'my_show_la_serie', 'tmdb_id': None, 'min_freq': 3, 'min_episodes': 6,
        'min_blocks': 6000, 'use_align': True, 'use_qwen': False, 'qwen_model_path': None, 'align_device': 'cpu',
        'qwen_n_gpu_layers': 0, 'exclude_episodes': []}
    assert w.work_dir == gd.PROJECT_ROOT / 'glossary_engine' / 'glossary_work' / 'my_show_la_serie'
    assert not dlg.run_btn.isEnabled() and dlg.cancel_btn.isEnabled() and not dlg.save_btn.isEnabled()
    assert dlg.progress_bar.maximum() == 0


def test_nome_vuoto_usa_il_primo_candidato(dlg):
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg._name_candidates = ['Il Candidato']
    dlg._on_run()
    assert FakeWorker.instances[0].payload['name'] == 'il_candidato'
    dlg._name_candidates = []
    dlg._on_run()
    assert FakeWorker.instances[1].payload['name'] == 'my_show'            # nome della cartella


def test_payload_con_tmdb_e_qwen(dlg, monkeypatch, tmp_path):
    import core.glossary_state as gs
    from utils.config import get_config
    monkeypatch.setattr(gs, 'load_used', lambda tid: {(1, 2), (1, 3)} if tid == 99 else set())
    monkeypatch.setattr(type(get_config()), 'resolve_llm_model', lambda self, key='x', preference=None: ('/m/q.gguf', -1))
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('Show')
    dlg._tmdb_id = 99
    dlg._on_run()
    p = FakeWorker.instances[0].payload
    assert p['name'] == 'show_99' and p['tmdb_id'] == 99 and p['use_qwen'] is True and p['qwen_model_path'] == '/m/q.gguf'
    assert p['qwen_n_gpu_layers'] == -1 and sorted(p['exclude_episodes']) == [[1, 2], [1, 3]]


def test_qwen_su_sola_cpu_non_si_accende(dlg, monkeypatch):
    from utils.config import get_config
    monkeypatch.setattr(type(get_config()), 'resolve_llm_model', lambda self, key='x', preference=None: ('/m/q.gguf', 0))
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('S')
    dlg._on_run()
    p = FakeWorker.instances[0].payload
    assert p['use_qwen'] is False and p['qwen_model_path'] is None and p['qwen_n_gpu_layers'] == 0


def test_lettura_stato_episodi_fallita_non_blocca(dlg, monkeypatch):
    import core.glossary_state as gs
    monkeypatch.setattr(gs, 'load_used', lambda tid: (_ for _ in ()).throw(OSError('x')))
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('S')
    dlg._tmdb_id = 5
    dlg._on_run()
    assert FakeWorker.instances[0].payload['exclude_episodes'] == []


REPORT = {'gate': {'ok': True, 'blocks': 7000, 'need_blocks': 6000}, 'tmdb_id': 77, 'episodes_used': [[1, 1], [1, 2]],
          'candidates': [
              {'term': 'Khaleesi', 'dominant': 'Khaleesi', 'status': 'auto', 'occurrences': 12, 'clusters': [
                  {'text': 'Khaleesi', 'n': 10, 'examples': [{'en': 'x' * 100, 'it': 'y'}]}]},
              {'term': 'Winterfell', 'dominant': 'Grande Inverno', 'status': 'review'},
              {'term': 'Boh', 'dominant': None, 'status': 'reject'}]}


def finish(dlg, tmp_path, report):
    p = tmp_path / 'report.json'
    p.write_text(json.dumps(report), encoding='utf-8')
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('S')
    dlg._tmdb_id = 77
    dlg._on_run()
    FakeWorker.instances[-1].finished_ok.emit(str(p))
    return FakeWorker.instances[-1]


def test_esito_ok_crea_le_card(dlg, tmp_path):
    from utils.translations import tr
    finish(dlg, tmp_path, REPORT)
    assert dlg.status_label.text() == tr('glossary_status_done').format(n=3)
    assert [c.record['term'] for c in dlg._term_cards] == ['Khaleesi', 'Winterfell', 'Boh']
    assert [c.approve_cb.isChecked() for c in dlg._term_cards] == [True, False, False]
    assert [c.rendering_edit.text() for c in dlg._term_cards] == ['Khaleesi', 'Grande Inverno', '']
    assert dlg.save_btn.isEnabled() and dlg.run_btn.isEnabled() and not dlg.cancel_btn.isEnabled()
    assert dlg.progress_bar.maximum() == 1 and dlg.progress_bar.value() == 1


def test_esito_gate_insufficiente(dlg, tmp_path):
    from utils.translations import tr
    rep = dict(REPORT, gate={'ok': False, 'blocks': 100, 'need_blocks': 6000}, candidates=[REPORT['candidates'][0]])
    finish(dlg, tmp_path, rep)
    assert dlg.status_label.text() == tr('glossary_gate_insufficient').format(blocks=100, need=6000)
    assert dlg._term_cards == [] and not dlg.save_btn.isEnabled()


def test_esito_errore_qwen_e_report_illeggibile(dlg, tmp_path):
    from utils.translations import tr
    finish(dlg, tmp_path, dict(REPORT, qwen_channel_error='GPU piena'))
    assert tr('glossary_qwen_channel_failed').format(msg='GPU piena') in dlg.log_view.toPlainText()
    w = FakeWorker.instances[-1]
    dlg._on_run()
    w = FakeWorker.instances[-1]
    w.finished_ok.emit(str(tmp_path / 'non_esiste.json'))
    assert dlg.status_label.text().startswith(tr('glossary_status_failed').format(msg='Report illeggibile: ')[:20])
    assert dlg.run_btn.isEnabled()


def test_segnali_progresso_gate_log_fallimento(dlg):
    from utils.translations import tr
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('S')
    dlg._tmdb_id = 1
    dlg._on_run()
    w = FakeWorker.instances[0]
    w.progress.emit('align', 2, 8, 'msg')
    assert dlg.status_label.text() == '[align] msg (2/8)' and (dlg.progress_bar.maximum(), dlg.progress_bar.value()) == (8, 2)
    w.progress.emit('fase', 0, 0, '')
    assert dlg.status_label.text() == 'fase'
    w.gate.emit({'ok': False, 'blocks': 1, 'need_blocks': 2})
    assert dlg.status_label.text() == tr('glossary_gate_insufficient').format(blocks=1, need=2)
    w.log_line.emit('riga')
    assert 'riga' in dlg.log_view.toPlainText()
    w.failed.emit('boom')
    assert dlg.status_label.text() == tr('glossary_status_failed').format(msg='boom') and dlg.run_btn.isEnabled()
    assert not dlg.cancel_btn.isEnabled()


def test_annulla_e_chiusura(dlg):
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('S')
    dlg._tmdb_id = 1
    dlg._on_run()
    w = FakeWorker.instances[0]
    dlg._on_cancel()
    assert w.cancelled and not dlg.cancel_btn.isEnabled()


# ---------------------------------------------------------------------------------------------------- salvataggio
def test_salvataggio_dei_termini_approvati(dlg, tmp_path, boxes, monkeypatch):
    import core.glossary as G
    import core.glossary_state as GS
    from utils.translations import tr
    calls = {}
    monkeypatch.setattr(G, 'merge_glossary', lambda tid, terms: calls.setdefault('merge', (tid, dict(terms))) and Path('/g/77.json'))
    monkeypatch.setattr(GS, 'mark_used', lambda tid, eps: calls.setdefault('used', (tid, eps)))
    finish(dlg, tmp_path, REPORT)
    boxes.clear()
    dlg._term_cards[1].approve_cb.setChecked(True)
    dlg._term_cards[1].rendering_edit.setText('  Grande Inverno ')
    dlg._term_cards[2].approve_cb.setChecked(True)               # senza resa: scartato
    dlg._on_save()
    assert calls['merge'] == (77, {'Khaleesi': 'Khaleesi', 'Winterfell': 'Grande Inverno'})
    assert calls['used'] == (77, [(1, 1), (1, 2)])
    assert boxes == [('information', tr('glossary_dialog_title'),
                      tr('glossary_save_success').format(n=2, path=str(Path('/g/77.json'))))]


def test_salvataggio_senza_termini_o_senza_tmdb_o_con_errore(dlg, tmp_path, boxes, monkeypatch):
    import core.glossary as G
    from utils.translations import tr
    dlg._on_save()
    assert boxes == []                                               # nessun report: niente
    finish(dlg, tmp_path, dict(REPORT, tmdb_id=None, episodes_used=[]))
    boxes.clear()
    dlg._tmdb_id = None
    dlg._on_save()
    assert boxes == [('warning', tr('glossary_dialog_title'), tr('glossary_error_no_tmdb_save'))]
    boxes.clear()
    dlg._tmdb_id = 5
    for c in dlg._term_cards:
        c.approve_cb.setChecked(False)
    dlg._on_save()
    assert boxes == [('information', tr('glossary_dialog_title'), tr('glossary_no_terms_approved'))]
    boxes.clear()
    dlg._term_cards[0].approve_cb.setChecked(True)
    monkeypatch.setattr(G, 'merge_glossary', lambda tid, terms: (_ for _ in ()).throw(OSError('disco')))
    dlg._on_save()
    assert boxes == [('critical', tr('glossary_dialog_title'), tr('glossary_save_error').format(error='disco'))]


def test_salvataggio_senza_episodi_non_marca(dlg, tmp_path, boxes, monkeypatch):
    import core.glossary as G
    import core.glossary_state as GS
    monkeypatch.setattr(G, 'merge_glossary', lambda tid, terms: Path('/g/x.json'))
    monkeypatch.setattr(GS, 'mark_used', lambda *a: (_ for _ in ()).throw(AssertionError('non va chiamata')))
    finish(dlg, tmp_path, dict(REPORT, episodes_used=[]))
    dlg._on_save()
    assert boxes[-1][0] == 'information'


def test_senza_tmdb_non_legge_gli_episodi_usati(dlg, monkeypatch):
    import core.glossary_state as gs
    called = []
    monkeypatch.setattr(gs, 'load_used', lambda tid: called.append(tid) or set())
    dlg.folder_edit.setText(str(dlg.show_dir))
    dlg.name_edit.setText('S')
    dlg._on_run()
    assert called == []
