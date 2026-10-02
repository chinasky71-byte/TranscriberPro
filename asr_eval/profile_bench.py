# -*- coding: utf-8 -*-
"""Banco profili di trascrizione: tempo reale (min per ora di audio) e deriva
di testo per profilo, su Faster-Whisper e Qwen3-ASR.

Serve a dare valori ATTENDIBILI ai riquadri dei profili (Impostazioni ->
Trascrizione) e a verificare se il profilo cambia davvero il risultato.

Differenze volute rispetto a asr_bench.py (v. advisor 02/10/2026):
  * LUNGO: tutte le finestre vengono concatenate e trascritte in UNA chiamata
    (Whisper: "file unico" come in produzione; Qwen3: tutti i chunk insieme).
    Le finestre da 150 s riempirebbero poco i batch grandi (fast/batch) e
    nasconderebbero proprio la differenza che si vuole misurare.
  * Un processo nuovo per ogni combinazione (fatica adaptive-batch a zero).
  * Batch REALMENTE usato letto dal log (il tetto VRAM/beam puo' abbassare l'hint).
  * Retry di lingua come in produzione (valori letti dalla config reale).
  * Ripetizione di 'maximum' a fine giro: la differenza A/A e' il rumore.
  * Cartella di lavoro SEPARATA (work_profile/): `prepare` riscrive le sha di
    windows.jsonl (Demucs non e' deterministico) e invaliderebbe le ipotesi
    del banco ASR del 24/09 in work/.

Procedura (dalla cartella Transcriber_Pro, Transcriber Pro CHIUSO, >=20 GB RAM liberi):
    set PYTHONIOENCODING=utf-8
    venv\\Scripts\\python.exe asr_eval\\profile_bench.py setup
    venv\\Scripts\\python.exe asr_eval\\asr_bench.py --work asr_eval\\work_profile prepare --allow-blocked
    venv\\Scripts\\python.exe asr_eval\\profile_bench.py all        # ~2 h
    venv\\Scripts\\python.exe asr_eval\\profile_bench.py report

Whisper: 5 profili (workers/beam/batch). Qwen3: solo i profili con batch distinto
(fast=8, quality=4, maximum=2; balanced e batch hanno batch 8 come fast).
Lingua di default: italiano, 4 finestre equidistanti (~10 min) per ciascuno dei 5 film = ~50 min; --lang en per l'inglese.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics as stt
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent
for p in (str(HERE), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sandbox  # noqa: E402  (sempre per primo)

SRC_WORK = HERE / 'work'
MIN_FREE_RAM_GB = 20.0       # regola dell'utente per tutti i banchi
GAP_S = 0.5                  # silenzio fra finestre concatenate
PROFILES = ['fast', 'balanced', 'quality', 'maximum', 'batch']
# (motore, profilo, tag): 'maximum' prima e di nuovo alla fine (rumore A/A)
PLAN: List[Tuple[str, str, str]] = (
    [('whisper', 'maximum', '')] + [('whisper', p, '') for p in ('fast', 'balanced', 'quality', 'batch')]
    + [('whisper', 'maximum', '_rep')]
    + [('qwen3', 'maximum', '')] + [('qwen3', p, '') for p in ('fast', 'quality')]
    + [('qwen3', 'maximum', '_rep')]
)


def _emit(msg: str) -> None:
    print(msg, flush=True)


def _work(args) -> Path:
    return Path(args.work).resolve()


def _real_retry_settings() -> Dict[str, object]:
    """Retry di lingua come in produzione: valori della config reale (default True)."""
    try:
        d = json.loads((Path.home() / '.transcriberpro' / 'config.json').read_text(encoding='utf-8'))
    except Exception:
        d = {}
    return {k: d.get(k, True) for k in ('qwen3_lang_retry_enabled', 'whisper_lang_retry_enabled')} | {
        'qwen3_lang_retry_accept_langs': d.get('qwen3_lang_retry_accept_langs', ['en']),
        'whisper_lang_retry_accept_langs': d.get('whisper_lang_retry_accept_langs', ['en']),
    }


def _check_ram() -> bool:
    import psutil
    free = psutil.virtual_memory().available / 2 ** 30
    if free < MIN_FREE_RAM_GB:
        _emit(f"❌ RAM libera {free:.1f} GB < {MIN_FREE_RAM_GB:.0f} GB (regola dei banchi): libera memoria e rilancia")
        return False
    return True


def cmd_setup(args) -> int:
    """Copia plan.json in work_profile tenendo solo i film della lingua scelta e
    `--windows-per-film` finestre per film, equidistanti (piu' varieta' a parita'
    di audio). Il tempo/deriva non dipendono dalla sincronia col riferimento."""
    work = _work(args)
    work.mkdir(parents=True, exist_ok=True)
    src = SRC_WORK / 'plan.json'
    if not src.exists():
        _emit(f"❌ manca {src}")
        return 2
    plan = json.loads(src.read_text(encoding='utf-8'))
    keep = {}
    for fl, p in plan['film_langs'].items():
        if p['lang'] != args.lang:
            continue
        ws = sorted(p['windows'], key=lambda w: w['win_id'])
        n = max(1, min(args.windows_per_film, len(ws)))
        idx = sorted({round(i * (len(ws) - 1) / max(1, n - 1)) for i in range(n)}) if n > 1 else [len(ws) // 2]
        keep[fl] = {**p, 'windows': [ws[i] for i in idx]}
    plan['film_langs'] = keep
    plan['blocked'] = []
    (work / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding='utf-8')
    tot = sum(w['dur'] for p in keep.values() for w in p['windows']) / 60
    _emit(f"✅ {work}: {len(keep)} film {args.lang}, {sum(len(p['windows']) for p in keep.values())} finestre, ~{tot:.0f} min")
    for fl, p in keep.items():
        _emit(f"   - {fl}: {len(p['windows'])} finestre")
    return 0


def _long_wav(ab, work: Path, wins: List[Dict]):
    """Concatena i vocals.wav in un solo file. Ritorna (path, durata_s, offsets)."""
    import numpy as np
    import soundfile as sf
    out = work / 'profile_bench' / 'long_vocals.wav'
    out.parent.mkdir(parents=True, exist_ok=True)
    offsets, parts, t, sr0 = [], [], 0.0, None
    for w in wins:
        data, sr = sf.read(str(work / 'win' / w['win_id'] / 'vocals.wav'), dtype='float32')
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr0 is None:
            sr0 = sr
        elif sr != sr0:
            raise RuntimeError(f"sample rate diverso in {w['win_id']}: {sr} vs {sr0}")
        offsets.append(t)
        parts += [data, np.zeros(int(GAP_S * sr), dtype='float32')]
        t += len(data) / sr + GAP_S
    sf.write(str(out), np.concatenate(parts), sr0, subtype='FLOAT')
    return out, t, offsets


def cmd_run(args) -> int:
    import asr_bench as ab
    import runners as RN
    work = _work(args)
    ab.require_gpu_free()
    if not _check_ram():
        return 3
    retry = _real_retry_settings()
    cfg = sandbox.activate(work, overrides={'transcription_profile': args.profile, 'transcription_profile_locked': False, **retry})
    wins = sorted(ab.windows_for(work, args.engine, 'vocals', [args.lang]), key=lambda w: w['win_id'])[:args.max_windows]
    if not wins:
        _emit(f"❌ nessuna finestra in {work}/windows.jsonl: eseguire `setup` e `prepare`")
        return 4
    fp = ab.run_fingerprint(args.engine, 'vocals', cfg)
    tag = args.profile + args.tag
    _emit(f"▶️ profile_bench {args.engine} x {tag}: {len(wins)} finestre {args.lang}, retry={retry}")
    long_wav, total_s_audio, offsets = _long_wav(ab, work, wins)
    _emit(f"   audio concatenato: {total_s_audio / 60:.1f} min")
    logcap = RN.LogCapture()
    mon = RN.VramMonitor().start()
    t0 = time.time()
    if args.engine == 'whisper':
        from core.engines.faster_whisper_engine import FasterWhisperEngine
        eng = FasterWhisperEngine(log_callback=logcap)
        chunks = [(str(long_wav), 0.0, float(total_s_audio))]
    else:
        from core.engines.qwen3_asr_engine import Qwen3AsrEngine
        eng = Qwen3AsrEngine(log_callback=logcap)
        chunks = []
        for w, off in zip(wins, offsets):
            chunks += [(p, off + a, off + b) for p, a, b in ab._chunks_of(work, w, fp['chunk_profile'], 'vocals')]
    eng.load()
    if args.engine == 'whisper' and eng.batch_size_for_transcription is None:
        raise RuntimeError("BatchedInferencePipeline non attivo: non e' il percorso di produzione")
    load_s = time.time() - t0
    mon.take_peak()
    try:
        r = RN.transcribe_window(eng, chunks, args.lang, logcap)
    finally:
        peak = mon.take_peak()
        mon.stop()
        try:
            eng.unload()
        except Exception:
            pass
    sandbox.check_real_config()
    batch_used = None
    for line in logcap.lines:
        m = re.search(r'Batch size: adaptive=(\d+), safe_ceiling=(\d+), using=(\d+)', line)
        if m:
            batch_used = {'adaptive': int(m.group(1)), 'safe_ceiling': int(m.group(2)), 'using': int(m.group(3))}
    info = {'engine': args.engine, 'profile': args.profile, 'tag': args.tag, 'lang': args.lang, 'status': r['status'],
            'error': r.get('error'), 'audio_s': round(total_s_audio, 1), 'n_windows': len(wins),
            'elapsed_s': r['elapsed_s'], 'min_per_hour': round(r['elapsed_s'] / 60 / (total_s_audio / 3600), 2),
            'load_s': round(load_s, 1), 'vram_peak_mb': peak, 'vram_baseline_mb': mon.baseline,
            'batch_used': batch_used, 'batch_size_attr': getattr(eng, 'batch_size', None),
            'num_workers': getattr(eng, 'num_workers', None), 'beam_size': getattr(eng, 'beam_size', None),
            'retry_settings': retry, 'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'text': ' '.join(s['text'] for s in r['segments']), 'n_segments': len(r['segments'])}
    out_dir = work / 'profile_bench'
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.engine}__{tag}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    _emit(f"✅ {args.engine} x {tag}: {r['status']} {r['elapsed_s']:.0f}s = {info['min_per_hour']} min/h, "
          f"batch usato={batch_used or info['batch_size_attr']}")
    return 0 if r['status'] != 'failed' else 6


def cmd_all(args) -> int:
    work = _work(args)
    for engine, profile, tag in PLAN:
        out = work / 'profile_bench' / f"{engine}__{profile}{tag}.json"
        if out.exists() and not args.force:
            _emit(f"⏭️  {engine} x {profile}{tag}: gia' misurato (--force per rifare)")
            continue
        cmd = [sys.executable, str(Path(__file__).resolve()), '--work', str(work), 'run', '--engine', engine,
               '--profile', profile, '--tag', tag, '--lang', args.lang, '--max-windows', str(args.max_windows)]
        _emit(f"\n=== {engine} x {profile}{tag} ===")
        rc = subprocess.call(cmd)
        if rc != 0:
            _emit(f"❌ {engine} x {profile}{tag}: uscita {rc}, mi fermo")
            return rc
    return cmd_report(args)


def _tokens(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


def _divergence(ref_text: str, hyp_text: str) -> float:
    import metrics as M
    ref, hyp = _tokens(ref_text), _tokens(hyp_text)
    if not ref:
        return 0.0
    c = M.count_ops(M.align(ref, hyp))
    return (c['S'] + c['D'] + c['I']) / len(ref)


def cmd_report(args) -> int:
    work = _work(args)
    out_dir = work / 'profile_bench'
    lines = ["Banco profili di trascrizione (audio post-Demucs, concatenato in una sola chiamata)",
             "Tempo = solo ASR (esclusi caricamento modello e Demucs). Retry di lingua come in produzione.",
             "Deriva = % di parole diverse rispetto al primo 'maximum' dello stesso motore (NON e' un WER).",
             "Rumore A/A = differenza fra i due 'maximum': scarti minori vanno letti come 'nessuna differenza'.", ""]
    data: Dict[str, dict] = {}
    for f in sorted(out_dir.glob('*__*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        data[f.stem] = d
    for engine in ('whisper', 'qwen3'):
        ref = data.get(f"{engine}__maximum")
        rep = data.get(f"{engine}__maximum_rep")
        lines.append(f"## {engine}")
        if ref and rep:
            aa = abs(rep['min_per_hour'] - ref['min_per_hour']) / ref['min_per_hour'] * 100
            lines.append(f"Rumore A/A tempo: {aa:.1f}%  (maximum {ref['min_per_hour']} vs ripetizione {rep['min_per_hour']} min/h); "
                         f"deriva testo A/A: {100 * _divergence(ref['text'], rep['text']):.2f}%")
        lines.append(f"{'profilo':<14}{'min/h':>8}{'tempo s':>9}{'carico s':>10}{'VRAM MB':>9}{'deriva%':>9}  stato / parametri / batch usato")
        for name, d in sorted(((k, v) for k, v in data.items() if k.startswith(engine + '__')),
                              key=lambda kv: (kv[1]['profile'] != 'maximum', kv[1]['tag'], kv[0])):
            div = 0.0 if name == f"{engine}__maximum" else (
                100 * _divergence(ref['text'], d['text']) if ref else float('nan'))
            vr = (d['vram_peak_mb'] - d['vram_baseline_mb']) if d.get('vram_peak_mb') and d.get('vram_baseline_mb') else float('nan')
            par = f"w={d.get('num_workers')} beam={d.get('beam_size')} attr={d.get('batch_size_attr')} usato={d.get('batch_used')}"
            lines.append(f"{d['profile'] + d['tag']:<14}{d['min_per_hour']:>8.1f}{d['elapsed_s']:>9.0f}{d['load_s']:>10.1f}"
                         f"{vr:>9.0f}{div:>9.2f}  {d['status']} {par}")
        lines.append("")
    text = '\n'.join(lines)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'report.txt').write_text(text, encoding='utf-8')
    _emit(text)
    return 0


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--work', type=Path, default=HERE / 'work_profile', help="cartella dati separata (default work_profile)")
    sub = p.add_subparsers(dest='cmd', required=True)
    ss = sub.add_parser('setup', help="crea work_profile: plan.json ridotto (finestre equidistanti per film)")
    ss.add_argument('--lang', default='it', choices=['it', 'en'])
    ss.add_argument('--windows-per-film', type=int, default=4)
    sr = sub.add_parser('run', help="un motore x un profilo (processo nuovo, GPU)")
    sr.add_argument('--engine', required=True, choices=['whisper', 'qwen3'])
    sr.add_argument('--profile', required=True, choices=PROFILES)
    sr.add_argument('--tag', default='', help="suffisso del file (es. _rep per la ripetizione A/A)")
    sr.add_argument('--lang', default='it', choices=['it', 'en'])
    sr.add_argument('--max-windows', type=int, default=20)
    sa = sub.add_parser('all', help="tutte le combinazioni in sequenza, poi report")
    sa.add_argument('--lang', default='it', choices=['it', 'en'])
    sa.add_argument('--max-windows', type=int, default=20)
    sa.add_argument('--force', action='store_true')
    sub.add_parser('report', help="tabella riassuntiva")
    args = p.parse_args(argv)
    return {'setup': cmd_setup, 'run': cmd_run, 'all': cmd_all, 'report': cmd_report}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
