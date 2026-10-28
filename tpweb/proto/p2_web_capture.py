# -*- coding: utf-8 -*-
"""Fase 2: cattura la PAGINA WEB negli stessi stati di p2_qt_capture.py, con la stessa dimensione (1400x900 CSS) e le stesse scale.

Uso (sul PC Windows):  python tpweb/proto/p2_web_capture.py --out tpweb/proto/results/p2_web_windows --scales 1.0 1.25 1.5 --channel msedge
Scrive <out>/<scala>/<stato>.png e <stato>.json (scatole di alcuni elementi). Nessuna elaborazione vera: le righe sono scritte direttamente
nello stato della coda; config e cronologia in una cartella temporanea (HOME isolata). Il motore non parte."""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
STATES = ['vuota', 'righe', 'filtro_attivi', 'filtro_coda', 'filtro_completati', 'pipeline', 'cronologia']
SETTINGS_STATES = ['imp_general', 'imp_jobs', 'imp_transcription', 'imp_translation', 'imp_batch', 'imp_opensubtitles', 'imp_ocr']       # come p2_qt_capture.py
PATHS = ['C:/Video/Film Uno.mkv', 'C:/Video/Serie Due S01E02 - Un episodio con un titolo molto lungo che deve essere accorciato.mkv',
         'C:/Video/Documentario.mp4']
HISTORY = [{'name': 'Film Uno', 'date_iso': '2026-10-27T21:05:09', 'src_lang': 'eng', 'dst_lang': 'ita', 'duration_seconds': 3725, 'size_bytes': 1610612736,
            'srt_path': 'C:/v/uno.srt', 'video_path': 'C:/v/uno.mkv'},
           {'name': 'Serie Due S01E02', 'date_iso': '2026-10-28T08:00:00', 'src_lang': 'auto', 'dst_lang': 'ita', 'duration_seconds': 2710,
            'size_bytes': 904857600, 'srt_path': 'C:/v/due.srt', 'video_path': 'C:/v/due.mkv'}]
SELECTORS = {'titlebar': '[data-testid=titlebar]', 'tabbar': '[data-testid=tabbar]', 'leftPanel': '[data-testid=left-panel]',
             'centerPanel': '[data-testid=center-panel]', 'rightPanel': '[data-testid=right-panel]', 'fileList': '[data-testid=file-list]',
             'add-files': '[data-testid=add-files]', 'add-folder': '[data-testid=add-folder]', 'clear': '[data-testid=clear]',
             'start': '[data-testid=start]', 'stop': '[data-testid=stop]', 'progress': '[data-testid=progress]'}


class _OfflineTmdb:
    """TMDB senza rete: la cattura non deve dipendere da Internet ne' dalla chiave dell'utente (nessuna locandina, titolo dal nome)."""
    api_key = None

    def parse_filename(self, name):
        import re
        m = re.match(r'(?P<t>.+?)[ .]S(?P<s>\d+)E(?P<e>\d+)', Path(name).stem)
        if m:
            return {'title': m.group('t').strip(), 'type': 'tv', 'season': int(m.group('s')), 'episode': int(m.group('e'))}
        return {'title': Path(name).stem, 'type': 'movie'}

    def get_media_info(self, name):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(Path(__file__).resolve().parent / 'results' / ('p2_web_' + ('windows' if sys.platform == 'win32' else 'linux'))))
    ap.add_argument('--scales', nargs='+', type=float, default=[1.0, 1.25, 1.5])
    ap.add_argument('--states', nargs='+', default=STATES + SETTINGS_STATES)
    ap.add_argument('--channel', default=None, help="es. msedge (Edge installato); senza: Chromium di Playwright")
    ap.add_argument('--executable', default=None)
    a = ap.parse_args()
    orig_env = dict(os.environ)                      # il browser va lanciato con l'ambiente VERO: Edge cerca il suo profilo in USERPROFILE
    home = Path(tempfile.mkdtemp(prefix='tp_p2w_home_'))
    os.environ['HOME'] = os.environ['USERPROFILE'] = str(home)
    from utils import config as cfg
    cfg.Config.CONFIG_DIR = home / '.transcriberpro'
    cfg.Config.CONFIG_FILE = cfg.Config.CONFIG_DIR / 'config.json'
    cfg.reset_config()
    config = cfg.get_config()
    config.set('language', 'it', save=False)
    (home / 'history.json').write_text(json.dumps(HISTORY), encoding='utf-8')
    from tpweb.launcher import build
    srv = build(config, history_path=home / 'history.json', project_root=ROOT, shutdown_fn=lambda: None, tmdb_client=_OfflineTmdb()).start()
    wq = srv.queue
    from playwright.sync_api import sync_playwright
    report = {}
    with sync_playwright() as p:
        kw = {'channel': a.channel} if a.channel else ({'executable_path': a.executable} if a.executable else {})
        browser = p.chromium.launch(args=['--no-sandbox', '--headless=new'] if a.channel else ['--no-sandbox'], env=orig_env, **kw)
        for scale in a.scales:
            ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, device_scale_factor=scale)
            for state in a.states:
                wq.clear()
                if state not in ('vuota', 'cronologia'):
                    wq.add(PATHS, {PATHS[0]: '1.5 GB', PATHS[1]: '862 MB', PATHS[2]: '2.1 GB'})
                    wq.set_overrides([PATHS[1]], 'target_language', 'eng')
                    wq.set_overrides([PATHS[1]], 'mux_subtitle_into_video', True)
                    wq.queue.take_next(); wq.on_file_started(PATHS[0]); wq.on_file_completed(PATHS[0])
                    wq.queue.take_next(); wq.on_file_started(PATHS[1]); wq.on_file_progress(PATHS[1], 45)
                if state == 'pipeline':                  # la stessa anteprima dei passi di p2_qt_capture.py
                    from core.jobs.step_plan import StepTracker, PlanOptions
                    t = StepTracker(PATHS[1].replace('Serie Due S01E02 - Un episodio con un titolo molto lungo che deve essere accorciato', 'Serie Due S01E02'), PlanOptions(), clock=lambda: 1000.0)
                    t.feed_event('phase', {'name': 'extract'}); t.feed_event('phase', {'name': 'asr', 'engine': 'qwen3'}); t.feed_event('bar', {'phase': 'asr', 'pct': 40})
                    wq.on_file_steps(PATHS[1], t.snapshot())
                else:
                    wq.last_steps = None
                page = ctx.new_page()
                page.goto(srv.url)
                page.wait_for_selector('[data-testid=left-panel]')
                try:
                    page.wait_for_selector('[data-testid=gpu-badge]', timeout=15000)      # il rilevamento della scheda video puo' richiedere secondi
                except Exception:
                    pass
                if state.startswith('filtro_'):
                    page.click('[data-filter=%s]' % {'filtro_attivi': 'processing', 'filtro_coda': 'queued', 'filtro_completati': 'completed'}[state])
                if state.startswith('imp_'):                 # la finestra Impostazioni su una scheda, come SettingsDialog(initial_tab=...)
                    page.evaluate("tab => fetch('/api/settings/last_tab', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tab})})", state[4:])
                    page.click('[data-testid=open-settings]')
                    page.wait_for_selector('[data-testid=settings-dialog] .settings-page:not(.hidden) .page')
                if state == 'cronologia':
                    page.click('[data-tab=history]')
                    page.wait_for_selector('[data-testid=history] tbody tr')
                time.sleep(1.2)
                page.mouse.move(5, 895)                          # il puntatore fuori da ogni controllo (niente hover)
                d = Path(a.out) / str(scale)
                d.mkdir(parents=True, exist_ok=True)
                if state.startswith('imp_'):
                    page.locator('[data-testid=settings-dialog]').screenshot(path=str(d / (state + '.png')))      # il dialogo, come dlg.grab()
                else:
                    page.screenshot(path=str(d / (state + '.png')))
                boxes = {}
                for k, sel in SELECTORS.items():
                    loc = page.locator(sel)
                    if loc.count():
                        b = loc.first.bounding_box()
                        boxes[k] = [round(b['x'], 1), round(b['y'], 1), round(b['width'], 1), round(b['height'], 1)]
                (d / (state + '.json')).write_text(json.dumps({'boxes': boxes, 'dpr': scale}, indent=1), encoding='utf-8')
                report[f'{scale}/{state}'] = 'ok'
                print(f'{scale} {state}: ok', flush=True)
                page.close()
            ctx.close()
        browser.close()
    srv.stop()
    (Path(a.out) / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
