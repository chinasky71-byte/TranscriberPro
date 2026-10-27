# -*- coding: utf-8 -*-
"""core/services/metadata_service.py (senza Qt): TitleResolver e find_poster con un client TMDB finto."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services.metadata_service import PosterResult, TitleResolver, find_poster  # noqa: E402
from linux_tests_fake_tmdb import FakeTmdb  # noqa: E402


def test_titolo_senza_qt_film_serie_assoluto(monkeypatch):
    r = TitleResolver(FakeTmdb({'title': 'The Show', 'type': 'tv', 'season': 3, 'episode': 12}))
    assert r.title_for('/v/x.mkv', 'x.mkv') == 'The Show S03E12' and r.cache == {'/v/x.mkv': 'The Show S03E12'}
    tm = FakeTmdb({'title': 'Anime', 'type': 'tv', 'absolute': 5, 'year': 2001})
    r = TitleResolver(tm)
    clock = {'t': 50.0}
    monkeypatch.setattr(time, 'monotonic', lambda: clock['t'])
    assert r.title_for('/v/a.mkv', 'a.mkv') == 'Anime E05' and r.cache == {}
    clock['t'] += 5.0                                        # esattamente 5 s: rivaluta
    tm.resolved = (1, 5)
    assert r.title_for('/v/a.mkv', 'a.mkv') == 'Anime S01E05' and r.provisional == {}
    r.clear()
    assert r.cache == {} and r.provisional == {}


def test_find_poster_stati(tmp_path):
    from PIL import Image
    png = tmp_path / 'p.png'
    Image.new('RGB', (4, 4)).save(png)
    ok = FakeTmdb(media={'poster_path': '/p.jpg', 'title': 'Heat'}, poster=png)
    assert find_poster('/v/Heat.mkv', ok) == PosterResult('found', png, 'Heat')
    assert ok.media_calls == ['Heat.mkv'] and ok.download_calls == [('/p.jpg', 'Heat')]
    assert find_poster('/v/x.mkv', FakeTmdb(media=None)).status == 'none'
    assert find_poster('/v/x.mkv', FakeTmdb(media={'poster_path': '', 'title': 't'})).status == 'none'
    assert find_poster('/v/x.mkv', FakeTmdb(media={'poster_path': '/p', 'title': 't'}, poster=None)).status == 'none'
    assert find_poster('/v/x.mkv', FakeTmdb(media={'poster_path': '/p', 'title': 't'}, poster=tmp_path / 'manca.png')).status == 'none'
    with pytest.raises(RuntimeError):
        find_poster('/v/x.mkv', FakeTmdb(boom=True))


def test_find_poster_annullamento_a_ogni_passo(tmp_path):
    from PIL import Image
    png = tmp_path / 'p.png'
    Image.new('RGB', (4, 4)).save(png)
    tm = FakeTmdb(media={'poster_path': '/p', 'title': 't'}, poster=png)
    assert find_poster('/v/x.mkv', tm, lambda: True).status == 'cancelled' and tm.media_calls == []
    seq = iter([False, True])                                  # annullato dopo la ricerca: niente download
    assert find_poster('/v/x.mkv', tm, lambda: next(seq)).status == 'cancelled' and tm.download_calls == []
    seq = iter([False, False, True])                           # annullato dopo il download
    assert find_poster('/v/x.mkv', tm, lambda: next(seq)).status == 'cancelled' and len(tm.download_calls) == 1
