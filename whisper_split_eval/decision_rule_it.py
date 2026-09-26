"""
REGOLA DI DECISIONE — split di Whisper per frasi in ITALIANO (conferma su file interi mai visti).
Congelata il 2026-09-26 PRIMA di preparare o trascrivere i file di conferma (sha256 in
decision_rule_it.sha256). NON MODIFICARE DOPO AVER VISTO I RISULTATI.

Contesto: le regole italiane (core/whisper_sentence_split.py, ramo lang='it') sono state sviluppate su 3 file di
TARATURA (Casper, Il diavolo veste Prada, The Bad Guy); qui si confermano su 8 file di CONFERMA (i restanti di
work_it/selection_it.json, campo set == 'conferma'), mai analizzati. Italiano NON attivo di default qualunque
sia l'esito: si accende solo con whisper_split_sentence_langs = ['en','it'] e la decisione e' dell'utente.

RICALIBRAZIONI rispetto alla v5 (inglese), decise guardando SOLO i dati di taratura (motivi):
  * (0) campione: >= 6 file validi su 8 (non 7): due dei file selezionati potrebbero non avere sottotitolo
    letto o audio valido; se meno di 6 -> INSUFFICIENTE (non si aggiungono ne' sostituiscono file).
  * (a) midcut assoluto <= 0,20 (come in inglese) E rapporto nuova/attuale <= 0,25 (in inglese 0,16-0,20 su
    tre campioni; sulla taratura italiana 0,20).
  * (b) doppio: parole identiche; testo per segmento nativo == concatenazione dei pezzi SENZA spazi aggiunti;
    ogni pezzo che inizia con un token senza spazio iniziale (taglio dentro parola) deve essere preceduto da un
    salto >= 18 s (glitch di timestamp di Whisper: es. "Cos" a 1423 s e "'e'" a 1529 s in Casper; il taglio li'
    e' voluto, altrimenti un blocco mostrava tre frasi 100 s in anticipo). Qualunque altro taglio dentro parola
    = fallimento.
  * (d) durata contata in PAROLE INTERE (token con spazio iniziale), non in token: nessun pezzo di >= 2 parole
    intere oltre 9,0 s; un pezzo di una sola parola intera oltre 9,0 s ammesso solo se lo split attuale contiene
    lo stesso pezzo; blocchi > 9 s nuova <= attuale. (In taratura "Cos'e'" contava come 2 parole.)
  * (f_lt1) quota blocchi < 1 s: nuova <= max(quota professionale, 1,0%). Motivo: i sottotitoli professionali
    italiani dei film doppiati sono traduzioni dall'inglese (in taratura solo 0,26% di cue < 1 s contro 1,6-4,3%
    dei professionali inglesi nei tre campioni inglesi): confrontare con un riferimento cosi' raro e' instabile
    (5 blocchi su 1100). Il tetto assoluto 1,0% e' piu' severo di tutti i riferimenti inglesi.
  * (i) POS indipendente (spaCy it_core_news_lg): quota di blocchi che finiscono su DET/ADP/CCONJ/SCONJ/AUX
    nuova <= 0,5 x attuale (taratura: 3,4% contro 23,8% = 0,14). Indipendente dalle liste di regole.
  * (h) regressione, calcolata SUL CODICE FINALE su GPU: l'inglese con le lingue di default resta bit-identico
    ai risultati v5 salvati (2 file) e Wristcutters (italiano) con lingue di default == run 'off' salvato.
Invariati dalla v5: (c) quote >84 car / >20 cps / >2 righe, (e) opzione spenta bit-identica, (e2) run GPU 'on' ==
ricostruzione offline (con lang='it'), (f_lt15) e (f_densita) ancorati ai sottotitoli professionali italiani,
(g) ogni file: midcut nuova < attuale e blocchi/min nuova <= cue/min professionali.

Se NON e' VINCENTE: si riporta e si lascia l'italiano spento, senza correggere-e-riprovare su questi file.
Se e' VINCENTE: si riporta; l'accensione (aggiungere 'it' a whisper_split_sentence_langs) la decide l'utente.
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
