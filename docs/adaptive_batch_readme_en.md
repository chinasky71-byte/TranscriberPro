# Batch Size in Translation - Transcriber Pro

## Overview

When translating with local engines (NLLB and Aya), subtitles are processed in **batches** — groups of lines sent to the model in a single operation. This increases throughput compared to translating one subtitle at a time.

> **Note:** Batch size applies exclusively to **translation** (NLLB, Aya).
> Transcription (Faster-Whisper) is controlled by `beam_size` and `num_workers`, configurable via Transcription Profiles.

---

## Default Values

| Engine | Default Batch Size | Min | Max |
|--------|-------------------|-----|-----|
| NLLB-200 | 12 | 1 | 24 |
| NLLB Finetuned | 12 | 1 | 24 |
| Aya-23-8B | 8 | 1 | 10 |

---

## Out of Memory (OOM) Handling

If a **CUDA Out of Memory** error occurs during translation, the system reacts automatically:

1. Batch size is **halved**
2. GPU memory is freed (`torch.cuda.empty_cache()`)
3. The batch is retried with the reduced value
4. This repeats up to 3 times per batch
5. If the error persists after 3 attempts, the batch is skipped with an error log

**Example:**

```
Translating batch [12 subtitles]... → CUDA OOM
Reducing batch: 12 → 6, retrying...
Translating batch [6 subtitles]... → OK
```

The reduced batch size persists for the rest of the current translation session.

---

## Transcription Profiles

Profiles do not control translation batch size — they control **Faster-Whisper** behaviour:

| Profile | Model | beam_size | VAD |
|---------|-------|-----------|-----|
| Fast | small | 1 | Yes |
| Balanced | medium | 3 | Yes |
| Quality | large-v3 | 5 | Yes |
| Maximum | large-v3 | 10 | No |
| Batch | medium | 3 | Yes |

Selectable under **Settings → Transcription Profile**.

---

## Practical Tips

**GPU with limited VRAM (<8 GB):**
The system will automatically reduce the batch size on the first OOM. No manual configuration required.

**Recurring OOM errors:**
If the batch size keeps shrinking each session, your VRAM is likely insufficient for the selected model:
- Switch from Aya-23-8B to NLLB (lighter)
- Or use Claude API / OpenAI (no local GPU usage)
- Close other VRAM-heavy applications before starting translation

**Powerful GPU (≥12 GB VRAM):**
The default batch sizes (12 for NLLB, 8 for Aya) are tuned for mid-range GPUs. On cards with plenty of free VRAM, the fixed batch size won't saturate the GPU — most translation time is spent on model loading and data transfer, not computation.

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
