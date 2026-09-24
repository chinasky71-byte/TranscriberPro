"""
Regole di decisione v2 (PROVA CONFERMATIVA) dell'esperimento FRASI SPEZZATE,
CONGELATE il 2026-09-24 PRIMA di qualsiasi traduzione su dati nuovi.

NON MODIFICARE DOPO AVER VISTO I RISULTATI (lo sha256 di questo file e' salvato
al primo `translate` in work_conf/runs_split.csv; `report` dichiara NON_VALIDO
il verdetto se cambia).

PERCHE' ESISTE. La v1 (decision_rules_split.py) e' stata applicata alla lettera
e ha dato ARCHIVIA, ma era DIFETTOSA: il suo testo dice che COMET e' la metrica
di record e che chrF da solo premia la letteralita', mentre il codice richiedeva
anche chrF > 0; e la memoria di progetto (criteri_giudizio_finetuning) indica
come metrica PRINCIPALE la preferenza del giudice (validata dall'utente il
19/08) e chrF come metrica invalida (stesso difetto che a luglio fece scartare
per errore TranslateGemma-4B). Sulla v1: chrF -0,62 (n.s.), COMET +0,03 in 7
film su 7, GEMBA B 303 contro A 161. La v1 non viene riscritta: questa prova
la sostituisce SU DATI NUOVI, con la gerarchia corretta decisa PRIMA.

DATI NUOVI: ipotesi di Qwen3-ASR (qwen3__vocals) sulle stesse 140 finestre
audio; sono testi e segmentazioni diversi da quelli della prova v1 (Whisper),
quindi unita' diverse. Qwen3 e' il motore standard dell'utente.

GERARCHIA (tutti gli endpoint primari devono passare):
1. GEMBA (preferenza fra i giudizi non pari, gpt-4o, A e B nella stessa
   chiamata con ordine casuale) su un CAMPIONE casuale di GEMBA_SAMPLE_N unita'
   fuse dei film di test (seme fisso): quota di B >= gemba_min_b_share con
   test esatto binomiale unilaterale p <= gemba_alpha; almeno
   gemba_min_decisive giudizi decisivi; la quota di B deve essere > 0,5 in
   almeno gemba_films_b_majority dei film con >= gemba_film_min_decisive
   giudizi decisivi (nessun film da solo domina).
2. COMET (wmt22-comet-da, con riferimento; finestre con riferimento ITA):
   IC95% del delta (B-A) sopra 0 e Wilcoxon esatto per film p <= 0,05 con
   almeno min_films film e min_windows_merged finestre.
chrF: SOLO DESCRITTIVO (riportato, non decide). CometKiwi: diagnostica.

GUARDIE (come v1): blocchi vuoti, blocchi fusi/ritemporizzati, ripiego,
aumento di cps>20 e di blocchi >84 caratteri, sbilanciamento ai tagli,
inglese residuo B <= A, controllo negativo (deriva chrF <= 0,5; b_iso == A),
coerenza con il midcut, nessuna finestra fallita.

ESITI: PROPOSTA_PRODUZIONE = si integra la ricomposizione in core/ dietro
un'opzione di configurazione SPENTA di default, da attivare dopo un controllo
alla cieca dell'utente su file reali. ARCHIVIA = si chiude qui (dopo due prove
con gerarchie diverse, la seconda pre-registrata).
"""

FROZEN_ON = "2026-09-24"
NOTE = "PROVA CONFERMATIVA v2 — non modificare dopo aver visto i risultati"

PRIMARY_ENGINE = 'nllb_finetuned'
OPTIONAL_ENGINES = []
DECIDING_VARIANT = 'b_full'
SENSITIVITY_VARIANT = 'b_iso'
ASR_SOURCE = 'qwen3__vocals'

GEMBA_SAMPLE_N = 250
GEMBA_SAMPLE_SEED = 20260924

SPLIT_RULES = {
    'min_films': 6,
    'min_windows_merged': 30,
    'ci_level': 0.95,
    'bootstrap_n': 10_000,
    'bootstrap_seed': 20260924,
    'wilcoxon_max_p': 0.05,        # ora sul delta COMET per film
    'min_gain_chrf': 0.0,          # non usato (chrF descrittivo)
    'min_gain_comet': 0.0,
    'chrf_gate': False,            # <-- la differenza chiave rispetto alla v1
    'gemba_primary': True,
    'gemba_min_decisive': 120,
    'gemba_min_b_share': 0.55,
    'gemba_alpha': 0.025,          # binomiale esatto unilaterale
    'gemba_film_min_decisive': 5,
    'gemba_films_b_majority': 0.70,
    'gemba_min_films_evaluable': 4,
    'comet_required': True,
    'max_empty_pct': 1.0,
    'max_dropped_pct': 1.0,
    'max_fallback_pct': 5.0,
    'max_cps_high_increase_pts': 2.0,
    'max_over84_increase_pts': 1.0,
    'max_imbalance_p90': 0.20,
    'untranslated_no_increase': True,
    'negative_max_abs_chrf_drift': 0.5,
    'negative_iso_identical': True,
    'merges_require_midcut': True,
    'sensitivity_same_sign': False,   # chrF b_iso: descrittivo
    'engines_same_sign': False,       # un solo motore misurato
    'gemba_b_pref_not_lower': True,
    'max_failed_windows': 0,
}

VERDICTS = ('PROPOSTA_PRODUZIONE', 'INDICATIVO_B', 'ARCHIVIA', 'INSUFFICIENTE', 'NON_VALUTABILE', 'NON_VALIDO')
