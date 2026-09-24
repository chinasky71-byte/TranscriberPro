"""
Regole di decisione del banco ASR, CONGELATE il 2026-09-24 prima di
qualsiasi run.

NON MODIFICARE DOPO AVER VISTO I RISULTATI. Lo sha256 di questo file viene
registrato in runs.csv al primo run; `report` avvisa se e' cambiato.

Interpretazioni fissate qui (il progetto era ambiguo o contraddittorio):
- GAIN = WERc(produzione) - WERc(sfidante): positivo = sfidante migliore.
  Il progetto definiva Delta = sfidante - produzione ma chiedeva "IC sopra
  0 a favore dello sfidante": le due frasi si contraddicono, vale GAIN.
- Guardia allucinazioni: violata solo se lo sfidante supera la produzione
  di PIU' del 50% E di PIU' di 2/ora (con produzione a 0/ora la sola
  regola del +50% bocciarebbe anche una singola allucinazione).
- Controllo d'ascolto IT (5 battute per film): riferimento verificato se
  almeno IT_LISTEN_MIN_OK su 5 sono giudicate fedeli (soglia non presente
  nel progetto: e' una scelta di questo banco).
- Un film con finestre fallite per un motore non entra nel confronto di
  quel motore: il verdetto diventa NON_VALUTABILE finche' non si rilancia.
"""

FROZEN_ON = "2026-09-24"
NOTE = "non modificare dopo aver visto i risultati"

PRODUCTION_ENGINE = {'en': 'canary', 'it': 'qwen3'}
CHALLENGERS = {'en': ['whisper', 'qwen3'], 'it': ['whisper']}
PRIMARY_ARM = 'vocals'

DECISION_RULES = {
    'min_films_main_en': 8,
    'min_films_it': 6,
    'min_gain_abs': 0.015,        # 1,5 punti WERc
    'min_gain_rel': 0.10,         # oppure 10% relativo al WERc di produzione
    'ci_level': 0.95,
    'bootstrap_n': 10_000,
    'bootstrap_seed': 20260924,
    'halluc_max_rel_increase': 0.50,
    'halluc_max_abs_increase_per_h': 2.0,
    'missed_max_increase_pts': 2.0,
    'names_max_drop_pts': 3.0,
    'secondary_same_sign': True,
    'max_failed_windows': 0,
    'gold_must_agree': True,
}

IT_LISTEN_MIN_OK = 4
IT_FIDELITY_TRANSLATION_LCS = 0.85
IT_FIDELITY_MIN_WPM_EXCESS = 0.10
EN_SDH_SAME_LCS = 0.95

WINDOW_RULES = {
    'target_s': 150.0,
    'tol_s': 30.0,
    'min_pause_s': 1.0,
    'range': (0.04, 0.94),
    'n_bands': 10,
    'min_ref_words': 150,
    'max_music_frac': 0.10,
    'max_sound_frac': 0.25,
    'max_italic_frac': 0.30,
    'pad_s': 5.0,
    'seed': 20260924,
    'it_dev_windows_office_romance': 2,
}

SYNC_RULES = {
    'search_s': 3.0,
    'step_s': 0.05,
    'correct_if_abs_gt_s': 0.30,
    'min_agreement': 0.30,
}

# Gruppi film. Chiave = sottostringa (minuscolo) del nome file.
FILM_GROUPS = {
    'en': {
        'main': ['dirty angels', 'your monster', 'friendship', 'good fortune', 'good boy',
                 'ladies first', 'mother mary', 'office romance', 'return to silent hill'],
        'secondary': ['black box', 'tremors', 'il piacere e tutto mio', 'goldeneye'],
        'report_only': ['macbeth'],
        'dev': ['archive', 'skylines'],
    },
    'it': {
        # origine: 'doppiato' | 'nato_ita'; gruppo: 'main' | 'secondary'
        'candidates': {
            'office romance': {'origin': 'doppiato', 'group': 'main', 'prefer': 'dubtitle'},
            'ladies first': {'origin': 'doppiato', 'group': 'main', 'prefer': 'dubtitle'},
            'dirty angels': {'origin': 'doppiato', 'group': 'main', 'prefer': 'sdh'},
            'force of nature': {'origin': 'doppiato', 'group': 'main', 'prefer': 'sdh'},
            'scream 4': {'origin': 'doppiato', 'group': 'secondary', 'prefer': 'sdh'},
            'vita nella banlieue 2': {'origin': 'doppiato', 'group': 'secondary', 'prefer': 'sdh'},
            'grazie ragazzi': {'origin': 'nato_ita', 'group': 'main', 'prefer': 'any'},
            'scordato': {'origin': 'nato_ita', 'group': 'secondary', 'prefer': 'any'},
        },
        'excluded': ['the moon', 'the animal kingdom'],
    },
}
