# Adaptive Batch Size — Transcriber Pro

## Overview

When translating with local engines (NLLB, NLLB Finetuned, Aya), subtitles are processed in **batches** — groups of lines sent to the model in a single GPU operation. A larger batch means fewer calls to `model.generate()` and therefore higher throughput.

The **Adaptive Batch Size** system manages this value dynamically: it starts from an initial value, increases it progressively during a warm-up phase, then monitors and adjusts it based on actual VRAM usage throughout the translation.

> **Note:** Batch size applies exclusively to **translation** (NLLB, Aya).
> For transcription (Faster-Whisper), these values are used only when `BatchedInferencePipeline`
> is available (faster-whisper ≥ 1.1.0).

---

## How It Works

### 1. Warm-up
During the first N iterations (default: 5), the system increases the batch by **+4 per step** as long as VRAM stays below the high threshold:

```
Warm-up [1/5]: batch  8 → 12  (mem=51%)
Warm-up [2/5]: batch 12 → 16  (mem=52%)
Warm-up [3/5]: batch 16 → 20  (mem=52%)
Warm-up [4/5]: batch 20 → 24  (mem=52%)
Warm-up [5/5]: batch 24 → 28  (mem=52%)
```

During warm-up, the log shows only these messages — percentage progress starts after warm-up completes.

### 2. Steady-state
After warm-up, VRAM is monitored on every batch:

| Condition | Action |
|-----------|--------|
| VRAM > 85% (high threshold) | batch − 2 |
| VRAM < 60% (low threshold) | batch + 1 |
| 60% ≤ VRAM ≤ 85% | no change |
| Every 10 batches | `torch.cuda.empty_cache()` |

### 3. OOM Recovery
If a CUDA Out of Memory error occurs:

| Situation | Behaviour |
|-----------|-----------|
| 1st or 2nd consecutive OOM | batch halved, warm-up reset |
| 3rd consecutive OOM | batch → `min_size` (panic fallback) |

After each successful batch the consecutive OOM counter is reset.

---

## Configuration

The settings panel is accessible via the **🎯** button in the main window header.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_size` | 0 (auto) | Starting batch size. 0 = auto-detect from VRAM |
| `min_size` | 1 | Absolute minimum (panic fallback) |
| `max_size` | 24 | Maximum allowed ceiling |
| `warmup_batches` | 5 | Number of steps in the warm-up phase |
| `high_threshold` | 0.85 | VRAM threshold to reduce batch |
| `low_threshold` | 0.60 | VRAM threshold to increase batch |

### Auto-detect `initial_size`

When `initial_size = 0`, the value is derived automatically from available VRAM:

| Available VRAM | Initial size |
|---------------|--------------|
| ≥ 24 GB | 16 |
| ≥ 12 GB | 8 |
| ≥ 8 GB | 4 |
| < 8 GB | 2 |
| CPU | 4 |

---

## End-of-session Summary

At the end of each translation the log prints a summary:

```
Batch manager stats — batch medio: 21.9 (min=8, max=24), OOM: 0, aggiustamenti: 11, batch totali: 39
```

---

## Real-world Results (RTX 3060 12GB, NLLB Finetuned, 861 subtitles)

| Configuration | Avg batch | VRAM used | Time |
|---------------|-----------|-----------|------|
| Fixed (pre-adaptive) | 12 | ~6.0 GB | 134s |
| Adaptive, max=24, step +2 | 21.9 | ~6.5 GB | 117s |
| Adaptive, max=32, step +4 | 41.1 | ~8.1 GB | 107s |

**−20% translation time** compared to the original fixed batch size, with zero OOM errors.

---

## Integration with Transcription Profiles

Each profile defines a `batch_size_hint` used as `initial_size` for the transcriber (active only with `BatchedInferencePipeline`):

| Profile | batch_size_hint |
|---------|----------------|
| Fast | 12 |
| Balanced | 8 |
| Quality | 4 |
| Maximum | 2 |
| Batch | 16 |

---

## Practical Tips

**Low VRAM GPU (< 8 GB):** leave `initial_size = 0` (auto-detect) and lower `max_size` to 8–12. The system will adapt automatically.

**Powerful GPU (≥ 12 GB) with stable VRAM:** increase `max_size` and `warmup_batches` to reach the ceiling faster. If VRAM stays below 60% throughout the translation, you can raise the max further.

**Recurring OOM errors:** if OOM appears even with small batches, VRAM is insufficient for the selected model. Switch from Aya-23-8B to NLLB (lighter), or use Claude API / OpenAI (no local GPU required).

---

*Transcriber Pro — Python 3.11 / CUDA 12.6 / PyTorch 2.8*
