"""
REGOLA DI DECISIONE — split di Whisper per frasi in FRANCESE (modello di produzione whisper-large-v3-french, v1.26.0),
conferma su file mai visti. Scritta il 2026-09-28 DOPO la taratura (3 file: Les Misérables 2019, Les Orphelins,
Intouchables) e PRIMA della preparazione dei file di conferma (selezione gia' congelata in
work_fr/selection_fr.json, seme 20261001, 9 film francesi originali). sha256 in decision_rule_fr.sha256.
NON MODIFICARE DOPO AVER VISTO I RISULTATI DI CONFERMA.

Criteri: IDENTICI a decision_rule_it2.py (a, b, c, d, e, e2, f, g, h, i), con queste differenze dichiarate:
- (a) rapporto midcut nuova/attuale <= 0,33 invece di 0,25. Motivo (taratura): il parlato francese dei film ha
  frasi lunghe legate da virgole; oltre i 84 caratteri il taglio migliore disponibile e' la virgola, che la metrica
  conta come "a meta' frase". Taratura: 45,1% -> 12,6% (rapporto 0,28); dei tagli interni del nuovo split 1664 sono
  a fine frase, 342 su virgola, 82 dopo parola qualunque/funzionale. Il tetto assoluto 20% resta.
- (b) "glitch" (taglio dentro parola ammesso): salto >= 9 s dentro la parola (come l'italiano) OPPURE parola intera
  (token attaccati) piu' lunga di 9 s. Taratura: 17 tagli con salto >= 9 s (elisioni "C" | "'est") e 1 caso
  "Oh" | "!" con salto 5,2 s e "!" lungo 7,2 s (una parola di 12 s non esiste: timestamp errato).
- (h) regressione OFFLINE (regression_check_fr.py): split ricalcolato dai segmenti nativi salvati == run GPU 'on'
  registrati con il modulo precedente, inglese v5 (8 file) e italiano round 2 (8 file). L'audio di quei banchi e'
  stato cancellato il 26/09. Il francese con le lingue di default (en, it) usa lo split originale: test CPU
  (test_french.TestLanguageGate) + criterio (e).
- (i) POS con spaCy fr_core_news_lg (italiano: it_core_news_lg).
- (d) i pezzi di UNA sola parola oltre 9 s non decidono (si riportano). Taratura: 2 casi nuovi, entrambi parole con
  timestamp errati: "Sous-titrage" (allucinazione di Whisper "Sous-titrage MFP.", "-titrage" lungo 11 s; l'attuale
  tagliava DENTRO la parola e lasciava "-titrage MFP." da 15,4 s) e "C'est" con 9,4 s di salto fra "C" e "'est"
  (l'attuale tagliava dentro la parola). Una parola di oltre 9 s e' sempre un glitch; restano decisivi: nessun pezzo
  di 2+ parole oltre 9 s e blocchi oltre 9 s non in aumento.
- (0) campione: >= 6 file validi su 9 (il nono e' riserva per sottotitoli non validi).
Se NON e' VINCENTE: il francese resta spento, si riporta. Se e' VINCENTE: l'accensione ('fr' in
whisper_split_sentence_langs) la decide l'utente.
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-28'
MIN_FILES = 6
MIN_TITLES = 6
MIDCUT_MAX = 0.20
MIDCUT_RATIO_MAX = 0.33
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
    # francese: i pezzi di UNA parola oltre 9 s sono per definizione timestamp errati (stessa definizione di glitch
    # del criterio b): si riportano ma non decidono (vedi docstring)
    c['d_durata'] = (m['multiword_pieces_gt9s'] == 0 and n['n_gt9s'] <= o['n_gt9s'],
                     f"pezzi >=2 parole intere >9s: {m['multiword_pieces_gt9s']}; blocchi >9s {o['n_gt9s']} -> "
                     f"{n['n_gt9s']}; (informativo) pezzi di 1 parola >9s non presenti nell'attuale: "
                     f"{m['singleword_gt9s_not_in_old']}")
    c['e_opzione_spenta'] = (m['off_identical'], f"bit-identico: {m['off_identical_detail']}")
    cap = max(p['lt1'], LT1_ABS_CAP)
    c['f_lt1'] = (n['lt1'] <= cap, f"quota <1s: attuale {o['lt1']:.4f} -> nuova {n['lt1']:.4f} (tetto {cap:.4f}; professionale {p['lt1']:.4f})")
    c['f_lt15'] = _closer_and_below('quota <1,5s', n['lt15_share'], o['lt15_share'], p['lt15'], '.4f')
    c['f_densita'] = _closer_and_below('blocchi/min', n['per_min'], o['per_min'], p['per_min'], '.2f')
    bad = [f"{k}: midcut {v['old_midcut']:.3f}->{v['new_midcut']:.3f}, blocchi/min {v['new_per_min']:.1f} (pro {v['pro_per_min']:.1f})"
           for k, v in m['per_file'].items()
           if not (v['new_midcut'] < v['old_midcut'] and v['new_per_min'] <= v['pro_per_min'])]
    c['g_per_file'] = (not bad, 'tutti i file migliorano' if not bad else 'file non conformi: ' + '; '.join(bad))
    c['e2_on_coerente'] = (bool(m['on_run_consistent']), 'run GPU on == ricostruzione offline (lang=fr): %s' % m['on_run_consistent'])
    pr = m.get('pos_ratio')
    c['i_pos_indipendente'] = (pr is not None and pr <= POS_RATIO_MAX,
                               f"blocchi che finiscono su parola funzionale (spaCy): rapporto nuova/attuale {pr} (soglia {POS_RATIO_MAX}); "
                               f"{m.get('pos_detail', '')}")
    c['h_regressione'] = (bool(m.get('en_regression_ok')) and bool(m.get('it_default_ok')),
                          f"inglese v5 bit-identico (offline): {m.get('en_regression_ok')}; italiano round 2 bit-identico (offline): {m.get('it_default_ok')}")
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
