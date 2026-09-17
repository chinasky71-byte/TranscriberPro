"""
Canary CLI - Trascrizione Canary-Qwen-2.5B in subprocess isolato (venv_canary)
File: core/engines/canary_cli.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Script standalone eseguito dal python di venv_canary (NeMo NON è installato
   nel venv di produzione: setuptools/lightning/protobuf incompatibili)
✅ SOLO stdlib + nemo: nessun import dal progetto (il venv_canary non ha le
   dipendenze di Transcriber Pro)
✅ Input:  args.json {model_id, hf_cache, batch_size, chunks: [{path, start, end}, ...]}
✅ Output: out.json  {ok, error, chunks: [{text}, ...]}
✅ Progress su stdout riga per riga ("PROGRESS i/n") → il parent le inoltra
   al log GUI

USO: venv_canary/Scripts/python.exe core/engines/canary_cli.py <args.json>
"""
import json
import os
import sys
import time

import torch


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
        # batch_size si legge DENTRO al try: un valore rovinato a mano in
        # config.json altrimenti esplode prima che out.json esista, e il
        # parent vedrebbe solo "exit code 1" senza il motivo
        try:
            batch_size = max(1, int(args.get('batch_size', 8) or 8))
        except (TypeError, ValueError):
            print("WARN: batch_size non valido in args.json, uso 8", flush=True)
            batch_size = 8

        print("LOAD_START", flush=True)
        t0 = time.time()
        from nemo.collections.speechlm2.models import SALM

        model = SALM.from_pretrained(model_id)
        model = model.eval()
        try:
            if torch.cuda.is_available():
                model = model.to(torch.bfloat16).cuda()
        except Exception as e:
            print(f"WARN: uso CPU ({e})", flush=True)
        print(f"LOAD_DONE {time.time() - t0:.1f}s", flush=True)

        # Token a cui troncare ogni riga del batch: HF `generate()` a batch>1
        # continua fino alla riga PIU' LUNGA e riempie di padding le altre
        # dopo il loro EOS — a batch=1 (comportamento storico) non serviva,
        # perché lì lo stop-on-EOS ferma l'unica riga senza lasciare coda.
        # Si include anche il pad perché su questo tokenizer è <|endoftext|>,
        # che Qwen usa come fine-turno alternativa: NeMo passa a HF il solo
        # text_eos_id come stop, quindi se il modello lo emettesse la riga
        # tirerebbe dritto fino a max_new_tokens con spazzatura in coda.
        stop_ids = [model.text_eos_id]
        if (getattr(model.tokenizer, 'pad', None) is not None
                and model.text_pad_id != model.text_eos_id):
            stop_ids.append(model.text_pad_id)
        stop_tokens = torch.tensor(stop_ids)

        def _decode_row(row):
            row = row.cpu()
            end = torch.isin(row, stop_tokens).nonzero(as_tuple=True)[0]
            if end.numel() > 0:
                row = row[:end[0]]
            return model.tokenizer.ids_to_text(row).strip()

        def _is_oom(exc) -> bool:
            oom_cls = getattr(torch.cuda, 'OutOfMemoryError', None)
            if oom_cls is not None and isinstance(exc, oom_cls):
                return True
            return 'out of memory' in str(exc).lower()

        def _transcribe_batch(batch):
            """Testi di un gruppo di chunk, in ORDINE. Se la VRAM non basta
            dimezza e riprova: a batch=1 il modello ci stava di sicuro
            (comportamento storico), quindi la ricorsione ha sempre un
            fondo. NB: su WDDM un batch troppo grande spesso non solleva
            OOM, rallenta e basta — questo ripiego copre solo l'OOM vero."""
            try:
                answer_ids = model.generate(
                    prompts=[
                        [{"role": "user",
                          "content": f"Transcribe the following: {model.audio_locator_tag}",
                          "audio": [ch['path']]}]
                        for ch in batch
                    ],
                    max_new_tokens=256,
                )
            except Exception as exc:
                if len(batch) == 1 or not _is_oom(exc):
                    raise
                print(f"WARN: VRAM insufficiente su {len(batch)} chunk, "
                      f"dimezzo il batch", flush=True)
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                half = len(batch) // 2
                return _transcribe_batch(batch[:half]) + _transcribe_batch(batch[half:])

            rows = list(answer_ids)
            # Il parent appaia i testi ai chunk per POSIZIONE (zip): una riga
            # in meno non darebbe errore, sposterebbe in silenzio i tempi di
            # tutti i chunk successivi del file. Meglio fallire qui.
            if len(rows) != len(batch):
                raise RuntimeError(
                    f"generate() ha restituito {len(rows)} righe per {len(batch)} "
                    f"chunk: allineamento testo/tempi non garantito")
            return [_decode_row(r) for r in rows]

        n = len(chunks)
        for batch_start in range(0, n, batch_size):
            batch = chunks[batch_start:batch_start + batch_size]
            t1 = time.time()
            texts = _transcribe_batch(batch)
            # Stima cosmetica: il tempo del batch spalmato sui suoi chunk
            per_chunk = (time.time() - t1) / len(batch)
            for j, text in enumerate(texts):
                result['chunks'].append({'text': text})
                print(f"PROGRESS {batch_start + j + 1}/{n} "
                      f"({per_chunk:.1f}s)", flush=True)

        if len(result['chunks']) != n:
            raise RuntimeError(
                f"prodotti {len(result['chunks'])} testi per {n} chunk: "
                f"allineamento testo/tempi non garantito")

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
