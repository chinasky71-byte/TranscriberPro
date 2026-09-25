"""
Esecuzione GPU di faster-whisper sulle finestre del banco asr_eval, con lo
STESSO modo di chiamare il motore di asr_bench `run` (sandbox della config,
load() prima di ogni CUDA, transcribe_chunks([(vocals, 0.0, dur)], '', 'en'),
engine.last_segments) e lo stesso audio vocals gia' preparato (sola lettura).

Modi:
  raw  -> `_split_segment_by_words` sostituito dall'identita': si salvano i
          segmenti NATIVI (pre-split, NON arrotondati) e i chunk VAD reali
          (collect_chunks avvolta: confini esatti per costruzione). Lo split
          e' una funzione pura dei segmenti: tutte le varianti si riapplicano
          poi offline (analyze.py).
  on   -> motore di produzione con l'opzione whisper_split_sentence_aware=True
          (via overrides del sandbox, mai Config.set): conferma end-to-end
          dell'aggancio. Salva i segmenti come il banco (arrotondati).
  off  -> motore di produzione con l'opzione spenta (controllo negativo).

Output: whisper_split_eval/work/<modo>/<win_id>.json. Un solo processo, un
solo modello; unload a fine script.

Uso:  set PYTHONIOENCODING=utf-8
      ..\\venv\\Scripts\\python.exe run_whisper.py --mode raw [--role test] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR = ROOT / 'asr_eval'
for p in (str(ASR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sandbox  # noqa: E402  (PER PRIMO: redirige la config)

WORK = HERE / 'work'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['raw', 'on', 'off'], required=True)
    ap.add_argument('--role', default=None, help='test | dev | eval (default: tutte le finestre EN)')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--lang', default='en', help="lingua delle finestre da eseguire (default: en)")
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--bench-work', type=Path, default=ASR / 'work',
                    help='cartella del banco con windows.jsonl e win/ (sola lettura)')
    ap.add_argument('--out-root', type=Path, default=None, help='cartella di output (default work/)')
    args = ap.parse_args()
    global WORK
    if args.out_root is not None:
        WORK = args.out_root.resolve()
    bench_work = args.bench_work.resolve()

    import runners as RN
    reasons = RN.gpu_busy_reasons()
    if reasons:
        print('GPU non libera: ' + '; '.join(reasons))
        return 3

    overrides = {'whisper_split_sentence_aware': args.mode == 'on'}
    cfg = sandbox.activate(WORK, overrides=overrides)
    print('opzione whisper_split_sentence_aware =', cfg.get('whisper_split_sentence_aware'))

    wins = [json.loads(l) for l in (bench_work / 'windows.jsonl').read_text(encoding='utf-8').splitlines()
            if l.strip()]
    if args.role == 'eval':
        sys.path.insert(0, str(HERE))
        import decision_rule as DRULE
        wins = [w for w in wins if DRULE.is_eval_window(w)]
    else:
        wins = [w for w in wins if w['lang'] == args.lang and (args.role is None or w['role'] == args.role)]
    if args.limit:
        wins = wins[:args.limit]
    out_dir = WORK / args.mode
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [w for w in wins if args.force or not (out_dir / f"{w['win_id']}.json").exists()]
    print(f"finestre {len(wins)}, da fare {len(todo)}")
    if not todo:
        return 0

    import faster_whisper.transcribe as FT
    vad_log = []
    _orig_collect = FT.collect_chunks

    def _collect(audio, chunks, *a, **k):
        audio_chunks, meta = _orig_collect(audio, chunks, *a, **k)
        sr = 16000
        vad_log.append({
            'speech': [[c['start'] / sr, c['end'] / sr] for c in chunks],
            'chunks': [{'start': m['segments'][0]['start'] / sr, 'end': m['segments'][-1]['end'] / sr,
                        'speech': [[s['start'] / sr, s['end'] / sr] for s in m['segments']]}
                       for m in meta if m.get('segments')],
        })
        return audio_chunks, meta
    FT.collect_chunks = _collect

    from core.engines.faster_whisper_engine import FasterWhisperEngine
    if args.mode == 'raw':
        FasterWhisperEngine._split_segment_by_words = lambda self, seg, *a, **k: [dict(seg)]

    logcap = RN.LogCapture()
    eng = FasterWhisperEngine(log_callback=logcap)
    eng.load()
    if eng.batch_size_for_transcription is None:
        raise RuntimeError("BatchedInferencePipeline non attivo: non e' il percorso di produzione")
    t_all = time.time()
    try:
        for k, w in enumerate(todo, 1):
            wav = bench_work / 'win' / w['win_id'] / 'vocals.wav'
            vad_log.clear()
            eng._last_segments = []
            t0 = time.time()
            ok, lang = eng.transcribe_chunks([(str(wav), 0.0, float(w['dur']))], '', w['lang'])
            segs = list(eng.last_segments or [])
            rec = {'win_id': w['win_id'], 'mode': args.mode, 'lang': lang, 'elapsed_s': round(time.time() - t0, 3),
                   'errors': [l for l in logcap.lines if 'Errore' in l]}
            if args.mode == 'raw':
                rec['segments'] = [{'start': float(s['start']), 'end': float(s['end']), 'text': s['text'],
                                    'words': [{'start': float(x['start']), 'end': float(x['end']),
                                               'word': x['word']} for x in s.get('words') or []]}
                                   for s in segs]
                rec['vad'] = vad_log[-1] if vad_log else None
            else:
                rec['segments'] = RN.clean_segments(segs)
            RN.write_json_atomic(out_dir / f"{w['win_id']}.json", rec)
            logcap.lines.clear()
            print(f"  [{k}/{len(todo)}] {w['win_id']}: {len(segs)} seg {rec['elapsed_s']:.1f}s", flush=True)
            if k % 10 == 0:
                sandbox.check_real_config()
    finally:
        eng.unload()
        FT.collect_chunks = _orig_collect
    sandbox.check_real_config()
    print(f"fatto in {time.time() - t_all:.0f}s; Config.set chiamate: {sandbox.set_calls()}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
