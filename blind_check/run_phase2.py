"""
Passo 3 — DOPPIA TRADUZIONE (GPU) dello stesso SRT sorgente con NLLB-FT reale.

Per ogni work/src/<id>.src.srt:
  base         = translator.translate_file(...)                (opzione spenta)
  ricomposta   = core.sentence_recompose.translate_srt_with_recompose(...)
                 (opzione accesa; stessa logica del ramo di core/pipeline.py)
L'ordine base/ricomposta e' casuale (seme fisso per file) per non introdurre un
effetto d'ordine (warm-up, batch adattivo). Glossario vuoto e contesto None in
entrambi i bracci. Uscite: work/tr/<id>/base.srt, ricomposta.srt, res.json.
Ripresa automatica. Rifiuta di partire se la GPU e' occupata.

Uso: set PYTHONIOENCODING=utf-8
     venv\\Scripts\\python.exe blind_check\\run_phase2.py
"""
import random
import sys
import time

import common as C
import decision_rule as R


def main():
    sel = C.read_json(C.WORK / 'selection.json')
    items = [it for it in (sel or {}).get('items', []) if (C.WORK / 'src' / f"{it['id']}.src.srt").exists()]
    if not items:
        sys.exit("nessun SRT sorgente in work/src: lancia prima run_phase1.py")

    import sandbox
    import asr_bench as AB
    AB.require_gpu_free()
    sandbox.activate(C.WORK / 'sandbox_p2')
    from core.translator import get_translator
    from core.sentence_recompose import translate_srt_with_recompose

    def new_translator():
        t = get_translator(model_type='nllb_finetuned', context=None, glossary={})
        if type(t).__name__ != 'NLLBFineTunedTranslator':
            raise SystemExit(f"ripiego silenzioso della factory: {type(t).__name__}")
        t.set_log_callback(lambda m: None)
        return t

    state = {'t': new_translator()}

    def fn(inp, out):
        if getattr(state['t'], 'model', True) is None:      # scaricato dal serbatoio L3
            try:
                state['t'].cleanup()
            except Exception:
                pass
            state['t'] = new_translator()
        return state['t'].translate_file(input_path=str(inp), output_path=str(out), src_lang='en',
                                         tgt_lang='it', context=None)

    def run_base(src, out):
        return fn(src, out)

    def run_recomposed(src, out):
        return translate_srt_with_recompose(
            src, out, fn, config={'lang': 'en', 'tgt_lang': 'it'}, log=lambda m: None,
            polish_fn=lambda texts: state['t']._polish(texts))

    rc = 0
    for it in items:
        d = C.WORK / 'tr' / it['id']
        if (d / 'res.json').exists():
            continue
        d.mkdir(parents=True, exist_ok=True)
        src = C.WORK / 'src' / f"{it['id']}.src.srt"
        order = ['base', 'ricomposta']
        random.Random(f"{R.SEED}:{it['id']}").shuffle(order)
        res = {'id': it['id'], 'order': order}
        t0 = time.time()
        for arm in order:
            out = d / f"{arm}.srt"
            if arm == 'base':
                res['base_ok'] = bool(run_base(src, out))
            else:
                res['ricomposta'] = run_recomposed(src, out)
        res['seconds'] = round(time.time() - t0, 1)
        C.write_json_atomic(d / 'res.json', res)
        rr = res['ricomposta']
        ok = res['base_ok'] and rr['ok'] and rr['mode'] == 'recompose'
        print(f"{'OK ' if ok else 'ATTENZIONE'} {it['id']}: ordine {order}, unita' fuse {rr['n_merged_units']}, "
              f"modo {rr['mode']} {rr['reason']}, {res['seconds']} s", flush=True)
        rc = rc or (0 if ok else 1)
    try:
        state['t'].cleanup()
    except Exception:
        pass
    sandbox.check_real_config()
    return rc


if __name__ == '__main__':
    sys.exit(main())
