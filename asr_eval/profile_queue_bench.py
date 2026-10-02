# -*- coding: utf-8 -*-
"""Banco CODA: il vantaggio di un profilo regge su una coda lunga di file?

Replica la produzione: ogni file gira in un PROCESSO NUOVO (come pipeline_cli) e
riceve `files_processed = i` (n. di file gia' elaborati nella coda), che il gestore
adattivo usa per la penalita' "fatigue" (>5, >10, >20 file: tetto batch ridotto).
Ogni "file" = 5 finestre consecutive (~12 min di audio) prese a rotazione dal
work_profile gia' preparato da profile_bench.py. Giro intercalato: per ogni file
si misurano tutti i profili di seguito (la deriva termica non favorisce nessuno).

NON modifica profile_bench.py (che puo' essere in esecuzione): lo importa soltanto.
Va lanciato SOLO a banco principale finito (la GPU deve essere libera).

    set PYTHONIOENCODING=utf-8
    venv\\Scripts\\python.exe asr_eval\\profile_queue_bench.py queue      # ~1 h
    venv\\Scripts\\python.exe asr_eval\\profile_queue_bench.py report

Opzioni utili: --profiles maximum,balanced,batch,fast  --files 12  --windows-per-file 5
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent
for p in (str(HERE), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sandbox  # noqa: E402  (sempre per primo)
import profile_bench as pb  # noqa: E402

DEFAULT_PROFILES = ['maximum', 'balanced', 'batch']
DEFAULT_FILES = 12            # attraversa le soglie di fatigue a 5 e 10 file
WINDOWS_PER_FILE = 5


def _emit(msg: str) -> None:
    print(msg, flush=True)


def _qdir(work: Path) -> Path:
    return work / 'profile_bench' / 'queue'


def cmd_run(args) -> int:
    import asr_bench as ab
    import runners as RN
    work = Path(args.work).resolve()
    ab.require_gpu_free()
    if not pb._check_ram():
        return 3
    retry = pb._real_retry_settings()
    cfg = sandbox.activate(work, overrides={'transcription_profile': args.profile, 'transcription_profile_locked': False, **retry})
    allw = sorted(ab.windows_for(work, 'whisper', 'vocals', [args.lang]), key=lambda w: w['win_id'])
    if not allw:
        _emit("❌ nessuna finestra: eseguire prima setup/prepare del banco profili")
        return 4
    n = len(allw)
    start = (args.index * args.windows_per_file) % n
    wins = [allw[(start + k) % n] for k in range(min(args.windows_per_file, n))]
    long_wav, total_s, _ = pb._long_wav(ab, work, wins)
    _emit(f"▶️ coda: file #{args.index} (files_processed={args.index}) x {args.profile}: "
          f"{len(wins)} finestre, {total_s / 60:.1f} min")
    logcap = RN.LogCapture()
    mon = RN.VramMonitor().start()
    t0 = time.time()
    from core.engines.faster_whisper_engine import FasterWhisperEngine
    eng = FasterWhisperEngine(log_callback=logcap)
    eng.load()
    if eng.batch_size_for_transcription is None:
        raise RuntimeError("BatchedInferencePipeline non attivo: non e' il percorso di produzione")
    eng.set_files_processed(args.index)       # come pipeline.py:578-579
    load_s = time.time() - t0
    mon.take_peak()
    try:
        r = RN.transcribe_window(eng, [(str(long_wav), 0.0, float(total_s))], args.lang, logcap)
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
    info = {'profile': args.profile, 'index': args.index, 'files_processed': args.index, 'status': r['status'],
            'audio_s': round(total_s, 1), 'elapsed_s': r['elapsed_s'],
            'min_per_hour': round(r['elapsed_s'] / 60 / (total_s / 3600), 2), 'load_s': round(load_s, 1),
            'vram_peak_mb': peak, 'vram_baseline_mb': mon.baseline, 'batch_used': batch_used,
            'n_segments': len(r['segments']), 'when': time.strftime('%Y-%m-%dT%H:%M:%S')}
    d = _qdir(work)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"whisper__{args.profile}__f{args.index:02d}.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    _emit(f"✅ #{args.index} {args.profile}: {r['status']} {r['elapsed_s']:.0f}s = {info['min_per_hour']} min/h, batch={batch_used}")
    return 0 if r['status'] != 'failed' else 6


def cmd_queue(args) -> int:
    work = Path(args.work).resolve()
    profiles = [p.strip() for p in args.profiles.split(',') if p.strip()]
    for i in range(args.files):
        for prof in profiles:
            out = _qdir(work) / f"whisper__{prof}__f{i:02d}.json"
            if out.exists() and not args.force:
                _emit(f"⏭️  #{i} {prof}: gia' misurato")
                continue
            cmd = [sys.executable, str(Path(__file__).resolve()), '--work', str(work), 'run', '--profile', prof,
                   '--index', str(i), '--lang', args.lang, '--windows-per-file', str(args.windows_per_file)]
            rc = subprocess.call(cmd)
            if rc != 0:
                _emit(f"❌ #{i} {prof}: uscita {rc}, mi fermo")
                return rc
    return cmd_report(args)


def cmd_report(args) -> int:
    work = Path(args.work).resolve()
    rows: Dict[tuple, dict] = {}
    for f in sorted(_qdir(work).glob('whisper__*__f*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        rows[(d['profile'], d['index'])] = d
    profiles = sorted({k[0] for k in rows}, key=lambda p: (p != 'maximum', p))
    idx = sorted({k[1] for k in rows})
    L = ["Banco coda (Whisper, un processo nuovo per file, files_processed = indice del file)",
         "Per ogni file e profilo: min/h di ASR e batch realmente usato (tetto di sicurezza fra parentesi).", ""]
    L.append(f"{'file':>5}" + ''.join(f"{p:>26}" for p in profiles))
    for i in idx:
        cells = []
        for p in profiles:
            d = rows.get((p, i))
            if not d:
                cells.append(f"{'-':>26}")
                continue
            b = d.get('batch_used') or {}
            cells.append(f"{d['min_per_hour']:>10.2f} b={b.get('using', '?')}({b.get('safe_ceiling', '?')})".rjust(26))
        L.append(f"{i:>5}" + ''.join(cells))
    L.append("")
    L.append("Totale (solo file misurati da tutti i profili):")
    common = [i for i in idx if all((p, i) in rows for p in profiles)]
    base = None
    for p in profiles:
        tot = sum(rows[(p, i)]['elapsed_s'] for i in common)
        if base is None:
            base = tot
        diff = f"{(tot - base) / base * 100:+.1f}% vs {profiles[0]}" if base else ''
        L.append(f"  {p:<10} {tot / 60:7.1f} min su {len(common)} file   {diff}")
    text = '\n'.join(L)
    _qdir(work).mkdir(parents=True, exist_ok=True)
    (_qdir(work) / 'report_queue.txt').write_text(text, encoding='utf-8')
    _emit(text)
    return 0


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--work', type=Path, default=HERE / 'work_profile')
    sub = p.add_subparsers(dest='cmd', required=True)
    sr = sub.add_parser('run', help="un file della coda (processo nuovo)")
    sr.add_argument('--profile', required=True, choices=pb.PROFILES)
    sr.add_argument('--index', type=int, required=True)
    sr.add_argument('--lang', default='it', choices=['it', 'en'])
    sr.add_argument('--windows-per-file', type=int, default=WINDOWS_PER_FILE)
    sq = sub.add_parser('queue', help="intera coda, profili intercalati, poi report")
    sq.add_argument('--profiles', default=','.join(DEFAULT_PROFILES))
    sq.add_argument('--files', type=int, default=DEFAULT_FILES)
    sq.add_argument('--lang', default='it', choices=['it', 'en'])
    sq.add_argument('--windows-per-file', type=int, default=WINDOWS_PER_FILE)
    sq.add_argument('--force', action='store_true')
    sub.add_parser('report', help="tabella riassuntiva")
    args = p.parse_args(argv)
    return {'run': cmd_run, 'queue': cmd_queue, 'report': cmd_report}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
