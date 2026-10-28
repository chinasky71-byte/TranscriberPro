#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conversione di TranslateGemma-12B (fine-tuned) in GGUF quantizzati per il percorso llama.cpp del traduttore.

Si esegue IN LOCALE (servono i pesi, che non sono nel repository, e decine di GB di disco). Guida completa:
docs/GGUF_CONVERSIONE.md. Passi, nell'ordine:

  plan      stampa disco/RAM richiesti e i comandi, non esegue niente
  merge     (solo se i pesi sono ancora base + adattatore LoRA separati) fonde l'adattatore nel modello
  convert   cartella HF -> GGUF f16 con convert_hf_to_gguf.py di llama.cpp
  corpus    costruisce il testo di calibrazione per l'imatrix da un file di coppie EN<TAB>IT
  imatrix   calcola la matrice di importanza con llama-imatrix
  quantize  f16 -> Q4_K_M, Q3_K_M, IQ3_M (e Q8_0 se serve come base dell'imatrix) con llama-quantize
  verify    legge l'intestazione dei GGUF: architettura, quantizzazione, dimensione REALE in GiB

Versione di llama.cpp: la STESSA vendorizzata da llama-cpp-python 0.3.34 (commit e3546c794), cosi' il file prodotto e il
runtime del prodotto parlano la stessa versione del formato. Il pin del prodotto non si cambia.

Il nome dei file prodotti, `<nome>-<QUANT>.gguf`, e' quello che il motore (core/llm_subtitle_translator/gguf_engine.py)
riconosce in `models/translategemma-12b-gguf/`.

Solo libreria standard, tranne `merge` (torch, transformers, peft) e `verify --smoke` (llama-cpp-python).
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LLAMA_CPP_COMMIT = 'e3546c794'          # vendorizzato da llama-cpp-python 0.3.34 (CHANGELOG: "update llama.cpp to ggml-org/llama.cpp@e3546c794")
DEFAULT_QUANTS = ('Q4_K_M', 'Q3_K_M', 'IQ3_M')
# IQ3_M funziona anche senza imatrix (llama.cpp lo impone solo a IQ1/IQ2/IQ3_XXS): con l'imatrix si attende una qualita' migliore,
# non misurata. Lo script avvisa, non rifiuta.
RECOMMEND_IMATRIX = ('IQ3_M', 'Q3_K_M')
N_PARAMS_B = 11.77                      # parametri del 12B (miliardi), stima per le risorse
GIB = 1024 ** 3

# file_type di GGUF (llama_ftype) -> nome, per `verify`
FTYPES = {0: 'F32', 1: 'F16', 2: 'Q4_0', 3: 'Q4_1', 7: 'Q8_0', 8: 'Q5_0', 9: 'Q5_1', 10: 'Q2_K', 11: 'Q3_K_S',
          12: 'Q3_K_M', 13: 'Q3_K_L', 14: 'Q4_K_S', 15: 'Q4_K_M', 16: 'Q5_K_S', 17: 'Q5_K_M', 18: 'Q6_K',
          19: 'IQ2_XXS', 20: 'IQ2_XS', 21: 'Q2_K_S', 22: 'IQ3_XS', 23: 'IQ3_XXS', 24: 'IQ1_S', 25: 'IQ4_NL',
          26: 'IQ3_S', 27: 'IQ3_M', 28: 'IQ2_S', 29: 'IQ2_M', 30: 'IQ4_XS', 31: 'IQ1_M', 32: 'BF16'}


# ------------------------------------------------------------------------------------------------ funzioni pure
def estimate_resources(n_params_b: float = N_PARAMS_B, quants=DEFAULT_QUANTS, with_q8: bool = True) -> dict:
    """Stime (GiB) di disco e RAM. NON misure: i pesi f16 sono ~2 byte/parametro, i quantizzati i bpw tipici di llama.cpp."""
    bpw = {'F16': 16.0, 'BF16': 16.0, 'Q8_0': 8.5, 'Q4_K_M': 4.85, 'Q3_K_M': 3.9, 'IQ3_M': 3.66}
    size = {k: n_params_b * 1e9 * v / 8 / GIB for k, v in bpw.items()}
    out = [q for q in quants] + (['Q8_0'] if with_q8 else [])
    return {'f16_gib': size['F16'], 'sizes_gib': {q: size[q] for q in out},
            'disk_gib': size['F16'] + sum(size[q] for q in out),
            # merge: il modello bf16 intero in RAM + l'adattatore. Conversione e quantizzazione leggono a mmap.
            'ram_merge_gib': size['BF16'] * 1.2}


def build_convert_cmd(model_dir, out_gguf, llama_cpp_dir, outtype='bf16', python=None):
    return [python or sys.executable, str(Path(llama_cpp_dir) / 'convert_hf_to_gguf.py'), str(model_dir),
            '--outfile', str(out_gguf), '--outtype', outtype]


def find_binary(llama_cpp_dir, name):
    """build/bin/<name>, oppure build/bin/Release/<name> (generatori multi-config di Visual Studio). Errore chiaro se manca."""
    exe = name + ('.exe' if os.name == 'nt' else '')
    cands = [Path(llama_cpp_dir) / 'build' / 'bin' / exe, Path(llama_cpp_dir) / 'build' / 'bin' / 'Release' / exe]
    for c in cands:
        if c.is_file():
            return str(c)
    return str(cands[0])        # non esiste: _run lo segnala


def build_quantize_cmd(llama_cpp_dir, src_gguf, dst_gguf, quant, imatrix=None, threads=None, binary=None):
    exe = binary or find_binary(llama_cpp_dir, 'llama-quantize')
    cmd = [exe]
    if imatrix:
        cmd += ['--imatrix', str(imatrix)]
    cmd += [str(src_gguf), str(dst_gguf), quant]
    if threads:
        cmd.append(str(threads))
    return cmd


def build_imatrix_cmd(llama_cpp_dir, gguf, corpus, out, ngl=0, ctx=512, binary=None):
    exe = binary or find_binary(llama_cpp_dir, 'llama-imatrix')
    # --parse-special: senza, <start_of_turn>/<end_of_turn>/<bos> del corpus diventano testo e non i token speciali del motore.
    return [exe, '-m', str(gguf), '-f', str(corpus), '-o', str(out), '-c', str(ctx), '-ngl', str(ngl), '--parse-special']


def quant_filename(stem: str, quant: str) -> str:
    return f'{stem}-{quant}.gguf'


def parse_pairs(text: str, max_pairs=None):
    """Righe 'inglese<TAB>italiano' -> [(en, it)]. Righe vuote, senza tab o con un lato vuoto: scartate. Le interruzioni
    di riga dentro una battuta si scrivono come \\n letterale."""
    pairs = []
    for line in text.splitlines():
        if '\t' not in line:
            continue
        en, it = line.split('\t', 1)
        en, it = en.replace('\\n', '\n').strip(), it.replace('\\n', '\n').strip()
        if en and it:
            pairs.append((en, it))
            if max_pairs and len(pairs) >= max_pairs:
                break
    return pairs


def corpus_from_pairs(pairs, prompt_fn):
    """Testo di calibrazione nel formato ESATTO del training/inferenza: prompt reso + risposta italiana + fine turno.
    `prompt_fn(en) -> str` e' il prompt del motore (render_prompt di gguf_engine)."""
    return ''.join(prompt_fn(en) + it + '<end_of_turn>\n' for en, it in pairs)


def read_gguf_meta(path, keys=('general.architecture', 'general.file_type', 'general.name', 'tokenizer.chat_template')):
    """Intestazione GGUF letta a mano (solo le chiavi richieste): {chiave: valore}, piu' 'n_tensors', 'size_bytes'."""
    want = set(keys)
    out = {'size_bytes': Path(path).stat().st_size}
    with open(path, 'rb') as f:
        if f.read(4) != b'GGUF':
            raise ValueError('non e\' un file GGUF')
        version, = struct.unpack('<I', f.read(4))
        if version < 2 or version > 3:
            raise ValueError(f'versione GGUF {version} non supportata')
        n_tensors, n_kv = struct.unpack('<QQ', f.read(16))
        out['n_tensors'] = n_tensors

        def rd_str():
            n, = struct.unpack('<Q', f.read(8))
            return f.read(n).decode('utf-8', errors='replace')

        sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
        fmts = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}

        def rd_val(t):
            if t == 8:
                return rd_str()
            if t == 9:
                et, = struct.unpack('<I', f.read(4))
                n, = struct.unpack('<Q', f.read(8))
                return [rd_val(et) for _ in range(n)]
            return struct.unpack('<' + fmts[t], f.read(sizes[t]))[0]

        for _ in range(n_kv):
            key = rd_str()
            t, = struct.unpack('<I', f.read(4))
            val = rd_val(t)
            if key in want:
                out[key] = val
    if 'general.file_type' in out:
        out['quant'] = FTYPES.get(out['general.file_type'], f"ftype {out['general.file_type']}")
    return out


# ------------------------------------------------------------------------------------------------ esecuzione
def _run(cmd, dry=False):
    print('$ ' + ' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    if dry:
        return 0
    exe = Path(cmd[0])
    if exe.name.startswith('llama-') and not exe.is_file():
        sys.exit(f'{exe} non esiste: compila llama.cpp (cmake --build llama.cpp/build --config Release --target llama-quantize llama-imatrix)')
    rc = subprocess.call(cmd)
    if rc != 0:
        sys.exit(f'comando fallito (codice {rc})')
    return rc


def _need_free_gib(path, gib):
    p = Path(path).resolve().parent
    while not p.exists() and p != p.parent:
        p = p.parent
    free = shutil.disk_usage(p).free / GIB
    if free < gib:
        sys.exit(f'spazio libero insufficiente su {path}: {free:.0f} GiB liberi, ne servono almeno {gib:.0f}')


def cmd_plan(a):
    q = [x.strip() for x in a.quants.split(',') if x.strip()]
    r = estimate_resources(quants=q, with_q8=not a.no_q8)
    print(f'llama.cpp da usare: commit {LLAMA_CPP_COMMIT} (git clone https://github.com/ggml-org/llama.cpp && git -C llama.cpp checkout {LLAMA_CPP_COMMIT})')
    print(f'GGUF f16: ~{r["f16_gib"]:.1f} GiB. Quantizzati (stime): ' + ', '.join(f'{k} ~{v:.1f} GiB' for k, v in r['sizes_gib'].items()))
    print(f'Disco totale (f16 + quantizzati): ~{r["disk_gib"]:.0f} GiB. Merge LoRA: ~{r["ram_merge_gib"]:.0f} GiB di RAM.')
    print('Sono STIME: `verify` stampa le dimensioni reali, da riportare in utils/gguf_quant.py (QUANT_WEIGHTS_GIB).')
    for qq in q:
        if qq in RECOMMEND_IMATRIX:
            print(f'{qq}: imatrix consigliata, non obbligatoria (passi `corpus` e `imatrix`).')


def cmd_merge(a):
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForImageTextToText
    except Exception as exc:
        sys.exit(f'servono torch, transformers e peft in questo ambiente: {exc}')
    est = estimate_resources()
    print(f'Carico il modello base in bf16 su CPU: servono ~{est["ram_merge_gib"]:.0f} GiB di RAM libera.')
    model = AutoModelForImageTextToText.from_pretrained(a.base, dtype=torch.bfloat16, low_cpu_mem_usage=True)
    import json
    try:
        declared = json.loads((Path(a.adapter) / 'adapter_config.json').read_text(encoding='utf-8')).get('base_model_name_or_path')
    except Exception:
        declared = None
    print(f'Base dichiarata dall\'adattatore: {declared} (usata: {a.base}) - controlla che siano lo stesso modello.')
    probe_name, before = next((n, p.detach().clone()) for n, p in model.named_parameters() if 'q_proj.weight' in n)
    model = PeftModel.from_pretrained(model, a.adapter, is_trainable=False).merge_and_unload()
    after = dict(model.named_parameters()).get(probe_name)
    if after is None or torch.equal(before, after.detach()):
        sys.exit(f'ATTENZIONE: il peso {probe_name} NON e\' cambiato dopo il merge: l\'adattatore non e\' stato applicato '
                 '(chiavi non combacianti?). Non converto un modello senza fine-tuning: nessun file scritto.')
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out, safe_serialization=True)
    from transformers import AutoTokenizer
    AutoTokenizer.from_pretrained(a.base).save_pretrained(a.out)
    for extra in ('tokenizer.model', 'generation_config.json', 'chat_template.jinja', 'chat_template.json'):
        if (Path(a.base) / extra).is_file() and not (Path(a.out) / extra).is_file():
            shutil.copy2(Path(a.base) / extra, Path(a.out) / extra)
    print(f'Modello fuso in {a.out} (il delta LoRA e\' arrotondato in bf16). Confronta l\'uscita prima/dopo su qualche riga.')


def cmd_convert(a):
    model = Path(a.model)
    for need in ('config.json', 'tokenizer.model'):
        if not (model / need).is_file():
            sys.exit(f'manca {need} in {model}: senza, il convertitore ripiega su tokenizer.json e il vocabolario puo\' differire dal riferimento')
    conv = Path(a.llama_cpp) / 'convert_hf_to_gguf.py'
    if not conv.is_file():
        sys.exit(f'convert_hf_to_gguf.py non trovato in {a.llama_cpp}')
    if not a.dry_run:
        _need_free_gib(a.out, estimate_resources()['f16_gib'] + 2)
    _run(build_convert_cmd(model, a.out, a.llama_cpp, a.outtype), a.dry_run)


def cmd_corpus(a):
    sys.path.insert(0, str(ROOT))
    from core.llm_subtitle_translator.engine import build_mt_messages
    from core.llm_subtitle_translator.gguf_engine import render_prompt
    pairs = parse_pairs(Path(a.pairs).read_text(encoding='utf-8'), a.max_pairs)
    if len(pairs) < 100:
        sys.exit(f'solo {len(pairs)} coppie valide: per una imatrice utile ne servono almeno alcune centinaia')
    text = corpus_from_pairs(pairs, lambda en: render_prompt(build_mt_messages(en)))
    Path(a.out).write_text(text, encoding='utf-8')
    print(f'{len(pairs)} coppie -> {a.out} ({len(text) // 1024} KiB)')


def cmd_imatrix(a):
    _run(build_imatrix_cmd(a.llama_cpp, a.gguf, a.corpus, a.out, a.ngl, a.ctx), a.dry_run)


def cmd_quantize(a):
    src = Path(a.gguf)
    stem = a.name or src.stem
    for suf in ('-f16', '-F16', '-bf16', '-BF16', '-f32'):
        if stem.endswith(suf):
            stem = stem[:-len(suf)]
            break
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    quants = [x.strip() for x in a.quants.split(',') if x.strip()]
    for q in quants:
        if q in RECOMMEND_IMATRIX and not a.imatrix:
            print(f'ATTENZIONE: {q} senza imatrix: si attende una qualita\' minore (non misurata). Passa --imatrix per il confronto corretto.')
    for q in quants:
        _run(build_quantize_cmd(a.llama_cpp, src, outdir / quant_filename(stem, q), q, a.imatrix, a.threads), a.dry_run)


def cmd_verify(a):
    bad = 0
    for p in a.files:
        m = read_gguf_meta(p)
        gib = m['size_bytes'] / GIB
        arch = m.get('general.architecture')
        suffix = Path(p).stem.rsplit('-', 1)[-1].upper()
        mism = suffix in DEFAULT_QUANTS and m.get('quant') != suffix
        ok = arch == 'gemma3' and not mism
        bad += not ok
        print(f'{Path(p).name}: arch={arch} quant={m.get("quant", "?")} {gib:.2f} GiB tensori={m["n_tensors"]} '
              f'chat_template={"si" if m.get("tokenizer.chat_template") else "no"}' + ('' if arch == 'gemma3' else '   <-- NON gemma3') + ('   <-- il nome dice ' + suffix if mism else ''))
    if a.smoke:
        sys.path.insert(0, str(ROOT))
        from core.llm_subtitle_translator.gguf_engine import GGUFEngine
        for p in a.files:
            e = GGUFEngine(p, 'smoke', n_parallel=1, n_gpu_layers=a.ngl, log_callback=print)
            try:
                print(Path(p).name, '->', e.generate([e.mt_messages('Where are you going?')], max_new_tokens=32))
            finally:
                e.unload()
    print('NB: il template di chat incorporato non serve al motore del prodotto (usa render_prompt).')
    sys.exit(1 if bad else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('plan'); p.set_defaults(fn=cmd_plan)
    p.add_argument('--quants', default=','.join(DEFAULT_QUANTS)); p.add_argument('--no-q8', action='store_true')

    p = sub.add_parser('merge'); p.set_defaults(fn=cmd_merge)
    p.add_argument('--base', required=True); p.add_argument('--adapter', required=True); p.add_argument('--out', required=True)

    p = sub.add_parser('convert'); p.set_defaults(fn=cmd_convert)
    p.add_argument('--model', required=True, help='cartella HF dei pesi fine-tuned gia\' fusi')
    p.add_argument('--llama-cpp', required=True, help=f'clone di llama.cpp al commit {LLAMA_CPP_COMMIT}')
    p.add_argument('--out', required=True, help='GGUF f16 di uscita'); p.add_argument('--outtype', default='bf16', choices=['f16', 'bf16'], help='bf16 = tipo nativo di Gemma3 (default); f16 puo\' perdere range')
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser('corpus'); p.set_defaults(fn=cmd_corpus)
    p.add_argument('--pairs', required=True, help='file UTF-8 con righe EN<TAB>IT (NON le battute del banco di qualita\')')
    p.add_argument('--out', required=True); p.add_argument('--max-pairs', type=int, default=1000)

    p = sub.add_parser('imatrix'); p.set_defaults(fn=cmd_imatrix)
    p.add_argument('--llama-cpp', required=True); p.add_argument('--gguf', required=True); p.add_argument('--corpus', required=True)
    p.add_argument('--out', required=True); p.add_argument('--ngl', type=int, default=0); p.add_argument('--ctx', type=int, default=512)
    p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser('quantize'); p.set_defaults(fn=cmd_quantize)
    p.add_argument('--llama-cpp', required=True); p.add_argument('--gguf', required=True)
    p.add_argument('--outdir', required=True); p.add_argument('--quants', default=','.join(DEFAULT_QUANTS))
    p.add_argument('--imatrix'); p.add_argument('--name', help='prefisso dei file (default: nome del f16)')
    p.add_argument('--threads', type=int); p.add_argument('--dry-run', action='store_true')

    p = sub.add_parser('verify'); p.set_defaults(fn=cmd_verify)
    p.add_argument('files', nargs='+'); p.add_argument('--smoke', action='store_true'); p.add_argument('--ngl', type=int, default=0)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == '__main__':
    main()
