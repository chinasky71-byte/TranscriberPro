"""
Regole di decisione dell'esperimento FRASI SPEZZATE (braccio A = blocchi
come oggi, braccio B = ricomposizione + ridivisione), CONGELATE il
2026-09-24 PRIMA di qualsiasi traduzione.

NON MODIFICARE DOPO AVER VISTO I RISULTATI. Lo sha256 di questo file viene
registrato al primo `translate` (work/runs_split.csv); `report` avvisa e
dichiara il verdetto NON VALIDO se il file e' cambiato dopo.

Interpretazioni fissate qui:
- DELTA = metrica(B) - metrica(A): positivo = B migliore (chrF, COMET).
- Variante che DECIDE: 'b_full' = il file delle unita' tradotto per intero,
  come farebbe la produzione (anche le unita' di un solo blocco passano di
  nuovo dal motore). 'b_iso' (unita' di un blocco prese da A: la differenza
  e' SOLO l'effetto della fusione) e' di sensibilita': deve avere lo stesso
  segno.
- Popolazione primaria: finestre con ALMENO UNA unita' fusa. Le finestre
  senza fusioni sono il CONTROLLO NEGATIVO (non entrano nel delta).
- Rumore di fondo: sulle finestre del controllo negativo b_full ritraduce
  gli stessi blocchi in un batch diverso; la loro deriva di chrF misura il
  rumore del motore (fp16/beam/padding), non l'effetto della fusione.
- COMET e' la metrica di record se misurata (wmt22-comet-da, con
  riferimento). CometKiwi e' solo diagnostica (mette ultimo il traduttore
  umano: memoria mt_film_bench_2026_08). Senza COMET il verdetto massimo e'
  'INDICATIVO_B' (chrF da solo premia la letteralita').
- TranslateGemma: conta per la concordanza SOLO se tradotta con
  llm_unit_budget='span' (budget = 84 x blocchi dell'unita'); col budget di
  produzione (tetto 84 per qualunque unita') il braccio B e' penalizzato per
  costruzione e il run e' solo descrittivo.
- Giudice LLM (GEMBA-MQM): facoltativo, dietro --llm-judge; i due bracci
  nella STESSA chiamata, ordine casuale (mt_eval/run_gemba.py). Se misurato,
  la preferenza per B non deve essere inferiore a quella per A.
"""

FROZEN_ON = "2026-09-24"
NOTE = "non modificare dopo aver visto i risultati"

PRIMARY_ENGINE = 'nllb_finetuned'
OPTIONAL_ENGINES = ['llm']
DECIDING_VARIANT = 'b_full'
SENSITIVITY_VARIANT = 'b_iso'
ASR_SOURCE = 'canary__vocals'      # ipotesi del banco asr_eval tradotte (motore EN di produzione)

SPLIT_RULES = {
    # campione minimo (per motore)
    'min_films': 6,
    'min_windows_merged': 30,
    # statistica
    'ci_level': 0.95,
    'bootstrap_n': 10_000,
    'bootstrap_seed': 20260924,
    'wilcoxon_max_p': 0.05,        # Wilcoxon esatto sui delta medi per film
    'min_gain_chrf': 0.0,          # IC95% del delta chrF interamente sopra questo
    'min_gain_comet': 0.0,         # IC95% del delta COMET (per finestra) sopra questo
    # guardie strutturali (sui blocchi delle unita' fuse; punti percentuali)
    'max_empty_pct': 1.0,          # blocchi vuoti in B (A non ne ha)
    'max_dropped_pct': 1.0,        # blocchi fusi/ritemporizzati (fallback 'span')
    'max_fallback_pct': 5.0,       # unita' fuse finite in ripiego
    'max_cps_high_increase_pts': 2.0,   # blocchi > 20 cps: B - A
    'max_over84_increase_pts': 1.0,     # blocchi > 84 caratteri: B - A
    'max_imbalance_p90': 0.20,     # |frazione IT - frazione EN| ai tagli, 90 percentile
    'untranslated_no_increase': True,   # inglese residuo (audit) B <= A
    # controllo negativo
    'negative_max_abs_chrf_drift': 0.5,  # |chrF(b_full) - chrF(A)| medio, finestre senza fusioni
    'negative_iso_identical': True,      # b_iso == A sulle finestre senza fusioni (per costruzione)
    'merges_require_midcut': True,       # finestra con midcut(formatter)==0 -> nessuna fusione
    # coerenza
    'sensitivity_same_sign': True,       # b_iso con lo stesso segno di b_full
    'engines_same_sign': True,           # NLLB-FT e TranslateGemma(span) concordi, se entrambi misurati
    'gemba_b_pref_not_lower': True,      # se GEMBA misurato: preferenze B >= A
    'max_failed_windows': 0,
}

VERDICTS = ('PROPOSTA_PRODUZIONE', 'INDICATIVO_B', 'ARCHIVIA', 'INSUFFICIENTE', 'NON_VALUTABILE', 'NON_VALIDO')
