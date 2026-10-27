# -*- coding: utf-8 -*-
"""core/services/sync_batch_plan.py: stato della tabella della coda di sync, senza Qt (stati, riepilogo, scelta manuale, duplicati)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import sync_pairing as SP
from core.services.sync_batch_plan import CHECK, DUP, NOSRT, READY, PlanSummary, SyncBatchPlan


def plan_with(*pairs, left=0):
    p = SyncBatchPlan()
    p.pairs = list(pairs)
    p.left_srts = [Path(f'/s/{i}.srt') for i in range(left)]
    return p


def mk(video, srt=None, include=True, note='', score=1.0):
    p = SP.Pair(video=Path(video), srt=Path(srt) if srt else None, score=score, note=note, include=include)
    p.refresh_output()
    return p


def test_scan_con_cartelle_vuote_non_tocca_nulla(tmp_path):
    p = SyncBatchPlan()
    p.pairs = [mk('/v/a.mkv', '/s/a.srt')]
    assert p.scan('', str(tmp_path), False) is False and p.scan(str(tmp_path), '  ', False) is False
    assert len(p.pairs) == 1
    assert p.scan(str(tmp_path), str(tmp_path), False) is True and p.pairs == []


def test_stati_e_riepilogo():
    pairs = [mk('/v/a.mkv', '/s/a.srt'), mk('/v/b.mkv'), mk('/v/c.mkv', '/s/c.srt', note='incerto'),
             mk('/v/d.mkv', '/s/d.srt', note='incerto', include=False), mk('/v/e.mkv', '/s/a.srt')]
    # e usa lo stesso output di a: duplicato (entrambe incluse)
    p = plan_with(*pairs, left=2)
    summary = p.refresh()
    states = [p.state_of(x) for x in p.pairs]
    assert states == [DUP, NOSRT, CHECK, CHECK, DUP]
    assert summary == PlanSummary(ready=1, check=1, nosrt=1, left=2)      # c pronta ma da controllare; d non inclusa
    assert [p.is_checked(x) for x in p.pairs] == [True, False, True, False, True]
    assert p.runnable() == [pairs[2]]


def test_scelta_manuale():
    p = plan_with(mk('/v/a.mkv', '/s/a.srt', note='incerto', score=0.7), mk('/v/b.mkv', include=False, score=0.0))
    p.choose_srt(0, '/s/z.srt')
    a = p.pairs[0]
    assert (a.srt, a.score, a.note, a.include) == (Path('/s/z.srt'), 1.0, '', True)
    assert a.output == SP.default_output_path('/s/z.srt')
    p.choose_srt(1, '/s/y.srt')
    b = p.pairs[1]
    assert (b.score, b.include) == (1.0, True)
    p.choose_srt(1, None)
    assert (b.srt, b.score, b.include, b.output) == (None, 0.0, False, None)
    p.set_include(0, False)
    assert p.pairs[0].include is False


def test_etichetta_srt():
    assert SyncBatchPlan.srt_label('/s/b/Film.srt', '/s ') == str(Path('b') / 'Film.srt')
    assert SyncBatchPlan.srt_label('/altro/Film.srt', '/s') == 'Film.srt'


def test_duplicato_con_nota_non_conta_fra_le_da_controllare():
    p = plan_with(mk('/v/a.mkv', '/s/a.srt', note='incerto'), mk('/v/b.mkv', '/s/a.srt'))
    assert p.refresh() == PlanSummary(ready=0, check=0, nosrt=0, left=0)
    assert [p.state_of(x) for x in p.pairs] == [DUP, DUP]


def test_runnable_ricalcola_i_duplicati():
    a, b, c = mk('/v/a.mkv', '/s/a.srt'), mk('/v/b.mkv', '/s/a.srt'), mk('/v/c.mkv', '/s/c.srt')
    p = plan_with(a, b, c)            # nessun refresh() prima
    assert p.runnable() == [c]
