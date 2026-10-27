# Silero VAD (vendored)

Voice activity detection model, used by `core/vad.py` to find speech intervals
(the subtitle synchroniser anchors existing subtitles to them).

## Origin
- Upstream: https://github.com/snakers4/silero-vad (model `silero_vad_v6.onnx`)
- Copied from the `faster_whisper` package (same file, unmodified) while Whisper
  was still a dependency, so the model stays available once Whisper is removed.
- Licence: **MIT** (Silero VAD). The file is redistributed unmodified.

## Why vendored
Two megabytes of weights versus: a Python package we no longer use, a runtime
download, or an extra LLM. `onnxruntime` is already a project dependency, so the
inference needs nothing new.
