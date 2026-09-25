"""
Funzioni condivise di whisper_split_eval (solo CPU, nessun torch).

- carica windows.jsonl e gli hyp del banco asr_eval (SOLA LETTURA);
- carica la funzione ORIGINALE `_split_segment_by_words` dal backup del
  motore (whisper_split_eval/_orig_split.py, copia testuale del metodo) e la
  variante nuova (core/whisper_sentence_split.py, per percorso);
- metriche: midcut (split_eval/midcut.py) sui segmenti e sui blocchi del
  formatter di produzione (split_eval/prodmods.py, readability=True).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR_WORK = ROOT / 'asr_eval' / 'work'
WORK = HERE / 'work'

for p in (str(ROOT),):
    if p not in sys.path:
        sys.path.insert(0, p)


def load_path(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def midcut_mod():
    return load_path('_wse_midcut', ROOT / 'split_eval' / 'midcut.py')


def prodmods_mod():
    return load_path('_wse_prodmods', ROOT / 'split_eval' / 'prodmods.py')


def new_split_mod():
    return load_path('_wse_new_split', ROOT / 'core' / 'whisper_sentence_split.py')


def orig_split_mod():
    return load_path('_wse_orig_split', HERE / '_orig_split.py')


def read_jsonl(p: Path) -> List[Dict]:
    return [json.loads(l) for l in Path(p).read_text(encoding='utf-8').splitlines() if l.strip()]


def windows() -> List[Dict]:
    return read_jsonl(ASR_WORK / 'windows.jsonl')


def bench_hyp(win_id: str) -> Dict:
    return json.loads((ASR_WORK / 'hyp' / 'whisper__vocals' / f'{win_id}.json').read_text(encoding='utf-8'))


def round_segments(segs: Sequence[Dict]) -> List[Dict]:
    """Stesso arrotondamento di asr_eval/runners.clean_segments (shift 0)."""
    out = []
    for s in segs:
        words = [{'start': round(float(w['start']), 3), 'end': round(float(w['end']), 3),
                  'word': str(w['word'])} for w in (s.get('words') or [])]
        out.append({'start': round(float(s['start']), 3), 'end': round(float(s['end']), 3),
                    'text': str(s.get('text', '')), 'words': words})
    return out


def formatter_blocks(segs: Sequence[Dict]) -> List[Dict]:
    """Blocchi del formatter di produzione (readability=True, senza speaker),
    con le righe di testo: {start, end, text (righe unite da \\n)}."""
    PM = prodmods_mod()
    MC = midcut_mod()
    s2 = [{'start': float(s['start']), 'end': float(s['end']), 'text': str(s.get('text', '')),
           **({'words': s['words']} if s.get('words') else {})} for s in segs]
    srt = PM.SubtitleFormatter(readability=True).format_srt(s2)
    return MC.srt_blocks(srt)


def midcut_stats(blocks: Sequence[Dict], lang: str = 'en') -> Dict:
    return midcut_mod().midcut_stats(blocks, lang)
