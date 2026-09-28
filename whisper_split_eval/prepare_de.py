"""
TEDESCO (28/09/2026): copia di prepare_fr.py con WORK=work_de, selection_de.json, lang 'de' e ref_lang (de/it) nel record.

Preparazione dei 6 file INTERI (v4): audio inglese -> Demucs vocals (percorso di
produzione, AudioProcessor.separate_vocals) + sottotitolo professionale incorporato.
Scrive work_full/windows.jsonl (un "finestra" = un file intero, t0 = 0) e
work_full/win/<id>/{raw.wav,vocals.wav,ref.srt}: cosi' run_whisper.py
(--bench-work work_full --out-root work_full_runs --mode raw|off|on) e
analyze_v4.py funzionano come per le finestre.

GPU: come asr_bench prepare, guardia GPU libera e sandbox della config.
Ripresa automatica (salta i file gia' pronti). Uso:
    set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe prepare_full.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR = ROOT / 'asr_eval'
for p in (str(ASR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import asr_bench as AB  # noqa: E402  (importa per primo sandbox)

WORK = HERE / 'work_de'
NO_WINDOW = {'creationflags': 0x08000000} if os.name == 'nt' else {}


def run(cmd, timeout):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                       **NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} fallito: {r.stderr.strip()[-300:]}")


def _ram(tag: str) -> None:
    try:
        import psutil
        vm = psutil.virtual_memory()
        AB.emit(f"  🧠 RAM [{tag}]: processo {psutil.Process().memory_info().rss / 1e9:.2f} GB, "
                f"sistema libera {vm.available / 1e9:.1f} GB")
    except Exception:
        pass


def _clear_vram() -> None:
    """Stessa sequenza di core/pipeline.py Pipeline._clear_vram (riferimenti gia' azzerati)."""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            try:
                torch._C._cuda_clearCublasWorkspaces()
            except Exception:
                pass
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


def _write_windows(sel) -> None:
    recs = []
    for it in sel['items']:
        d = WORK / 'win' / it['id'] / 'done.json'
        if d.exists():
            recs.append(json.loads(d.read_text(encoding='utf-8')))
    ok = [r for r in recs if r.get('status') == 'ok']
    with open(WORK / 'windows.jsonl', 'w', encoding='utf-8') as f:
        for r in ok:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    AB.emit(f"windows.jsonl: {len(ok)} file validi su {len(recs)} preparati")


def main() -> int:
    sel = json.loads((WORK / 'selection_de.json').read_text(encoding='utf-8'))
    only = sys.argv[1] if len(sys.argv) > 1 else None      # un solo file per processo (memoria)
    if only:
        sel['items'] = [i for i in sel['items'] if i['id'] == only]
    todo = [i for i in sel['items'] if not (WORK / 'win' / i['id'] / 'done.json').exists()]
    if not todo:
        AB.emit('nulla da fare')
        _write_windows(json.loads((WORK / 'selection_de.json').read_text(encoding='utf-8')))
        return 0
    AB.require_gpu_free()
    cfg = AB.sandbox.activate(WORK)
    from core.engines.faster_whisper_engine import FasterWhisperEngine
    whisper = FasterWhisperEngine(log_callback=AB.emit)
    whisper.load()   # ctranslate2 inizializza CUDA per primo (STEP 2.5 della pipeline)
    from core.audio_processor import AudioProcessor
    from utils.resource_monitor import release_ram_to_os
    ap = AudioProcessor()
    # Demucs a CHUNK (percorso robusto di produzione: chunk da 5 min, overlap 10 s) per OGNI file oltre i 5 minuti,
    # invece dello standard path (tensore intero in RAM). Stesso codice di AudioProcessor, si sposta solo la soglia
    # dell'istanza. I vocals dei file <= 90 min differiscono minimamente da quelli che la produzione avrebbe scelto.
    ap.STANDARD_PATH_THRESHOLD = ap.FAST_PATH_THRESHOLD
    ap.set_log_callback(AB.emit)
    recs = []
    try:
        for it in sel['items']:
            wd = WORK / 'win' / it['id']
            wd.mkdir(parents=True, exist_ok=True)
            done = wd / 'done.json'
            if done.exists():
                recs.append(json.loads(done.read_text(encoding='utf-8')))
                AB.emit(f"⏭️ {it['id']} gia' pronto")
                continue
            t0 = time.time()
            AB.emit(f"\n🎬 {it['id']} ({it['duration'] / 60:.0f} min)")
            raw, ref = wd / 'raw.wav', wd / 'ref.srt'
            run(['ffmpeg', '-y', '-v', 'error', '-i', it['file'], '-map', f"0:{it['audio_index']}", '-vn',
                 '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', str(raw)], 3600)
            if it['kind'] == 'controllo':
                # controllo negativo di lingua: audio grezzo italiano (senza Demucs), nessun riferimento
                shutil.copy(str(raw), str(wd / 'vocals.wav'))
                import soundfile as sf
                dur = sf.info(str(wd / 'vocals.wav')).duration
                rec = {'win_id': it['id'], 'film': it['id'], 'title': it['title'], 'lang': 'de', 'role': 'test',
                       'group': 'controllo', 't0': 0.0, 't1': round(dur, 3), 'dur': round(dur, 3), 'names': [],
                       'cues': [], 'status': 'ok', 'kind': 'controllo'}
                done.write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')
                recs.append(rec)
                AB.emit(f"  ✅ controllo {it['id']} pronto ({dur / 60:.1f} min, audio grezzo)")
                continue
            run(['ffmpeg', '-y', '-v', 'error', '-i', it['file'], '-map', f"0:{it['sub_index']}", '-c:s', 'srt',
                 str(ref)], 600)
            cues = AB.R.parse_srt(ref)
            if len(cues) < 300:
                AB.emit(f"⛔ {it['id']}: sottotitolo professionale con solo {len(cues)} cue: file NON valido")
                done.write_text(json.dumps({'id': it['id'], 'status': 'excluded', 'reason': f'{len(cues)} cue'}),
                                encoding='utf-8')
                recs.append(json.loads(done.read_text(encoding='utf-8')))
                continue
            AB.emit(f"  ✅ audio {raw.stat().st_size / 1e6:.0f} MB, {len(cues)} cue professionali; Demucs...")
            voc = ap.separate_vocals(raw)
            if not voc or not Path(voc).exists():
                raise RuntimeError(f"Demucs fallito su {it['id']}")
            shutil.move(str(voc), str(wd / 'vocals.wav'))
            _ram('dopo Demucs')
            ap.cleanup_model()                 # come STEP 3 della pipeline: scarica Demucs...
            release_ram_to_os()                # ...e restituisce la RAM all'OS (utils/resource_monitor.py)
            _ram('dopo cleanup Demucs')
            import soundfile as sf
            dur = sf.info(str(wd / 'vocals.wav')).duration
            rec = {'win_id': it['id'], 'film': it['id'], 'title': it['title'], 'lang': 'de', 'role': 'test',
                   'group': 'full', 't0': 0.0, 't1': round(dur, 3), 'dur': round(dur, 3), 'names': [],
                   'cues': cues, 'status': 'ok', 'kind': it['kind'], 'ref_lang': it.get('ref_lang', 'de')}
            done.write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')
            recs.append(rec)
            AB.emit(f"  ✅ {it['id']} pronto in {time.time() - t0:.0f}s (vocals {dur / 60:.1f} min)")
            AB.sandbox.check_real_config()
    finally:
        ap.cleanup_model()
        whisper.unload()
        _clear_vram()                          # come Pipeline._clear_vram, sicuro DOPO l'unload di Whisper
        release_ram_to_os()
        _ram('a fine processo')
    _write_windows(json.loads((WORK / 'selection_de.json').read_text(encoding='utf-8')))
    AB.sandbox.check_real_config()
    return 0


if __name__ == '__main__':
    sys.exit(main())
