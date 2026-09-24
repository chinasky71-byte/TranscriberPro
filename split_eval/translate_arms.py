"""
Costruzione degli SRT sorgente (CPU) e traduzione dei due bracci (GPU).

BUILD (CPU, nessun modello). Per ogni finestra inglese del banco asr_eval:
  segmenti del motore ASR (work/hyp/<asr_key>/<win>.json)
    -> SubtitleFormatter(readability=True).format_srt(segmenti)   [senza speaker:
       e' il percorso _format_srt_fallback della pipeline]
    -> SubtitleCleaner.clean_file (STEP 5)                        = src.srt
    -> recompose(blocchi di src.srt)                              = units.srt + mapping.json
  e il riferimento italiano della finestra: le battute del sub ITA 'normale'
  (traduzione dell'inglese) che cadono nella finestra, dopo un controllo di
  sincronia EN<->IT per film.

TRANSLATE (GPU, UN processo per motore, A e B nello stesso processo sullo
stesso modello caricato):
  A = translate_file(src.srt)                      come la produzione oggi
  B = translate_file(units.srt) -> resplit -> postprocess.process sull'intera
      lista dei blocchi finali. Due varianti derivate a costo zero:
        b_full: le unita' di un blocco prese dalla traduzione di units.srt
                (quello che farebbe la produzione);
        b_iso : le unita' di un blocco prese da A (differenza = solo fusione).
Firma e uso REALI (core/translator.py): get_translator(model_type, context,
glossary) e translate_file(input_path, output_path, src_lang, tgt_lang,
context); la pipeline passa percorsi str e codici ISO 639-1 ('en','it').
Qui: glossario {} e contesto None (NLLB lo ignora comunque; il ramo LLM non
lo usa piu').

Sandbox: asr_eval/sandbox.py importato PER PRIMO fra i moduli del banco.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASR = ROOT / 'asr_eval'
for _p in (str(ROOT), str(ASR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sandbox  # noqa: E402  (per primo fra i moduli del banco)
import asr_bench as AB  # noqa: E402
import refs as R  # noqa: E402
import runners as RN  # noqa: E402

from split_eval import midcut as MC  # noqa: E402
from split_eval import prodmods  # noqa: E402
from split_eval import recompose as RC  # noqa: E402
from split_eval import srtio  # noqa: E402

SPLIT_WORK = HERE / 'work'
ASR_WORK = ASR / 'work'
SCHEMA_OUT = 'split-eval/out/1'
EXPECTED_CLASS = {'nllb_finetuned': 'NLLBFineTunedTranslator', 'llm': 'LLMSubtitleTranslator'}
SYNC_RULES = {'search_s': 3.0, 'max_abs_median_s': 0.5, 'min_matched': 0.5}
_AUDIT_RE = re.compile(r'Traduzione completata \| (.*) \| inglese residuo: (\d+)')


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def rules_sha() -> str:
    from split_eval import rules_select
    return AB.sha256_file(Path(rules_select.load().__file__))


# ══ RIFERIMENTO ITALIANO ══════════════════════════════════════════════════

def sync_check(en_abs: Sequence[Dict], it_abs: Sequence[Dict], rules: Dict = SYNC_RULES) -> Dict:
    """Sfasamento mediano fra le battute EN e la battuta IT piu' vicina (per
    inizio). ok se abbastanza battute trovano un partner entro search_s e la
    mediana e' entro max_abs_median_s."""
    starts = sorted(c['s'] for c in it_abs if not c.get('music'))
    ds = []
    n = 0
    import bisect
    for c in en_abs:
        if c.get('music'):
            continue
        n += 1
        k = bisect.bisect_left(starts, c['s'])
        cand = [starts[j] for j in (k - 1, k) if 0 <= j < len(starts)]
        if not cand:
            continue
        d = min(cand, key=lambda x: abs(x - c['s'])) - c['s']
        if abs(d) <= rules['search_s']:
            ds.append(d)
    med = statistics.median(ds) if ds else None
    matched = len(ds) / n if n else 0.0
    ok = med is not None and matched >= rules['min_matched'] and abs(med) <= rules['max_abs_median_s']
    return {'ok': ok, 'median_s': None if med is None else round(med, 3), 'matched': round(matched, 3), 'n_en': n}


def resolve_it_ref(entry: Dict, ov: Dict, en_windows: Sequence[Dict], split_work: Path, asr_work: Path,
                   extract: bool, allow_pending: bool, emit: Callable = print) -> Dict:
    subs = [s for s in entry.get('subs', []) if s.get('lang') == 'ita' and s.get('kind') == 'normal'
            and s.get('text')]
    if not subs:
        return {'status': 'missing', 'reason': 'nessuna traccia ITA normale di testo'}
    s = subs[0]
    use = AB._usable(entry, s['index'], ov)
    if use == 'no':
        return {'status': 'rejected', 'index': s['index'], 'reason': 'provenienza scartata'}
    if use == 'pending' and not allow_pending:
        return {'status': 'pending', 'index': s['index'],
                'reason': "provenienza da confermare in audit_overrides.json (o --allow-pending-it)"}
    path = asr_work / 'subs' / entry['key'] / f"{s['index']}.srt"
    if not path.exists():
        path = split_work / 'subs_it' / entry['key'] / f"{s['index']}.srt"
    if not path.exists() and extract:
        emit(f"  📥 estrazione sub ITA {entry['key']}#{s['index']} (lettura del file video)")
        R.extract_subs(Path(entry['file']), [(s['index'], s['codec'], path)])
    if not path.exists():
        return {'status': 'not_extracted', 'index': s['index'], 'reason': 'sub ITA non estratto'}
    it_cues = R.parse_srt(path)
    en_abs = [{**c, 's': w['t0'] + c['s'], 'e': w['t0'] + c['e']} for w in en_windows for c in w.get('cues', [])]
    sync = sync_check(en_abs, it_cues)
    return {'status': 'ok' if sync['ok'] else 'sync_dubbia', 'index': s['index'], 'path': str(path),
            'sync': sync, 'provenance': use}


def window_it_cues(it_cues: Sequence[Dict], t0: float, t1: float) -> List[Dict]:
    """Battute IT (tempi assoluti) con il punto medio nella finestra, riportate
    ai tempi della finestra (stessa convenzione di windows.jsonl: s - t0)."""
    out = []
    for c in it_cues:
        if c.get('music'):
            continue
        mid = 0.5 * (c['s'] + c['e'])
        if t0 <= mid <= t1:
            text = MC.clean_text(c['text'])
            if text:
                out.append({'s': round(c['s'] - t0, 3), 'e': round(c['e'] - t0, 3), 'text': text})
    return out


# ══ BUILD (CPU) ════════════════════════════════════════════════════════════

def build_window(win: Dict, segments: Sequence[Dict], out_dir: Path, recompose_cfg: Optional[Dict] = None) -> Dict:
    """Formatter -> cleaner -> recompose per una finestra. Scrive fmt.srt,
    src.srt, units.srt, mapping.json in out_dir e ritorna la riga d'indice."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = prodmods.SubtitleFormatter(readability=True).format_srt(
        [{'start': float(s['start']), 'end': float(s['end']), 'text': str(s.get('text', '')),
          **({'words': s['words']} if s.get('words') else {})} for s in segments])
    row = {'win_id': win['win_id'], 'film': win['film'], 'group': win.get('group'), 'role': win.get('role'),
           't0': win['t0'], 't1': win['t1'], 'dur': win.get('dur')}
    if not fmt.strip():
        return {**row, 'status': 'empty', 'error': 'formatter senza blocchi'}
    RN.write_text_atomic(out_dir / 'fmt.srt', fmt)
    Cleaner = prodmods.SubtitleCleaner()
    got = Cleaner.clean_file(out_dir / 'fmt.srt', out_dir / 'src.srt')
    if Path(got) != out_dir / 'src.srt' or not (out_dir / 'src.srt').exists():
        return {**row, 'status': 'failed', 'error': 'SubtitleCleaner non ha scritto src.srt'}
    src_txt = (out_dir / 'src.srt').read_text(encoding='utf-8')
    blocks = srtio.parse_blocks(src_txt)
    if [b['index'] for b in blocks] != list(range(1, len(blocks) + 1)):
        return {**row, 'status': 'failed', 'error': 'src.srt: indici non consecutivi 1..N'}
    probs = srtio.roundtrip_problems(blocks)
    units, mapping = RC.recompose(blocks, recompose_cfg)
    ublocks = [{'index': u['uid'], 'start': u['start'], 'end': u['end'], 'text': u['text']} for u in units]
    probs += srtio.roundtrip_problems(ublocks)
    units_txt = srtio.render(ublocks, skip_empty=False)
    RN.write_text_atomic(out_dir / 'units.srt', units_txt)
    RN.write_json_atomic(out_dir / 'mapping.json', mapping)
    if probs:
        return {**row, 'status': 'failed', 'error': '; '.join(probs)[:300]}
    fmt_blocks = MC.srt_blocks(fmt)
    merged = [u for u in units if u['merged']]
    return {**row, 'status': 'ok', 'error': None,
            'n_blocks': len(blocks), 'n_units': len(units), 'n_merged_units': len(merged),
            'n_merged_blocks': sum(len(u['blocks']) for u in merged),
            'midcut_hyp': MC.midcut_stats([{'start': s['start'], 'end': s['end'], 'text': s.get('text', '')}
                                           for s in segments], 'en'),
            'midcut_fmt': MC.midcut_stats(fmt_blocks, 'en'),
            'midcut_src': MC.midcut_stats(blocks, 'en'),
            'midcut_ref_en': MC.midcut_stats(win.get('cues', []), 'en'),
            'src_sha': sha_text(src_txt), 'units_sha': sha_text(units_txt),
            'recompose_config': mapping['config']}


def build(split_work: Path, asr_work: Path, asr_key: str, recompose_cfg: Optional[Dict] = None,
          extract_it: bool = True, allow_pending_it: bool = False, films: Optional[List[str]] = None,
          emit: Callable = print) -> List[Dict]:
    wins = [w for w in AB.read_jsonl(asr_work / 'windows.jsonl') if w['lang'] == 'en']
    if films:
        wins = [w for w in wins if any(f in w['film'] for f in films)]
    if not wins:
        emit(f"❌ nessuna finestra inglese in {asr_work / 'windows.jsonl'} (asr_eval: plan + prepare)")
        return []
    arm = asr_key.split('__', 1)[1]
    hyp_dir = asr_work / 'hyp' / asr_key
    audit = AB.read_json(asr_work / 'audit.json', {}) or {}
    ov = AB._overrides(asr_work)
    by_film: Dict[str, List[Dict]] = {}
    for w in wins:
        by_film.setdefault(w['film'], []).append(w)
    it_refs = {}
    for film, ws in sorted(by_film.items()):
        entry = (audit.get('films') or {}).get(film)
        if not entry:
            it_refs[film] = {'status': 'missing', 'reason': 'film assente da audit.json'}
            continue
        it_refs[film] = resolve_it_ref(entry, ov, ws, split_work, asr_work, extract_it, allow_pending_it, emit)
        emit(f"  [it-ref] {film}: {it_refs[film]['status']} {it_refs[film].get('sync', '')}")
    RN.write_json_atomic(split_work / 'it_refs.json', it_refs)
    it_cache: Dict[str, List[Dict]] = {}
    rows = []
    for w in wins:
        hp = hyp_dir / f"{w['win_id']}.json"
        h = AB.read_json(hp)
        if not h or h.get('status') not in ('ok', 'partial'):
            rows.append({'win_id': w['win_id'], 'film': w['film'], 'status': 'no_hyp',
                         'error': 'ipotesi mancante o fallita'})
            continue
        if h.get('wav_sha') != (w.get('sha') or {}).get(arm):
            rows.append({'win_id': w['win_id'], 'film': w['film'], 'status': 'stale',
                         'error': "ipotesi di un wav diverso da quello attuale"})
            continue
        d = split_work / 'build' / w['win_id']
        row = build_window(w, h['segments'], d, recompose_cfg)
        ref = it_refs.get(w['film'], {})
        row['it_ref_status'] = ref.get('status')
        if ref.get('status') in ('ok', 'sync_dubbia') and ref.get('path'):
            if ref['path'] not in it_cache:
                it_cache[ref['path']] = R.parse_srt(Path(ref['path']))
            cues = window_it_cues(it_cache[ref['path']], w['t0'], w['t1'])
            RN.write_json_atomic(d / 'it_ref.json', {'film': w['film'], 'status': ref['status'], 'cues': cues})
            row['midcut_ref_it'] = MC.midcut_stats(cues, 'it')
        row['asr_key'] = asr_key
        rows.append(row)
        if row['status'] == 'ok':
            emit(f"  {w['win_id']}: {row['n_blocks']} blocchi, {row['n_merged_units']} unita' fuse "
                 f"({row['n_merged_blocks']} blocchi), midcut formatter {row['midcut_fmt']['n_midcut']}")
        else:
            emit(f"  ⛔ {w['win_id']}: {row['status']} {row.get('error')}")
    AB.write_jsonl_atomic(split_work / 'build' / 'index.jsonl', rows)
    emit(f"✅ build: {sum(1 for r in rows if r['status'] == 'ok')}/{len(rows)} finestre pronte")
    return rows


# ══ TRANSLATE (GPU) ═════════════════════════════════════════════════════════

def translation_fingerprint(cfg, engine: str, llm_unit_budget: str) -> Dict:
    def g(k, d=None):
        try:
            return cfg.get(k, d)
        except Exception:
            return d
    try:
        beams = cfg.get_nllb_num_beams()
    except Exception:
        beams = g('nllb_num_beams', 7)
    try:
        abc = cfg.get_adaptive_batch_config()
    except Exception:
        abc = {k: g(k) for k in ('adaptive_batch_initial_size', 'adaptive_batch_min_size',
                                 'adaptive_batch_max_size')}
    fp = {'engine': engine, 'nllb_num_beams': beams, 'adaptive_batch': abc,
          'reservoir_engine': g('reservoir_engine', 'auto'), 'context': None, 'glossary': {}}
    if engine == 'llm':
        fp.update(llm_translator_model=g('llm_translator_model'), llm_translator_adapter=g('llm_translator_adapter'),
                  llm_translator_model_path=g('llm_translator_model_path'), llm_unit_budget=llm_unit_budget)
    return json.loads(json.dumps(fp, sort_keys=True, default=str))


def make_translator(engine: str):
    """get_translator REALE, con il controllo sul ripiego silenzioso: la
    factory, se NLLBFineTunedTranslator fallisce, restituisce NLLBTranslator
    base (sottoclasse-madre: isinstance non basterebbe)."""
    from core.translator import get_translator
    t = get_translator(model_type=engine, context=None, glossary={})
    want = EXPECTED_CLASS[engine]
    if type(t).__name__ != want:
        raise RuntimeError(f"get_translator('{engine}') ha restituito {type(t).__name__}, atteso {want}: "
                           f"ripiego silenzioso della factory, il run non misurerebbe il motore giusto")
    return t


@contextlib.contextmanager
def llm_unit_budget_patch(nblocks_by_uid: Dict[int, int]):
    """Solo nel processo del banco e solo durante la traduzione di units.srt:
    SubtitleUnit.budget ha un tetto di 84 caratteri (2 righe) per QUALUNQUE
    unita'; per un'unita' di k blocchi il tetto diventa 84*k. Le unita' di un
    blocco restano al valore di produzione."""
    from core.llm_subtitle_translator import prompt_builder as PB
    orig = PB.SubtitleUnit.budget

    def budget(self):
        k = nblocks_by_uid.get(self.id, 1)
        if k <= 1:
            return orig.fget(self)
        cap = PB.CPL_MAX * 2 * k
        if self.duration <= 0:
            return cap
        return max(12, min(int(self.duration * PB.CPS_MAX), cap))
    PB.SubtitleUnit.budget = property(budget)
    try:
        yield
    finally:
        PB.SubtitleUnit.budget = orig


def parse_audit(lines: Sequence[str]) -> Dict:
    out = {}
    for l in lines:
        m = _AUDIT_RE.search(l)
        if m:
            for part in m.group(1).split(' | '):
                if ': ' in part:
                    k, v = part.rsplit(': ', 1)
                    try:
                        out[k.strip()] = int(v)
                    except ValueError:
                        pass
            out['inglese residuo'] = int(m.group(2))
    return out


def _translate_one(translator, src: Path, dst: Path, logcap: RN.LogCapture) -> Tuple[bool, List[Dict], Dict, float]:
    k = logcap.mark()
    t0 = time.time()
    ok = translator.translate_file(input_path=str(src), output_path=str(dst), src_lang='en', tgt_lang='it',
                                   context=None)
    el = time.time() - t0
    blocks = srtio.parse_blocks(dst.read_text(encoding='utf-8')) if (ok and dst.exists()) else []
    return bool(ok), blocks, parse_audit(logcap.since(k)), el


def _polish(texts: List[str]) -> List[str]:
    """Stessa rifinitura di BaseTranslator._polish (postprocess.process con
    l'ordine temporale), applicata alla lista FINALE dei blocchi di B."""
    pp = prodmods.postprocess_module()
    res = pp.process({i: t for i, t in enumerate(texts)}, order=list(range(len(texts))))
    return [res.get(i, t) if t else t for i, t in enumerate(texts)]


def assemble_b(a_texts: List[str], unit_texts: Dict[int, str], mapping: Dict,
               cfg: Optional[Dict] = None) -> Dict:
    """Dal testo tradotto delle unita' ai blocchi finali di B (due varianti)."""
    rb, rep = RC.resplit(unit_texts, mapping, cfg)
    merged_pos = sorted(j for u in mapping['units'] if u['merged'] for j in u['blocks'])
    mset = set(merged_pos)
    b_full = [b['text'] for b in rb]
    b_iso = [rb[i]['text'] if i in mset else a_texts[i] for i in range(len(rb))]
    return {'b_full': _polish(b_full), 'b_iso': _polish(b_iso), 'drop': [bool(b['drop']) for b in rb],
            'times_b': [[b['start'], b['end']] for b in rb], 'resplit': rep, 'merged_positions': merged_pos}


def translator_alive(translator) -> bool:
    """False se il serbatoio L3 (BaseTranslator._reservoir_translate ->
    self.cleanup()) ha scaricato il modello: NLLBTranslator non lo ricarica e
    ogni translate_file successivo restituirebbe False."""
    return getattr(translator, 'model', True) is not None \
        and getattr(translator, 'batch_manager', True) is not None


def model_signature(translator) -> Optional[str]:
    """Precisione REALE del modello caricato (fp16 o 8-bit li sceglie il loader
    in base alla VRAM libera): A e B devono girare sullo stesso."""
    m = getattr(translator, 'model', None)
    if m is None or not hasattr(m, 'dtype'):
        return None
    return f"{m.dtype}|8bit={bool(getattr(m, 'is_loaded_in_8bit', False))}"


def translate_window(translator, engine: str, bdir: Path, odir: Path, row: Dict, fp: Dict,
                     llm_unit_budget: str, logcap: RN.LogCapture,
                     revive: Optional[Callable] = None) -> Dict:
    src_path, units_path = bdir / 'src.srt', bdir / 'units.srt'
    mapping = json.loads((bdir / 'mapping.json').read_text(encoding='utf-8'))
    src_blocks = srtio.parse_blocks(src_path.read_text(encoding='utf-8'))
    unit_blocks = srtio.parse_blocks(units_path.read_text(encoding='utf-8'))
    base = {'schema': SCHEMA_OUT, 'win_id': row['win_id'], 'film': row['film'], 'engine': engine,
            'fingerprint': fp, 'src_sha': row['src_sha'], 'units_sha': row['units_sha'], 'status': 'failed',
            'error': None}
    odir.mkdir(parents=True, exist_ok=True)
    if revive:
        translator = revive()
    sig_a = model_signature(translator)
    ok_a, a_blocks, audit_a, el_a = _translate_one(translator, src_path, odir / 'A.srt', logcap)
    if not ok_a or [b['index'] for b in a_blocks] != [b['index'] for b in src_blocks]:
        return {**base, 'error': f"braccio A: translate_file={ok_a}, blocchi {len(a_blocks)}/{len(src_blocks)}"}
    nblocks = {u['uid']: len(u['blocks']) for u in mapping['units']}
    patch = llm_unit_budget_patch(nblocks) if (engine == 'llm' and llm_unit_budget == 'span') \
        else contextlib.nullcontext()
    if revive:
        translator = revive()
    sig_b = model_signature(translator)
    if sig_a != sig_b:
        return {**base, 'error': f"modello diverso fra A ({sig_a}) e B ({sig_b}) dopo il ricaricamento"}
    with patch:
        ok_b, bu_blocks, audit_b, el_b = _translate_one(translator, units_path, odir / 'B_units.srt', logcap)
    if not ok_b or [b['index'] for b in bu_blocks] != [b['index'] for b in unit_blocks]:
        return {**base, 'error': f"braccio B: translate_file={ok_b}, unita' {len(bu_blocks)}/{len(unit_blocks)}"}
    a_texts = [b['text'] for b in a_blocks]
    asm = assemble_b(a_texts, {b['index']: b['text'] for b in bu_blocks}, mapping)
    times = [[b['start'], b['end']] for b in src_blocks]
    for name, texts in (('B_full', asm['b_full']), ('B_iso', asm['b_iso'])):
        RN.write_text_atomic(odir / f"{name}.srt", srtio.render(
            [{'start': s, 'end': e, 'text': t, 'drop': d}
             for (s, e), t, d in zip(asm['times_b'], texts, asm['drop'])], renumber=True))
    return {**base, 'status': 'ok', 'elapsed_s': {'A': round(el_a, 2), 'B': round(el_b, 2)},
            'model_signature': sig_a,
            'audit': {'A': audit_a, 'B': audit_b}, 'times': times, 'times_b': asm['times_b'],
            'src_texts': [b['text'] for b in src_blocks], 'a_texts': a_texts,
            'b_full_texts': asm['b_full'], 'b_iso_texts': asm['b_iso'], 'drop': asm['drop'],
            'units_src': {b['index']: b['text'] for b in unit_blocks},
            'units_translated': {b['index']: b['text'] for b in bu_blocks},
            'merged_positions': asm['merged_positions'], 'resplit': asm['resplit'],
            'merged_units': [{'uid': u['uid'], 'blocks': u['blocks']} for u in mapping['units'] if u['merged']]}


def out_is_current(path: Path, row: Dict, fp: Dict) -> bool:
    d = AB.read_json(path)
    return bool(d) and d.get('schema') == SCHEMA_OUT and d.get('status') == 'ok' \
        and d.get('fingerprint') == fp and d.get('src_sha') == row.get('src_sha') \
        and d.get('units_sha') == row.get('units_sha')


def translate(split_work: Path, engine: str, limit: int = 0, llm_unit_budget: str = 'span',
              factory: Optional[Callable] = None, cfg=None, emit: Callable = print) -> int:
    """GPU. factory/cfg servono ai test (traduttore finto); in uso reale
    restano None: GPU libera verificata, sandbox attivo, get_translator reale."""
    if factory is None:
        AB.require_gpu_free()
        cfg = sandbox.activate(split_work)
        factory = make_translator
    fp = translation_fingerprint(cfg, engine, llm_unit_budget)
    rows = [r for r in AB.read_jsonl(split_work / 'build' / 'index.jsonl') if r.get('status') == 'ok']
    if limit:
        rows = rows[:limit]
    out_dir = split_work / 'out' / engine
    todo = [r for r in rows if not out_is_current(out_dir / f"{r['win_id']}.json", r, fp)]
    emit(f"▶️ translate {engine}: {len(rows)} finestre, da fare {len(todo)}")
    run_id = time.strftime('%Y%m%d-%H%M%S') + f"_{engine}"
    t_start = time.time()
    counts = {'ok': 0, 'failed': 0}
    logcap = RN.LogCapture()
    translator = None

    def revive():
        nonlocal translator
        if not translator_alive(translator):
            emit("  ♻️ modello scaricato dal serbatoio L3: ricreo il traduttore")
            try:
                translator.cleanup()
            except Exception:
                pass
            translator = factory(engine)
            translator.set_log_callback(logcap)
        return translator

    try:
        if todo:
            translator = factory(engine)
            translator.set_log_callback(logcap)
        for k, r in enumerate(todo, 1):
            try:
                res = translate_window(translator, engine, split_work / 'build' / r['win_id'],
                                       out_dir / r['win_id'], r, fp, llm_unit_budget, logcap, revive)
            except Exception as e:
                res = {'schema': SCHEMA_OUT, 'win_id': r['win_id'], 'film': r['film'], 'engine': engine,
                       'fingerprint': fp, 'status': 'failed', 'error': f"{type(e).__name__}: {e}"[:500]}
            counts['ok' if res['status'] == 'ok' else 'failed'] += 1
            RN.write_json_atomic(out_dir / f"{r['win_id']}.json", res)
            emit(f"  [{k}/{len(todo)}] {r['win_id']}: {res['status']}" + (f" — {res['error']}" if res.get('error') else ''))
            if k % 5 == 0 and sandbox._state.get('active'):
                sandbox.check_real_config()
    finally:
        if translator is not None:
            try:
                translator.cleanup()
            except Exception:
                pass
    RN.write_text_atomic(split_work / 'logs' / f"{run_id}.log", '\n'.join(logcap.lines))
    AB.append_csv(split_work / 'runs_split.csv', RUN_COLUMNS, {
        'run_id': run_id, 'engine': engine, 'n_windows': len(rows), 'n_done': counts['ok'],
        'n_failed': counts['failed'], 'n_skipped': len(rows) - len(todo), 'total_s': round(time.time() - t_start, 1),
        'fingerprint': json.dumps(fp, sort_keys=True), 'rules_sha': rules_sha(),
        'llm_unit_budget': llm_unit_budget if engine == 'llm' else '',
        'config_set_calls': json.dumps(sandbox.set_calls(), ensure_ascii=False)})
    if sandbox._state.get('active'):
        sandbox.check_real_config()
    emit(f"✅ {run_id}: ok={counts['ok']} falliti={counts['failed']}")
    return 0 if counts['failed'] == 0 else 6


RUN_COLUMNS = ['run_id', 'engine', 'n_windows', 'n_done', 'n_failed', 'n_skipped', 'total_s', 'fingerprint',
               'rules_sha', 'llm_unit_budget', 'config_set_calls']
