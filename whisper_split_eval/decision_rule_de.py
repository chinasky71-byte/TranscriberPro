"""
REGOLA DI DECISIONE — split di Whisper per frasi in TEDESCO (modello di produzione primeline whisper-large-v3-german,
v1.26.0), conferma su 8 film mai visti (work_de/selection_de.json, scelta fissa, titoli gia' usati esclusi).
Scritta il 2026-09-28 DOPO la taratura (La rosa bianca, La sala professori, Il cielo brucia) e PRIMA della
preparazione dei film di conferma. sha256 in decision_rule_de.sha256. NON MODIFICARE DOPO AVER VISTO LA CONFERMA.

Criteri come decision_rule_fr.py, con queste differenze dichiarate:
- (a) MISURA PRINCIPALE (scelta dell'utente dopo il francese): TAGLI NUDI (naked_cuts.py, liste fisse): blocco che
  finisce senza punteggiatura e successivo che non apre con congiunzione ne' trattino, pausa < 1 s. Non usa la
  minuscola (in tedesco i sostantivi sono maiuscoli). Soglie: nuova <= NAKED_MAX e rapporto nuova/attuale <=
  NAKED_RATIO_MAX. Taratura: 45,0% -> 3,3% (rapporto 0,073). I professionali (solo film con sub tedeschi) si
  riportano. La metrica midcut e' solo informativa.
- (c) cps>20: limite +4,0 punti invece di +2,0 (CPS20_MAX_DELTA). Motivo: blocchi piu' corti alzano per costruzione
  la quota di blocchi letti a piu' di 20 caratteri/s: francese conferma +2,4, tedesco taratura +2,7 (20,4% -> 23,1%;
  professionali 11,9%: condensano il testo, l'ASR no). Resta una guardia contro peggioramenti oltre l'effetto
  strutturale.
- (f) quota di blocchi < 1,5 s: nuova <= professionali + 3 punti (LT15_PRO_MARGIN) invece di "sotto i
  professionali". Motivo: in taratura 2 riferimenti su 3 sono sottotitoli ITALIANI (solo forma); tedesco taratura
  6,1% -> 13,7% contro 12,2% dei riferimenti. Le altre guardie di durata (f_lt1, d) restano invariate.
- (g) per file: tagli nudi in calo in ogni file (invece del midcut) e densita' <= professionali.
- (h) regressione OFFLINE su inglese v5, italiano round 2 E FRANCESE (acceso in v1.27.0): regression_check_de.py.
- (i) POS spaCy de_core_news_lg contando SOLO i blocchi che non finiscono con punteggiatura (in tedesco la frase
  finisce spesso su ausiliare o particella separabile).
- (0) campione >= 6 film validi su 8.
Se NON e' VINCENTE: il tedesco resta spento, si riporta. Se e' VINCENTE: l'accensione la decide l'utente.
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-28'
MIN_FILES = 6
MIN_TITLES = 6
NAKED_MAX = 0.06
NAKED_RATIO_MAX = 0.20
GT84_MAX_DELTA = 0.010
CPS20_MAX_DELTA = 0.040
LT15_PRO_MARGIN = 0.03
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
    ratio = n['naked'] / max(1e-9, o['naked'])
    c['a_tagli_nudi'] = (n['naked'] <= NAKED_MAX and ratio <= NAKED_RATIO_MAX,
                         f"attuale {o['naked']:.4f} -> nuova {n['naked']:.4f} (soglie {NAKED_MAX}; rapporto {ratio:.3f} "
                         f"<= {NAKED_RATIO_MAX}; professionali con sub tedeschi {m.get('pro_naked', float('nan')):.4f}; "
                         f"midcut informativo {o['fmt_midcut']:.4f} -> {n['fmt_midcut']:.4f})")
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
    c['f_lt15'] = (n['lt15_share'] <= p['lt15'] + LT15_PRO_MARGIN,
                   f"quota <1,5s: attuale {o['lt15_share']:.4f} -> nuova {n['lt15_share']:.4f} (tetto professionale "
                   f"{p['lt15']:.4f} + {LT15_PRO_MARGIN})")
    c['f_densita'] = _closer_and_below('blocchi/min', n['per_min'], o['per_min'], p['per_min'], '.2f')
    bad = [f"{k}: tagli nudi {v['old_naked']:.3f}->{v['new_naked']:.3f}, blocchi/min {v['new_per_min']:.1f} (pro {v['pro_per_min']:.1f})"
           for k, v in m['per_file'].items()
           if not (v['new_naked'] < v['old_naked'] and v['new_per_min'] <= v['pro_per_min'])]
    c['g_per_file'] = (not bad, 'tutti i file migliorano' if not bad else 'file non conformi: ' + '; '.join(bad))
    c['e2_on_coerente'] = (bool(m['on_run_consistent']), 'run GPU on == ricostruzione offline (lang=de): %s' % m['on_run_consistent'])
    pr = m.get('pos_ratio')
    c['i_pos_indipendente'] = (pr is not None and pr <= POS_RATIO_MAX,
                               f"blocchi che finiscono su parola funzionale (spaCy): rapporto nuova/attuale {pr} (soglia {POS_RATIO_MAX}); "
                               f"{m.get('pos_detail', '')}")
    c['h_regressione'] = (bool(m.get('en_regression_ok')) and bool(m.get('it_default_ok')),
                          f"inglese v5 bit-identico (offline): {m.get('en_regression_ok')}; italiano round 2 e francese bit-identici (offline): {m.get('it_default_ok')}")
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
