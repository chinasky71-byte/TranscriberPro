"""
REGOLA DI DECISIONE v2 — prova CONFERMATIVA dello split per confini di frase
su finestre NUOVE (mai usate: ne' le 140 di asr_eval/work, ne' le 107 di
valutazione / 33 di tuning della v1).

Data: 2026-09-25. NON MODIFICARE DOPO AVER VISTO I RISULTATI (sha256 in
decision_rule_v2.sha256, registrato al primo run). Criteri = testo del
revisore indipendente, adottato senza indebolirlo.

Dati: finestre generate da fresh_bench.py (seme 20260925, gruppi EN main +
secondary; esclusi dev archive/skylines, usati per il tuning della v1, e
report_only macbeth), audio vocals preparato da asr_bench.prepare.
Bracci, sugli STESSI segmenti nativi e lo stesso audio:
  attuale = run GPU con opzione spenta (work_fresh_runs/off)
  nuova   = run GPU con opzione accesa (work_fresh_runs/on, pause_s=1.0)
  nativi  = run GPU con split = identita' (work_fresh_runs/raw), serve per
            (b') testo per segmento nativo e (d') confronto parola singola.
Blocchi = SubtitleFormatter(readability=True) di produzione senza speaker
(come asr_bench fmt_midcut); rapporti AGGREGATI sulle finestre.

Interpretazioni fissate PRIMA della misura:
  - (c) "nessun blocco con piu' righe (>2) in piu'": NUMERO di blocchi con
    piu' di 2 righe, nuova <= attuale.
  - (f) durata di un blocco = end - start del blocco SRT prodotto dal
    formatter (dopo _enforce_min_duration). "blocchi <1 s <= attuale +0,2
    punti" = QUOTA sul totale blocchi; "numero di blocchi <= +15%" =
    n_nuova <= 1,15 x n_attuale; "blocchi <1,5 s <= attuale x 1,5" = NUMERO
    (conteggio) di blocchi <1,5 s, nuova <= 1,5 x attuale.
  - (d') "pezzo" = segmento restituito dallo split (motore), prima del
    formatter; "lo split attuale contiene lo stesso pezzo" = un pezzo di una
    parola con stessi start ed end (arrotondati al ms) nel braccio attuale.
  - (e) bit-identico: run GPU 'off' == split originale (_orig_split.py)
    riapplicato offline ai segmenti nativi della run 'raw' (le finestre sono
    nuove: non esiste un hyp del banco con cui confrontarle), E metodo reale
    del motore con config finta spenta == split originale su tutti i
    segmenti nativi. Inoltre run 'on' == ricostruzione offline (coerenza).
  - WERc: asr_eval/metrics.score_window, aggregato (errori/parole rif.).

Criteri (tutti necessari per 'VINCENTE'):
  (0) campione: >= 40 finestre di >= 8 film, tutte nuove (0 sovrapposizioni
      temporali, stesso film, con le finestre gia' usate);
  (a) midcut dei blocchi del formatter (nuova) <= 0,20;
  (b') sequenza delle parole (start, end, word) identica allo split attuale;
      per ogni segmento nativo, testo concatenato dei pezzi (spazi
      normalizzati) == segment.text normalizzato; WERc uguale entro 1e-9;
  (c) quota blocchi > 84 caratteri: nuova - attuale <= +1,0 punti;
      quota blocchi > 20 cps: nuova - attuale <= +2,0 punti;
      numero blocchi con > 2 righe: nuova <= attuale;
  (d') nessun pezzo di >= 2 parole dura oltre 9,0 s; un pezzo di una sola
      parola oltre 9,0 s e' ammesso solo se lo split attuale contiene lo
      stesso pezzo; numero di blocchi > 9,0 s: nuova <= attuale;
  (e) opzione spenta -> output bit-identico (v. sopra);
  (f) quota blocchi < 1,0 s: nuova <= attuale + 0,2 punti;
      numero di blocchi: nuova <= attuale x 1,15;
      numero di blocchi < 1,5 s: nuova <= attuale x 1,5.
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-25'
SEED = 20260925
MIN_WINDOWS = 40
MIN_FILMS = 8
MIDCUT_MAX = 0.20
WERC_TOL = 1e-9
GT84_MAX_DELTA = 0.010
CPS20_MAX_DELTA = 0.020
MAX_PIECE_DUR_S = 9.0
LT1_MAX_DELTA = 0.002
NBLOCKS_MAX_RATIO = 1.15
LT15_MAX_RATIO = 1.5


def verdict(m: Dict) -> Dict:
    o, n = m['old'], m['new']
    c = {}
    c['0_campione'] = (m['n_windows'] >= MIN_WINDOWS and m['n_films'] >= MIN_FILMS and m['n_overlaps'] == 0,
                       f"{m['n_windows']} finestre, {m['n_films']} film, sovrapposizioni {m['n_overlaps']}")
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
    dlt1 = n['lt1'] - o['lt1']
    c['f_lt1'] = (dlt1 <= LT1_MAX_DELTA, f"quota <1s {o['lt1']:.4f} -> {n['lt1']:.4f} (delta {dlt1:+.4f})")
    c['f_nblocchi'] = (n['n_blocks'] <= NBLOCKS_MAX_RATIO * o['n_blocks'],
                       f"blocchi {o['n_blocks']} -> {n['n_blocks']} (x{n['n_blocks'] / max(1, o['n_blocks']):.3f})")
    c['f_lt15'] = (n['n_lt15'] <= LT15_MAX_RATIO * o['n_lt15'],
                   f"blocchi <1,5s {o['n_lt15']} -> {n['n_lt15']} (limite {LT15_MAX_RATIO * o['n_lt15']:.1f})")
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
