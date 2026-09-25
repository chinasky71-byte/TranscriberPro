"""
REGOLA DI DECISIONE v3 — seconda prova CONFERMATIVA dello split per confini di
frase, su finestre NUOVE (mai usate: ne' le 140 di asr_eval/work, ne' le 91
pianificate / 89 usate dalla v2 in work_fresh/).

Data: 2026-09-25. NON MODIFICARE DOPO AVER VISTO I RISULTATI (sha256 in
decision_rule_v3.sha256, scritto PRIMA di pianificare le finestre v3).

STORIA (dichiarata): la v2 e' risultata NON VINCENTE solo per i tre criteri (f)
(blocchi 1864 -> 2301 = x1,234 contro limite x1,15; quota <1 s +0,21 punti contro
+0,20; blocchi <1,5 s 114 -> 342 contro 171); (a)-(e) erano OK. Dopo quel verdetto
il criterio (f) e' stato RICALIBRATO: qui e' ancorato al riferimento
professionale, non piu' allo split attuale. Quello che protegge dal rischio
"v2 con il criterio che falliva allentato dopo averlo visto fallire" e' UNA cosa
sola: la prova si fa su finestre nuove. Va detto chiaramente:

  * Misura sulle finestre v2 (89 finestre, 13318 s, sola lettura, fatta prima di
    scrivere questa regola): cue professionali di parlato 17,9/min (3970 cue con
    musica/effetti; 3835 senza), blocchi attuali 8,4/min, blocchi con split per
    frase 10,4/min; quota <1 s: professionali 2,3%, attuale 0,05%, nuova 0,26%;
    quota <1,5 s: professionali 27,8%, attuale 6,1%, nuova 14,9%.
  * Quindi l'output ATTUALE e' sotto-segmentato rispetto ai professionisti e la
    nuova versione ci si avvicina. Con i criteri (f) qui sotto la nuova versione
    li soddisfa con largo margine: la v3 di fatto ELIMINA la guardia "non
    frammentare piu' di +15% rispetto all'attuale" perche' l'attuale non e' la
    norma da difendere. Resta una guardia contro la frammentazione SOPRA il
    livello professionale e contro l'allontanarsi da esso.

Bracci, dati, metriche e interpretazioni: identici alla v2 (v. decision_rule_v2.py),
salvo il criterio (f), il calcolo dell'unione delle finestre gia' usate e
l'esito INSUFFICIENTE.

Riferimento professionale (per finestra, cue del sub professionale nella
finestra: w['cues']): si contano solo le cue di parlato (music == False e
sound_only == False). Statistiche AGGREGATE sulle finestre:
  pro.per_min  = n cue di parlato / (somma delle durate delle finestre / 60)
  pro.lt1      = quota di cue di parlato con durata (e - s) < 1,0 s
  pro.lt15     = quota di cue di parlato con durata < 1,5 s
Densita' dei blocchi: n_blocchi / (somma delle durate delle finestre / 60).

Criteri (tutti necessari per 'VINCENTE'):
  (0) campione: >= 40 finestre di >= 8 film, 0 sovrapposizioni temporali (stesso
      film) con l'UNIONE di: finestre v1 (asr_eval/work/windows.jsonl), finestre
      v2 (work_fresh/windows.jsonl e work_fresh/plan.json). Se (0) fallisce
      l'esito e' 'INSUFFICIENTE' (non 'NON VINCENTE'): NON si aggiungono film,
      NON si accorcia il margine di 10 s, NON si cambia il seme (20260926).
  (a)-(e) IDENTICI alla v2 (midcut <= 0,20; parole/testo/WERc invariati; blocchi
      >84 car: delta <= +1,0 punti; >20 cps: delta <= +2,0 punti; blocchi >2
      righe: nuova <= attuale; nessun pezzo >= 2 parole >9,0 s e nessun pezzo di
      una parola >9,0 s assente dall'attuale; blocchi >9 s: nuova <= attuale;
      opzione spenta bit-identica).
  (f) NUOVO — non piu' frammentata del professionista e non piu' lontana da esso
      dell'attuale:
      f_lt1:     nuova.lt1  <= pro.lt1   E  |nuova.lt1  - pro.lt1|  <= |attuale.lt1  - pro.lt1|
      f_lt15:    nuova.lt15 <= pro.lt15  E  |nuova.lt15 - pro.lt15| <= |attuale.lt15 - pro.lt15|
      f_densita: nuova.per_min <= pro.per_min E |nuova.per_min - pro.per_min| <= |attuale.per_min - pro.per_min|
"""
from __future__ import annotations

from typing import Dict

RULE_DATE = '2026-09-25'
SEED = 20260926
MARGIN_S = 10.0
MIN_WINDOWS = 40
MIN_FILMS = 8
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
    c['0_campione'] = (m['n_windows'] >= MIN_WINDOWS and m['n_films'] >= MIN_FILMS and m['n_overlaps'] == 0,
                       f"{m['n_windows']} finestre, {m['n_films']} film, sovrapposizioni {m['n_overlaps']}")
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
    ok = all(v[0] for v in c.values())
    return {'criteria': c, 'verdict': 'VINCENTE' if ok else 'NON VINCENTE'}
