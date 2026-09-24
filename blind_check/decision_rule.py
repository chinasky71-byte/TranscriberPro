"""
Regola di decisione del CONTROLLO ALLA CIECA della ricomposizione delle frasi
(core/sentence_recompose.py, opzione translation_recompose_sentences), su file
reali della libreria dell'utente. CONGELATA il 2026-09-25 PRIMA di scegliere i
file e di produrre qualsiasi traduzione.

NON MODIFICARE DOPO AVER VISTO I GIUDIZI (lo sha256 di questo file viene
registrato da conta.py nel report).

Protocollo: per ogni file si trascrive UNA volta, poi si traduce lo stesso SRT
sorgente due volte (base = opzione spenta, ricomposizione = opzione accesa).
L'utente vede solo le unita' in cui le due traduzioni differiscono, con
l'ordine A/B scambiato a caso (mappatura nascosta), e risponde per ognuna
"quale pubblicheresti?" (A, B o pari) segnalando eventuali DIFETTI VISIBILI
(unione di battute di parlanti diversi, taglio che spezza il senso).

Verdetto (nell'ordine):
1. INSUFFICIENTE: meno di MIN_DECISIVE giudizi non pari.
2. ARCHIVIA/DIFETTOSA se i difetti attribuiti alla ricomposizione superano
   MAX_DEFECT_RATE dei giudizi (anche con una preferenza favorevole).
3. PROMUOVI se la quota di preferenze per la ricomposizione fra i giudizi non
   pari e' >= MIN_SHARE E il test esatto binomiale unilaterale (H0: 50%) ha
   p <= ALPHA E i film in cui la ricomposizione e' in maggioranza sono almeno
   FILMS_MAJORITY dei film con >= FILM_MIN_DECISIVE giudizi non pari.
4. Altrimenti ARCHIVIA.
PROMUOVI significa: proporre di attivare l'opzione per default (a discrezione
dell'utente, con l'avvertenza sui file con molti parlanti), non attivarla da soli.
"""

FROZEN_ON = "2026-09-25"
NOTE = "non modificare dopo aver visto i giudizi"

SEED = 20260925
N_FILMS = 5                 # film scelti (radici in FILMS_FROM)
N_SERIES = 3                # episodi di serie da V:
FILMS_FROM = ('Y:', 'Y:', 'W:', 'W:', 'Y:')     # radice di ciascun film, in ordine
EXCERPT_MIN = 20            # minuti di estratto per file
EXCERPT_START_FRAC = 0.30   # inizio dell'estratto (frazione della durata)
MIN_FILM_MIN = 75           # durata minima di un film (min)
MIN_EPISODE_MIN = 35        # durata minima di un episodio (min)
MAX_DURATION_MIN = 210
YEAR_RANGE = (1995, 2025)   # anno del film dalla cartella "Titolo (AAAA)"
ENGINES = ('whisper', 'qwen3')   # assegnati in alternanza ai file selezionati
MAX_PAIRS_PER_FILE = 15
N_PAIRS_TARGET = 100

MIN_DECISIVE = 60
MIN_SHARE = 0.60
ALPHA = 0.025               # binomiale esatto unilaterale
MAX_DEFECT_RATE = 0.03      # difetti visibili della ricomposizione / giudizi totali
FILMS_MAJORITY = 0.60       # quota di film con maggioranza per la ricomposizione
FILM_MIN_DECISIVE = 5
