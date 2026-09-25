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
