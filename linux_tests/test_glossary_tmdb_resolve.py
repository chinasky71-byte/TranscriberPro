# -*- coding: utf-8 -*-
"""Fase 4b: CARATTERIZZAZIONE della ricerca TMDB del glossario (prima in gui/glossary_dialog.py::_TmdbResolveWorker, ora anche in
core/services/glossary_service.py::resolve_tmdb). Gli stessi casi passano su entrambe: ordine dei candidati, salto delle cartelle
"Season N", doppioni, ripiego sul candidato successivo, risultati senza id, eccezioni."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeTmdb:
    def __init__(self, shows=None, raises=False):
        self.shows, self.raises, self.searched = shows or {}, raises, []

    def parse_filename(self, name):
        n = name.replace('.', ' ').replace('_', ' ')
        year = None
        if n.endswith(' 2019'):
            n, year = n[:-5], 2019
        return {'title': n.strip(), 'year': year}

    def search_tv(self, title, year=None):
        if self.raises:
            raise RuntimeError('rete')
        self.searched.append((title, year))
        return self.shows.get(title.lower())


def impl_old(cands):
    pytest.importorskip('PyQt6.QtCore', exc_type=ImportError)
    from gui.glossary_dialog import _TmdbResolveWorker
    from PyQt6.QtCore import Qt
    out = []
    w = _TmdbResolveWorker(cands)
    w.resolved.connect(lambda r, u: out.append((r, u)), Qt.ConnectionType.DirectConnection)
    w.run()
    assert len(out) == 1                                    # il segnale parte sempre una volta
    return out[0]


def impl_core(cands):
    from core.services import glossary_service as GS
    return GS.resolve_tmdb(cands)


IMPLS = [impl_old] + ([impl_core] if 'resolve_tmdb' in dir(__import__('core.services.glossary_service', fromlist=['x'])) else [])


@pytest.fixture(params=IMPLS, ids=lambda f: f.__name__)
def resolve(request, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')

    def go(cands, fake):
        import utils.tmdb_client as tc
        monkeypatch.setattr(tc, 'get_tmdb_client', lambda: fake)
        return request.param(cands)
    return go


def test_si_ferma_al_primo_che_risolve(resolve):
    f = FakeTmdb({'show uno': {'id': 7, 'title': 'Show Uno'}, 'show due': {'id': 9}})
    assert resolve(['Show.Uno', 'Show Due'], f) == ({'id': 7, 'title': 'Show Uno'}, 'Show Uno')
    assert f.searched == [('Show Uno', None)]


def test_salta_le_cartelle_stagione_e_passa_al_successivo(resolve):
    f = FakeTmdb({'show uno': {'id': 7}})
    assert resolve(['Season 2', 'season 03', 'Show Uno'], f)[1] == 'Show Uno'
    assert [s[0] for s in f.searched] == ['Show Uno']                      # "Season N" non arriva mai a search_tv


def test_doppioni_in_minuscolo_e_candidati_vuoti(resolve):
    f = FakeTmdb()
    assert resolve(['', '  ', 'Show Uno', 'show uno', 'SHOW UNO'], f) == (None, None)
    assert f.searched == [('Show Uno', None)]


def test_anno_dal_nome_file_e_ripiego_se_il_primo_non_trova(resolve):
    f = FakeTmdb({'show due': {'id': 9}})
    r, used = resolve(['Show.Uno.2019', 'Show Due'], f)
    assert (r, used) == ({'id': 9}, 'Show Due')
    assert f.searched == [('Show Uno', 2019), ('Show Due', None)]


def test_risultato_senza_id_non_vale(resolve):
    f = FakeTmdb({'show uno': {'title': 'senza id'}, 'show due': {'id': 3}})
    assert resolve(['Show Uno', 'Show Due'], f) == ({'id': 3}, 'Show Due')


def test_eccezione_diventa_nessun_risultato(resolve):
    assert resolve(['Show Uno'], FakeTmdb(raises=True)) == (None, None)


def test_nessun_candidato(resolve):
    assert resolve([], FakeTmdb()) == (None, None)
