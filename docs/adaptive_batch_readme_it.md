# Batch Size nella Traduzione - Transcriber Pro

## Panoramica

Durante la traduzione con i motori locali (NLLB e Aya), i sottotitoli vengono processati in **batch** — gruppi di righe inviati al modello in una singola operazione. Questo aumenta il throughput rispetto a tradurre un sottotitolo alla volta.

> **Nota:** Il batch size riguarda esclusivamente la **traduzione** (NLLB, Aya).
> La trascrizione (Faster-Whisper) è controllata da `beam_size` e `num_workers`, configurabili tramite i Profili di Trascrizione.

---

## Valori di Default

| Motore | Batch Size default | Min | Max |
|--------|--------------------|-----|-----|
| NLLB-200 | 12 | 1 | 24 |
| NLLB Finetuned | 12 | 1 | 24 |
| Aya-23-8B | 8 | 1 | 10 |

---

## Gestione Out of Memory (OOM)

Se durante la traduzione si verifica un errore **CUDA Out of Memory**, il sistema reagisce automaticamente:

1. Il batch size viene **dimezzato**
2. La memoria GPU viene liberata (`torch.cuda.empty_cache()`)
3. Il batch viene ritentato con il nuovo valore ridotto
4. Questo processo si ripete fino a 3 volte per batch
5. Se dopo 3 tentativi l'errore persiste, il batch viene saltato con log di errore

**Esempio:**

```
Traduzione batch [12 sottotitoli]... → CUDA OOM
Riduzione batch: 12 → 6, retry...
Traduzione batch [6 sottotitoli]... → OK
```

Il batch size ridotto rimane per tutta la sessione di traduzione corrente.

---

## Profili di Trascrizione

I profili non controllano il batch size della traduzione, ma il comportamento di **Faster-Whisper**:

| Profilo | Modello | beam_size | VAD |
|---------|---------|-----------|-----|
| Fast | small | 1 | Sì |
| Balanced | medium | 3 | Sì |
| Quality | large-v3 | 5 | Sì |
| Maximum | large-v3 | 10 | No |
| Batch | medium | 3 | Sì |

Selezionabili in **Settings → Transcription Profile**.

---

## Consigli Pratici

**GPU con poca VRAM (<8 GB):**
Il sistema ridurrà automaticamente il batch size al primo OOM. Non è necessaria nessuna configurazione manuale.

**OOM ricorrente:**
Se il batch continua a ridursi ad ogni sessione, probabilmente la VRAM è insufficiente per il modello scelto:
- Passa da Aya-23-8B a NLLB (più leggero)
- Oppure usa Claude API / OpenAI (non usano GPU locale)
- Chiudi altre applicazioni che occupano VRAM prima di avviare la traduzione

**GPU potente (≥12 GB VRAM):**
Il batch size di default (12 per NLLB, 8 per Aya) è già bilanciato per GPU mid-range. Su GPU con molta VRAM libera, il batch size fisso non satura la GPU al 100% — la maggior parte del tempo di traduzione è speso nel caricamento del modello e nel trasferimento dati, non nel calcolo.

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
