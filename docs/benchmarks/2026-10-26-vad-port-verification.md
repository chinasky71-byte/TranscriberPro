# Own VAD instead of Whisper's: verification (2026-10-26)

Before removing Whisper, the one dependency that was not about transcription had to
be proven equivalent: the subtitle synchroniser used `faster_whisper.vad` to find
speech intervals. `core/vad.py` now drives the same Silero v6 model through
`onnxruntime` (vendored weights, MIT), and `core/subtitle_synchronizer.py` uses it.

Three checks on a 10-minute Italian clip (audio Italian, reference subtitle from the
file's own Italian track).

## 1. Same intervals as before

Same audio, same thresholds (0.5 / 250 ms / 300 ms / 100 ms pad), old
implementation versus new:

| | Segments | Speech detected | Runtime |
|---|---|---|---|
| `faster_whisper.vad` (old) | 154 | 420.0 s | 0.52 s |
| `core/vad.py` (new) | 166 | 411.4 s | 0.76 s |

- **Intersection: 411.4 s, 98.0% of the detected speech.**
- **Median difference between segment starts: 0.000 s.**
- The new one splits a few boundaries slightly differently and reports 2% less
  speech; both run in under a second on ten minutes of audio.

## 2. The synchroniser still recovers a desync

Clip re-muxed **without subtitle streams** (`-map 0:v -map 0:a`), so the anchor can
only come from the audio, and the reference SRT shifted by **+2.5 s** to simulate a
release whose timing is off. Run through `core.sync_cli`:

```
No non-Italian embedded subtitle found — using the audio speech as reference.
VAD: 168 speech intervals.
Global alignment: scale 1.00010, offset -2.35 s; segments with different offset: 1;
mean speech coverage 87% (by chance: 70%); lines with low coverage: 2/214.
```

| | First cue | Last cue | Offset vs truth (median / max) | Text |
|---|---|---|---|---|
| input, shifted | 00:00:05,795 | 00:10:03,183 | +2.500 s (by construction) | — |
| output, synced | 00:00:03,446 | 00:10:00,893 | **+0.183 s / 0.21 s** | 214 cues, **WER 0.00%** |

The 2.5 s error is reduced to two tenths of a second across the whole clip, and the
text is untouched: only timings move.

## 3. Transcription unchanged

The qwen3 path does not use the VAD at all, but the check costs three minutes and
guards against surprises elsewhere in the pipeline:

| Metric | Baseline | After the VAD port |
|---|---|---|
| WER | 11.79% | 11.87% |
| CER | 6.10% | 6.18% |
| chrF | 94.50 | 94.35 |
| Drift median | 0.60 s | 0.66 s |
| Wall time | 134.4 s | 134.7 s |

Everything inside the run-to-run noise measured on this clip (±0.5 WER points,
bfloat16 generation is not bit-exact).

## Conclusion

The port is equivalent, the synchroniser still does its job and transcription is
unchanged: nothing blocks removing `faster-whisper`, `ctranslate2` and `whisperx`
from the project.
