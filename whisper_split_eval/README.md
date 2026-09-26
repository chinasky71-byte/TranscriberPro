# whisper_split_eval — split dei segmenti faster-whisper per confini di frase

Domanda: il 41% dei blocchi Whisper che finiscono a meta' frase (banco
`asr_eval`, `fmt_midcut`) nasce da `FasterWhisperEngine._split_segment_by_words`?
Se si', uno split che preferisce i confini di frase lo riduce senza toccare il testo?

## File
- `run_whisper.py` — GPU, 1 processo, solo Whisper large-v3 int8_float16, stesso
  modo di chiamare il motore di `asr_bench run` (sandbox config, stesso audio
  `asr_eval/work/win/*/vocals.wav`, sola lettura). `--mode raw` salva i segmenti
  NATIVI (split = identita') + i chunk VAD reali; `--mode on|off` = motore di
  produzione con opzione accesa/spenta.
- `analyze.py` — CPU: `diag` (attribuzione dei tagli), `tune` (set di tuning),
  `eval` (regola congelata + verdetto). Lo split e' una funzione pura dei
  segmenti nativi: i bracci si confrontano sugli stessi segmenti.
- `decision_rule.py` — regola scritta PRIMA della misura (sha256 in
  `decision_rule.sha256`). Non modificarla.
- `compare_gpu.py` — run GPU `on` == ricostruzione offline; `off` == hyp del banco.
- `_orig_split.py` — copia del metodo originale; `test_support.py` — estrae il
  metodo REALE dal sorgente del motore (ast) e lo esegue con una config finta.
- `tests/` — 26 test CPU, nessun modello.
- `work/` — dati (in .gitignore).

## Comandi
```
cd whisper_split_eval
set PYTHONIOENCODING=utf-8
..\venv\Scripts\python.exe run_whisper.py --mode raw          (~12 min GPU, 140 finestre)
..\venv\Scripts\python.exe analyze.py diag --set test
..\venv\Scripts\python.exe analyze.py eval                    (verdetto)
..\venv\Scripts\python.exe run_whisper.py --mode on  --role eval
..\venv\Scripts\python.exe run_whisper.py --mode off --role eval
..\venv\Scripts\python.exe compare_gpu.py [--module <v1>]
cd tests & ..\..\venv\Scripts\python.exe -m unittest discover -p "test_*.py"
```

## Note di metodo (post-hoc dichiarati)
- Dopo il primo `eval` e' stata aggiunta al modulo la regola "mai tagliare dentro
  una parola" (token senza spazio iniziale, es. `post|-traumatic`): 1 caso su
  4028 pezzi. I numeri cambiano di 0,03 punti di midcut. Le misure `posthoc` di
  `analyze.py eval` (testo vs testo nativo Whisper, pezzi >9 s di una sola parola
  identici nello split attuale) sono state aggiunte DOPO aver visto il verdetto.
- La diagnosi `diag --set test` includeva il braccio nuovo sulle finestre di
  valutazione prima dell'`eval`; i parametri NON sono stati toccati dopo.

## Esito finale (25/09/2026) — PROMOSSO, attivo di default solo per l'inglese

Regole successive, tutte congelate prima di guardare i dati (sha256 nei file `.sha256`):

| Prova | Dati | Esito |
|---|---|---|
| v1 (`decision_rule.py`) | 140 finestre | difetto della regola dichiarato, sostituita |
| v2 (`decision_rule_v2.py`) | 89 finestre nuove, 12 film | NON VINCENTE solo per i 3 criteri (f) (blocchi +23% contro +15% consentito) |
| v3b (`decision_rule_v3b.py`) | 45 finestre nuove, 10 film, margine 0 s | VINCENTE ((f) ancorato al riferimento professionale, ricalibrato dopo la v2) |
| v4 (`decision_rule_v4.py`) | 6 file interi (4 film, 2 episodi) | NON VINCENTE per un solo criterio: un caso di taglio dentro parola, presente anche nello split originale |

Dopo la v4 il ripiego dello split e' stato corretto (mai tagli dentro una parola; 40 test verdi, verifica offline su tutti i segmenti salvati: un solo segmento cambia) e l'opzione `whisper_split_sentence_aware` e' stata attivata di default, **solo per l'inglese** (unica lingua misurata; altre lingue usano lo split originale). Riserve dichiarate: (f) ricalibrato dopo il fallimento della v2, margine 0 s nella v3b, nessuna misura sull'effetto in traduzione, correzione del ripiego verificata solo offline sugli stessi dati.

Comandi v4: `select_full.py` -> `run_prepare_loop.sh` (un file per processo: il Demucs sui file lunghi arriva a 23-25 GB di RAM) -> `run_whisper.py --bench-work work_full --out-root work_full_runs --mode raw|off|on` -> `analyze_v4.py`.

## Conferma v5 (25/09/2026) — VINCENTE su dati nuovi con il codice corretto

`decision_rule_v5.py` (sha256 `bf5b8911...`, congelata prima di scegliere i file): stessi criteri della v4 piu' (e2) run GPU `on` == ricostruzione offline e (h) controllo negativo di lingua. 8 file inglesi interi mai usati (5 film, 3 episodi) + 1 controllo italiano, Demucs a chunk, un file per processo.
Esito: midcut 41,6% -> 8,3%, parole identiche (0 segmenti con testo diverso su 658), blocchi >84 car 0,95% -> 0, >2 righe 118 -> 15, >9 s 49 -> 13, opzione spenta bit-identica, (f) OK (blocchi/min 6,3 -> 7,7; professionali 12,1), ogni file migliora, `on` GPU == offline, controllo italiano (628 segmenti) off == on. Verdetto: `results/verdict_v5.json`.

## Italiano (26/09/2026) — regole pronte e confermate, NON attivate di default

Il modulo ha un ramo `lang='it'` (abbreviazioni, articoli/preposizioni/congiunzioni, locuzioni, iniziali) e il motore legge la lista `whisper_split_sentence_langs` (default `['en']`). Per accenderlo: `whisper_split_sentence_langs: ["en", "it"]` in `config.json`.

| Prova | Dati | Esito |
|---|---|---|
| Taratura | 3 file (2 film doppiati + 1 serie italiana) | regole sviluppate qui; midcut 36-51% -> 3,5-12% |
| Round 1, `decision_rule_it.py` | 7 file di conferma validi | NON VINCENTE per un solo criterio su 14: 4 pezzi di una parola >9 s (elisioni "C'era", "Dov'e'" con salto di 10-15 s dentro la parola, timestamp errati di Whisper) sotto la soglia glitch di 18 s |
| Fix | `glitch_gap_s` 18 -> 9 s (= tetto duro di durata) | verificato offline: inglese bit-identico su 2323 segmenti, sull'italiano cambiano solo i 4 segmenti in causa |
| Round 2, `decision_rule_it2.py` (congelata prima della selezione) | 8 file NUOVI (5 film doppiati, 3 serie) | VINCENTE: midcut 46,8% -> 11,2% (rapporto 0,238, soglia 0,25), blocchi su parola funzionale (spaCy) 24,9% -> 2,1%, parole identiche, ogni file migliora, regressione inglese/italiano OK |

Nota di trasparenza: nel round 2 la prima analisi dava NON VINCENTE per un taglio dentro parola su un salto di 17,3 s, perche' `analyze_it2.py` classificava i glitch con la soglia 18 s del round 1 invece dei 9 s dichiarati nella regola e nel modulo. Allineata la costante (nessun dato nuovo), il verdetto e' VINCENTE; i due esiti sono in `results/`.

Riserve: la maggior parte dei file e' doppiaggio; l'italiano originale e' coperto da 3 file (The Bad Guy, Sono qui per Caos, Guerrieri); i sottotitoli professionali dei doppiati sono traduzioni, usati solo per forma dei blocchi; effetto sulla traduzione e ascolto umano non misurati. Le fixture con dialoghi reali (`tests/data_*.json`) restano solo in locale.
