# -*- coding: utf-8 -*-
"""Attrezzi per le prove della pagina nel browser (Chromium del cloud via Playwright): server vero, finto pipeline, righe d'esempio."""
import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _queue_testkit as kit  # noqa: E402

CHROME = (glob.glob('/opt/pw-browsers/chromium-*/chrome-linux/chrome') or [None])[0]


class FakeTmdb:
    """TMDB finto: nessuna rete. `poster` = file della locandina da restituire (None = nessuna)."""
    api_key = 'k'

    def __init__(self, poster=None, delay=0.0, delays=None):
        self.poster, self.delay, self.calls = poster, delay, []
        self.delays = delays or {}                    # ritardo per nome file (prevale su `delay`)

    def parse_filename(self, name):
        import re
        m = re.match(r'(?P<t>.+?)[ .]S(?P<s>\d+)E(?P<e>\d+)', Path(name).stem)
        if m:
            return {'title': m.group('t').strip(), 'type': 'tv', 'season': int(m.group('s')), 'episode': int(m.group('e'))}
        return {'title': Path(name).stem, 'type': 'movie'}

    def get_media_info(self, name):
        import time
        self.calls.append(name)
        time.sleep(self.delays.get(Path(name).name, self.delay))
        return {'poster_path': '/p.jpg', 'title': Path(name).stem} if self.poster else None

    def download_poster(self, poster_path, title):
        return self.poster


def make_server(tmp_path, monkeypatch, language='it', sampler=None, tmdb=None, gpu_detect=None, tool_engines=None):
    """Server di prova: config e cronologia isolate, il finto `pipeline_cli` al posto del vero, nessuno spegnimento reale."""
    from utils import config as cfg
    from tpweb.launcher import build
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    config = cfg.get_config()
    config.set('language', language, save=False)
    monkeypatch.setattr(subprocess, 'Popen', kit.PopenSpy())
    import utils.cache_cleaner as cc
    monkeypatch.setattr(cc, 'cleanup_non_italian_caches', lambda log_callback=None: {'removed': [], 'failed': []})
    srv = build(config, history_path=tmp_path / 'history.json', project_root=ROOT, shutdown_fn=lambda: None, sampler=sampler,
                 tmdb_client=tmdb or FakeTmdb(), gpu_detect=gpu_detect or (lambda first: ('NVIDIA RTX 4090', 'nvidia', False)), tool_engines=tool_engines).start()
    return srv, config


def seed_rows(wq):
    """Tre righe come lo stato «righe» di p2_qt_capture.py: completato, in lavorazione al 45% con eccezione, in coda."""
    p = ['C:/Video/Film Uno.mkv',
         'C:/Video/Serie Due S01E02 - Un episodio con un titolo molto lungo che deve essere accorciato.mkv',
         'C:/Video/Documentario.mp4']
    wq.add(p, {p[0]: '1.5 GB', p[1]: '862 MB', p[2]: '2.1 GB'})
    wq.set_overrides([p[1]], 'target_language', 'eng')
    wq.set_overrides([p[1]], 'mux_subtitle_into_video', True)
    wq.queue.take_next()
    wq.on_file_started(p[0]); wq.on_file_completed(p[0])
    wq.queue.take_next()
    wq.on_file_started(p[1]); wq.on_file_progress(p[1], 45)
    return p


def make_server_with_tools(tmp_path, monkeypatch, tool_engines):
    return make_server(tmp_path, monkeypatch, tool_engines=tool_engines)
