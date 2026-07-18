"""
Canary CLI - Trascrizione Canary-Qwen-2.5B in subprocess isolato (venv_canary)
File: core/engines/canary_cli.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Script standalone eseguito dal python di venv_canary (NeMo NON è installato
   nel venv di produzione: setuptools/lightning/protobuf incompatibili)
✅ SOLO stdlib + nemo: nessun import dal progetto (il venv_canary non ha le
   dipendenze di Transcriber Pro)
✅ Input:  args.json {model_id, hf_cache, chunks: [{path, start, end}, ...]}
✅ Output: out.json  {ok, error, chunks: [{text}, ...]}
✅ Progress su stdout riga per riga ("PROGRESS i/n") → il parent le inoltra
   al log GUI

USO: venv_canary/Scripts/python.exe core/engines/canary_cli.py <args.json>
"""
import json
import os
import sys
import time


def main() -> int:
    if len(sys.argv) < 2:
        print("ERRORE: manca args.json", flush=True)
        return 2

    args_path = sys.argv[1]
    with open(args_path, 'r', encoding='utf-8') as f:
        args = json.load(f)

    model_id = args.get('model_id', 'nvidia/canary-qwen-2.5b')
    out_path = args['output_json']
    chunks = args.get('chunks', [])

    # Redirige la cache HF su quella del progetto (modello già scaricato lì)
    hf_cache = args.get('hf_cache')
    if hf_cache:
        os.environ.setdefault('HF_HOME', hf_cache)
        os.environ.setdefault('HUGGINGFACE_HUB_CACHE', os.path.join(hf_cache, 'hub'))

    result = {'ok': False, 'error': None, 'chunks': []}

    try:
        print("LOAD_START", flush=True)
        t0 = time.time()
        from nemo.collections.speechlm2.models import SALM

        model = SALM.from_pretrained(model_id)
        model = model.eval()
        try:
            import torch
            if torch.cuda.is_available():
                model = model.to(torch.bfloat16).cuda()
        except Exception as e:
            print(f"WARN: uso CPU ({e})", flush=True)
        print(f"LOAD_DONE {time.time() - t0:.1f}s", flush=True)

        n = len(chunks)
        for i, ch in enumerate(chunks):
            t1 = time.time()
            answer_ids = model.generate(
                prompts=[
                    [{"role": "user",
                      "content": f"Transcribe the following: {model.audio_locator_tag}",
                      "audio": [ch['path']]}]
                ],
                max_new_tokens=256,
            )
            text = model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip()
            result['chunks'].append({'text': text})
            print(f"PROGRESS {i + 1}/{n} ({time.time() - t1:.1f}s)", flush=True)

        result['ok'] = True

    except Exception as e:
        import traceback
        result['error'] = f"{e}\n{traceback.format_exc()}"
        print(f"ERRORE: {e}", flush=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)

    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
