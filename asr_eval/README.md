# asr_eval: banco di accuratezza ASR

Misura Whisper large-v3 (profilo di produzione), Canary-Qwen-2.5B (solo inglese) e Qwen3-ASR su finestre di circa 150 s dei film in `Z:\OMV_CONDIVISA\QBDownloads\ItaTorrents_Upload`. Il riferimento sono i sottotitoli professionali già presenti nei file. La metrica principale è il WERc (WER senza intercalari, con le ripetizioni collassate). Il verdetto segue le regole in `decision_rules.py`, congelate il 24/09/2026.

## Avvertenze

- **Non lanciare mai `prepare`, `run` o `run-all` con la coda di Transcriber Pro attiva, e nemmeno con l'app soltanto aperta.** I tre comandi rifiutano di partire se `nvidia-smi` mostra processi python sulla GPU, oppure se è in esecuzione un `main.py`.
- **Sandbox:** ogni processo del banco lavora su una copia della configurazione in `work/_cfg/`. `Config.save` non fa nulla e `Config.set` scrive solo in memoria. Se `~/.transcriberpro/config.json` cambia durante il banco, il comando si ferma con errore. I log di Transcriber Pro finiscono comunque in `~/.transcriberpro/logs`.
- **Motori chiamati direttamente:** i motori non passano da `EngineRouter`, quindi un errore resta un fallimento registrato, senza ripiego su Whisper. Un film con finestre fallite rende il verdetto `NON_VALUTABILE` finché il run non viene rilanciato.

## Ordine di esecuzione

Esegui i comandi dalla cartella `Transcriber_Pro`.

```
set PYTHONIOENCODING=utf-8
set PY=venv\Scripts\python.exe
```

**1. `audit` (solo CPU).** Estrae i sottotitoli: una lettura completa di ogni file su Z:.

```
%PY% asr_eval\asr_bench.py audit --clips
```

**2. Revisione manuale (a mano).**

- `work\audit_overrides.json`: scrivi `accept` o `reject` per le tracce scritte nel 2026. Oggi sono quasi tutte, compreso tutto il gruppo principale inglese.
- `work\listen_check.csv`: ascolta le clip e scrivi `S` o `N` nella colonna `ok`. Il riferimento italiano vale se almeno 4 battute su 5 sono `S`.

**3. `plan` (solo CPU).** Sceglie le finestre usando solo i sottotitoli.

```
%PY% asr_eval\asr_bench.py plan
```

**4. `prepare` (GPU, una volta sola).** Estrae l'audio delle finestre, esegue Demucs, stima la sincronia e crea i chunk.

```
%PY% asr_eval\asr_bench.py prepare
```

**5. `run-all` (GPU).** Avvia un processo nuovo per ogni combinazione motore × braccio, poi esegue `score` e `report`.

```
%PY% asr_eval\asr_bench.py run-all
```

**6. Set d'oro.** `gold-make` prepara i file da correggere. Correggi a mano `work\gold\<lingua>\*.txt` ascoltando l'audio: parti dal sottotitolo professionale, non dall'output dei motori. Poi rilancia `gold-score` e `report`.

```
%PY% asr_eval\asr_bench.py gold-make
%PY% asr_eval\asr_bench.py gold-score
%PY% asr_eval\asr_bench.py report
```

Puoi lanciare un singolo motore così: `%PY% asr_eval\asr_bench.py run --engine qwen3 --arm vocals`. La ripresa è automatica: il comando salta le ipotesi già valide per lo stesso wav e la stessa configurazione.

L'arbitro `--engine w2v` non è implementato.

## Dati (`work\`)

| Percorso | Contenuto |
|---|---|
| `audit.json`, `subs\` | risultati di `audit` e sottotitoli estratti |
| `plan.json` | finestre scelte da `plan` |
| `prep\` | stato della preparazione per film e lingua |
| `windows.jsonl`, `films.json` | elenco delle finestre preparate e dei film |
| `win\<id>\` | `raw.wav`, `vocals.wav`, `vocals_rms.npy` e `chunks\` |
| `hyp\<motore>__<braccio>\<id>.json` | ipotesi dei motori |
| `runs.csv` | un'esecuzione per riga |
| `scores.csv` | una riga per finestra × motore × braccio |
| `report.txt` | report finale |
| `gold\` | set d'oro |

## Test (CPU, circa 15 s)

```
cd asr_eval\tests
..\..\venv\Scripts\python.exe -m unittest discover -p "test_*.py"
```
