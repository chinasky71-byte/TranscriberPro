"""
Test CPU della coda multi-file del Subtitle Sync (nessun modello, nessuna GPU):
  - core/sync_pairing.py: percorso di output identico alla vecchia logica, abbinamento, episodi, duplicati
  - core/sync_cli.py: round-trip degli argomenti e dei codici di uscita
  - gui/sync_batch_worker.py: coda con subprocess finto (successo, fallimento, annullamento)
  - gui/sync_dialog.py: tabella delle coppie in modalita' offscreen
Esecuzione:  venv\\Scripts\\python.exe -m unittest test_sync_batch -v   (dalla cartella del progetto)
"""
import json
import os
import sys
import tempfile
import textwrap
import time
import types
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import sync_pairing as SP  # noqa: E402


def old_output_logic(external_srt_path: Path) -> Path:
    """Copia della logica che era dentro SubtitleSynchronizer.__init__ prima del refactor."""
    stem = external_srt_path.stem
    _KNOWN = {'it', 'ita', 'italian', 'en', 'eng', 'english', 'es', 'spa', 'fr', 'fre', 'fra', 'de', 'deu', 'ger',
              'pt', 'por', 'ru', 'rus', 'ja', 'jpn'}
    if '.' in stem:
        base, lang = stem.rsplit('.', 1)
        if lang.lower() in _KNOWN:
            stem = base
    return external_srt_path.parent / f"{stem}.synced.it.srt"


class TestPairing(unittest.TestCase):
    def test_output_identical_to_old_logic(self):
        for name in ('film.it.srt', 'Movie.2019.1080p.x264.srt', 'a.b.c.en.srt', 'noext.srt', 'X.ITA.srt', 'S01E01.eng.srt',
                     'Film.2020.ru.srt', 'a..srt', 'The.Show.S01E02.1080p.WEB.H264-GRP.srt'):
            p = Path('C:/x/y') / name
            self.assertEqual(SP.default_output_path(p), old_output_logic(p), name)

    def test_episodes_never_cross(self):
        vids = [Path(f'Show.S01E0{i}.1080p.mkv') for i in (1, 2, 3)]
        srts = [Path(f'Show.S01E0{i}.it.srt') for i in (3, 1, 2)]
        pairs, left = SP.pair_files(vids, srts)
        for p in pairs:
            self.assertEqual(SP.episode_key(p.video.name), SP.episode_key(p.srt.name))
        self.assertEqual(left, [])

    def test_different_episode_scores_zero(self):
        self.assertEqual(SP.similarity('Show.S01E01.mkv', 'Show.S01E02.it.srt'), 0.0)
        self.assertEqual(SP.similarity('Show 1x05.mkv', 'Show.S01E06.it.srt'), 0.0)
        self.assertGreater(SP.similarity('Show 1x05.mkv', 'Show.S01E05.it.srt'), 0.9)

    def test_noise_and_year_ignored(self):
        self.assertGreater(SP.similarity('Dune.Part.Two.2024.2160p.UHD.BluRay.x265-GRP.mkv', 'Dune Part Two (2024).it.srt'), 0.85)

    def test_unmatched_and_leftovers(self):
        vids = [Path('Alpha.2020.mkv'), Path('Zzz Unrelated Movie.mkv')]
        srts = [Path('Alpha.2020.it.srt'), Path('Completely Other Thing.srt')]
        pairs, left = SP.pair_files(vids, srts)
        by = {p.video.name: p for p in pairs}
        self.assertEqual(by['Alpha.2020.mkv'].srt.name, 'Alpha.2020.it.srt')
        self.assertIsNone(by['Zzz Unrelated Movie.mkv'].srt)
        self.assertFalse(by['Zzz Unrelated Movie.mkv'].include)
        self.assertEqual([s.name for s in left], ['Completely Other Thing.srt'])

    def test_synced_files_are_never_sources(self):
        pairs, left = SP.pair_files([Path('Film.mkv')], [Path('Film.synced.it.srt'), Path('Film.it.srt')])
        self.assertEqual(pairs[0].srt.name, 'Film.it.srt')

    def test_deterministic_ties(self):
        vids = [Path('Film.mkv')]
        srts = [Path('b/Film.it.srt'), Path('a/Film.it.srt')]
        r1 = SP.pair_files(vids, srts)[0][0].srt
        r2 = SP.pair_files(vids, list(reversed(srts)))[0][0].srt
        self.assertEqual(r1, r2)

    def test_global_assignment_not_greedy_by_video(self):
        # "Movie" e' simile a entrambi gli SRT, ma quello esatto va a Movie e l'altro a "Movie Extended"
        vids = [Path('Movie Extended.mkv'), Path('Movie.mkv')]
        srts = [Path('Movie.it.srt'), Path('Movie Extended.it.srt')]
        pairs, _ = SP.pair_files(vids, srts)
        by = {p.video.name: p.srt.name for p in pairs}
        self.assertEqual(by, {'Movie.mkv': 'Movie.it.srt', 'Movie Extended.mkv': 'Movie Extended.it.srt'})

    def test_duplicate_outputs_flagged_and_excluded(self):
        a = SP.Pair(video=Path('a.mkv'), srt=Path('d/X.it.srt'))
        b = SP.Pair(video=Path('b.mkv'), srt=Path('d/X.en.srt'))     # stesso output: X.synced.it.srt
        c = SP.Pair(video=Path('c.mkv'), srt=Path('e/X.it.srt'))     # altra cartella: nessun conflitto
        for p in (a, b, c):
            p.refresh_output()
        self.assertEqual(SP.mark_duplicates([a, b, c]), 2)
        self.assertTrue(a.duplicate and b.duplicate and not c.duplicate)
        self.assertEqual(SP.runnable([a, b, c]), [c])
        b.include = False
        SP.mark_duplicates([a, b, c])
        self.assertFalse(a.duplicate)
        self.assertEqual(SP.runnable([a, b, c]), [a, c])

    def test_list_files_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'sub').mkdir()
            for n in ('a.mkv', 'sub/b.MP4', 'c.txt'):
                (Path(td) / n).write_text('x')
            self.assertEqual([p.name for p in SP.list_files(td, SP.VIDEO_EXT)], ['a.mkv'])
            self.assertEqual([p.name for p in SP.list_files(td, SP.VIDEO_EXT, True)], ['a.mkv', 'b.MP4'])


class TestSyncCli(unittest.TestCase):
    def run_cli(self, args: dict, fake_ok=True, raises=False):
        from core import sync_cli
        mod = types.ModuleType('core.subtitle_synchronizer')

        class Fake:
            def __init__(self, video_path, external_srt_path, output_path=None, log_callback=None, progress_callback=None):
                self._output_path = Path(output_path) if output_path else Path(external_srt_path).with_name('out.synced.it.srt')
                self.log, self.prog = log_callback, progress_callback

            def synchronize(self):
                if raises:
                    raise RuntimeError('boom')
                self.log('1. Estrazione ancore')
                self.prog(40)
                return fake_ok
        mod.SubtitleSynchronizer = Fake
        saved = sys.modules.get('core.subtitle_synchronizer')
        sys.modules['core.subtitle_synchronizer'] = mod
        try:
            with tempfile.TemporaryDirectory() as td:
                ap = Path(td) / 'args.json'
                rp = Path(td) / 'result.json'
                ap.write_text(json.dumps(dict(args, result_path=str(rp))), encoding='utf-8')
                rc = sync_cli.main(['x', str(ap)])
                res = json.loads(rp.read_text(encoding='utf-8')) if rp.exists() else None
        finally:
            if saved is None:
                sys.modules.pop('core.subtitle_synchronizer', None)
            else:
                sys.modules['core.subtitle_synchronizer'] = saved
        return rc, res

    def test_success(self):
        rc, res = self.run_cli({'video_path': 'v.mkv', 'external_srt_path': 's.srt', 'output_path': 'o.srt'})
        self.assertEqual(rc, 0)
        self.assertTrue(res['success'])
        self.assertTrue(res['output_path'].endswith('o.srt'))

    def test_failure_and_exception(self):
        rc, res = self.run_cli({'video_path': 'v.mkv', 'external_srt_path': 's.srt'}, fake_ok=False)
        self.assertEqual(rc, 1)
        self.assertFalse(res['success'])
        rc, res = self.run_cli({'video_path': 'v.mkv', 'external_srt_path': 's.srt'}, raises=True)
        self.assertEqual(rc, 1)
        self.assertIn('boom', res['error'])

    def test_invalid_args(self):
        from core import sync_cli
        self.assertEqual(sync_cli.main(['x']), 2)
        self.assertEqual(sync_cli.main(['x', 'does_not_exist.json']), 2)
        rc, _ = self.run_cli({'video_path': 'v.mkv'})
        self.assertEqual(rc, 2)


FAKE_CLI = textwrap.dedent('''
    import json, sys, time
    a = json.loads(open(sys.argv[1], encoding='utf-8').read())
    name = a['video_path']
    print("1. Estrazione ancore", flush=True)
    print("[SYNC-PCT] 25", flush=True)
    if 'SLOW' in name:
        time.sleep(60)
    if 'FAIL' in name:
        print("ERRORE finto", flush=True)
        open(a['result_path'], 'w').write(json.dumps({"success": False, "output_path": None, "error": "fallita apposta"}))
        sys.exit(1)
    print("[SYNC-PCT] 90", flush=True)
    open(a['result_path'], 'w').write(json.dumps({"success": True, "output_path": a['output_path'], "error": None}))
''')


class TestBatchWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make(self, names):
        self.td = tempfile.TemporaryDirectory()
        d = Path(self.td.name)
        (d / 'fake_sync_cli_for_test.py').write_text(FAKE_CLI, encoding='utf-8')
        os.environ['PYTHONPATH'] = str(d) + os.pathsep + os.environ.get('PYTHONPATH', '')
        pairs = []
        for n in names:
            p = SP.Pair(video=Path(n), srt=Path(f'{n}.it.srt'))
            p.refresh_output()
            pairs.append(p)
        return pairs

    def tearDown(self):
        if hasattr(self, 'td'):
            self.td.cleanup()

    def run_worker(self, pairs, cancel_after=None):
        from gui.sync_batch_worker import SyncBatchWorker
        SyncBatchWorker.CLI_MODULE = 'fake_sync_cli_for_test'
        w = SyncBatchWorker(pairs)
        ev = {'fin': [], 'prog': [], 'start': [], 'done': None, 'log': []}
        w.pair_finished.connect(lambda i, ok, info: ev['fin'].append((i, ok, info)))
        w.pair_progress.connect(lambda i, p: ev['prog'].append((i, p)))
        w.pair_started.connect(lambda i, v: ev['start'].append(i))
        w.all_done.connect(lambda a, b, c: ev.__setitem__('done', (a, b, c)))
        w.log_message.connect(ev['log'].append)
        if cancel_after is not None:
            import threading
            threading.Timer(cancel_after, w.cancel).start()
        w.run()          # sincrono: nessun event loop necessario con connessioni dirette
        return ev

    def test_success_failure_and_continue(self):
        pairs = self.make(['ok1.mkv', 'FAIL.mkv', 'ok2.mkv'])
        ev = self.run_worker(pairs)
        self.assertEqual([(i, ok) for i, ok, _ in ev['fin']], [(0, True), (1, False), (2, True)])
        self.assertEqual(ev['done'], (2, 1, 0))
        self.assertIn('fallita apposta', ev['fin'][1][2])
        self.assertTrue(any(p == (0, 90) for p in ev['prog']))
        self.assertTrue(any(p == (0, 100) for p in ev['prog']))      # 100 solo a successo confermato
        self.assertFalse(any(p == (1, 100) for p in ev['prog']))

    def test_cancel_kills_child_and_stops_queue(self):
        pairs = self.make(['SLOW1.mkv', 'never.mkv'])
        t = time.time()
        ev = self.run_worker(pairs, cancel_after=3)
        self.assertLess(time.time() - t, 20, 'il figlio dorme 60 s: la cancellazione deve ucciderlo')
        self.assertEqual(ev['start'], [0])
        self.assertEqual(ev['done'][0], 0)
        self.assertEqual(ev['done'][2], 2)              # entrambe non eseguite


class TestDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_pair_table_and_manual_duplicate(self):
        from gui.sync_dialog import SyncDialog
        with tempfile.TemporaryDirectory() as td:
            v, s = Path(td) / 'v', Path(td) / 's'
            v.mkdir()
            s.mkdir()
            for i in (1, 2):
                (v / f'Show.S01E0{i}.mkv').write_text('x')
                (s / f'Show.S01E0{i}.it.srt').write_text('x')
            dlg = SyncDialog()
            dlg.bv_dir.setText(str(v))
            dlg.bs_dir.setText(str(s))
            dlg._batch_pair()
            self.assertEqual(dlg.b_table.rowCount(), 2)
            self.assertEqual([p.srt.name for p in dlg._pairs], ['Show.S01E01.it.srt', 'Show.S01E02.it.srt'])
            self.assertEqual(len(SP.runnable(dlg._pairs)), 2)
            # scelta manuale: la riga 2 usa lo stesso SRT della riga 1 -> output duplicato, nessuna coppia eseguibile per quei due
            combo = dlg.b_table.cellWidget(1, 2)
            combo.setCurrentIndex(combo.findText('Show.S01E01.it.srt'))
            self.assertTrue(all(p.duplicate for p in dlg._pairs))
            self.assertEqual(SP.runnable(dlg._pairs), [])
            # deselezionando una delle due il conflitto sparisce
            dlg.b_table.item(1, 0).setCheckState(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.CheckState.Unchecked)
            self.assertEqual(len(SP.runnable(dlg._pairs)), 1)
            dlg.deleteLater()


if __name__ == '__main__':
    unittest.main()
