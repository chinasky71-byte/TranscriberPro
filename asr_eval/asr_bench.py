"""
asr_eval - banco di accuratezza ASR contro i sottotitoli professionali
File: asr_eval/asr_bench.py

Uso (SEMPRE con l'interprete del venv principale, MAI con la coda di
Transcriber Pro attiva: prepare/run rifiutano se la GPU e' occupata):

    venv\\Scripts\\python.exe asr_eval\\asr_bench.py <sottocomando> ...

Sottocomandi:
    audit       ffprobe + estrazione sub + provenienza/fedelta' (solo CPU)
    plan        scelta delle finestre dai soli sottotitoli (solo CPU)
    prepare     audio finestre + Demucs + sfasamento + chunk (GPU, una volta)
    run         un motore x un braccio in QUESTO processo (GPU)
    run-all     un sottoprocesso nuovo per ogni motore x braccio, poi score+report
    score       punteggi per finestra -> scores.csv (solo CPU)
    report      statistica e verdetto secondo decision_rules.py (solo CPU)
    gold-make   esporta le finestre del set d'oro in file di testo editabili
    gold-score  ricalcola la classifica sull'oro e la confronta con i sub

REGOLA FERREA: nessun Config.set(), nessuna scrittura della config reale
(v. sandbox.py); nessun EngineRouter (niente ripieghi silenziosi).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent
for p in (str(HERE), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sandbox  # noqa: E402  (sempre per primo fra i moduli del banco)
import decision_rules as DR  # noqa: E402
import metrics as M  # noqa: E402
import normalize as NZ  # noqa: E402
import refs as R  # noqa: E402
import runners as RN  # noqa: E402
import stats as ST  # noqa: E402
import windows as W  # noqa: E402

DEFAULT_ROOT = Path(r"Z:\OMV_CONDIVISA\QBDownloads\ItaTorrents_Upload")
DEFAULT_WORK = HERE / 'work'
VIDEO_EXT = ('.mkv', '.mp4', '.avi')
ENGINE_LANGS = {'whisper': ('en', 'it'), 'qwen3': ('en', 'it'), 'canary': ('en',), 'w2v': ('en', 'it')}
RUN_ORDER = [('whisper', 'vocals'), ('qwen3', 'vocals'), ('canary', 'vocals'),
             ('whisper', 'raw'), ('qwen3', 'raw'), ('canary', 'raw')]
DEFAULT_ENGINE_CHUNK_CAP_S = {'canary': 35.0, 'qwen3': 150.0, 'faster-whisper': 30.0}
ENGINE_CORE_NAME = {'canary': 'canary', 'qwen3': 'qwen3', 'whisper': 'faster-whisper'}

SCORE_COLUMNS = [
    'win_id', 'film', 'lang', 'role', 'group', 'origin', 'tag', 'engine', 'arm', 'status', 'error',
    'dur_s', 'n_ref', 'n_hyp', 'S', 'D', 'I', 'wer', 'n_ref_c', 'n_hyp_c', 'Sc', 'Dc', 'Ic', 'Cc', 'werc',
    'n_cues_ge3', 'n_missed', 'n_halluc', 'halluc_words', 'energy_available',
    'names_total', 'names_hit', 'num_total', 'num_hit', 'n_timing', 'timing_med_abs_s', 'timing_med_s',
    'hyp_end_punct', 'hyp_cap_start', 'ref_end_punct', 'ref_cap_start',
    'hyp_midcut', 'hyp_midcut_n', 'hyp_midcut_den', 'fmt_midcut', 'fmt_midcut_n', 'fmt_midcut_den',
    'ref_midcut', 'ref_midcut_n', 'ref_midcut_den',
    'elapsed_s', 'vram_peak_mb', 'n_failed_chunks', 'hit_mask', 'norm_version',
]
RUN_COLUMNS = ['run_id', 'engine', 'arm', 'started', 'n_windows', 'n_done', 'n_skipped', 'n_failed',
               'n_partial', 'load_s', 'total_s', 'vram_baseline_mb', 'vram_peak_mb', 'fingerprint',
               'decision_rules_sha', 'norm_version', 'config_set_calls']


def emit(msg: str) -> None:
    print(msg, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def rules_sha() -> str:
    return sha256_file(HERE / 'decision_rules.py')


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def read_jsonl(path: Path) -> List[Dict]:
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]


def write_jsonl_atomic(path: Path, rows: Sequence[Dict]) -> None:
    RN.write_text_atomic(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def write_csv_atomic(path: Path, columns: Sequence[str], rows: Sequence[Dict], delimiter=',') -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), extrasaction='ignore', delimiter=delimiter)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    RN.write_text_atomic(path, buf.getvalue(), encoding='utf-8-sig' if delimiter == ';' else 'utf-8')


def append_csv(path: Path, columns: Sequence[str], row: Dict) -> None:
    rows = []
    if Path(path).exists():
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    rows.append(row)
    write_csv_atomic(path, columns, rows)


def require_gpu_free() -> None:
    reasons = RN.gpu_busy_reasons()
    if reasons:
        emit("❌ GPU NON libera: il banco rifiuta di partire (non disturbare la coda di Transcriber Pro).")
        for r in reasons:
            emit(f"   - {r}")
        sys.exit(3)


# ── chunk: stessi limiti per motore di AudioProcessor.process_for_transcription ──

def chunk_profile(engine: str, cfg, caps: Optional[Dict[str, float]] = None) -> Tuple[str, Tuple[float, float, float]]:
    """Replica AudioProcessor.__init__ (validazione) + process_for_transcription
    (cap per motore, righe 143-163): chiamando chunk_audio_intelligent a mano
    il cap NON verrebbe applicato."""
    caps = caps or DEFAULT_ENGINE_CHUNK_CAP_S
    target = int(cfg.get('asr_chunk_target_duration', 20))
    min_d = int(cfg.get('asr_chunk_min_duration', 10))
    max_d = int(cfg.get('asr_chunk_max_duration', 25))
    if not (0 < min_d < target <= max_d):
        target, min_d, max_d = 20, 10, 25
    t, mn, mx = float(target), float(min_d), float(max_d)
    cap = caps.get(ENGINE_CORE_NAME.get(engine, engine))
    if cap is not None and mx > cap:
        mx = cap
        t = min(t, mx * 0.8)
        mn = min(mn, t * 0.5)
    return f"t{t:g}_m{mn:g}_x{mx:g}", (t, mn, mx)


def run_fingerprint(engine: str, arm: str, cfg) -> Dict:
    fp = {'engine': engine, 'arm': arm, 'settings': sandbox.fingerprint(cfg), 'norm': NZ.NORM_VERSION}
    if engine in ('qwen3', 'canary'):
        fp['chunk_profile'] = chunk_profile(engine, cfg)[0]
    return fp


# ══ AUDIT ═══════════════════════════════════════════════════════════════════

def _overrides(work: Path) -> Dict:
    return read_json(work / 'audit_overrides.json', {}) or {}


def _listen_results(work: Path) -> Dict[str, List[str]]:
    path = work / 'listen_check.csv'
    out: Dict[str, List[str]] = {}
    if not path.exists():
        return out
    text = path.read_text(encoding='utf-8-sig')
    delim = ';' if text.splitlines()[0].count(';') >= text.splitlines()[0].count(',') else ','
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        key = f"{r.get('film')}#{r.get('track')}"
        out.setdefault(key, []).append((r.get('ok') or '').strip().upper())
    return out


def audit_film(video: Path, work: Path, *, extract: bool, today: date) -> Dict:
    probe = R.ffprobe(video)
    name = video.name
    key = R.film_key(name)
    fmt = probe.get('format') or {}
    entry = {'file': str(video), 'name': name, 'key': key,
             'duration': float(fmt.get('duration') or 0), 'format_start': float(fmt.get('start_time') or 0),
             'audio': [], 'subs': []}
    for s in probe.get('streams', []):
        tags = s.get('tags') or {}
        if s.get('codec_type') == 'audio':
            entry['audio'].append({'index': s['index'], 'lang': R.lang3(s), 'title': tags.get('title', ''),
                                   'channels': s.get('channels'), 'start_time': float(s.get('start_time') or 0)})
        elif s.get('codec_type') == 'subtitle':
            status, reasons = R.provenance(s, name, today)
            entry['subs'].append({
                'index': s['index'], 'lang': R.lang3(s), 'lang_raw': tags.get('language', ''),
                'codec': s.get('codec_name'), 'text': s.get('codec_name') in R.TEXT_SUB_CODECS,
                'title': tags.get('title', ''), 'kind': R.sub_kind(s),
                'start_time': float(s.get('start_time') or 0),
                'writing_date': tags.get('_STATISTICS_WRITING_DATE_UTC', ''),
                'frames': tags.get('NUMBER_OF_FRAMES'),
                'provenance': status, 'provenance_reasons': reasons})
    en_group = R.group_of(name, DR.FILM_GROUPS['en'])
    it_spec = _it_spec(name)
    wanted = []
    for sub in entry['subs']:
        if not sub['text'] or sub['kind'] == 'forced':
            continue
        if (sub['lang'] == 'eng' and en_group) or (sub['lang'] == 'ita' and it_spec):
            wanted.append(sub)
    sub_dir = work / 'subs' / key
    todo = [(s['index'], s['codec'], sub_dir / f"{s['index']}.srt") for s in wanted
            if not (sub_dir / f"{s['index']}.srt").exists()]
    if extract and todo:
        emit(f"  📥 estrazione di {len(todo)} tracce testo in un passaggio...")
        R.extract_subs(video, todo)
    cues_by_idx = {}
    for s in wanted:
        p = sub_dir / f"{s['index']}.srt"
        if p.exists():
            s['path'] = str(p)
            cues = R.parse_srt(p)
            cues_by_idx[s['index']] = cues
            lang2 = 'en' if s['lang'] == 'eng' else 'it'
            s.update(n_cues=len(cues), n_words=len(R.cue_tokens(cues, lang2)),
                     wpm=round(R.words_per_minute(cues, lang2) or 0, 1),
                     music_cues=sum(c['music'] for c in cues), sound_cues=sum(c['sound_only'] for c in cues),
                     italic_cues=sum(c['italic'] for c in cues))
    eng = [s for s in wanted if s['lang'] == 'eng' and s['index'] in cues_by_idx]
    normal = next((s for s in eng if s['kind'] == 'normal'), None)
    sdh = next((s for s in eng if s['kind'] == 'sdh'), None)
    entry['en_cmp'] = R.en_choice(cues_by_idx.get(normal['index']) if normal else None,
                                  cues_by_idx.get(sdh['index']) if sdh else None, DR.EN_SDH_SAME_LCS)
    entry['en_cmp'].update(normal=normal['index'] if normal else None, sdh=sdh['index'] if sdh else None)
    ita = [s for s in wanted if s['lang'] == 'ita' and s['index'] in cues_by_idx]
    it_normal = next((s for s in ita if s['kind'] == 'normal'), None)
    fid_rules = {'translation_lcs': DR.IT_FIDELITY_TRANSLATION_LCS, 'min_wpm_excess': DR.IT_FIDELITY_MIN_WPM_EXCESS}
    for s in ita:
        if it_spec and it_spec['origin'] == 'nato_ita':
            s['fidelity'] = {'decision': 'nato_ita'}
        elif s['kind'] == 'normal':
            s['fidelity'] = {'decision': 'normale_film_doppiato'}
        elif it_normal is None:
            s['fidelity'] = {'decision': 'senza_confronto'}
        else:
            s['fidelity'] = R.fidelity_it(cues_by_idx[s['index']], cues_by_idx[it_normal['index']], fid_rules)
    return entry


def _it_spec(name: str) -> Optional[Dict]:
    low = name.lower()
    for k, v in DR.FILM_GROUPS['it']['candidates'].items():
        if k in low:
            return dict(v, match=k)
    return None


def _usable(entry: Dict, idx: int, ov: Dict) -> str:
    """'ok' | 'pending' | 'no' per la provenienza di una traccia."""
    s = next((x for x in entry['subs'] if x['index'] == idx), None)
    if s is None:
        return 'no'
    o = (ov.get('tracks') or {}).get(f"{entry['key']}#{idx}")
    if o == 'reject':
        return 'no'
    if o == 'accept':
        return 'ok'
    return {'ok': 'ok', 'confirm': 'pending'}.get(s['provenance'], 'no')


def resolve_refs(entry: Dict, ov: Dict, listen: Dict[str, List[str]]) -> Dict[str, Dict]:
    """Decide il riferimento EN e IT del film applicando regole + override."""
    name = entry['name']
    out = {}
    en_group = R.group_of(name, DR.FILM_GROUPS['en'])
    has_eng_audio = any(a['lang'] == 'eng' for a in entry['audio'])
    if not en_group:
        out['en'] = {'status': 'excluded', 'reason': 'fuori dai gruppi EN'}
    elif not has_eng_audio:
        out['en'] = {'status': 'excluded', 'reason': 'nessuna traccia audio inglese'}
    else:
        cmp_ = entry.get('en_cmp') or {}
        order = ['normal', 'sdh'] if cmp_.get('use') == 'normal' else ['sdh', 'normal']
        chosen, st = None, 'excluded'
        for kind in order:
            idx = cmp_.get(kind)
            if idx is None:
                continue
            u = _usable(entry, idx, ov)
            if u != 'no':
                chosen, st = idx, u
                break
        out['en'] = {'status': 'ok' if st == 'ok' else ('pending_provenienza' if st == 'pending' else 'excluded'),
                     'reason': '' if chosen is not None else 'nessun sub ENG utilizzabile',
                     'ref_index': chosen, 'group': en_group, 'rule': cmp_,
                     'audio_index': next((a['index'] for a in entry['audio'] if a['lang'] == 'eng'), None)}
    spec = _it_spec(name)
    excluded_it = any(k in name.lower() for k in DR.FILM_GROUPS['it']['excluded'])
    if not spec or excluded_it:
        out['it'] = {'status': 'excluded', 'reason': 'non candidato IT'}
        return out
    prefer = spec['prefer']
    ita = [s for s in entry['subs'] if s['lang'] == 'ita' and s.get('fidelity')]
    rank = {'dubtitle': 0, 'sdh': 1, 'normal': 2}
    if prefer == 'sdh':
        rank = {'sdh': 0, 'dubtitle': 1, 'normal': 2}
    ita.sort(key=lambda s: rank.get(s['kind'], 9))
    forced_dec = ov.get('it_decision') or {}
    chosen = None
    status, reason = 'excluded', 'nessuna traccia ITA fedele al doppiaggio'
    for s in ita:
        dec = forced_dec.get(f"{entry['key']}#{s['index']}") or s['fidelity']['decision']
        if dec not in ('candidato', 'senza_confronto', 'nato_ita'):
            continue
        u = _usable(entry, s['index'], ov)
        if u == 'no':
            continue
        chosen = s
        if u == 'pending':
            status, reason = 'pending_provenienza', 'conferma manuale della provenienza'
            break
        votes = [v for v in listen.get(f"{entry['key']}#{s['index']}", []) if v in ('S', 'N')]
        if len(votes) < 5:
            status, reason = 'pending_ascolto', f"controllo d'ascolto incompleto ({len(votes)}/5)"
        elif votes.count('S') >= DR.IT_LISTEN_MIN_OK:
            status, reason = 'ok', ''
        else:
            status, reason = 'excluded', f"ascolto: solo {votes.count('S')}/5 fedeli"
        break
    out['it'] = {'status': status, 'reason': reason, 'ref_index': chosen['index'] if chosen else None,
                 'group': spec['group'], 'origin': spec['origin'],
                 'fidelity': chosen['fidelity'] if chosen else None,
                 'audio_index': next((a['index'] for a in entry['audio'] if a['lang'] == 'ita'), None)}
    return out


def _write_overrides_template(work: Path, audit: Dict) -> None:
    path = work / 'audit_overrides.json'
    ov = read_json(path, {}) or {}
    tracks = ov.setdefault('tracks', {})
    ov.setdefault('it_decision', {})
    ov['_istruzioni'] = ("tracks: 'accept'|'reject' per le tracce con provenienza da confermare (null = "
                         "non deciso). it_decision: forza la decisione di fedelta' ('candidato').")
    for e in audit['films'].values():
        for s in e['subs']:
            k = f"{e['key']}#{s['index']}"
            if s['provenance'] == 'confirm' and s.get('path') and k not in tracks:
                tracks[k] = None
    RN.write_json_atomic(path, ov)


def _write_listen_check(work: Path, audit: Dict, clips: bool) -> None:
    path = work / 'listen_check.csv'
    existing = {}
    if path.exists():
        text = path.read_text(encoding='utf-8-sig')
        for r in csv.DictReader(io.StringIO(text), delimiter=';'):
            existing[(r['film'], r['track'], r['n'])] = r
    rows = []
    ov = _overrides(work)
    for e in audit['films'].values():
        res = resolve_refs(e, ov, {})
        it = res.get('it') or {}
        idx = it.get('ref_index')
        if idx is None or not (work / 'subs' / e['key'] / f"{idx}.srt").exists():
            continue
        cues = [c for c in R.parse_srt(Path(work / 'subs' / e['key'] / f"{idx}.srt"))
                if not c['music'] and len(NZ.normalize_text(c['text'], 'it')) >= 3
                and DR.WINDOW_RULES['range'][0] * e['duration'] <= c['s'] <= DR.WINDOW_RULES['range'][1] * e['duration']]
        rng = random.Random(f"listen:{e['key']}:{idx}")
        pick = sorted(rng.sample(cues, min(5, len(cues))), key=lambda c: c['s'])
        for n, c in enumerate(pick, 1):
            clip = work / 'listen' / f"{e['key']}_{idx}_{n}.wav"
            if clips and not clip.exists() and it.get('audio_index') is not None:
                R.extract_clip(Path(e['file']), it['audio_index'], c['s'] - 3.0, c['e'] - c['s'] + 6.0, clip)
            prev = existing.get((e['key'], str(idx), str(n)), {})
            rows.append({'film': e['key'], 'track': idx, 'n': n, 'start': f"{c['s']:.2f}", 'end': f"{c['e']:.2f}",
                         'text': c['text'].replace('\n', ' / '), 'clip': str(clip) if clip.exists() else '',
                         'ok': prev.get('ok', '')})
    write_csv_atomic(path, ['film', 'track', 'n', 'start', 'end', 'text', 'clip', 'ok'], rows, delimiter=';')


def cmd_audit(args) -> int:
    work: Path = args.work
    root: Path = args.root
    work.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT)
    if args.films:
        keys = [k.strip().lower() for k in args.films.split(',') if k.strip()]
        files = [p for p in files if any(k in p.name.lower() for k in keys)]
    audit = read_json(work / 'audit.json', {'schema': 'asr-bench/audit/1', 'films': {}})
    today = date.today()
    for f in files:
        emit(f"🔎 {f.name}")
        entry = audit_film(f, work, extract=not args.no_extract, today=today)
        audit['films'][entry['key']] = entry
    audit['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    RN.write_json_atomic(work / 'audit.json', audit)
    _write_overrides_template(work, audit)
    _write_listen_check(work, audit, clips=args.clips)
    ov, listen = _overrides(work), _listen_results(work)
    emit("\nRiepilogo riferimenti:")
    for e in audit['films'].values():
        res = resolve_refs(e, ov, listen)
        for lang in ('en', 'it'):
            r = res[lang]
            if r['status'] == 'excluded' and r.get('reason') in ('fuori dai gruppi EN', 'non candidato IT'):
                continue
            emit(f"  [{lang}] {e['key']:<34} {r['status']:<20} traccia={r.get('ref_index')} "
                 f"gruppo={r.get('group')} {r.get('reason', '')}")
        n_conf = sum(1 for s in e['subs'] if s['provenance'] == 'confirm')
        n_rej = sum(1 for s in e['subs'] if s['provenance'] == 'reject')
        if n_conf or n_rej:
            emit(f"       provenienza: {n_conf} da confermare, {n_rej} scartate automaticamente")
    emit(f"\n✅ audit.json, audit_overrides.json, listen_check.csv in {work}")
    return 0


# ══ PLAN (scelta finestre, solo CPU) ═════════════════════════════════════════

def build_plan(work: Path, audit: Dict, only: Optional[List[str]] = None) -> Dict:
    ov, listen = _overrides(work), _listen_results(work)
    plan = {'schema': 'asr-bench/plan/1', 'film_langs': {}, 'blocked': []}
    for e in audit['films'].values():
        if only and not any(k in e['name'].lower() for k in only):
            continue
        res = resolve_refs(e, ov, listen)
        for lang in ('en', 'it'):
            r = res[lang]
            if r['status'] != 'ok':
                if r['status'].startswith('pending'):
                    plan['blocked'].append(f"[{lang}] {e['key']}: {r['status']} ({r.get('reason', '')})")
                continue
            cues = R.parse_srt(work / 'subs' / e['key'] / f"{r['ref_index']}.srt")
            is_dev = lang == 'en' and r['group'] == 'dev'
            n_extra = DR.WINDOW_RULES['it_dev_windows_office_romance'] if (
                lang == 'it' and 'office romance' in e['name'].lower()) else 0
            wins = W.select_windows(cues, e['duration'], lang, DR.WINDOW_RULES, e['key'], n_extra=n_extra)
            n_test = 0
            n_dev = 0
            out_wins = []
            for w in wins:
                role = 'dev' if (is_dev or w['role'] == 'dev') else 'test'
                if role == 'test':
                    n_test += 1
                    tag = f"{n_test:02d}"
                    idx = n_test
                else:
                    n_dev += 1
                    tag = f"dev{n_dev}"
                    idx = 0
                inside = W.cues_inside(cues, w['t0'], w['t1'])
                margin = DR.WINDOW_RULES['pad_s'] + DR.SYNC_RULES['search_s']
                around = [c for c in cues if c['e'] > w['t0'] - margin and c['s'] < w['t1'] + margin]
                out_wins.append({
                    'win_id': f"{lang}__{e['key']}__{tag}", 'film': e['key'], 'lang': lang, 'role': role,
                    'tag': tag, 'idx': idx, 't0': w['t0'], 't1': w['t1'], 'dur': round(w['t1'] - w['t0'], 3),
                    'stats': {k: w[k] for k in ('n_cues', 'n_words', 'music_frac', 'sound_frac', 'italic_frac')},
                    'cues_film': inside, 'cues_sync': around})
            fl = f"{lang}__{e['key']}"
            plan['film_langs'][fl] = {
                'film': e['key'], 'file': e['file'], 'name': e['name'], 'lang': lang,
                'group': r['group'], 'origin': r.get('origin'), 'ref_index': r['ref_index'],
                'audio_index': r['audio_index'], 'duration': e['duration'],
                'names': R.names_from_cues(cues, lang), 'windows': out_wins,
                'n_valid_bands': sum(1 for w in out_wins if w['role'] == 'test')}
    return plan


def cmd_plan(args) -> int:
    work: Path = args.work
    audit = read_json(work / 'audit.json')
    if not audit:
        emit("❌ audit.json mancante: lancia 'audit' prima")
        return 2
    only = [k.strip().lower() for k in args.films.split(',')] if args.films else None
    plan = build_plan(work, audit, only)
    RN.write_json_atomic(work / 'plan.json', plan)
    for fl, p in plan['film_langs'].items():
        emit(f"  {fl:<40} gruppo={p['group']:<10} finestre test={p['n_valid_bands']} "
             f"dev={sum(1 for w in p['windows'] if w['role'] == 'dev')} nomi={len(p['names'])}")
    for b in plan['blocked']:
        emit(f"  ⛔ {b}")
    emit(f"✅ plan.json scritto ({len(plan['film_langs'])} film-lingua)")
    return 0


# ══ PREPARE (GPU) ═════════════════════════════════════════════════════════════

def _ffmpeg_audio(video: Path, audio_index: int, t0: float, dur: float, dest: Path) -> None:
    """Stessi parametri di AudioTrackSelector.extract_audio_track, con -ss/-t."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{max(0.0, t0):.3f}', '-t', f'{dur:.3f}',
                        '-i', str(video), '-map', f'0:{audio_index}', '-vn', '-acodec', 'pcm_s16le',
                        '-ar', '16000', '-ac', '1', str(dest)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900,
                       **RN._NO_WINDOW)
    if r.returncode != 0 or not dest.exists():
        raise RuntimeError(f"ffmpeg fallito ({dest.name}): {r.stderr.strip()[:300]}")


def _cut(src: Path, dest: Path, start_s: float, dur_s: float, subtype: str) -> None:
    import soundfile as sf
    y, sr = sf.read(str(src), dtype='float32', always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    a = int(round(start_s * sr))
    b = a + int(round(dur_s * sr))
    if a < 0 or b > len(y):
        raise RuntimeError(f"taglio fuori dal file imbottito ({src.name}: {a}-{b} su {len(y)})")
    tmp = dest.with_suffix('.tmp.wav')
    sf.write(str(tmp), y[a:b], sr, subtype=subtype)
    os.replace(tmp, dest)


def cmd_prepare(args) -> int:
    work: Path = args.work
    plan = read_json(work / 'plan.json')
    if not plan:
        emit("❌ plan.json mancante: lancia 'plan' prima")
        return 2
    if plan.get('blocked'):
        emit("⛔ Riferimenti in attesa di conferma manuale (non inclusi finche' non decisi):")
        for b in plan['blocked']:
            emit(f"   - {b}")
        if not args.allow_blocked:
            emit("   Completa audit_overrides.json / listen_check.csv e rilancia 'plan', "
                 "oppure passa --allow-blocked per preparare solo i film gia' pronti.")
            return 4
    require_gpu_free()
    cfg = sandbox.activate(work)
    from core.engines.faster_whisper_engine import FasterWhisperEngine
    import numpy as np

    whisper = FasterWhisperEngine(log_callback=emit)
    whisper.load()   # ctranslate2 inizializza CUDA per primo (STEP 2.5 della pipeline)
    from core.audio_processor import AudioProcessor, ENGINE_CHUNK_CAP_S
    ap = AudioProcessor()
    ap.set_log_callback(emit)
    pad = DR.WINDOW_RULES['pad_s']
    only = [k.strip().lower() for k in args.films.split(',')] if args.films else None
    prep_dir = work / 'prep'
    try:
        for fl, p in plan['film_langs'].items():
            if only and not any(k in p['name'].lower() for k in only):
                continue
            out_path = prep_dir / f"{fl}.json"
            if out_path.exists() and not args.force:
                emit(f"⏭️ {fl} gia' preparato")
                continue
            emit(f"\n🎬 {fl} ({len(p['windows'])} finestre)")
            video = Path(p['file'])
            items = []
            for w in p['windows']:
                wd = work / 'win' / w['win_id']
                raw_pad = wd / 'raw_pad.wav'
                _ffmpeg_audio(video, p['audio_index'], w['t0'] - pad, w['dur'] + 2 * pad, raw_pad)
                voc_pad = ap.separate_vocals(raw_pad)
                if not voc_pad or not Path(voc_pad).exists():
                    raise RuntimeError(f"Demucs fallito su {w['win_id']}")
                items.append((W.rms_db_from_wav(Path(voc_pad)), w['cues_sync'], w['t0'] - pad))
                sandbox.check_real_config()
            sync = W.estimate_offset(items, DR.SYNC_RULES)
            per_win = [W.estimate_offset([it], DR.SYNC_RULES)['offset_s'] for it in items]
            sync['per_window_offsets'] = per_win
            emit(f"  ⏱️ sfasamento {sync['offset_s']:+.2f}s phi={sync['phi']:.3f} "
                 f"(a 0: {sync['phi_at_zero']:.3f}) applicato={sync['apply_s']:+.2f}s "
                 f"per finestra={per_win}")
            lid = []
            recs = []
            if sync['ok']:
                apply = sync['apply_s']
                for w in p['windows']:
                    wd = work / 'win' / w['win_id']
                    raw, voc = wd / 'raw.wav', wd / 'vocals.wav'
                    _cut(wd / 'raw_pad.wav', raw, pad + apply, w['dur'], 'PCM_16')
                    _cut(wd / 'raw_pad_vocals.wav', voc, pad + apply, w['dur'], 'FLOAT')
                    np.save(wd / 'vocals_rms.npy', W.rms_db_from_wav(voc))
                    chunks = {}
                    engines = ('canary', 'qwen3') if p['lang'] == 'en' else ('qwen3',)
                    for eng in engines:
                        key, (t, mn, mx) = chunk_profile(eng, cfg, ENGINE_CHUNK_CAP_S)
                        if key in chunks:
                            continue
                        orig = (ap.CHUNK_TARGET_DURATION, ap.CHUNK_MIN_DURATION, ap.CHUNK_MAX_DURATION)
                        ap.CHUNK_TARGET_DURATION, ap.CHUNK_MIN_DURATION, ap.CHUNK_MAX_DURATION = t, mn, mx
                        try:
                            times = ap.chunk_audio_intelligent(voc)
                        finally:
                            ap.CHUNK_TARGET_DURATION, ap.CHUNK_MIN_DURATION, ap.CHUNK_MAX_DURATION = orig
                        if not times:
                            raise RuntimeError(f"chunking fallito su {w['win_id']}")
                        for arm, src in (('vocals', voc), ('raw', raw)):
                            d = wd / 'chunks' / key / arm
                            d.mkdir(parents=True, exist_ok=True)
                            made = ap._create_physical_chunks(src, times, d)
                            if len(made) != len(times):
                                raise RuntimeError(f"chunk fisici incompleti su {w['win_id']}/{arm}")
                        chunks[key] = [[round(a, 3), round(b, 3)] for a, b in times]
                    if len(lid) < 3:
                        from faster_whisper.audio import decode_audio
                        audio = decode_audio(str(raw), sampling_rate=16000)[:16000 * 30]
                        wm = getattr(whisper.faster_whisper_model, 'model', whisper.faster_whisper_model)
                        lang_d, prob, _ = wm.detect_language(audio=audio)
                        lid.append({'win_id': w['win_id'], 'lang': lang_d, 'prob': round(float(prob), 3)})
                    cues_rel = [{**c, 's': round(c['s'] - w['t0'], 3), 'e': round(c['e'] - w['t0'], 3)}
                                for c in w['cues_film']]
                    recs.append({k: v for k, v in w.items() if k not in ('cues_film', 'cues_sync')} | {
                        'group': p['group'], 'origin': p.get('origin'), 'ref_index': p['ref_index'],
                        'audio_index': p['audio_index'], 'offset_apply_s': apply,
                        'sha': {'raw': sha256_file(raw), 'vocals': sha256_file(voc)},
                        'chunks': chunks, 'names': p['names'], 'cues': cues_rel})
                    for f in ('raw_pad.wav', 'raw_pad_vocals.wav'):
                        try:
                            (wd / f).unlink()
                        except OSError:
                            pass
            lid_bad = sum(1 for x in lid if x['lang'] != p['lang'])
            status = 'ok' if sync['ok'] and lid_bad < 2 else 'excluded'
            reason = '' if status == 'ok' else ('sincronia debole' if not sync['ok'] else 'LID diversa dal tag')
            RN.write_json_atomic(out_path, {'film_lang': fl, 'status': status, 'reason': reason, 'sync': sync,
                                            'lid': lid, 'windows': recs if status == 'ok' else [],
                                            'meta': {k: v for k, v in p.items() if k != 'windows'}})
            emit(f"  {'✅' if status == 'ok' else '⛔'} {fl}: {status} {reason} LID={lid}")
            sandbox.check_real_config()
    finally:
        ap.cleanup_model()
        whisper.unload()
    _rebuild_windows(work)
    sandbox.check_real_config()
    return 0


def _rebuild_windows(work: Path) -> None:
    rows, films = [], {}
    for pth in sorted((work / 'prep').glob('*.json')):
        d = read_json(pth)
        films[d['film_lang']] = {'status': d['status'], 'reason': d['reason'], 'sync': d['sync'],
                                 'lid': d['lid'], **d['meta']}
        rows.extend(d['windows'])
    write_jsonl_atomic(work / 'windows.jsonl', rows)
    RN.write_json_atomic(work / 'films.json', films)
    emit(f"✅ windows.jsonl: {len(rows)} finestre, films.json: {len(films)} film-lingua")


# ══ RUN (GPU) ══════════════════════════════════════════════════════════════════

def windows_for(work: Path, engine: str, arm: str, langs: Optional[Sequence[str]] = None) -> List[Dict]:
    wins = [w for w in read_jsonl(work / 'windows.jsonl') if w['lang'] in ENGINE_LANGS[engine]]
    if langs:
        wins = [w for w in wins if w['lang'] in langs]
    if arm == 'raw':
        wins = [w for w in wins if w['role'] == 'test' and w['idx'] % 2 == 1]
    return wins


def _chunks_of(work: Path, w: Dict, profile: str, arm: str) -> List[Tuple[str, float, float]]:
    if profile not in w['chunks']:
        raise RuntimeError(f"profilo chunk {profile} non preparato per {w['win_id']} "
                           f"(preparati: {list(w['chunks'])}): la config e' cambiata dopo 'prepare'")
    d = work / 'win' / w['win_id'] / 'chunks' / profile / arm
    return [(str(d / f"chunk_{i + 1:04d}.wav"), a, b) for i, (a, b) in enumerate(w['chunks'][profile])]


def _hyp_record(w: Dict, engine: str, arm: str, res: Dict, wav_sha: str, fp: Dict, vram) -> Dict:
    return {'schema': RN.SCHEMA_HYP, 'win_id': w['win_id'], 'engine': engine, 'arm': arm,
            'lang': w['lang'], 'status': res['status'], 'error': res.get('error'),
            'n_failed_chunks': res.get('n_failed_chunks', 0), 'n_aligner_failed': res.get('n_aligner_failed', 0),
            'segments': res['segments'], 'elapsed_s': res['elapsed_s'], 'audio_s': w['dur'],
            'vram_peak_mb': vram, 'wav_sha': wav_sha, 'fingerprint': fp,
            'detected_lang': res.get('detected_lang'), 'group_size': res.get('group_size'),
            'group_elapsed_s': res.get('group_elapsed_s')}


def _vram_delta(peak, mon) -> Optional[float]:
    """Picco sopra la base misurata prima del caricamento del modello (la
    memoria totale include browser e overlay: la base li toglie)."""
    if peak is None or mon.baseline is None:
        return None
    return round(peak - mon.baseline, 0)


def cmd_run(args) -> int:
    work: Path = args.work
    engine, arm = args.engine, args.arm
    if engine == 'w2v':
        emit("❌ --engine w2v (arbitro wav2vec2-xlsr-53): NON IMPLEMENTATO in questa versione del banco.")
        return 5
    require_gpu_free()
    cfg = sandbox.activate(work)
    fp = run_fingerprint(engine, arm, cfg)
    langs = [l.strip() for l in args.lang.split(',')] if args.lang else None
    wins = windows_for(work, engine, arm, langs)
    if args.limit:
        wins = wins[:args.limit]
    hyp_dir = work / 'hyp' / f"{engine}__{arm}"
    wav_name = 'vocals.wav' if arm == 'vocals' else 'raw.wav'
    todo = [w for w in wins if not RN.hyp_is_current(hyp_dir / f"{w['win_id']}.json",
                                                     w['sha'][arm], fp)]
    emit(f"▶️ run {engine} x {arm}: {len(wins)} finestre, da fare {len(todo)}")
    run_id = time.strftime('%Y%m%d-%H%M%S') + f"_{engine}_{arm}"
    started = time.strftime('%Y-%m-%dT%H:%M:%S')
    t_start = time.time()
    mon = RN.VramMonitor().start()
    logcap = RN.LogCapture(echo=emit if args.verbose else None)
    counts = {'ok': 0, 'failed': 0, 'partial': 0}
    peaks: List[float] = []
    load_s = 0.0
    eng = None
    try:
        if todo:
            t0 = time.time()
            if engine == 'whisper':
                from core.engines.faster_whisper_engine import FasterWhisperEngine
                eng = FasterWhisperEngine(log_callback=logcap)
                eng.load()
                if eng.batch_size_for_transcription is None:
                    raise RuntimeError("BatchedInferencePipeline non attivo: non e' il percorso di produzione")
            elif engine == 'qwen3':
                from core.engines.qwen3_asr_engine import Qwen3AsrEngine
                eng = Qwen3AsrEngine(log_callback=logcap)
                eng.load()
            elif engine == 'canary':
                from core.engines.canary_engine import CanaryEngine
                eng = CanaryEngine(log_callback=logcap)
                eng.load()
            load_s = time.time() - t0
            mon.take_peak()
        if engine == 'canary' and todo:
            profile = fp['chunk_profile']
            gsize = max(1, args.canary_group)
            for gi in range(0, len(todo), gsize):
                group_w = todo[gi:gi + gsize]
                group = [(w['win_id'], [(p, a, b) for p, a, b in _chunks_of(work, w, profile, arm)], w['dur'])
                         for w in group_w]
                emit(f"  🧩 gruppo Canary {gi // gsize + 1}: {len(group)} finestre")
                res = RN.canary_group(eng, group, work / '_canary' / arm / f"g{gi // gsize + 1:03d}", logcap)
                peak = mon.take_peak()
                if peak is not None:
                    peaks.append(peak)
                for w in group_w:
                    r = res[w['win_id']]
                    counts[r['status']] += 1
                    RN.write_json_atomic(hyp_dir / f"{w['win_id']}.json",
                                         _hyp_record(w, engine, arm, r, w['sha'][arm], fp, _vram_delta(peak, mon)))
                sandbox.check_real_config()
        else:
            for k, w in enumerate(todo, 1):
                if engine == 'whisper':
                    wav = work / 'win' / w['win_id'] / wav_name
                    chunks = [(str(wav), 0.0, float(w['dur']))]
                else:
                    chunks = _chunks_of(work, w, fp['chunk_profile'], arm)
                r = RN.transcribe_window(eng, chunks, w['lang'], logcap)
                peak = mon.take_peak()
                if peak is not None:
                    peaks.append(peak)
                counts[r['status']] += 1
                RN.write_json_atomic(hyp_dir / f"{w['win_id']}.json",
                                     _hyp_record(w, engine, arm, r, w['sha'][arm], fp, _vram_delta(peak, mon)))
                emit(f"  [{k}/{len(todo)}] {w['win_id']}: {r['status']} {len(r['segments'])} seg "
                     f"{r['elapsed_s']:.1f}s" + (f" — {r['error']}" if r.get('error') else ''))
                if k % 10 == 0:
                    sandbox.check_real_config()
    finally:
        mon.stop()
        if eng is not None:
            try:
                eng.unload()
            except Exception:
                pass
    RN.write_text_atomic(work / 'logs' / f"{run_id}.log", '\n'.join(logcap.lines))
    row = {'run_id': run_id, 'engine': engine, 'arm': arm, 'started': started, 'n_windows': len(wins),
           'n_done': counts['ok'] + counts['partial'], 'n_skipped': len(wins) - len(todo),
           'n_failed': counts['failed'], 'n_partial': counts['partial'], 'load_s': round(load_s, 1),
           'total_s': round(time.time() - t_start, 1), 'vram_baseline_mb': mon.baseline,
           'vram_peak_mb': max(peaks, default=None),
           'fingerprint': json.dumps(fp, ensure_ascii=False, sort_keys=True),
           'decision_rules_sha': rules_sha(), 'norm_version': NZ.NORM_VERSION,
           'config_set_calls': json.dumps(sandbox.set_calls(), ensure_ascii=False)}
    append_csv(work / 'runs.csv', RUN_COLUMNS, row)
    sandbox.check_real_config()
    emit(f"✅ {run_id}: ok={counts['ok']} parziali={counts['partial']} falliti={counts['failed']} "
         f"saltati={row['n_skipped']}")
    return 0 if counts['failed'] == 0 else 6


def cmd_run_all(args) -> int:
    work: Path = args.work
    require_gpu_free()
    rc_all = 0
    for engine, arm in RUN_ORDER:
        require_gpu_free()
        cmd = [sys.executable, str(HERE / 'asr_bench.py'), '--work', str(work), 'run',
               '--engine', engine, '--arm', arm, '--canary-group', str(args.canary_group)]
        emit(f"\n══ {engine} x {arm} (processo nuovo) ══")
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        rc = subprocess.run(cmd, cwd=str(ROOT_DIR), env=env).returncode
        emit(f"   exit code {rc}")
        if rc in (3,):
            return rc
        rc_all = rc_all or rc
    cmd_score(args)
    cmd_report(args)
    return rc_all


# ══ SCORE / REPORT (CPU) ════════════════════════════════════════════════════════

def _load_rms(work: Path, win_id: str):
    p = work / 'win' / win_id / 'vocals_rms.npy'
    if not p.exists():
        return None
    import numpy as np
    return np.load(p)


def score_rows(work: Path) -> List[Dict]:
    wins = {w['win_id']: w for w in read_jsonl(work / 'windows.jsonl')}
    rows = []
    details = {}
    for hd in sorted((work / 'hyp').glob('*__*')):
        engine, arm = hd.name.split('__', 1)
        for hp in sorted(hd.glob('*.json')):
            h = read_json(hp)
            w = wins.get(h['win_id'])
            if w is None:
                continue
            base = {'win_id': w['win_id'], 'film': w['film'], 'lang': w['lang'], 'role': w['role'],
                    'group': w['group'], 'origin': w.get('origin'), 'tag': w['tag'], 'engine': engine,
                    'arm': arm, 'status': h['status'], 'error': h.get('error'), 'dur_s': w['dur'],
                    'elapsed_s': h.get('elapsed_s'), 'vram_peak_mb': h.get('vram_peak_mb'),
                    'n_failed_chunks': h.get('n_failed_chunks'), 'norm_version': NZ.NORM_VERSION}
            if h.get('wav_sha') != w['sha'][arm]:
                base.update(status='stale', error='ipotesi di un wav diverso da quello attuale')
                rows.append(base)
                continue
            if h['status'] == 'failed':
                rows.append(base)
                continue
            sc = M.score_window(w['cues'], h['segments'], w['lang'], names=set(w.get('names') or []),
                                rms_db=_load_rms(work, w['win_id']), dur_s=w['dur'])
            details[f"{engine}__{arm}__{w['win_id']}"] = sc.pop('halluc_detail')
            sc.update(fmt_midcut_fields(h['segments'], w['lang']))
            rows.append({**base, **sc})
    RN.write_json_atomic(work / 'score_detail.json', details)
    return rows


def fmt_midcut_fields(segments: List[Dict], lang: str) -> Dict:
    """Midcut sui blocchi che SubtitleFormatter(readability=True) di
    produzione farebbe dai segmenti (senza speaker). Il formatter si carica
    per percorso (split_eval/prodmods.py), senza torch ne' il pacchetto core."""
    try:
        from split_eval import midcut as MC
        st = MC.midcut_stats(MC.formatter_blocks(segments), lang) if segments else None
    except Exception as e:  # la misura descrittiva non deve far fallire lo score
        emit(f"  ⚠️ midcut formatter non calcolato: {type(e).__name__}: {e}")
        st = None
    return M.midcut_fields('fmt', st)


def cmd_score(args) -> int:
    rows = score_rows(args.work)
    write_csv_atomic(args.work / 'scores.csv', SCORE_COLUMNS, rows)
    emit(f"✅ scores.csv: {len(rows)} righe")
    return 0


def _f(x) -> Optional[float]:
    try:
        return float(x) if x not in (None, '', 'None') else None
    except ValueError:
        return None


def _i(x) -> int:
    v = _f(x)
    return int(v) if v is not None else 0


def load_scores(work: Path) -> List[Dict]:
    with open(work / 'scores.csv', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def paired_films(rows: List[Dict], lang: str, prod: str, ch: str, arm_p: str, arm_c: str,
                 groups: Optional[Sequence[str]], role: str = 'test',
                 win_filter=None) -> Tuple[ST.Paired, int]:
    """{film: [(err_prod, err_ch, n_ref)]} sulle finestre dove entrambi hanno
    un'ipotesi valida; ritorna anche il numero di finestre fallite/mancanti."""
    idx = {}
    for r in rows:
        if r['lang'] != lang or r['role'] != role or (groups and r['group'] not in groups):
            continue
        idx[(r['win_id'], r['engine'], r['arm'])] = r
    wins = sorted({k[0] for k in idx})
    out: ST.Paired = {}
    n_failed = 0
    for wid in wins:
        if win_filter and not win_filter(wid):
            continue
        a, b = idx.get((wid, prod, arm_p)), idx.get((wid, ch, arm_c))
        if a is None and b is None:
            continue
        ok_a = a is not None and a['status'] in ('ok', 'partial')
        ok_b = b is not None and b['status'] in ('ok', 'partial')
        if not (ok_a and ok_b):
            n_failed += 1
            continue
        film = a['film']
        ea = _i(a['Sc']) + _i(a['Dc']) + _i(a['Ic'])
        eb = _i(b['Sc']) + _i(b['Dc']) + _i(b['Ic'])
        out.setdefault(film, []).append((ea, eb, _i(a['n_ref_c'])))
    return out, n_failed


def engine_summary(rows: List[Dict], lang: str, engine: str, arm: str, groups: Optional[Sequence[str]],
                   role: str = 'test', win_ids: Optional[set] = None) -> Dict:
    rs = [r for r in rows if r['lang'] == lang and r['engine'] == engine and r['arm'] == arm
          and r['role'] == role and (not groups or r['group'] in groups)
          and (win_ids is None or r['win_id'] in win_ids)]
    ok = [r for r in rs if r['status'] in ('ok', 'partial')]
    by_film: Dict[str, List[Tuple[int, int]]] = {}
    by_film_n: Dict[str, List[Tuple[int, int]]] = {}
    for r in ok:
        by_film.setdefault(r['film'], []).append((_i(r['Sc']) + _i(r['Dc']) + _i(r['Ic']), _i(r['n_ref_c'])))
        by_film_n.setdefault(r['film'], []).append((_i(r['S']) + _i(r['D']) + _i(r['I']), _i(r['n_ref'])))
    fw = [ST.film_wer(v) for v in by_film.values()]
    fwn = [ST.film_wer(v) for v in by_film_n.values()]
    nref = sum(_i(r['n_ref_c']) for r in ok) or 1
    hours = sum(_f(r['dur_s']) or 0 for r in ok) / 3600
    audio_min = sum(_f(r['dur_s']) or 0 for r in ok) / 60
    el = sum(_f(r['elapsed_s']) or 0 for r in ok)
    cues3 = sum(_i(r['n_cues_ge3']) for r in ok)
    names_t = sum(_i(r['names_total']) for r in ok)
    num_t = sum(_i(r['num_total']) for r in ok)
    tims = [_f(r['timing_med_abs_s']) for r in ok if _f(r['timing_med_abs_s']) is not None]
    vram = [_f(r['vram_peak_mb']) for r in ok if _f(r['vram_peak_mb']) is not None]
    return {
        'n_windows': len(rs), 'n_ok': len(ok), 'n_failed': len(rs) - len(ok),
        'n_partial': sum(1 for r in ok if r['status'] == 'partial'), 'n_films': len(by_film),
        'werc': sum(x for x in fw if x is not None) / len(fw) if fw else None,
        'wer': sum(x for x in fwn if x is not None) / len(fwn) if fwn else None,
        'S_pct': 100 * sum(_i(r['Sc']) for r in ok) / nref, 'D_pct': 100 * sum(_i(r['Dc']) for r in ok) / nref,
        'I_pct': 100 * sum(_i(r['Ic']) for r in ok) / nref,
        'missed_pct': 100 * sum(_i(r['n_missed']) for r in ok) / cues3 if cues3 else None,
        'halluc_per_h': sum(_i(r['n_halluc']) for r in ok) / hours if hours else None,
        'names_pct': 100 * sum(_i(r['names_hit']) for r in ok) / names_t if names_t else None,
        'num_pct': 100 * sum(_i(r['num_hit']) for r in ok) / num_t if num_t else None,
        'timing_med_s': sorted(tims)[len(tims) // 2] if tims else None,
        's_per_min': el / audio_min if audio_min else None,
        'vram_peak_mb': max(vram) if vram else None,
        'hyp_end_punct': _mean([_f(r['hyp_end_punct']) for r in ok]),
        'ref_end_punct': _mean([_f(r['ref_end_punct']) for r in ok]),
        **{f'{p}_midcut': _ratio(ok, f'{p}_midcut_n', f'{p}_midcut_den') for p in ('hyp', 'fmt', 'ref')},
    }


def _ratio(rows: List[Dict], num: str, den: str) -> Optional[float]:
    n = sum(_i(r.get(num)) for r in rows)
    d = sum(_i(r.get(den)) for r in rows)
    return n / d if d else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _fmt(x, pct=False, nd=2):
    if x is None:
        return '-'
    return f"{100 * x:.{nd}f}" if pct else f"{x:.{nd}f}"


def symmetric_filter(rows: List[Dict], lang: str, engines: Sequence[str], thr: float = 0.80) -> set:
    """Finestre in cui l'unione dei motori (braccio vocals) ritrova >= thr
    delle parole del riferimento."""
    masks: Dict[str, List[str]] = {}
    for r in rows:
        if r['lang'] == lang and r['arm'] == 'vocals' and r['engine'] in engines and r.get('hit_mask'):
            masks.setdefault(r['win_id'], []).append(r['hit_mask'])
    keep = set()
    for wid, ms in masks.items():
        n = len(ms[0])
        if n == 0 or any(len(m) != n for m in ms):
            continue
        hit = sum(1 for i in range(n) if any(m[i] == '1' for m in ms))
        if hit / n >= thr:
            keep.add(wid)
    return keep


def build_report(work: Path) -> str:
    rows = load_scores(work)
    out: List[str] = []
    P = out.append
    films = read_json(work / 'films.json', {}) or {}
    P(f"BANCO ASR — report {time.strftime('%Y-%m-%d %H:%M')}")
    P(f"Regole congelate il {DR.FROZEN_ON} ({DR.NOTE}); normalizzazione {NZ.NORM_VERSION}")
    shas = []
    if (work / 'runs.csv').exists():
        with open(work / 'runs.csv', encoding='utf-8') as f:
            shas = [r['decision_rules_sha'] for r in csv.DictReader(f)]
    cur = rules_sha()
    if shas and shas[0] != cur:
        P("⚠️⚠️ decision_rules.py E' CAMBIATO dopo il primo run: il verdetto sotto NON e' valido.")
    elif len(set(shas)) > 1:
        P("⚠️ decision_rules.py ha avuto sha diversi fra i run.")
    R_ = DR.DECISION_RULES
    gold = read_json(work / 'gold' / 'gold_verdict.json', {}) or {}
    for lang in ('en', 'it'):
        lr = [r for r in rows if r['lang'] == lang]
        if not lr:
            continue
        prod = DR.PRODUCTION_ENGINE[lang]
        P('')
        P('=' * 100)
        P(f"LINGUA {lang.upper()} — produzione: {prod}")
        engines = sorted({(r['engine'], r['arm']) for r in lr})
        groups_all = sorted({r['group'] for r in lr})
        for grp in (['main', 'secondary', 'report_only'] if lang == 'en' else ['main', 'secondary']):
            if grp not in groups_all:
                continue
            P(f"\n-- gruppo {grp} (finestre test; WER = media per film) --")
            P(f"{'motore/braccio':<18}{'film':>5}{'fin':>5}{'fall':>5}{'WERc%':>8}{'WER%':>8}{'S%':>6}{'D%':>6}"
              f"{'I%':>6}{'perse%':>8}{'all/h':>7}{'nomi%':>7}{'num%':>7}{'t_med':>7}{'s/min':>7}{'+VRAM':>8}")
            for eng, arm in engines:
                s = engine_summary(rows, lang, eng, arm, [grp])
                if not s['n_windows']:
                    continue
                P(f"{eng + '/' + arm:<18}{s['n_films']:>5}{s['n_ok']:>5}{s['n_failed']:>5}"
                  f"{_fmt(s['werc'], True):>8}{_fmt(s['wer'], True):>8}{_fmt(s['S_pct'], nd=1):>6}"
                  f"{_fmt(s['D_pct'], nd=1):>6}{_fmt(s['I_pct'], nd=1):>6}{_fmt(s['missed_pct']):>8}"
                  f"{_fmt(s['halluc_per_h']):>7}{_fmt(s['names_pct'], nd=1):>7}{_fmt(s['num_pct'], nd=1):>7}"
                  f"{_fmt(s['timing_med_s']):>7}{_fmt(s['s_per_min'], nd=1):>7}{_fmt(s['vram_peak_mb'], nd=0):>8}")
        P("\nPunteggiatura (solo descrittiva, riferimento inaffidabile): quota segmenti chiusi da .!?…")
        for eng, arm in engines:
            s = engine_summary(rows, lang, eng, arm, None)
            P(f"   {eng}/{arm}: ipotesi {_fmt(s['hyp_end_punct'])}  riferimento {_fmt(s['ref_end_punct'])}")
        P("\nFrasi spezzate (midcut, solo descrittiva; split_eval/midcut.py): quota di blocchi che finiscono "
          "a meta' frase (%)")
        for eng, arm in engines:
            s = engine_summary(rows, lang, eng, arm, None)
            P(f"   {eng}/{arm}: segmenti {_fmt(s['hyp_midcut'], True)}  blocchi formatter "
              f"{_fmt(s['fmt_midcut'], True)}  riferimento {_fmt(s['ref_midcut'], True)}")
        P("\n-- VERDETTO (braccio vocals, regole congelate) --")
        for ch in DR.CHALLENGERS[lang]:
            if (ch, 'vocals') not in engines or (prod, 'vocals') not in engines:
                P(f"   {ch} vs {prod}: dati mancanti")
                continue
            if lang == 'en':
                main, nf1 = paired_films(rows, lang, prod, ch, 'vocals', 'vocals', ['main'])
                sec, nf2 = paired_films(rows, lang, prod, ch, 'vocals', 'vocals', ['secondary'])
                pg = engine_summary(rows, lang, prod, 'vocals', ['main'])
                cg = engine_summary(rows, lang, ch, 'vocals', ['main'])
                d = ST.decide_en(main, sec, pg, cg, pg['werc'], nf1 + nf2)
            else:
                allf, nf = paired_films(rows, lang, prod, ch, 'vocals', 'vocals', None)
                origin = {r['film']: r.get('origin') for r in lr}
                pg = engine_summary(rows, lang, prod, 'vocals', None)
                cg = engine_summary(rows, lang, ch, 'vocals', None)
                d = ST.decide_it(allf, origin, pg, cg, pg['werc'], nf)
            gv = (gold.get(lang) or {})
            if R_['gold_must_agree'] and gv and gv.get('agree') is False and d['verdict'] == 'CAMBIO_PROPOSTO':
                d['verdict'] = 'NON_VALIDO_ORO'
                d['reasons'].append("la classifica sull'oro differisce da quella sui sub")
            P(f"   {ch} vs {prod}: {d['verdict']}")
            P(f"      guadagno medio {_fmt(d.get('gain'), True)} punti WERc (positivo = sfidante migliore), "
              f"IC95% [{_fmt(d.get('ci_lo'), True)}, {_fmt(d.get('ci_hi'), True)}]")
            P(f"      Wilcoxon esatto W+={d.get('wilcoxon_w')} p={_fmt(d.get('wilcoxon_p'), nd=4)} "
              f"n={d.get('wilcoxon_n')} (p minimo ottenibile {_fmt(d.get('wilcoxon_min_p'), nd=4)})")
            if d.get('wilcoxon_n', 0) <= 5:
                P("      ⚠️ con <=5 film il p minimo e' >= 0,0625: il test NON puo' risultare significativo")
            if lang == 'en':
                P(f"      gruppo secondario: guadagno {_fmt(d.get('gain_secondary'), True)}")
            else:
                P(f"      per origine: {{{', '.join(f'{k}: {_fmt(v, True)}' for k, v in d['gain_by_origin'].items())}}}")
                P(f"      per film: {{{', '.join(f'{k}: {_fmt(v, True)}' for k, v in d['gain_by_film'].items())}}}")
            for rsn in d.get('reasons', []):
                P(f"      - {rsn}")
            if gv:
                P(f"      oro: classifica {gv.get('rank_gold')} contro sub {gv.get('rank_subs')} "
                  f"-> {'CONCORDA' if gv.get('agree') else 'DISCORDA'}")
            elif R_['gold_must_agree']:
                P("      oro: non ancora valutato (gold-make/gold-score): il verdetto non e' definitivo")
        P("\n-- Demucs: vocals contro raw (finestre dispari; guadagno positivo = vocals meglio) --")
        for eng in sorted({e for e, a in engines if a == 'raw'}):
            raw_ids = {r['win_id'] for r in lr if r['engine'] == eng and r['arm'] == 'raw'}
            pf, nf = paired_films(rows, lang, eng, eng, 'raw', 'vocals', None,
                                  win_filter=lambda w, s=raw_ids: w in s)
            if not pf:
                continue
            lo, hi = ST.bootstrap_gain(pf, R_['bootstrap_n'], R_['bootstrap_seed'], R_['ci_level'])
            P(f"   {eng}: {_fmt(ST.mean_gain(pf), True)} punti, IC95% [{_fmt(lo, True)}, {_fmt(hi, True)}], "
              f"{len(pf)} film, {nf} finestre scartate")
        P("\n-- Sensibilita' (NON decide): filtro simmetrico (unione motori >= 80% parole ritrovate) --")
        keep = symmetric_filter(rows, lang, [e for e, a in engines if a == 'vocals'])
        P(f"   finestre tenute: {len(keep)}")
        for ch in DR.CHALLENGERS[lang]:
            pf, _ = paired_films(rows, lang, prod, ch, 'vocals', 'vocals', None, win_filter=lambda w: w in keep)
            if pf:
                P(f"   {ch} vs {prod}: guadagno {_fmt(ST.mean_gain(pf), True)} su {len(pf)} film")
        P("   arbitro esterno wav2vec2-xlsr-53: non implementato")
    P('')
    excl = [f"{k}: {v['status']} {v.get('reason', '')}" for k, v in films.items() if v.get('status') != 'ok']
    if excl:
        P("Film-lingua esclusi in prepare:")
        for e in excl:
            P(f"   - {e}")
    return '\n'.join(out)


def cmd_report(args) -> int:
    if not (args.work / 'scores.csv').exists():
        emit("❌ scores.csv mancante: lancia 'score' prima")
        return 2
    txt = build_report(args.work)
    RN.write_text_atomic(args.work / 'report.txt', txt)
    emit(txt)
    return 0


# ══ GOLD ═══════════════════════════════════════════════════════════════════════

_GOLD_LINE = re.compile(r'^\[\s*([\d.]+)\s*-->\s*([\d.]+)\s*\]\s?(.*)$')


def cmd_gold_make(args) -> int:
    work: Path = args.work
    wins = [w for w in read_jsonl(work / 'windows.jsonl') if w['role'] == 'test']
    index = read_json(work / 'gold' / 'index.json', {}) or {}
    for lang in ('en', 'it'):
        cand = [w for w in wins if w['lang'] == lang]
        cand.sort(key=lambda w: (w['group'] != 'main', w['win_id']))
        rng = random.Random(f"gold:{DR.WINDOW_RULES['seed']}:{lang}")
        by_film: Dict[str, List[Dict]] = {}
        for w in cand:
            by_film.setdefault(w['film'], []).append(w)
        films_main = sorted(f for f, ws in by_film.items() if ws[0]['group'] == 'main')
        films_other = sorted(f for f in by_film if f not in films_main)
        rng.shuffle(films_main)
        rng.shuffle(films_other)
        chosen = []
        order = films_main + films_other
        while len(chosen) < args.per_lang and any(by_film[f] for f in order):
            for f in order:
                if by_film[f] and len(chosen) < args.per_lang:
                    chosen.append(by_film[f].pop(rng.randrange(len(by_film[f]))))
        for w in chosen:
            path = work / 'gold' / lang / f"{w['win_id']}.txt"
            if path.exists() and not args.force:
                continue
            lines = [f"# {w['win_id']}  film={w['film']}  durata={w['dur']:.1f}s",
                     f"# AUDIO: {work / 'win' / w['win_id'] / 'raw.wav'}",
                     "# Correggi ALLA LETTERA contro l'audio, partendo dal sub professionale sotto.",
                     "# NON guardare l'output dei motori. Non toccare i tempi fra [ ]. Righe con # ignorate.",
                     "# Una battuta di sola musica: lascia il simbolo ♪ nella riga."]
            for c in w['cues']:
                lines.append(f"[{c['s']:.2f} --> {c['e']:.2f}] {c['text'].replace(chr(10), ' / ')}")
            RN.write_text_atomic(path, '\n'.join(lines) + '\n')
            index[w['win_id']] = {'lang': lang, 'path': str(path), 'template_sha': sha256_file(path)}
    RN.write_json_atomic(work / 'gold' / 'index.json', index)
    emit(f"✅ set d'oro: {len(index)} finestre in {work / 'gold'} — correggi i .txt poi lancia gold-score")
    return 0


def parse_gold(path: Path) -> List[Dict]:
    cues = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = _GOLD_LINE.match(line.strip())
        if not m:
            raise ValueError(f"{path.name}: riga non riconosciuta: {line[:80]}")
        text = m.group(3).replace(' / ', '\n')
        cues.append({'s': float(m.group(1)), 'e': float(m.group(2)), 'text': text, **R.cue_flags(text)})
    return cues


def rankings_agree(a: Dict[str, Optional[float]], b: Dict[str, Optional[float]], tie: float = 0.002) -> bool:
    """Classifiche concordi se nessuna coppia di motori e' in ordine opposto
    (differenze sotto `tie` = pari, non contano come discordanza)."""
    engines = [e for e in a if a.get(e) is not None and b.get(e) is not None]
    for i, x in enumerate(engines):
        for y in engines[i + 1:]:
            da, db = a[x] - a[y], b[x] - b[y]
            if abs(da) >= tie and abs(db) >= tie and (da > 0) != (db > 0):
                return False
    return True


def cmd_gold_score(args) -> int:
    work: Path = args.work
    index = read_json(work / 'gold' / 'index.json', {}) or {}
    wins = {w['win_id']: w for w in read_jsonl(work / 'windows.jsonl')}
    rows = load_scores(work) if (work / 'scores.csv').exists() else []
    verdict = {}
    out_rows = []
    for lang in ('en', 'it'):
        ids = [k for k, v in index.items() if v['lang'] == lang and k in wins]
        if not ids:
            continue
        untouched = [k for k in ids if sha256_file(Path(index[k]['path'])) == index[k]['template_sha']]
        if untouched:
            emit(f"  ⚠️ [{lang}] {len(untouched)}/{len(ids)} file d'oro ancora identici al modello (non corretti)")
        per_eng: Dict[str, List[Tuple[int, int]]] = {}
        for wid in ids:
            w = wins[wid]
            gcues = parse_gold(Path(index[wid]['path']))
            for hp in (work / 'hyp').glob(f"*__vocals/{wid}.json"):
                h = read_json(hp)
                if h['status'] == 'failed':
                    continue
                sc = M.score_window(gcues, h['segments'], lang, names=set(w.get('names') or []),
                                    rms_db=_load_rms(work, wid), dur_s=w['dur'])
                err = sc['Sc'] + sc['Dc'] + sc['Ic']
                per_eng.setdefault(h['engine'], []).append((err, sc['n_ref_c']))
                out_rows.append({'win_id': wid, 'lang': lang, 'engine': h['engine'], 'err': err,
                                 'n_ref_c': sc['n_ref_c'], 'werc': sc['werc']})
        gold_wer = {e: ST.film_wer(v) for e, v in per_eng.items()}
        sub_wer = {}
        for e in per_eng:
            rs = [r for r in rows if r['win_id'] in ids and r['engine'] == e and r['arm'] == 'vocals'
                  and r['status'] in ('ok', 'partial')]
            sub_wer[e] = ST.film_wer([(_i(r['Sc']) + _i(r['Dc']) + _i(r['Ic']), _i(r['n_ref_c'])) for r in rs])
        rg = sorted(gold_wer, key=lambda e: (gold_wer[e] is None, gold_wer[e] or 0))
        rs_ = sorted(sub_wer, key=lambda e: (sub_wer[e] is None, sub_wer[e] or 0))
        agree = rankings_agree(gold_wer, sub_wer)
        verdict[lang] = {'rank_gold': rg, 'rank_subs': rs_, 'agree': agree,
                         'werc_gold': gold_wer, 'werc_subs': sub_wer, 'n_windows': len(ids),
                         'n_untouched': len(untouched)}
        emit(f"  [{lang}] oro {rg} {gold_wer}\n       sub {rs_} {sub_wer} -> "
             f"{'CONCORDA' if agree else 'DISCORDA'}")
    RN.write_json_atomic(work / 'gold' / 'gold_verdict.json', verdict)
    write_csv_atomic(work / 'gold' / 'gold_scores.csv', ['win_id', 'lang', 'engine', 'err', 'n_ref_c', 'werc'],
                     out_rows)
    emit("✅ gold_verdict.json scritto (il report lo usa)")
    return 0


# ══ CLI ════════════════════════════════════════════════════════════════════════

def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--work', type=Path, default=DEFAULT_WORK, help=f"cartella dati (default {DEFAULT_WORK})")
    sub = p.add_subparsers(dest='cmd', required=True)

    sa = sub.add_parser('audit', help="ffprobe, estrazione sub, provenienza e fedelta' (CPU)")
    sa.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    sa.add_argument('--films', default=None, help="sottostringhe del nome file, separate da virgola")
    sa.add_argument('--no-extract', action='store_true', help="solo ffprobe, nessuna estrazione")
    sa.add_argument('--clips', action='store_true', help="estrae le clip audio per il controllo d'ascolto")

    sp = sub.add_parser('plan', help="scelta finestre dai soli sottotitoli (CPU)")
    sp.add_argument('--films', default=None)

    sr = sub.add_parser('prepare', help="audio finestre + Demucs + sfasamento + chunk (GPU)")
    sr.add_argument('--films', default=None)
    sr.add_argument('--force', action='store_true')
    sr.add_argument('--allow-blocked', action='store_true',
                    help="prepara i film pronti anche se altri attendono conferma manuale")

    for name in ('run', 'run-all'):
        s = sub.add_parser(name, help=("un motore x un braccio in questo processo (GPU)" if name == 'run'
                                       else "tutti i motori x bracci, un processo nuovo ciascuno, poi score+report"))
        if name == 'run':
            s.add_argument('--engine', required=True, choices=['whisper', 'qwen3', 'canary', 'w2v'])
            s.add_argument('--arm', required=True, choices=['vocals', 'raw'])
            s.add_argument('--lang', default=None, help="en,it (default: tutte quelle del motore)")
            s.add_argument('--limit', type=int, default=0)
            s.add_argument('--verbose', action='store_true')
        s.add_argument('--canary-group', type=int, default=100, help="finestre per chiamata Canary")

    sub.add_parser('score', help="punteggi per finestra -> scores.csv (CPU)")
    sub.add_parser('report', help="statistica e verdetto (CPU)")
    sg = sub.add_parser('gold-make', help="esporta il set d'oro da correggere a mano")
    sg.add_argument('--per-lang', type=int, default=10)
    sg.add_argument('--force', action='store_true', help="rigenera anche i file gia' presenti (perde le correzioni!)")
    sub.add_parser('gold-score', help="classifica sull'oro contro classifica sui sub")

    args = p.parse_args(argv[1:])
    args.work = Path(args.work).resolve()
    handlers = {'audit': cmd_audit, 'plan': cmd_plan, 'prepare': cmd_prepare, 'run': cmd_run,
                'run-all': cmd_run_all, 'score': cmd_score, 'report': cmd_report,
                'gold-make': cmd_gold_make, 'gold-score': cmd_gold_score}
    return handlers[args.cmd](args)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv))
