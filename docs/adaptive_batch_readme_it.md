# Adaptive Batch Size — Transcriber Pro

## Panoramica

Durante la traduzione con motori locali (NLLB, NLLB Finetuned, Aya), i sottotitoli vengono processati in **batch** — gruppi di righe inviati al modello in una singola operazione GPU. Un batch più grande significa meno chiamate a `model.generate()` e quindi maggiore throughput.

Il sistema **Adaptive Batch Size** gestisce questo valore dinamicamente: parte da un valore iniziale, lo aumenta progressivamente durante una fase di warm-up, poi lo monitora e aggiusta in base all'utilizzo reale della VRAM durante tutta la traduzione.

> **Nota:** Il batch size riguarda esclusivamente la **traduzione** (NLLB, Aya).
> La trascrizione (Faster-Whisper) utilizza questi valori solo se `BatchedInferencePipeline`
> è disponibile (faster-whisper ≥ 1.1.0).

---

## Fasi di funzionamento

### 1. Warm-up
Nelle prime N iterazioni (default: 5), il sistema aumenta il batch di **+4 per step** se la VRAM è sotto la soglia alta:

```
Warm-up [1/5]: batch  8 → 12  (mem=51%)
Warm-up [2/5]: batch 12 → 16  (mem=52%)
Warm-up [3/5]: batch 16 → 20  (mem=52%)
Warm-up [4/5]: batch 20 → 24  (mem=52%)
Warm-up [5/5]: batch 24 → 28  (mem=52%)
```

Durante il warm-up il log mostra solo questi messaggi — il progress percentuale parte dopo.

### 2. Steady-state
Dopo il warm-up, il sistema monitora la VRAM ad ogni batch:

| Condizione | Azione |
|------------|--------|
| VRAM > 85% (soglia alta) | batch − 2 |
| VRAM < 60% (soglia bassa) | batch + 1 |
| 60% ≤ VRAM ≤ 85% | nessuna modifica |
| Ogni 10 batch | `torch.cuda.empty_cache()` |

### 3. OOM Recovery
Se si verifica un errore CUDA Out of Memory:

| Situazione | Comportamento |
|------------|---------------|
| 1° o 2° OOM consecutivo | batch dimezzato, warm-up resettato |
| 3° OOM consecutivo | batch → `min_size` (panic fallback) |

Dopo ogni batch completato con successo il contatore OOM consecutivi viene azzerato.

---

## Configurazione

Il pannello si apre dal bottone **🎯** nella barra in alto della finestra principale.

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `initial_size` | 0 (auto) | Batch size di partenza. 0 = auto-detect dalla VRAM |
| `min_size` | 1 | Minimo assoluto (panic fallback) |
| `max_size` | 24 | Tetto massimo consentito |
| `warmup_batches` | 5 | Numero di step nella fase warm-up |
| `high_threshold` | 0.85 | Soglia VRAM per ridurre il batch |
| `low_threshold` | 0.60 | Soglia VRAM per aumentare il batch |

### Auto-detect `initial_size`

Se `initial_size = 0`, il valore viene calcolato automaticamente dalla VRAM disponibile:

| VRAM disponibile | Initial size |
|-----------------|--------------|
| ≥ 24 GB | 16 |
| ≥ 12 GB | 8 |
| ≥ 8 GB | 4 |
| < 8 GB | 2 |
| CPU | 4 |

---

## Statistiche finali

Al termine di ogni traduzione il log mostra un riepilogo:

```
Batch manager stats — batch medio: 21.9 (min=8, max=24), OOM: 0, aggiustamenti: 11, batch totali: 39
```

---

## Risultati reali (RTX 3060 12GB, NLLB Finetuned, 861 sottotitoli)

| Configurazione | Batch medio | VRAM usata | Tempo |
|----------------|-------------|------------|-------|
| Fisso (pre-adaptive) | 12 | ~6.0 GB | 134s |
| Adaptive, max=24, step +2 | 21.9 | ~6.5 GB | 117s |
| Adaptive, max=32, step +4 | 41.1 | ~8.1 GB | 107s |

**−20% di tempo** rispetto al batch size fisso originale, senza nessun OOM.

---

## Integrazione con i Profili di Trascrizione

Ogni profilo definisce un `batch_size_hint` usato come `initial_size` per il transcriber (attivo solo con `BatchedInferencePipeline`):

| Profilo | batch_size_hint |
|---------|----------------|
| Fast | 12 |
| Balanced | 8 |
| Quality | 4 |
| Maximum | 2 |
| Batch | 16 |

---

## Consigli pratici

**GPU con poca VRAM (< 8 GB):** lascia `initial_size = 0` (auto-detect), abbassa `max_size` a 8-12. Il sistema si adatterà automaticamente.

**GPU potente (≥ 12 GB) con VRAM stabile:** aumenta `max_size` e `warmup_batches` per raggiungere il tetto più in fretta. Se la VRAM resta sotto il 60% per tutta la traduzione, puoi alzare ulteriormente il max.

**OOM ricorrenti:** se compaiono OOM anche con batch piccoli, la VRAM è insufficiente per il modello scelto. Passa da Aya-23-8B a NLLB (più leggero), oppure usa Claude API / OpenAI (nessuna GPU locale richiesta).

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
