# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di gui/services/metadata_service.py::MetadataService e di PosterLoaderWorker.

Fissa il comportamento PRIMA dell'estrazione della logica in core/services/metadata_service.py: titolo mostrato sotto la
locandina (film, serie, anime con numero assoluto, titolo provvisorio rivalutato ogni 5 s, cache) e caricamento della locandina
(guardia `last_loaded_file`, segnali, errori). I test passano identici sul vecchio e sul nuovo codice. Client TMDB finto, nessuna rete."""
import sys
import time
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
    yield QApplication.instance() or QApplication([])


from linux_tests_fake_tmdb import FakeTmdb  # noqa: E402


def svc(tm):
    from gui.services.metadata_service import MetadataService
    return MetadataService(tm)


# ----------------------------------------------------------------------------------------------------------------- titolo

def test_film_serie_e_numeri_di_stagione_irreali(qt):
    s = svc(FakeTmdb({'title': 'Heat', 'type': 'movie', 'year': 1995}))
    assert s.overlay_title_for('/v/Heat.1995.mkv', 'Heat.1995.mkv') == 'Heat'
    s = svc(FakeTmdb({'title': 'The Show', 'type': 'tv', 'season': 3, 'episode': 12}))
    assert s.overlay_title_for('/v/x.mkv', 'x.mkv') == 'The Show S03E12'
    s = svc(FakeTmdb({'title': 'The Corporation', 'type': 'tv', 'season': 720, 'episode': 480}))   # 720x480 non e' una stagione
    assert s.overlay_title_for('/v/x.mkv', 'x.mkv') == 'The Corporation'


def test_cache_un_solo_parse_per_file(qt):
    tm = FakeTmdb({'title': 'Heat', 'type': 'movie'})
    s = svc(tm)
    assert s.overlay_title_for('/v/a.mkv', 'a.mkv') == 'Heat' and s.overlay_title_for('/v/a.mkv', 'a.mkv') == 'Heat'
    assert len(tm.parse_calls) == 1 and s.overlay_title_cache == {'/v/a.mkv': 'Heat'}
    s.clear_title_caches()
    assert s.overlay_title_cache == {} and s.overlay_title_provisional == {}
    s.overlay_title_for('/v/a.mkv', 'a.mkv')
    assert len(tm.parse_calls) == 2


def test_anime_con_numero_assoluto_provvisorio_e_poi_risolto(qt, monkeypatch):
    tm = FakeTmdb({'title': 'Anime', 'type': 'tv', 'absolute': 5}, resolved=None)
    s = svc(tm)
    clock = {'t': 1000.0}
    monkeypatch.setattr(time, 'monotonic', lambda: clock['t'])
    assert s.overlay_title_for('/v/an.mkv', 'an.mkv') == 'Anime E05'
    assert s.overlay_title_cache == {} and list(s.overlay_title_provisional) == ['/v/an.mkv']      # provvisorio: non in cache
    clock['t'] += 4.9
    assert s.overlay_title_for('/v/an.mkv', 'an.mkv') == 'Anime E05' and len(tm.parse_calls) == 1  # entro 5 s: nessuna rivalutazione
    clock['t'] += 0.2
    tm.resolved = (2, 3)
    assert s.overlay_title_for('/v/an.mkv', 'an.mkv') == 'Anime S02E03' and len(tm.parse_calls) == 2
    assert s.overlay_title_cache == {'/v/an.mkv': 'Anime S02E03'} and s.overlay_title_provisional == {}


def test_titolo_vuoto_film_usa_la_pulizia_della_ricerca(qt):
    s = svc(FakeTmdb({'title': '', 'type': 'movie'}))
    assert s.overlay_title_for('/v/1917.2019.1080p.mkv', '1917.2019.1080p.mkv') == '1917 2019 1080P'


def test_errore_nel_parse_ripiega_sul_nome_senza_estensione(qt):
    s = svc(FakeTmdb(boom=True))
    assert s.overlay_title_for('/v/Nome.Strano.mkv', 'Nome.Strano.mkv') == 'Nome.Strano'
    assert s.overlay_title_cache == {'/v/Nome.Strano.mkv': 'Nome.Strano'}                             # l'errore e' «definitivo»


def test_chiave_e_nome_file_alternativi(qt):
    tm = FakeTmdb({'title': 'T', 'type': 'movie'})
    s = svc(tm)
    assert s.overlay_title_for('', 'solo_nome.mkv') == 'T' and list(s.overlay_title_cache) == ['solo_nome.mkv']
    assert s.overlay_title_for('/v/da_percorso.mkv', '') == 'T' and tm.parse_calls[-1] == 'da_percorso.mkv'


def test_client_sostituibile_a_runtime(qt):
    a, b = FakeTmdb({'title': 'A', 'type': 'movie'}), FakeTmdb({'title': 'B', 'type': 'movie'})
    s = svc(a)
    assert s.overlay_title_for('/v/1.mkv', '1.mkv') == 'A'
    s.tmdb_client = b
    assert s.overlay_title_for('/v/2.mkv', '2.mkv') == 'B' and s.tmdb_client is b


# -------------------------------------------------------------------------------------------------------------- locandina

def _png(tmp_path):
    from PIL import Image
    p = tmp_path / 'poster.png'
    Image.new('RGB', (20, 30), (200, 10, 10)).save(p)
    return p


def _wait(app, cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_locandina_ok_e_guardia_sullo_stesso_file(qt, tmp_path):
    tm = FakeTmdb(media={'poster_path': '/p.jpg', 'title': 'Heat'}, poster=_png(tmp_path))
    s = svc(tm)
    ev = []
    s.poster_loading.connect(lambda p: ev.append(('loading', p)))
    s.poster_loaded.connect(lambda px: ev.append(('loaded', px.width(), px.height())))
    s.poster_failed.connect(lambda: ev.append(('failed',)))
    s.load_poster('/v/Heat.mkv')
    assert _wait(qt, lambda: len(ev) >= 2)
    assert ev == [('loading', '/v/Heat.mkv'), ('loaded', 20, 30)]
    assert tm.media_calls == ['Heat.mkv'] and tm.download_calls == [('/p.jpg', 'Heat')]          # nome COMPLETO con estensione
    s.load_poster('/v/Heat.mkv')                                                                   # stesso file: guardia
    qt.processEvents()
    assert len(ev) == 2 and len(tm.media_calls) == 1
    s.reset_last_loaded()
    s.load_poster('/v/Heat.mkv')
    assert _wait(qt, lambda: len(ev) >= 4) and len(tm.media_calls) == 2


@pytest.mark.parametrize('kw', [dict(media=None), dict(media={'title': 'x'}), dict(media={'poster_path': '', 'title': 'x'}),
                                dict(media={'poster_path': '/p', 'title': 'x'}, poster=None), dict(boom=True)])
def test_locandina_assente_o_errore_emette_failed(qt, tmp_path, kw):
    s = svc(FakeTmdb(**kw))
    ev = []
    s.poster_loaded.connect(lambda px: ev.append('loaded'))
    s.poster_failed.connect(lambda: ev.append('failed'))
    s.load_poster('/v/x.mkv')
    assert _wait(qt, lambda: bool(ev)) and ev == ['failed']


def test_file_locandina_inesistente_o_non_immagine(qt, tmp_path):
    bad = tmp_path / 'non_immagine.png'
    bad.write_text('non e un png')
    for poster in (bad, tmp_path / 'manca.png'):
        s = svc(FakeTmdb(media={'poster_path': '/p', 'title': 't'}, poster=poster))
        ev = []
        s.poster_failed.connect(lambda: ev.append('failed'))
        s.poster_loaded.connect(lambda px: ev.append('loaded'))
        s.load_poster('/v/x.mkv')
        assert _wait(qt, lambda: bool(ev)) and ev == ['failed']


def test_worker_annullato_non_emette(qt, tmp_path):
    from gui.workers import PosterLoaderWorker
    tm = FakeTmdb(media={'poster_path': '/p', 'title': 't'}, poster=_png(tmp_path))
    w = PosterLoaderWorker('/v/x.mkv', tm)
    got = []
    w.poster_loaded.connect(lambda px: got.append('l'))
    w.poster_failed.connect(lambda: got.append('f'))
    w.cancel()
    w.run()
    assert got == [] and tm.media_calls == []
