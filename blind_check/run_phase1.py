"""
Passo 2 — TRASCRIZIONE con la pipeline reale (GPU), UNA volta per file.

Esegue core.pipeline.ProcessingPipeline.process() su ogni estratto con il
motore assegnato (whisper / qwen3) e la config reale in sandbox (asr_eval/
sandbox.py: la config vera non viene mai scritta), ma con un traduttore FINTO
che si limita a catturare l'SRT che la pipeline darebbe al traduttore
(work/src/<id>.src.srt: dopo estrazione audio, Demucs, trascrizione,
diarizzazione, formattazione e pulizia, come in produzione). Cosi' i due bracci
del confronto partono dallo STESSO sorgente.

Ripresa automatica (salta gli estratti gia' catturati). Rifiuta di partire se
la GPU e' occupata (ASR_EVAL_ALLOW_GUI=1 permette l'app aperta ma inattiva).

Uso: set PYTHONIOENCODING=utf-8
     venv\\Scripts\\python.exe blind_check\\run_phase1.py [--limit N]
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

import common as C

ENGINE_MODE = {'whisper': 'faster-whisper', 'qwen3': 'qwen3'}


class CaptureTranslator:
    """Traduttore finto: cattura l'SRT sorgente e restituisce True."""
    model = object()

    def __init__(self, capture: Path):
        self.capture = capture

    def set_log_callback(self, cb):
        pass

    def translate_file(self, input_path, output_path, src_lang=None, tgt_lang=None, context=None):
        shutil.copyfile(input_path, self.capture)
        shutil.copyfile(input_path, output_path)
        return True

    def cleanup(self):
        pass

    def _polish(self, texts):
        return texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    sel = C.read_json(C.WORK / 'selection.json')
    if not sel or not all(it.get('excerpt') for it in sel['items']):
        sys.exit("selection.json mancante o senza estratti: lancia prima select_files.py")

    import sandbox
    import asr_bench as AB
    AB.require_gpu_free()
    (C.WORK / 'src').mkdir(parents=True, exist_ok=True)
    sandbox.activate(C.WORK / 'sandbox_p1')
    from utils.config import get_config
    cfg = get_config()
    cfg.settings.update({'translation_recompose_sentences': False, 'gender_correction_enabled': False,
                         'translation_model': 'nllb_finetuned'})
    import core.pipeline as P

    todo = [it for it in sel['items'] if not (C.WORK / 'src' / f"{it['id']}.src.srt").exists()]
    if a.limit:
        todo = todo[:a.limit]
    print(f"da trascrivere: {len(todo)} file su {len(sel['items'])}", flush=True)
    rc = 0
    for it in todo:
        cap = C.WORK / 'src' / f"{it['id']}.src.srt"
        cfg.settings['transcription_engine_mode'] = ENGINE_MODE[it['engine']]
        P.get_translator = lambda *args, _cap=cap, **kw: CaptureTranslator(_cap)
        t0 = time.time()
        print(f"\n=== {it['id']} | motore {it['engine']} ===", flush=True)
        pipe = P.ProcessingPipeline(it['excerpt'])
        pipe.set_log_callback(lambda m: print(str(m).encode('ascii', 'replace').decode()[:180], flush=True))
        try:
            ok = pipe.process(target_language='ita')
        except Exception as e:
            ok = False
            print(f"ERRORE: {type(e).__name__}: {e}", flush=True)
        try:
            pipe.cleanup()
        except Exception:
            pass
        final = Path(it['excerpt']).with_suffix('.it.srt')       # copia identita' scritta dallo STEP 7
        for junk in (final, Path(it['excerpt']).with_suffix('.en.srt')):
            try:
                junk.unlink()
            except OSError:
                pass
        if cap.exists():
            print(f"OK  {it['id']}: SRT sorgente catturato in {time.time() - t0:.0f} s", flush=True)
        else:
            print(f"KO  {it['id']}: nessun SRT catturato (process() -> {ok})", flush=True)
            rc = 1
    sandbox.check_real_config()
    return rc


if __name__ == '__main__':
    sys.exit(main())
