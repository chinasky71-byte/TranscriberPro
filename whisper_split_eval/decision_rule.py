"""
REGOLA DI DECISIONE — split dei segmenti faster-whisper per confini di frase.

Scritta il 24/09/2026 PRIMA di misurare la variante nuova sulle finestre di
valutazione. NON MODIFICARE DOPO AVER VISTO I RISULTATI: ogni modifica
successiva rende il verdetto post-hoc e va dichiarata come tale.

Partizione (fissata qui, prima della misura):
  - TUNING (scelta dei parametri, iterazioni libere): le finestre 'dev'
    (archive-2020, skylines-2020) + le finestre 'test' dei film
    TUNING_TEST_FILMS (good-boy-2026, return-to-silent-hill-2026,
    goldeneye-1995).
  - VALUTAZIONE (verdetto): tutte le altre finestre 'test' EN (11 film,
    107 finestre). Vincolo del committente: >= 40 finestre, >= 8 film.

Confronto: variante nuova (opzione whisper_split_sentence_aware=True)
contro lo split attuale, sugli STESSI segmenti nativi Whisper (lo split e'
una funzione pura dei segmenti; stesso audio vocals, stessa config del banco).
Blocchi = SubtitleFormatter(readability=True) di produzione, senza speaker
(stesso percorso di asr_bench `fmt_midcut`). Rapporti AGGREGATI (somma dei
numeratori / somma dei denominatori sulle finestre), come nel banco.

Criteri (tutti necessari per 'VINCENTE'):
  (a) midcut dei blocchi del formatter della variante <= 0,20;
  (b) testo invariato: per ogni finestra la sequenza delle parole
      (start, end, word) e il testo normalizzato concatenato sono IDENTICI
      allo split attuale (quindi WERc identico; lo si ricalcola comunque con
      asr_eval/metrics.score_window e deve coincidere a 1e-9); nessuna
      parola persa o duplicata;
  (c) guardie di leggibilita' sui blocchi:
      - quota blocchi con testo (righe unite da spazio) > 84 caratteri:
        variante - attuale <= +1,0 punti percentuali;
      - quota blocchi con cps > 20 (caratteri senza a capo / durata):
        variante - attuale <= +2,0 punti percentuali;
      - NUMERO di blocchi con piu' di 2 righe: variante <= attuale
        (interpretazione di "nessun blocco con piu' di 2 righe in piu'
        rispetto a oggi");
  (d) nessun pezzo prodotto dallo split nuovo dura piu' di 9,0 s, e il
      numero di blocchi del formatter > 9,0 s non aumenta;
  (e) controllo negativo: con l'opzione spenta l'output del motore e'
      bit-identico allo split attuale (offline su tutti i segmenti nativi
      di tutte le 140 finestre, via il metodo reale del motore con config
      finta; e, se eseguito, run GPU 'off' == hyp del banco).
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-24'
TUNING_TEST_FILMS = ('good-boy-2026', 'return-to-silent-hill-2026', 'goldeneye-1995')
MIN_EVAL_WINDOWS = 40
MIN_EVAL_FILMS = 8

MIDCUT_MAX = 0.20
WERC_TOL = 1e-9
GT84_MAX_DELTA = 0.010
CPS20_MAX_DELTA = 0.020
MAX_PIECE_DUR_S = 9.0


def is_eval_window(w: Dict) -> bool:
    return w['lang'] == 'en' and w['role'] == 'test' and w['film'] not in TUNING_TEST_FILMS


def is_tuning_window(w: Dict) -> bool:
    return w['lang'] == 'en' and (w['role'] == 'dev' or w['film'] in TUNING_TEST_FILMS)


def verdict(m: Dict) -> Dict:
    """m: dizionario di misure prodotto da analyze.py (cmd eval).
    Ritorna {'criteria': {nome: (ok, dettaglio)}, 'verdict': 'VINCENTE'|'NON VINCENTE'}."""
    c = {}
    c['0_campione'] = (m['n_windows'] >= MIN_EVAL_WINDOWS and m['n_films'] >= MIN_EVAL_FILMS,
                       f"{m['n_windows']} finestre, {m['n_films']} film")
    c['a_midcut'] = (m['new']['fmt_midcut'] <= MIDCUT_MAX,
                     f"attuale {m['old']['fmt_midcut']:.3f} -> nuova {m['new']['fmt_midcut']:.3f} (soglia {MIDCUT_MAX})")
    c['b_testo'] = (m['words_identical'] and m['text_identical']
                    and abs(m['new']['werc'] - m['old']['werc']) <= WERC_TOL,
                    f"parole identiche={m['words_identical']} testo identico={m['text_identical']} "
                    f"WERc {m['old']['werc']:.5f} -> {m['new']['werc']:.5f}")
    d84 = m['new']['gt84'] - m['old']['gt84']
    dcps = m['new']['cps20'] - m['old']['cps20']
    c['c_gt84'] = (d84 <= GT84_MAX_DELTA, f"{m['old']['gt84']:.4f} -> {m['new']['gt84']:.4f} (delta {d84:+.4f})")
    c['c_cps20'] = (dcps <= CPS20_MAX_DELTA, f"{m['old']['cps20']:.4f} -> {m['new']['cps20']:.4f} (delta {dcps:+.4f})")
    c['c_righe'] = (m['new']['n_gt2lines'] <= m['old']['n_gt2lines'],
                    f"blocchi >2 righe {m['old']['n_gt2lines']} -> {m['new']['n_gt2lines']}")
    c['d_durata'] = (m['new_max_piece_dur'] <= MAX_PIECE_DUR_S
                     and m['new']['n_gt9s'] <= m['old']['n_gt9s'],
                     f"pezzo piu' lungo {m['new_max_piece_dur']:.2f}s; blocchi >9s "
                     f"{m['old']['n_gt9s']} -> {m['new']['n_gt9s']}")
    c['e_opzione_spenta'] = (m['off_identical'], f"bit-identico con opzione spenta: {m['off_identical']}")
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
