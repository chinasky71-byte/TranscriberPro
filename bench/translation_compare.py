# -*- coding: utf-8 -*-
"""Confronto di motori di traduzione su una traccia professionale.

Il banco usato per la campagna del 2026-10-28 (vedi
`docs/benchmarks/2026-10-28-translation-engines.md`): una sorgente inglese
professionale, un riferimento italiano professionale, un motore per volta e
**lo stesso prompt-path** per tutti. Non tocca il prodotto e non importa nel
percorso di produzione: serve a decidere, con i numeri, se un motore vale.

Tre modalità, che coprono i tre casi incontrati:

  translategemma  il percorso di produzione: `GGUFEngine.mt_messages()` con le
                  regole del sottotitolo e il budget caratteri dentro il testo
                  (TranslateGemma non ha un ruolo system).
  chat            un modello istruito: chat template del GGUF, istruzione di
                  traduzione, e con `--rules` le regole sottotitolo + budget nel
                  system prompt (è lì che un modello a chat le accetta).
  raw             completion pura, per i modelli senza chat template (Seed-X).

Uso:
  python -m bench.translation_compare translate --engine translategemma \\
      --gguf models/translategemma-12b-gguf/translategemma-12b-it-finale-Q4_K_M.gguf \\
      --src en_professional.srt --ref it_professional.srt --out /tmp/out --name tg12b

  python -m bench.translation_compare translate --engine chat --family eurollm \\
      --gguf EuroLLM-22B-Instruct-2512.Q4_K_M.gguf --rules \\
      --src en_professional.srt --ref it_professional.srt --out /tmp/out --name eurollm22b

Metriche: chrF e WER sul testo intero (non per battuta: il sottotitolo umano
condensa e segmenta diversamente), caratteri per battuta, quota oltre i 42,
lunghezza contro sorgente e riferimento, blocchi identici alla sorgente, tempo.

ATTENZIONE alle due metriche che ingannano, misurate il 2026-10-28:
`copy_through` conta anche interiezioni, nomi e ritornelli che restano identici
*legittimamente* (21 su 29 nel 12B), e un output più corto della sorgente è
**condensazione**, cioè l'obiettivo del sottotitolo, non perdita di contenuto.
Vanno letti a mano prima di chiamarli difetti.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

from bench import metrics

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CUE = re.compile(r'\d+\s*\n(\d\d:\d\d:\d\d[,.]\d{3}) --> (\d\d:\d\d:\d\d[,.]\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)', re.S)
TAGS = re.compile(r'<[^>]+>|\{[^}]+\}')
CPL_MAX = 42

# Istruzione nativa per famiglia (dal model card di ciascuno). `{text}` è la battuta.
PROMPTS = {
    "tower": "Translate the following English source text to Italian:\nEnglish: {text}\nItalian: ",
    "hunyuan": "Translate the following segment into Italian, without additional explanation.\n\n{text}",
    "seedx": "Translate the following English sentence into Italian:\n{text} <it>",
    "eurollm": "Translate the following English text into Italian. Answer only with the translation.\n\n{text}",
}
# `raw` = nessun chat template nel GGUF: completion pura.
RAW_FAMILIES = {"seedx"}

# Regole del sottotitolo per i modelli con ruolo system (misurate: con queste il
# 22B è passato da 47 a 32 blocchi identici alla sorgente, e ha smesso di
# inventare parole come "Flappalacchere").
RULES = (
    "Sei un adattatore di sottotitoli italiano. Traduci dall'inglese all'italiano.\n"
    "Regole:\n"
    "- italiano parlato e naturale, registro del dialogo; nessun calco dall'inglese;\n"
    "- CONDENSA: la battuta deve stare in {budget} caratteri. Taglia riempitivi e\n"
    "  ripetizioni; non aggiungere nulla che non ci sia;\n"
    "- traduci TUTTO: nessuna parola inglese nella risposta, nemmeno interiezioni o\n"
    "  parole inventate (rendile con un equivalente italiano);\n"
    "- una sola riga, nessuna numerazione, nessuna spiegazione;\n"
    "- se la battuta inglese ha i trattini del dialogo (due parlanti), conservali;\n"
    "- non aggiungere pronomi o soggetti che l'inglese non ha;\n"
    "- apostrofi e accenti corretti (è, perché, così), mai e' o E';\n"
    "- le parolacce restano parolacce, con l'equivalente italiano più vicino."
)

# Riscrittura vincolata (il passaggio "editor" del 2026-10-28): bozza + inglese.
EDIT_SYSTEM = (
    "Sei un revisore di sottotitoli italiani. Ricevi la battuta inglese e una bozza "
    "italiana già tradotta.\n"
    "Il tuo compito: rendere l'italiano più naturale e scorrevole, correggere gli "
    "errori (articoli, concordanze, tempi, preposizioni) e i calchi dall'inglese.\n"
    "Paletti inderogabili:\n"
    "- non aggiungere NIENTE che non sia nella battuta inglese; non togliere informazioni;\n"
    "- la battuta finale deve stare in {budget} caratteri;\n"
    "- conserva le parolacce con parolacce italiane equivalenti;\n"
    "- se la bozza è già corretta e naturale, restituiscila IDENTICA;\n"
    "- rispondi SOLO con la battuta italiana, senza virgolette né spiegazioni."
)


# --------------------------------------------------------------------------- SRT
def sec(t: str) -> float:
    hms, _, ms = t.replace('.', ',').partition(',')
    h, m, s = (int(x) for x in hms.split(':'))
    return h * 3600 + m * 60 + s + int(ms or 0) / 1000


def parse(path) -> list:
    """[{start, end, text}] con i tag di formattazione rimossi."""
    raw = Path(path).read_text(encoding='utf-8-sig', errors='replace').replace('\r\n', '\n')
    out = []
    for m in CUE.finditer(raw):
        body = TAGS.sub('', m.group(3)).strip()
        if body:
            out.append({'start': m.group(1), 'end': m.group(2),
                        'text': ' '.join(body.split())})
    return out


def write_srt(cues, texts, path) -> None:
    blocks = []
    for i, (c, t) in enumerate(zip(cues, texts), 1):
        blocks.append(f"{i}\n{c['start']} --> {c['end']}\n{t}".rstrip())
    Path(path).write_text('\n\n'.join(blocks) + '\n', encoding='utf-8')


def budget_of(cue) -> int:
    from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
    unit = SubtitleUnit(id=0, text=cue['text'], duration=sec(cue['end']) - sec(cue['start']))
    return unit.budget


def clean(text: str) -> str:
    t = ' '.join((text or '').split())
    t = re.sub(r'^(ecco\s+(la\s+)?(nuova\s+)?(traduzione|versione)\s*:?|battuta\s*:)\s*', '', t, flags=re.I)
    return t.strip().strip('"').strip("'")


# ----------------------------------------------------------------------- metriche
def report(name, src, out, ref) -> dict:
    lens = [len(t) for t in out]
    src_text = ' '.join(c['text'] for c in src)
    ref_text = ' '.join(c['text'] for c in ref)
    out_text = ' '.join(t for t in out if t).strip()
    return {
        'engine': name,
        'cues_in': len(src), 'cues_out': len(out),
        'empty': sum(1 for t in out if not t.strip()),
        'chars_per_cue': round(statistics.mean(lens), 1) if lens else 0,
        'pct_over_42': round(100 * sum(1 for n in lens if n > CPL_MAX) / max(1, len(lens)), 1),
        'len_vs_source': round(len(out_text) / max(1, len(src_text)), 3),
        'len_vs_reference': round(len(out_text) / max(1, len(ref_text)), 3),
        'chrf_vs_reference': round(metrics.chrf(ref_text, out_text), 4),
        'wer_vs_reference': round(metrics.wer(ref_text.split(), out_text.split())['rate'], 4),
        # vedi l'avvertenza nel docstring: da leggere a mano
        'identical_to_source': len(metrics.untranslated_blocks([c['text'] for c in src], out)),
    }


# ------------------------------------------------------------------------ motori
def _template(llm):
    import jinja2
    raw = llm.metadata.get('tokenizer.chat_template', '')
    if not raw:
        raise SystemExit('questo GGUF non ha un chat template: usa --engine raw')
    return jinja2.Environment(trim_blocks=True, lstrip_blocks=True).from_string(raw)


def run_translategemma(args, src):
    import dataclasses
    from core.llm_subtitle_translator.gguf_engine import GGUFEngine
    engine = GGUFEngine(args.gguf, args.quant, n_parallel=args.n_parallel, ctx_per_seq=512)
    if args.context_file:
        # stesso canale del prodotto: `mt_prefix` nello spec. Misurato il
        # 2026-10-28: il 12B ignora il contesto (0-1 battute cambiate su 630).
        ctx = Path(args.context_file).read_text(encoding='utf-8').strip()
        engine.spec = dataclasses.replace(
            engine.spec, mt_prefix=engine.spec.mt_prefix + " Contesto dell'opera: " + ctx)
    engine.load()
    out, t0 = [], time.time()
    for i in range(0, len(src), args.n_parallel):
        group = src[i:i + args.n_parallel]
        convs = [engine.mt_messages(c['text'], src_lang='en', budget=budget_of(c)) for c in group]
        out.extend(engine.generate(convs, max_new_tokens=160))
        if (i + len(group)) % 80 == 0 or i + len(group) == len(src):
            print(f'  {i + len(group)}/{len(src)} ({time.time() - t0:.0f}s)', flush=True)
    engine.unload()
    return out, time.time() - t0


def run_chat(args, src):
    from llama_cpp import Llama
    llm = Llama(model_path=args.gguf, n_ctx=args.ctx, n_gpu_layers=-1, n_batch=256,
                verbose=False, seed=0)
    tpl = None if args.family in RAW_FAMILIES else _template(llm)
    ctx = ''
    if args.context_file:
        ctx = ("\n\nContesto dell'opera (non tradurlo, serviti solo per capire):\n"
               + Path(args.context_file).read_text(encoding='utf-8').strip())
    out, t0 = [], time.time()
    for i, c in enumerate(src, 1):
        content = PROMPTS[args.family].format(text=c['text'])
        try:
            if tpl is None:
                prompt = content
            else:
                msgs = [{'role': 'user', 'content': content}]
                if args.rules:
                    system = RULES.format(budget=budget_of(c)) + ctx
                    msgs = [{'role': 'system', 'content': system}] + msgs
                try:
                    prompt = tpl.render(messages=msgs, add_generation_prompt=True,
                                        enable_thinking=False)
                except Exception:      # template che non conosce enable_thinking
                    prompt = tpl.render(messages=msgs, add_generation_prompt=True)
            r = llm.create_completion(prompt=prompt, temperature=0.0, max_tokens=200)
            out.append(clean(r['choices'][0]['text']))
        except Exception as exc:
            print(f'  cue {i} KO: {exc}', flush=True)
            out.append('')
        if i % 80 == 0 or i == len(src):
            print(f'  {i}/{len(src)} ({time.time() - t0:.0f}s)', flush=True)
    del llm
    return out, time.time() - t0


def run_edit(args, src, draft):
    """Secondo passaggio: riscrive una bozza con paletti e fallback per battuta."""
    from llama_cpp import Llama
    llm = Llama(model_path=args.gguf, n_ctx=args.ctx, n_gpu_layers=-1, n_batch=256,
                verbose=False, seed=0)
    tpl = _template(llm)
    out, edited, kept = [], 0, 0
    rejected = {'empty': 0, 'long': 0, 'drift': 0}
    t0 = time.time()
    for i, (s, d) in enumerate(zip(src, draft), 1):
        msgs = [{'role': 'system', 'content': EDIT_SYSTEM.format(budget=budget_of(s))},
                {'role': 'user', 'content': f"INGLESE: {s['text']}\nBOZZA: {d['text']}"}]
        prompt = tpl.render(messages=msgs, add_generation_prompt=True, enable_thinking=False)
        r = llm.create_completion(prompt=prompt, temperature=0.0, max_tokens=220)
        cand, keep = clean(r['choices'][0]['text']), d['text']
        if not cand:
            rejected['empty'] += 1
        elif len(cand) > max(budget_of(s), len(d['text'])) * 1.15:
            rejected['long'] += 1
        elif metrics.similarity(cand.split(), keep.split()) < args.min_similarity:
            rejected['drift'] += 1
        else:
            keep = cand
            edited += (cand != d['text'])
        kept += (keep == d['text'])
        out.append(keep)
        if i % 40 == 0 or i == len(src):
            print(f'  {i}/{len(src)} ({time.time() - t0:.0f}s) modificati={edited} tenuti={kept}',
                  flush=True)
    del llm
    return out, time.time() - t0, {'cues_edited': edited, 'cues_unchanged': kept,
                                   'rejected': rejected}


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Confronto motori di traduzione EN→IT')
    sub = ap.add_subparsers(dest='cmd', required=True)

    t = sub.add_parser('translate', help='traduci la sorgente con un motore')
    t.add_argument('--engine', choices=('translategemma', 'chat', 'raw'), required=True)
    t.add_argument('--gguf', required=True)
    t.add_argument('--family', choices=sorted(PROMPTS), default='eurollm',
                   help='istruzione nativa (chat/raw)')
    t.add_argument('--quant', default='Q4_K_M', help='solo etichetta nei report')
    t.add_argument('--n-parallel', type=int, default=4)
    t.add_argument('--ctx', type=int, default=2048)
    t.add_argument('--rules', action='store_true', help='regole sottotitolo nel system prompt')
    t.add_argument('--context-file', default='', help='trama/sinossi da passare come contesto')
    t.add_argument('--no-accents', action='store_true',
                   help="non applicare la correzione accenti che il prodotto fa sempre")

    e = sub.add_parser('edit', help='riscrivi una bozza già tradotta')
    e.add_argument('--gguf', required=True)
    e.add_argument('--draft', required=True)
    e.add_argument('--ctx', type=int, default=2048)
    e.add_argument('--min-similarity', type=float, default=0.30)
    e.add_argument('--no-accents', action='store_true')

    for p in (t, e):
        p.add_argument('--src', required=True)
        p.add_argument('--ref', required=True)
        p.add_argument('--out', required=True)
        p.add_argument('--name', required=True)

    a = ap.parse_args(argv)
    src, ref = parse(a.src), parse(a.ref)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if a.cmd == 'edit':
        draft = parse(a.draft)
        if len(draft) != len(src):
            raise SystemExit(f'battute disallineate: src {len(src)} draft {len(draft)}')
        texts, elapsed, extra = run_edit(a, src, draft)
    else:
        engine = 'chat' if a.engine == 'chat' else (
            'translategemma' if a.engine == 'translategemma' else 'chat')
        texts, elapsed = (run_translategemma(a, src) if engine == 'translategemma'
                          else run_chat(a, src))
        extra = {}

    if not a.no_accents:
        from core.italian_accents import fix_text
        texts = [fix_text(t) for t in texts]

    write_srt(src, texts, outdir / f'{a.name}.srt')
    data = report(a.name, src, texts, ref)
    data['seconds'] = round(elapsed, 1)
    data.update(extra)
    (outdir / f'{a.name}.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
