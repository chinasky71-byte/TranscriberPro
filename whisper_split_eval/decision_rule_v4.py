"""
REGOLA DI DECISIONE v4 — prova su FILE INTERI (film e episodi) dello split per
confini di frase, richiesta dall'utente il 25/09/2026 dopo il VINCENTE della v3b
(finestre di 150 s). Congelata PRIMA di scegliere i file (sha256 in
decision_rule_v4.sha256). NON MODIFICARE DOPO AVER VISTO I RISULTATI.

Perche': le prove v2/v3b misuravano finestre di 150 s. Qui si guarda il
comportamento lungo un intero file (scene senza dialogo, musica, ritmi diversi)
con il percorso di produzione (audio inglese -> Demucs vocals -> Whisper
batched, file unico), su file MAI usati in nessun banco.

Campione: 6 file dalla libreria (4 film da Y:/W:, 2 episodi da V:), audio INGLESE,
sottotitolo professionale inglese incorporato (testo), seme 20260927, titoli del
banco ASR e dei controlli precedenti esclusi (select_full.py). Un file per titolo.
Bracci e run: identici alla v3b (raw = segmenti nativi, off, on; la config e
la sandbox sono le stesse), un "finestra" = un file intero (t0 = 0).
Riferimento professionale: cue di parlato (music/sound_only esclusi) del sub
incorporato, statistiche AGGREGATE sui file e (per g) per file.

Criteri (tutti necessari per 'VINCENTE'):
  (0) campione: >= 5 file validi (prepare riuscito, sub professionale letto),
      >= 5 titoli distinti, nessuno tra i titoli esclusi. Altrimenti
      'INSUFFICIENTE' (nessun file viene aggiunto o sostituito dopo).
  (a)-(e) IDENTICI alla v3b, calcolati sull'insieme dei file.
  (f) IDENTICO alla v3b (ancorato al riferimento professionale), sull'insieme.
  (g) NUOVO, per OGNI file valido: midcut nuova < midcut attuale E
      blocchi/min nuova <= cue/min professionali di quel file. Serve a
      escludere che il risultato aggregato nasconda un file peggiorato.
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-25'
SEED = 20260927
MIN_FILES = 5
MIN_TITLES = 5
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
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
