"""
REGOLA DI DECISIONE (round 2) — split di Whisper per frasi in ITALIANO, conferma su un SECONDO set di file
mai visti. Congelata il 2026-09-26 PRIMA di selezionare i file (sha256 in decision_rule_it2.sha256). NON
MODIFICARE DOPO AVER VISTO I RISULTATI.

STORIA (dichiarata): il round 1 (decision_rule_it.py, 7 file validi di conferma) e' risultato NON VINCENTE per
UN solo criterio su 14, (d): 4 pezzi di una sola parola oltre 9 s non presenti nello split attuale. Erano tutti
elisioni con salto di 10-15 s dentro la parola ("C'|era", "Dov'|e'", "D'|accordo"; glitch di timestamp di
Whisper) sotto la soglia glitch_gap_s = 18 s scelta guardando un solo caso (105 s). Tutti gli altri criteri
erano OK (midcut 46,0% -> 10,2%, rapporto 0,222; POS spaCy 23,2% -> 2,5%; regressione inglese/italiano OK).
Il round 1 NON viene ripescato: la soglia e' stata portata a 9,0 s (= hard_max_duration: nessuna parola contiene
piu' di 9 s di silenzio), verificata OFFLINE (inglese bit-identico su 2323 segmenti; sull'italiano cambiano solo
i 4 segmenti in causa) e ora si CONFERMA su file NUOVI (seed 20260930, titoli dei round precedenti esclusi,
sottotitolo con >= 600 cue dichiarati nei metadati).

Criteri: IDENTICI a decision_rule_it.py (a, b, c, d, e, e2, f, g, h, i), campione >= 6 file validi su 8.
Se NON e' VINCENTE: si riporta e l'italiano resta spento, nessun ulteriore giro. Se e' VINCENTE: si riporta e
l'accensione ('it' in whisper_split_sentence_langs) la decide l'utente.
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-26'
MIN_FILES = 6
MIN_TITLES = 6
MIDCUT_MAX = 0.20
MIDCUT_RATIO_MAX = 0.25
GT84_MAX_DELTA = 0.010
CPS20_MAX_DELTA = 0.020
MAX_PIECE_DUR_S = 9.0
LT1_ABS_CAP = 0.010
POS_RATIO_MAX = 0.5


def _closer_and_below(name, nv, ov, pv, fmt):
    ok = nv <= pv and abs(nv - pv) <= abs(ov - pv)
    return ok, f"{name}: attuale {ov:{fmt}} -> nuova {nv:{fmt}} (professionale {pv:{fmt}})"


def verdict(m: Dict) -> Dict:
    o, n, p = m['old'], m['new'], m['pro']
    c = {}
    c['0_campione'] = (m['n_windows'] >= MIN_FILES and m['n_films'] >= MIN_TITLES and m['n_excluded_titles'] == 0,
                       f"{m['n_windows']} file validi, {m['n_films']} titoli, titoli esclusi presenti {m['n_excluded_titles']}")
    if not c['0_campione'][0]:
        return {'criteria': c, 'verdict': 'INSUFFICIENTE'}
    ratio = n['fmt_midcut'] / max(1e-9, o['fmt_midcut'])
    c['a_midcut'] = (n['fmt_midcut'] <= MIDCUT_MAX and ratio <= MIDCUT_RATIO_MAX,
                     f"attuale {o['fmt_midcut']:.4f} -> nuova {n['fmt_midcut']:.4f} (soglie {MIDCUT_MAX}; rapporto "
                     f"{ratio:.3f} <= {MIDCUT_RATIO_MAX}; professionali {m.get('pro_midcut', float('nan')):.4f})")
    c['b_testo'] = (m['words_identical'] and m['native_text_bad_exact'] == 0 and m['inword_cuts_bad'] == 0,
                    f"parole identiche={m['words_identical']}; segmenti con testo diverso (senza spazi aggiunti)="
                    f"{m['native_text_bad_exact']} su {m['n_native']}; tagli dentro parola non su glitch="
                    f"{m['inword_cuts_bad']} (tagli su glitch: {m['inword_cuts_glitch']})")
    d84 = n['gt84'] - o['gt84']
    dcps = n['cps20'] - o['cps20']
    c['c_gt84'] = (d84 <= GT84_MAX_DELTA, f"{o['gt84']:.4f} -> {n['gt84']:.4f} (delta {d84:+.4f})")
    c['c_cps20'] = (dcps <= CPS20_MAX_DELTA, f"{o['cps20']:.4f} -> {n['cps20']:.4f} (delta {dcps:+.4f})")
    c['c_righe'] = (n['n_gt2lines'] <= o['n_gt2lines'], f"blocchi >2 righe {o['n_gt2lines']} -> {n['n_gt2lines']}")
    c['d_durata'] = (m['multiword_pieces_gt9s'] == 0 and m['singleword_gt9s_not_in_old'] == 0
                     and n['n_gt9s'] <= o['n_gt9s'],
                     f"pezzi >=2 parole intere >9s: {m['multiword_pieces_gt9s']}; pezzi di 1 parola >9s non presenti "
                     f"nell'attuale: {m['singleword_gt9s_not_in_old']}; blocchi >9s {o['n_gt9s']} -> {n['n_gt9s']}")
    c['e_opzione_spenta'] = (m['off_identical'], f"bit-identico: {m['off_identical_detail']}")
    cap = max(p['lt1'], LT1_ABS_CAP)
    c['f_lt1'] = (n['lt1'] <= cap, f"quota <1s: attuale {o['lt1']:.4f} -> nuova {n['lt1']:.4f} (tetto {cap:.4f}; professionale {p['lt1']:.4f})")
    c['f_lt15'] = _closer_and_below('quota <1,5s', n['lt15_share'], o['lt15_share'], p['lt15'], '.4f')
    c['f_densita'] = _closer_and_below('blocchi/min', n['per_min'], o['per_min'], p['per_min'], '.2f')
    bad = [f"{k}: midcut {v['old_midcut']:.3f}->{v['new_midcut']:.3f}, blocchi/min {v['new_per_min']:.1f} (pro {v['pro_per_min']:.1f})"
           for k, v in m['per_file'].items()
           if not (v['new_midcut'] < v['old_midcut'] and v['new_per_min'] <= v['pro_per_min'])]
    c['g_per_file'] = (not bad, 'tutti i file migliorano' if not bad else 'file non conformi: ' + '; '.join(bad))
    c['e2_on_coerente'] = (bool(m['on_run_consistent']), 'run GPU on == ricostruzione offline (lang=it): %s' % m['on_run_consistent'])
    pr = m.get('pos_ratio')
    c['i_pos_indipendente'] = (pr is not None and pr <= POS_RATIO_MAX,
                               f"blocchi che finiscono su parola funzionale (spaCy): rapporto nuova/attuale {pr} (soglia {POS_RATIO_MAX}); "
                               f"{m.get('pos_detail', '')}")
    c['h_regressione'] = (bool(m.get('en_regression_ok')) and bool(m.get('it_default_ok')),
                          f"inglese v5 bit-identico: {m.get('en_regression_ok')}; italiano con lingue di default == off: {m.get('it_default_ok')}")
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
