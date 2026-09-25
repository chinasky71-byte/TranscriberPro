"""
REGOLA DI DECISIONE v5 — conferma su DATI NUOVI dello split per frasi CORRETTO
(v1.21.0, gia' attivo di default solo per l'inglese). Congelata il 2026-09-25
PRIMA di scegliere i file (sha256 in decision_rule_v5.sha256). NON MODIFICARE
DOPO AVER VISTO I RISULTATI.

Perche': la correzione del ripiego (mai tagli dentro parola) e la guardia di
lingua sono state verificate solo offline sugli stessi dati della v4 e la
guardia non e' mai girata su GPU. Questa prova e' una CONFERMA, non un altro
giro di taratura: criteri (0) e (a)-(g) IDENTICI alla v4 (compreso (b'), il
controllo che unisce i pezzi con uno spazio: e' quello che ha scoperto il
taglio dentro parola), con seme nuovo e due aggiunte:
  (e2) la run GPU 'on' coincide con la ricostruzione offline (dimostra che il
       percorso di produzione con la guardia di lingua esegue davvero il nuovo
       split sull'inglese): m['on_run_consistent'] deve essere True;
  (h)  CONTROLLO NEGATIVO DI LINGUA: >= 1 file con audio non inglese
       (italiano), run 'off' e 'on' sul motore reale: output bit-identico
       (la guardia deve lasciare lo split originale). Non entra nelle metriche
       inglesi. Per il controllo si usa l'audio grezzo (senza Demucs).

Campione: >= 7 file inglesi validi su 8 selezionati (5 film <= 110 min da Y:/W:,
3 episodi da V:, titoli e SERIE mai usati in alcun banco, v4 compresa) + 1
controllo italiano. Seme 20260928.

Se la v5 NON e' VINCENTE: si RIPORTA l'esito e si propone di riportare il
default a False; NON si corregge-e-riprova-e-promuove di nuovo, e non si
ripristina il default senza l'utente.
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-25'
SEED = 20260928
MIN_FILES = 7
MIN_TITLES = 7
MIDCUT_MAX = 0.20
WERC_TOL = 1e-9
GT84_MAX_DELTA = 0.010
CPS20_MAX_DELTA = 0.020
MAX_PIECE_DUR_S = 9.0


def _f(name: str, nv: float, ov: float, pv: float, fmt: str):
    ok = nv <= pv and abs(nv - pv) <= abs(ov - pv)
    return ok, f"{name}: attuale {ov:{fmt}} -> nuova {nv:{fmt}} (professionale {pv:{fmt}})"


def verdict(m: Dict) -> Dict:
    o, n, p = m['old'], m['new'], m['pro']
    c = {}
    c['0_campione'] = (m['n_windows'] >= MIN_FILES and m['n_films'] >= MIN_TITLES and m['n_excluded_titles'] == 0,
                       f"{m['n_windows']} file validi, {m['n_films']} titoli, titoli esclusi presenti {m['n_excluded_titles']}")
    if not c['0_campione'][0]:
        return {'criteria': c, 'verdict': 'INSUFFICIENTE'}
    c['a_midcut'] = (n['fmt_midcut'] <= MIDCUT_MAX,
                     f"attuale {o['fmt_midcut']:.4f} -> nuova {n['fmt_midcut']:.4f} (soglia {MIDCUT_MAX})")
    c['b_testo'] = (m['words_identical'] and m['native_text_ok']
                    and abs(n['werc'] - o['werc']) <= WERC_TOL,
                    f"parole identiche={m['words_identical']}; segmenti nativi con testo diverso="
                    f"{m['native_text_bad']} su {m['n_native']}; WERc {o['werc']:.6f} -> {n['werc']:.6f}")
    d84 = n['gt84'] - o['gt84']
    dcps = n['cps20'] - o['cps20']
    c['c_gt84'] = (d84 <= GT84_MAX_DELTA, f"{o['gt84']:.4f} -> {n['gt84']:.4f} (delta {d84:+.4f})")
    c['c_cps20'] = (dcps <= CPS20_MAX_DELTA, f"{o['cps20']:.4f} -> {n['cps20']:.4f} (delta {dcps:+.4f})")
    c['c_righe'] = (n['n_gt2lines'] <= o['n_gt2lines'], f"blocchi >2 righe {o['n_gt2lines']} -> {n['n_gt2lines']}")
    c['d_durata'] = (m['multiword_pieces_gt9s'] == 0 and m['singleword_gt9s_not_in_old'] == 0
                     and n['n_gt9s'] <= o['n_gt9s'],
                     f"pezzi >=2 parole >9s: {m['multiword_pieces_gt9s']}; pezzi 1 parola >9s non presenti "
                     f"nell'attuale: {m['singleword_gt9s_not_in_old']} (1 parola >9s totali "
                     f"{m['singleword_pieces_gt9s']}); blocchi >9s {o['n_gt9s']} -> {n['n_gt9s']}")
    c['e_opzione_spenta'] = (m['off_identical'], f"bit-identico: {m['off_identical_detail']}")
    c['f_lt1'] = _f('quota <1s', n['lt1'], o['lt1'], p['lt1'], '.4f')
    c['f_lt15'] = _f('quota <1,5s', n['lt15_share'], o['lt15_share'], p['lt15'], '.4f')
    c['f_densita'] = _f('blocchi/min', n['per_min'], o['per_min'], p['per_min'], '.2f')
    bad = [f"{k}: midcut {v['old_midcut']:.3f}->{v['new_midcut']:.3f}, blocchi/min {v['new_per_min']:.1f} (pro {v['pro_per_min']:.1f})"
           for k, v in m['per_file'].items()
           if not (v['new_midcut'] < v['old_midcut'] and v['new_per_min'] <= v['pro_per_min'])]
    c['g_per_file'] = (not bad, 'tutti i file migliorano' if not bad else 'file non conformi: ' + '; '.join(bad))
    c['e2_on_coerente'] = (bool(m['on_run_consistent']), 'run GPU on == ricostruzione offline: %s' % m['on_run_consistent'])
    c['h_controllo_lingua'] = (m['n_controls'] >= 1 and m['control_ok'],
                               f"controlli non inglesi {m['n_controls']}, off == on bit-identico: {m['control_ok']} {m.get('control_detail', '')}")
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
