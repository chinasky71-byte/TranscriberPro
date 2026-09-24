# split_eval: frasi spezzate

Il banco misura quanti blocchi finiscono a metà frase (metrica `midcut`). Poi confronta due modi di tradurre:

- **braccio A**: i blocchi vengono tradotti uno per uno, come fa oggi la produzione;
- **braccio B**: le frasi spezzate vengono prima riunite in unità (`recompose`), tradotte come un blocco solo e infine ridivise in modo deterministico sui blocchi originali (`resplit`).

Il braccio B non è in produzione. Si decide solo in base alle regole congelate in `decision_rules_split.py`, fissate il 24/09/2026 prima di qualsiasi run.

## Comandi

Lanciali dalla cartella `Transcriber_Pro`:

```
set PYTHONIOENCODING=utf-8
venv\Scripts\python.exe split_eval\run_split_bench.py midcut
venv\Scripts\python.exe split_eval\run_split_bench.py build
venv\Scripts\python.exe split_eval\run_split_bench.py translate --engine nllb_finetuned
venv\Scripts\python.exe split_eval\run_split_bench.py translate --engine llm
venv\Scripts\python.exe split_eval\run_split_bench.py score
venv\Scripts\python.exe split_eval\run_split_bench.py score --comet
venv\Scripts\python.exe split_eval\run_split_bench.py report
```

| Comando | Risorse | Note |
|---|---|---|
| `midcut` | CPU | |
| `build` | CPU | Richiede `asr_eval` `prepare` + `run`. Può leggere Z: per estrarre il sub ITA. |
| `translate --engine nllb_finetuned` | GPU | Coda libera. Esegue A e B nello stesso processo. |
| `translate --engine llm` | GPU | Facoltativo: TranslateGemma. |
| `score` | CPU | |
| `score --comet` | GPU | Facoltativo: usa `venv_comet` e scarica `wmt22-comet-da`. |
| `report` | CPU | |

Il giudice GEMBA-MQM è a pagamento e parte solo se lo chiedi esplicitamente: `score --llm-judge`. Nella stessa chiamata giudica i due bracci in ordine casuale, con `mt_eval/run_gemba.py`.

`translate` si rifiuta di partire se la GPU è occupata o se gira `main.py`. Usa il sandbox della configurazione di `asr_eval` e riprende da dove si era fermato.

## Test

I test girano solo su CPU e durano pochi secondi:

```
cd split_eval\tests
..\..\venv\Scripts\python.exe -m unittest discover -p "test_*.py"
```

## Dati (`work\`)

| Percorso | Contenuto |
|---|---|
| `build\<finestra>\` | `fmt.srt` (formatter), `src.srt` (dopo il cleaner = input di A), `units.srt`, `mapping.json`, `it_ref.json` |
| `out\<motore>\<finestra>.json` e `out\<motore>\<finestra>\` | `A.srt`, `B_units.srt`, `B_full.srt`, `B_iso.srt` |
| `scores_split.csv`, `units_<motore>.jsonl`, `report_split.txt` | punteggi, unità e report |
| `runs_split.csv` | un run per riga, con lo sha delle regole |
