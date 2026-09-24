"""
Punteggio (CPU) e report del confronto A/B, verdetto secondo
decision_rules_split.py. Facoltativi, dietro flag espliciti:
  --comet      COMET per unita' fusa (GPU, venv_comet, script comet_units.py)
  --llm-judge  giudice GEMBA-MQM (API A PAGAMENTO) con mt_eval/run_gemba.py:
               A e B nella STESSA chiamata, ordine casuale per segmento.

Il riferimento italiano di una finestra sono le battute del sub ITA
'normale' della finestra (it_ref.json di build); quello di un'unita' fusa
sono le battute che si sovrappongono all'unita' (>= 30% della battuta).
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR = ROOT / 'asr_eval'
for _p in (str(ROOT), str(ASR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sandbox  # noqa: E402,F401  (per primo fra i moduli del banco)
import asr_bench as AB  # noqa: E402
import runners as RN  # noqa: E402
import stats as ST  # noqa: E402

from split_eval import rules_select  # noqa: E402
DRS = rules_select.load()
from split_eval import split_metrics as SM  # noqa: E402

SCORE_COLUMNS = [
    'engine', 'win_id', 'film', 'group', 'status', 'error', 'has_ref', 'n_blocks', 'n_merged_units',
    'n_merged_blocks', 'midcut_fmt', 'midcut_fmt_n', 'midcut_src_n', 'llm_unit_budget', 'chrf_a', 'chrf_bf', 'chrf_bi', 'd_bf', 'd_bi',
    'singleton_changed_bf', 'singleton_changed_bi', 'n_units_fallback', 'dev_p90', 'dev_max',
    'u_n', 'u_empty_a', 'u_empty_bf', 'u_dropped_bf', 'u_cps_high_a', 'u_cps_high_bf', 'u_over84_a', 'u_over84_bf',
    'u_over_cpl_a', 'u_over_cpl_bf', 'untr_a', 'untr_b', 'comet_a', 'comet_b', 'd_comet', 'fp_hash']

GEMBA = ROOT / 'mt_eval' / 'run_gemba.py'
COMET_PY = ROOT / 'venv_comet' / 'Scripts' / 'python.exe'


def _join(texts: Sequence[str], drop: Optional[Sequence[bool]] = None) -> str:
    drop = drop or [False] * len(texts)
    return ' '.join(' '.join(str(t).split()) for t, d in zip(texts, drop) if t and not d)


def unit_ref(cues: Sequence[Dict], s: float, e: float, min_frac: float = 0.3) -> str:
    out = []
    for c in cues:
        ov = min(e, c['e']) - max(s, c['s'])
        if ov > 0 and ov >= min_frac * max(1e-6, c['e'] - c['s']):
            out.append(c['text'])
    return ' '.join(' '.join(t.split()) for t in out)


def _fp_hash(fp) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()[:12]


def score_window(res: Dict, row: Dict, it_cues: Optional[List[Dict]], comet: Optional[Dict] = None,
                 unit_id_base: int = 0) -> Tuple[Dict, List[Dict]]:
    """Una riga di punteggio + le unita' fuse (per COMET/GEMBA)."""
    out = {'engine': res['engine'], 'win_id': res['win_id'], 'film': res['film'], 'group': row.get('group'),
           'status': res['status'], 'error': res.get('error'), 'fp_hash': _fp_hash(res.get('fingerprint')),
           'n_blocks': row.get('n_blocks'), 'n_merged_units': row.get('n_merged_units'),
           'n_merged_blocks': row.get('n_merged_blocks'),
           'midcut_fmt': (row.get('midcut_fmt') or {}).get('rate'),
           'midcut_fmt_n': (row.get('midcut_fmt') or {}).get('n_midcut'),
           'midcut_src_n': (row.get('midcut_src') or {}).get('n_midcut'),
           'llm_unit_budget': (res.get('fingerprint') or {}).get('llm_unit_budget'),
           'has_ref': bool(it_cues)}
    if res['status'] != 'ok':
        return out, []
    a, bf, bi, drop = res['a_texts'], res['b_full_texts'], res['b_iso_texts'], res['drop']
    mpos = set(res['merged_positions'])
    if it_cues:
        ref = ' '.join(c['text'] for c in it_cues)
        out['chrf_a'] = SM.chrf(_join(a), ref)
        out['chrf_bf'] = SM.chrf(_join(bf, drop), ref)
        out['chrf_bi'] = SM.chrf(_join(bi, drop), ref)
        out['d_bf'] = out['chrf_bf'] - out['chrf_a']
        out['d_bi'] = out['chrf_bi'] - out['chrf_a']
    same = lambda x, y: ' '.join(x.split()) == ' '.join(y.split())
    out['singleton_changed_bf'] = sum(1 for i, (x, y) in enumerate(zip(a, bf)) if i not in mpos and not same(x, y))
    out['singleton_changed_bi'] = sum(1 for i, (x, y) in enumerate(zip(a, bi)) if i not in mpos and not same(x, y))
    rep = res['resplit']
    out['n_units_fallback'] = rep['n_fallback']
    im = SM.imbalance(rep)
    out['dev_p90'], out['dev_max'] = im['p90'], im['max']
    times, times_b = res['times'], res['times_b']
    sa = SM.structural([{'start': s, 'end': e, 'text': t} for (s, e), t in zip(times, a)], mpos)['in_units']
    sb = SM.structural([{'start': s, 'end': e, 'text': t, 'drop': d}
                        for (s, e), t, d in zip(times_b, bf, drop)], mpos)['in_units']
    out.update(u_n=sa['n'], u_empty_a=sa['empty'], u_empty_bf=sb['empty'], u_dropped_bf=sb['dropped'],
               u_cps_high_a=sa['cps_high'], u_cps_high_bf=sb['cps_high'], u_over84_a=sa['over84'],
               u_over84_bf=sb['over84'], u_over_cpl_a=sa['over_cpl'], u_over_cpl_bf=sb['over_cpl'])
    units = []
    uid_src = {int(k): v for k, v in (res.get('units_src') or {}).items()}
    uid_tr = {int(k): v for k, v in (res.get('units_translated') or {}).items()}
    mapping_units = res.get('merged_units') or _mapping_units(res)
    # inglese residuo alla STESSA granularita' nei due bracci: unita' fusa
    # intera (A = blocchi di A riuniti) + blocchi singoli (non l'audit, che
    # in A conta per blocco e in B per unita')
    src_b = res.get('src_texts') or []
    single = {j: src_b[j] for j in range(len(src_b)) if j not in mpos}
    su = {mu['uid']: uid_src.get(mu['uid'], '') for mu in mapping_units}
    out['untr_a'] = len(SM.untranslated_units(su, {mu['uid']: _join([a[j] for j in mu['blocks']])
                                                   for mu in mapping_units}))         + len(SM.untranslated_units(single, {j: a[j] for j in single}))
    out['untr_b'] = len(SM.untranslated_units(su, uid_tr))         + len(SM.untranslated_units(single, {j: bf[j] for j in single}))
    for mu in mapping_units:
        s, e = res['times'][mu['blocks'][0]][0], res['times'][mu['blocks'][-1]][1]
        ta = _join([a[j] for j in mu['blocks']])
        tb = _join([bf[j] for j in mu['blocks']], [drop[j] for j in mu['blocks']])
        # id STABILE (contenuto, non posizione): COMET e il checkpoint GEMBA
        # si agganciano per id e non devono scivolare se cambiano le finestre
        key = f"{res['engine']}#{res['win_id']}#{mu['uid']}#{ta}#{tb}"
        units.append({'id': int(hashlib.sha256(key.encode('utf-8')).hexdigest()[:12], 16),
                      'engine': res['engine'], 'win_id': res['win_id'],
                      'film': res['film'], 'uid': mu['uid'], 'source': uid_src.get(mu['uid'], ''),
                      'a': ta, 'b': tb, 'reference': unit_ref(it_cues or [], s, e)})
    if comet:
        ca = [comet[u['id']]['a'] for u in units if u['id'] in comet]
        cb = [comet[u['id']]['b'] for u in units if u['id'] in comet]
        if ca:
            out['comet_a'], out['comet_b'] = sum(ca) / len(ca), sum(cb) / len(cb)
            out['d_comet'] = out['comet_b'] - out['comet_a']
    return out, units


def _mapping_units(res: Dict) -> List[Dict]:
    """Unita' fuse ricostruite dal risultato (posizioni dei blocchi per uid)."""
    rep_uids = [u['uid'] for u in res['resplit']['units']]
    pos = res['merged_positions']
    # le posizioni fuse sono ordinate e contigue per unita': si riassegnano
    # nell'ordine delle unita' del report, con la loro numerosita' 'n'
    out, k = [], 0
    for u in res['resplit']['units']:
        out.append({'uid': u['uid'], 'blocks': pos[k:k + u['n']]})
        k += u['n']
    assert len(out) == len(rep_uids)
    return out


def load_comet(split_work: Path, engine: str) -> Dict[int, Dict]:
    p = split_work / f"comet_{engine}.jsonl"
    if not p.exists():
        return {}
    return {int(r['id']): r for r in AB.read_jsonl(p)}


def score(split_work: Path, emit: Callable = print) -> List[Dict]:
    index = {r['win_id']: r for r in AB.read_jsonl(split_work / 'build' / 'index.jsonl')}
    rows = []
    for ed in sorted((split_work / 'out').glob('*')) if (split_work / 'out').exists() else []:
        if not ed.is_dir():
            continue
        engine = ed.name
        comet = load_comet(split_work, engine)
        units_all: List[Dict] = []
        for p in sorted(ed.glob('*.json')):
            res = AB.read_json(p)
            row = index.get(res.get('win_id'))
            if row is None:
                continue
            if res.get('status') == 'ok' and (res.get('src_sha') != row.get('src_sha')
                                             or res.get('units_sha') != row.get('units_sha')):
                res = {**res, 'status': 'stale', 'error': 'build cambiato dopo la traduzione'}
            ref = AB.read_json(split_work / 'build' / res['win_id'] / 'it_ref.json')
            cues = ref['cues'] if ref and ref.get('status') == 'ok' else None
            r, units = score_window(res, row, cues, comet, unit_id_base=len(units_all))
            rows.append(r)
            units_all += units
        AB.write_jsonl_atomic(split_work / f"units_{engine}.jsonl", units_all)
    AB.write_csv_atomic(split_work / 'scores_split.csv', SCORE_COLUMNS, rows)
    emit(f"✅ scores_split.csv: {len(rows)} righe")
    return rows


# ══ COMET / GEMBA (dietro flag) ══════════════════════════════════════════

def run_comet(split_work: Path, engine: str, model: str, emit: Callable = print) -> int:
    AB.require_gpu_free()
    if not COMET_PY.exists():
        emit(f"❌ {COMET_PY} assente")
        return 2
    cmd = [str(COMET_PY), str(HERE / 'comet_units.py'), '--units', str(split_work / f"units_{engine}.jsonl"),
           '--out', str(split_work / f"comet_{engine}.jsonl"), '--model', model]
    emit('  ' + ' '.join(cmd))
    import os
    return subprocess.run(cmd, cwd=str(ROOT), env=dict(os.environ, PYTHONIOENCODING='utf-8')).returncode


def gemba_inputs(split_work: Path, engine: str) -> Tuple[Path, Path, Path, int]:
    units = [u for u in AB.read_jsonl(split_work / f"units_{engine}.jsonl") if u['a'] != u['b']]
    n_sample = getattr(DRS, 'GEMBA_SAMPLE_N', 0)
    if n_sample:      # campione casuale (seme fisso) delle unita' dei film di test: v2, per il credito
        import random
        pool = sorted((u for u in units if '__dev' not in str(u.get('win_id'))), key=lambda u: u['id'])
        units = random.Random(DRS.GEMBA_SAMPLE_SEED).sample(pool, min(n_sample, len(pool)))
    d = split_work / 'gemba'
    src = d / f"split_{engine}_src.jsonl"
    pa, pb = d / f"split_{engine}_A.jsonl", d / f"split_{engine}_B.jsonl"
    AB.write_jsonl_atomic(src, [{'id': u['id'], 'source': u['source'],
                                 'reference': u['reference'] or '(nessun riferimento)',
                                 'category': engine} for u in units])
    AB.write_jsonl_atomic(pa, [{'id': u['id'], 'text': u['a']} for u in units])
    AB.write_jsonl_atomic(pb, [{'id': u['id'], 'text': u['b']} for u in units])
    return src, pa, pb, len(units)


def run_gemba(split_work: Path, engine: str, provider: str, limit: int, emit: Callable = print) -> int:
    src, pa, pb, n = gemba_inputs(split_work, engine)
    emit(f"  GEMBA-MQM su {n} unita' cambiate (API A PAGAMENTO; ~1.150 token/giudizio)")
    cmd = [sys.executable, str(GEMBA), '--src', str(src), '--a', str(pa), '--b', str(pb),
           '--name-a', f"split_{engine}_A", '--name-b', f"split_{engine}_B", '--provider', provider]
    if limit:
        cmd += ['--limit', str(limit)]
    import os
    return subprocess.run(cmd, cwd=str(ROOT), env=dict(os.environ, PYTHONIOENCODING='utf-8')).returncode


def load_gemba(engine: str, ids: Optional[set] = None, film_of: Optional[Dict] = None) -> Optional[Dict]:
    p = ROOT / 'mt_eval' / f"gemba_split_{engine}_A_vs_split_{engine}_B.jsonl"
    if not p.exists():
        return None
    rs = AB.read_jsonl(p)
    if ids is not None:                     # giudizi di unita' non piu' presenti: fuori
        rs = [r for r in rs if r.get('id') in ids]
    if not rs:
        return None
    w = {'minor': 1, 'major': 5, 'critical': 10}
    mqm = lambda es: sum(w.get(e.get('severity'), 1) for e in es)
    out = {'n': len(rs), 'pref_a': sum(1 for r in rs if r['preferred'] == 'a'),
           'pref_b': sum(1 for r in rs if r['preferred'] == 'b'),
           'tie': sum(1 for r in rs if r['preferred'] == 'tie'),
           'mqm_a': sum(mqm(r['errors_a']) for r in rs) / len(rs),
           'mqm_b': sum(mqm(r['errors_b']) for r in rs) / len(rs)}
    if film_of:
        pf: Dict[str, List[int]] = {}
        for r in rs:
            f = film_of.get(r.get('id'))
            if f is None:
                continue
            x = pf.setdefault(f, [0, 0, 0])
            x[{'a': 0, 'b': 1}.get(r['preferred'], 2)] += 1
        out['per_film'] = pf
    return out


def _binom_upper(n: int, k: int) -> float:
    """P(X >= k) con X ~ Binomiale(n, 0.5), esatto."""
    from math import comb
    return sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n


def gemba_primary(gemba: Optional[Dict], rules: Dict) -> Tuple[Optional[str], List[str]]:
    """Endpoint primario GEMBA della v2: (motivo di INSUFFICIENTE | None, motivi di ARCHIVIA)."""
    if not gemba:
        return 'GEMBA non misurato (endpoint primario)', []
    nd = gemba['pref_a'] + gemba['pref_b']
    if nd < rules['gemba_min_decisive']:
        return f"GEMBA: {nd} giudizi decisivi (minimo {rules['gemba_min_decisive']})", []
    reasons: List[str] = []
    share = gemba['pref_b'] / nd
    p = _binom_upper(nd, gemba['pref_b'])
    if share < rules['gemba_min_b_share'] or p > rules['gemba_alpha']:
        reasons.append(f"GEMBA: quota B {share:.3f} su {nd} decisivi (p unilaterale {p:.4f}); "
                       f"richiesti >= {rules['gemba_min_b_share']} e p <= {rules['gemba_alpha']}")
    pf = gemba.get('per_film') or {}
    evaluable = {f: v for f, v in pf.items() if v[0] + v[1] >= rules['gemba_film_min_decisive']}
    if len(evaluable) < rules['gemba_min_films_evaluable']:
        return f"GEMBA: solo {len(evaluable)} film con >= {rules['gemba_film_min_decisive']} giudizi decisivi", []
    b_maj = sum(1 for v in evaluable.values() if v[1] > v[0])
    if b_maj / len(evaluable) < rules['gemba_films_b_majority']:
        reasons.append(f"GEMBA: B in maggioranza solo in {b_maj}/{len(evaluable)} film "
                       f"(richiesto >= {rules['gemba_films_b_majority']:.0%})")
    return None, reasons


# ══ STATISTICA E VERDETTO ═══════════════════════════════════════════════════

def _f(x) -> Optional[float]:
    try:
        return float(x) if x not in (None, '', 'None') else None
    except ValueError:
        return None


def paired(rows: Sequence[Dict], key: str) -> ST.Paired:
    """{film: [(100-a, 100-b, 1)]}: con stats.film_gain il guadagno per film e'
    la media per finestra di b - a (positivo = B migliore)."""
    out: ST.Paired = {}
    for r in rows:
        d = _f(r.get(key))
        if d is None:
            continue
        out.setdefault(r['film'], []).append((d, 0.0, 1))
    return out


def delta_stats(rows: Sequence[Dict], key: str, rules: Dict = DRS.SPLIT_RULES) -> Dict:
    pf = paired(rows, key)
    if not pf:
        return {'n_films': 0, 'n_windows': 0, 'gain': None, 'ci_lo': None, 'ci_hi': None,
                'wilcoxon_p': None, 'wilcoxon_n': 0}
    lo, hi = ST.bootstrap_gain(pf, rules['bootstrap_n'], rules['bootstrap_seed'], rules['ci_level'])
    gains = [ST.film_gain(v) for v in pf.values()]
    w, p, n = ST.wilcoxon_exact([g for g in gains if g is not None])
    return {'n_films': len(pf), 'n_windows': sum(len(v) for v in pf.values()), 'gain': ST.mean_gain(pf),
            'ci_lo': lo, 'ci_hi': hi, 'wilcoxon_w': w, 'wilcoxon_p': p, 'wilcoxon_n': n,
            'wilcoxon_min_p': ST.min_p_wilcoxon(n)}


def engine_summary(rows: Sequence[Dict], engine: str) -> Dict:
    er = [r for r in rows if r['engine'] == engine]
    ok = [r for r in er if r['status'] == 'ok']
    merged = [r for r in ok if int(_f(r['n_merged_units']) or 0) > 0 and r.get('has_ref') in (True, 'True')]
    neg = [r for r in ok if int(_f(r['n_merged_units']) or 0) == 0]
    s = lambda k, rs: sum(int(_f(r.get(k)) or 0) for r in rs)
    u_n = s('u_n', merged) or 0
    pct = lambda k: 100.0 * s(k, merged) / u_n if u_n else 0.0
    n_units = s('n_merged_units', merged)
    devs = [_f(r['dev_p90']) for r in merged if _f(r['dev_p90']) is not None]
    neg_drift = [abs(_f(r['d_bf'])) for r in neg if _f(r.get('d_bf')) is not None]
    return {
        'n_windows': len(er), 'n_ok': len(ok), 'n_failed': len(er) - len(ok),
        'n_merged_windows': len(merged), 'n_neg_windows': len(neg), 'n_merged_units': n_units,
        'chrf_bf': delta_stats(merged, 'd_bf'), 'chrf_bi': delta_stats(merged, 'd_bi'),
        'comet': delta_stats([r for r in merged if _f(r.get('d_comet')) is not None], 'd_comet'),
        'empty_pct_bf': pct('u_empty_bf'), 'empty_pct_a': pct('u_empty_a'),
        'dropped_pct_bf': pct('u_dropped_bf'),
        'fallback_pct': 100.0 * s('n_units_fallback', merged) / n_units if n_units else 0.0,
        'cps_high_pct_a': pct('u_cps_high_a'), 'cps_high_pct_bf': pct('u_cps_high_bf'),
        'over84_pct_a': pct('u_over84_a'), 'over84_pct_bf': pct('u_over84_bf'),
        'imbalance_p90': (sorted(devs)[int(0.9 * (len(devs) - 1))] if devs else None),
        'untr_a': s('untr_a', ok), 'untr_b': s('untr_b', ok),
        'neg_mean_abs_drift_bf': (sum(neg_drift) / len(neg_drift)) if neg_drift else None,
        'neg_iso_changed': sum(1 for r in neg if int(_f(r.get('singleton_changed_bi')) or 0) > 0),
        'merges_without_midcut': sum(1 for r in ok if int(_f(r['n_merged_units']) or 0) > 0
                                     and int(_f(r.get('midcut_src_n')) or 0) == 0),
        'llm_unit_budget': sorted({r.get('llm_unit_budget') or '' for r in ok}),
        'singleton_changed_bf': s('singleton_changed_bf', ok),
        'fp_hashes': sorted({r.get('fp_hash') for r in ok}),
    }


def decide(summary: Dict, other: Optional[Dict] = None, gemba: Optional[Dict] = None,
           rules: Dict = DRS.SPLIT_RULES, rules_changed: bool = False) -> Dict:
    """Verdetto per UN motore secondo le regole congelate."""
    reasons: List[str] = []
    if rules_changed:
        return {'verdict': 'NON_VALIDO', 'reasons': ['decision_rules_split.py cambiato dopo il primo run']}
    if 'prod' in summary.get('llm_unit_budget', []):
        return {'verdict': 'NON_VALUTABILE', 'reasons': ["llm_unit_budget='prod': run solo descrittivo "
                                                         "(decision_rules_split.py)"]}
    if summary['n_failed'] > rules['max_failed_windows']:
        return {'verdict': 'NON_VALUTABILE', 'reasons': [f"{summary['n_failed']} finestre fallite: rilanciare"]}
    if len(summary['fp_hashes']) > 1:
        return {'verdict': 'NON_VALUTABILE', 'reasons': ['impronte di configurazione diverse fra finestre']}
    if rules['merges_require_midcut'] and summary['merges_without_midcut']:
        return {'verdict': 'NON_VALIDO', 'reasons': [f"{summary['merges_without_midcut']} finestre con fusioni "
                                                     f"ma midcut(formatter)=0: recompose incoerente con la metrica"]}
    c = summary['chrf_bf']
    cm = summary['comet']
    chrf_gate = rules.get('chrf_gate', True)
    base = c if chrf_gate else cm
    if base['n_films'] < rules['min_films'] or base['n_windows'] < rules['min_windows_merged']:
        return {'verdict': 'INSUFFICIENTE',
                'reasons': [f"{base['n_films']} film / {base['n_windows']} finestre con fusioni "
                            f"(minimo {rules['min_films']} / {rules['min_windows_merged']})"]}
    if chrf_gate:
        if c['ci_lo'] is None or c['ci_lo'] <= rules['min_gain_chrf']:
            reasons.append("IC95% del delta chrF (b_full) non interamente sopra 0")
        if c['wilcoxon_p'] is None or c['wilcoxon_p'] > rules['wilcoxon_max_p']:
            reasons.append(f"Wilcoxon per film p={c['wilcoxon_p']} > {rules['wilcoxon_max_p']}")
    elif cm['wilcoxon_p'] is None or cm['wilcoxon_p'] > rules['wilcoxon_max_p']:
        reasons.append(f"Wilcoxon per film (COMET) p={cm['wilcoxon_p']} > {rules['wilcoxon_max_p']}")
    bi = summary['chrf_bi']
    if rules['sensitivity_same_sign'] and (bi['gain'] is None or c['gain'] is None or (bi['gain'] > 0) != (c['gain'] > 0)):
        reasons.append("b_iso con segno diverso da b_full")
    if summary['empty_pct_bf'] > rules['max_empty_pct']:
        reasons.append(f"blocchi vuoti {summary['empty_pct_bf']:.2f}% > {rules['max_empty_pct']}%")
    if summary['dropped_pct_bf'] > rules['max_dropped_pct']:
        reasons.append(f"blocchi fusi/ritemporizzati {summary['dropped_pct_bf']:.2f}% > {rules['max_dropped_pct']}%")
    if summary['fallback_pct'] > rules['max_fallback_pct']:
        reasons.append(f"unita' in ripiego {summary['fallback_pct']:.2f}% > {rules['max_fallback_pct']}%")
    if summary['cps_high_pct_bf'] - summary['cps_high_pct_a'] > rules['max_cps_high_increase_pts']:
        reasons.append("blocchi > 20 cps aumentati oltre la soglia")
    if summary['over84_pct_bf'] - summary['over84_pct_a'] > rules['max_over84_increase_pts']:
        reasons.append("blocchi > 84 caratteri aumentati oltre la soglia")
    if summary['imbalance_p90'] is not None and summary['imbalance_p90'] > rules['max_imbalance_p90']:
        reasons.append(f"sbilanciamento p90 {summary['imbalance_p90']:.3f} > {rules['max_imbalance_p90']}")
    if rules['untranslated_no_increase'] and summary['untr_b'] > summary['untr_a']:
        reasons.append(f"inglese residuo B {summary['untr_b']} > A {summary['untr_a']}")
    d = summary['neg_mean_abs_drift_bf']
    if d is not None and d > rules['negative_max_abs_chrf_drift']:
        reasons.append(f"controllo negativo: deriva media |chrF| {d:.2f} > {rules['negative_max_abs_chrf_drift']}")
    if rules['negative_iso_identical'] and summary['neg_iso_changed']:
        reasons.append(f"controllo negativo: b_iso diverso da A in {summary['neg_iso_changed']} finestre")
    if other is not None and rules['engines_same_sign']:
        og = (other.get('chrf_bf') or {}).get('gain')
        if og is not None and c['gain'] is not None and (og > 0) != (c['gain'] > 0):
            reasons.append("segno discorde fra i due motori")
    if gemba and rules['gemba_b_pref_not_lower'] and gemba['pref_b'] < gemba['pref_a']:
        reasons.append(f"GEMBA: preferenze B {gemba['pref_b']} < A {gemba['pref_a']}")
    if rules.get('gemba_primary'):
        insuff, g_reasons = gemba_primary(gemba, rules)
        if insuff:
            return {'verdict': 'INSUFFICIENTE', 'reasons': [insuff]}
        reasons.extend(g_reasons)
    comet_ok = cm['n_windows'] > 0
    if comet_ok and (cm['ci_lo'] is None or cm['ci_lo'] <= rules['min_gain_comet']):
        reasons.append("IC95% del delta COMET non interamente sopra 0")
    if reasons:
        return {'verdict': 'ARCHIVIA', 'reasons': reasons}
    if not comet_ok:
        return {'verdict': 'INDICATIVO_B', 'reasons': ['COMET non misurato: chrF da solo non basta per la produzione']}
    return {'verdict': 'PROPOSTA_PRODUZIONE', 'reasons': []}


def _fmt(x, nd=2):
    return '-' if x is None else f"{x:.{nd}f}"


def rules_changed(split_work: Path) -> Tuple[bool, List[str]]:
    p = split_work / 'runs_split.csv'
    if not p.exists():
        return False, []
    with open(p, encoding='utf-8') as f:
        shas = [r['rules_sha'] for r in csv.DictReader(f)]
    from split_eval.translate_arms import rules_sha
    return bool(shas) and shas[0] != rules_sha(), shas


def build_report(split_work: Path) -> str:
    with open(split_work / 'scores_split.csv', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    changed, _ = rules_changed(split_work)
    out: List[str] = []
    P = out.append
    P(f"BANCO FRASI SPEZZATE — regole congelate il {DRS.FROZEN_ON} ({DRS.NOTE}); chrF: {SM.chrf_backend()}")
    if changed:
        P("⚠️⚠️ decision_rules_split.py E' CAMBIATO dopo il primo run: verdetto NON VALIDO.")
    index = AB.read_jsonl(split_work / 'build' / 'index.jsonl')
    ok_idx = [r for r in index if r.get('status') == 'ok']
    if ok_idx:
        def agg(k):
            n = sum((r.get(k) or {}).get('n_blocks') or 0 for r in ok_idx)
            m = sum((r.get(k) or {}).get('n_midcut') or 0 for r in ok_idx)
            return f"{100 * m / n:.2f}% ({m}/{n})" if n else '-'
        P(f"\nMidcut (quota blocchi a meta' frase) su {len(ok_idx)} finestre, sorgente {ok_idx[0].get('asr_key')}:")
        P(f"   segmenti ASR {agg('midcut_hyp')} | formatter {agg('midcut_fmt')} | dopo cleaner {agg('midcut_src')}")
        P(f"   sub professionali EN {agg('midcut_ref_en')} | IT {agg('midcut_ref_it')}")
    summaries = {e: engine_summary(rows, e) for e in sorted({r['engine'] for r in rows})}
    for engine, s in summaries.items():
        other_key = next((k for k in summaries if k != engine
                          and k in [DRS.PRIMARY_ENGINE] + DRS.OPTIONAL_ENGINES
                          and 'prod' not in summaries[k]['llm_unit_budget']), None)
        other = summaries.get(other_key) if other_key else None
        ids = {u['id'] for u in AB.read_jsonl(split_work / f"units_{engine}.jsonl")}             if (split_work / f"units_{engine}.jsonl").exists() else None
        film_of = ({u['id']: u['film'] for u in AB.read_jsonl(split_work / f"units_{engine}.jsonl")}
                   if ids is not None else None)
        gem = load_gemba(engine, ids, film_of)
        d = decide(s, other, gem, rules_changed=changed)
        P('')
        P('=' * 90)
        P(f"MOTORE {engine}: finestre {s['n_ok']}/{s['n_windows']} ok, con fusioni {s['n_merged_windows']} "
          f"(unita' fuse {s['n_merged_units']}), controllo negativo {s['n_neg_windows']}")
        for key, lab in (('chrf_bf', 'chrF b_full'), ('chrf_bi', 'chrF b_iso'), ('comet', 'COMET')):
            c = s[key]
            P(f"   {lab:<12} delta B-A {_fmt(c['gain'])} IC95% [{_fmt(c['ci_lo'])}, {_fmt(c['ci_hi'])}] "
              f"film={c['n_films']} fin={c['n_windows']} Wilcoxon p={_fmt(c.get('wilcoxon_p'), 4)}")
        P(f"   strutturali (blocchi delle unita' fuse): vuoti B {s['empty_pct_bf']:.2f}% | fusi/ritemp. "
          f"{s['dropped_pct_bf']:.2f}% | ripiego {s['fallback_pct']:.2f}% unita' | >20cps A {s['cps_high_pct_a']:.1f}% "
          f"B {s['cps_high_pct_bf']:.1f}% | >84car A {s['over84_pct_a']:.1f}% B {s['over84_pct_bf']:.1f}% | "
          f"sbilanciamento p90 {_fmt(s['imbalance_p90'], 3)}")
        P(f"   inglese residuo A {s['untr_a']} B {s['untr_b']} | controllo negativo: deriva |chrF| b_full "
          f"{_fmt(s['neg_mean_abs_drift_bf'])}, b_iso cambiato in {s['neg_iso_changed']} finestre | "
          f"blocchi singoli cambiati in b_full {s['singleton_changed_bf']} (rumore del motore)")
        if gem:
            P(f"   GEMBA ({gem['n']} unita'): pref A {gem['pref_a']} B {gem['pref_b']} pari {gem['tie']} | "
              f"MQM A {gem['mqm_a']:.2f} B {gem['mqm_b']:.2f}")
        P(f"   VERDETTO: {d['verdict']}")
        for r in d['reasons']:
            P(f"      - {r}")
    return '\n'.join(out)
