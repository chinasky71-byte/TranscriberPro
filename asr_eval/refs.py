"""
Riferimenti: lettura SRT (logica di gender_eval/build_film_groundtruth.py,
copiata e non importata: quel modulo carica spaCy all'import), marcatura
delle battute (♪, solo suoni, corsivo), ffprobe, estrazione sottotitoli in
un solo passaggio, provenienza, fedelta' al doppiaggio, scelta del
riferimento inglese, nomi propri ricorrenti.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import normalize as nz

_NO_WINDOW = {'creationflags': 0x08000000} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
TEXT_SUB_CODECS = {'subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt', 'text'}

_TS = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')
_RE_MUSIC_LINE = re.compile(r'^\s*#|#\s*$')


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, '0')) / 1000


def cue_flags(raw: str) -> Dict[str, bool]:
    plain = re.sub(r'<[^>]*>|\{[^}]*\}', '', raw)
    music = ('♪' in raw) or ('♫' in raw) or any(_RE_MUSIC_LINE.search(l) for l in plain.splitlines())
    italic = '<i>' in raw.lower() or '{\\i1}' in raw
    stripped = nz.strip_markup(raw)
    has_words = any(ch.isalnum() for ch in re.sub(r'[♪♫#]', '', stripped))
    had_words = any(ch.isalnum() for ch in plain)
    return {'music': music, 'italic': italic, 'sound_only': (not has_words) and had_words and not music}


def parse_srt_text(content: str) -> List[Dict]:
    """SRT -> battute {s, e, text (righe grezze), music, sound_only, italic}."""
    content = content.replace('﻿', '').replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', content):
        lines = block.strip('\n').split('\n')
        for k, line in enumerate(lines):
            m = _TS.search(line)
            if not m:
                continue
            g = m.groups()
            text = '\n'.join(l for l in lines[k + 1:] if l.strip())
            if text.strip():
                cues.append({'s': _ts(*g[:4]), 'e': _ts(*g[4:]), 'text': text, **cue_flags(text)})
            break
    cues.sort(key=lambda c: (c['s'], c['e']))
    return cues


def parse_srt(path: Path) -> List[Dict]:
    return parse_srt_text(Path(path).read_text(encoding='utf-8', errors='replace'))


def cue_tokens(cues: Sequence[Dict], lang: str) -> List[Tuple[str, float]]:
    out = []
    for c in cues:
        if c.get('music'):
            continue
        out.extend((t, c['s']) for t in nz.normalize_text(c['text'], lang))
    return out


def words_per_minute(cues: Sequence[Dict], lang: str) -> Optional[float]:
    speech = [c for c in cues if not c.get('music')]
    if not speech:
        return None
    span = (speech[-1]['e'] - speech[0]['s']) / 60
    return len(cue_tokens(speech, lang)) / span if span > 0 else None


# ── LCS ─────────────────────────────────────────────────────────────────

def lcs_len(a: Sequence[str], b: Sequence[str]) -> int:
    if not a or not b:
        return 0
    vocab: Dict[str, int] = {}
    ai = [vocab.setdefault(t, len(vocab)) for t in a]
    bi = [vocab.setdefault(t, len(vocab)) for t in b]
    prev = [0] * (len(bi) + 1)
    for x in ai:
        cur = [0]
        for j, y in enumerate(bi):
            cur.append(prev[j] + 1 if x == y else (prev[j + 1] if prev[j + 1] > cur[j] else cur[j]))
        prev = cur
    return prev[-1]


def blockwise_lcs(a: Sequence[Tuple[str, float]], b: Sequence[Tuple[str, float]],
                  block_s: float = 180.0) -> Tuple[int, int, int]:
    """LCS a blocchi temporali (stessa griglia per i due sub): (lcs, len_a, len_b)."""
    if not a or not b:
        return 0, len(a), len(b)
    t_end = max(a[-1][1], b[-1][1])
    total = 0
    k = 0
    while k * block_s <= t_end:
        lo, hi = k * block_s, (k + 1) * block_s
        total += lcs_len([t for t, s in a if lo <= s < hi], [t for t, s in b if lo <= s < hi])
        k += 1
    return total, len(a), len(b)


# ── ffprobe / estrazione ──────────────────────────────────────────────────

def ffprobe(video: Path) -> Dict:
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries',
         'format=duration,start_time:stream=index,codec_type,codec_name,channels,sample_rate,start_time'
         ':stream_tags:stream_disposition=default,forced,hearing_impaired',
         '-of', 'json', str(video)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, **_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe fallito su {video}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or '{}')


def extract_subs(video: Path, tracks: Sequence[Tuple[int, str, Path]]) -> None:
    """Estrae piu' tracce testo in UN solo passaggio sul file (I/O di rete)."""
    if not tracks:
        return
    cmd = ['ffmpeg', '-y', '-v', 'error', '-i', str(video)]
    for idx, codec, dest in tracks:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        cmd += ['-map', f'0:{idx}', '-c:s', 'copy' if codec == 'subrip' else 'srt', str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=1800, **_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"estrazione sottotitoli fallita: {r.stderr.strip()[:300]}")


def extract_clip(video: Path, audio_index: int, t0: float, dur: float, dest: Path) -> bool:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', f'{max(0.0, t0):.3f}', '-t', f'{dur:.3f}',
                        '-i', str(video), '-map', f'0:{audio_index}', '-vn', '-acodec', 'pcm_s16le',
                        '-ar', '16000', '-ac', '1', str(dest)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=600, **_NO_WINDOW)
    return r.returncode == 0 and Path(dest).exists() and Path(dest).stat().st_size > 44


# ── classificazione e provenienza ────────────────────────────────────────

def film_key(filename: str) -> str:
    stem = Path(filename).stem
    m = re.search(r'\b(19\d{2}|20\d{2})\b', stem)
    base = stem[:m.end()] if m else stem
    return re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')


def sub_kind(stream: Dict) -> str:
    tags = stream.get('tags') or {}
    title = (tags.get('title') or '').lower()
    disp = stream.get('disposition') or {}
    frames = _int(tags.get('NUMBER_OF_FRAMES') or tags.get('NUMBER_OF_FRAMES-eng'))
    if disp.get('forced') or 'forced' in title or (frames is not None and frames < 100):
        return 'forced'
    if 'dubtitle' in title:
        return 'dubtitle'
    if disp.get('hearing_impaired') or any(k in title for k in ('sdh', 'non udenti', '[cc]', 'hearing', 'cc')):
        return 'sdh'
    return 'normal'


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def provenance(stream: Dict, filename: str, today: Optional[date] = None) -> Tuple[str, List[str]]:
    """'ok' | 'reject' | 'confirm' con motivi (regola del progetto)."""
    tags = stream.get('tags') or {}
    title = tags.get('title') or ''
    lang = tags.get('language') or ''
    reasons = []
    if '- srt' in title.lower():
        reasons.append(f"titolo '{title}' (nome dello strumento dell'utente)")
    if len(lang) == 2:
        reasons.append(f"codice lingua a 2 lettere '{lang}'")
    if reasons:
        return 'reject', reasons
    year = (today or date.today()).year
    wdate = tags.get('_STATISTICS_WRITING_DATE_UTC') or ''
    recent = wdate.startswith(str(year))
    mine = 'chinasky' in filename.lower()
    if recent and mine:
        return 'reject', [f"scritto il {wdate} e nome file con 'chinasky'"]
    if recent:
        return 'confirm', [f"scritto il {wdate} (anno corrente): conferma manuale"]
    return 'ok', []


def lang3(stream: Dict) -> str:
    l = ((stream.get('tags') or {}).get('language') or 'und').lower()
    return {'it': 'ita', 'en': 'eng', 'fr': 'fre', 'fra': 'fre'}.get(l, l)


def group_of(filename: str, groups: Dict[str, List[str]]) -> Optional[str]:
    low = filename.lower()
    for g, keys in groups.items():
        if any(k in low for k in keys):
            return g
    return None


def names_from_cues(cues: Sequence[Dict], lang: str, min_count: int = 3) -> List[str]:
    """Nomi propri: parole maiuscole non a inizio frase, >= min_count volte,
    quasi mai scritte minuscole (<10%). Restituite normalizzate."""
    cap: Dict[str, int] = {}
    low: Dict[str, int] = {}
    for c in cues:
        if c.get('music'):
            continue
        text = nz.strip_markup(c['text'])
        for line in text.splitlines():
            line = re.sub(r'^\s*[-–—]+\s*', '', line)
            sentence_start = True
            for w in line.split():
                core = re.sub(r"^[^\wÀ-ÿ]+|[^\wÀ-ÿ']+$", '', w)
                core = re.sub(r"'s$", '', core)
                if core and core.isalpha():
                    key = nz.strip_accents(core.lower())
                    if core[0].isupper() and not core.isupper() and not sentence_start:
                        cap[key] = cap.get(key, 0) + 1
                    elif core[0].islower():
                        low[key] = low.get(key, 0) + 1
                sentence_start = w.rstrip('"»”\')').endswith(('.', '!', '?', '…', ':'))
    out = []
    for k, n in cap.items():
        if n >= min_count and low.get(k, 0) < 0.1 * (n + low.get(k, 0)):
            toks = nz.normalize_text(k, lang)
            if len(toks) == 1 and not nz.is_filler(toks[0], lang):
                out.append(toks[0])
    return sorted(set(out))


def fidelity_it(cand: Sequence[Dict], normal: Sequence[Dict], rules) -> Dict:
    """Fedelta' al doppiaggio di un sub ITA non normale rispetto al normale."""
    a, b = cue_tokens(cand, 'it'), cue_tokens(normal, 'it')
    lcs, la, lb = blockwise_lcs(a, b)
    share = lcs / la if la else 0.0
    wa, wb = words_per_minute(cand, 'it'), words_per_minute(normal, 'it')
    excess = (wa / wb - 1) if (wa and wb) else None
    if share >= rules['translation_lcs']:
        decision = 'traduzione'
    elif excess is not None and excess >= rules['min_wpm_excess']:
        decision = 'candidato'
    else:
        decision = 'dubbio'
    return {'lcs_share_cand': round(share, 3), 'lcs_share_normal': round(lcs / lb, 3) if lb else 0.0,
            'wpm_cand': round(wa, 1) if wa else None, 'wpm_normal': round(wb, 1) if wb else None,
            'wpm_excess': round(excess, 3) if excess is not None else None, 'decision': decision}


def en_choice(normal: Optional[Sequence[Dict]], sdh: Optional[Sequence[Dict]], same_thr: float) -> Dict:
    if normal and not sdh:
        return {'use': 'normal', 'lcs_min': None}
    if sdh and not normal:
        return {'use': 'sdh', 'lcs_min': None}
    if not normal and not sdh:
        return {'use': None, 'lcs_min': None}
    a, b = cue_tokens(normal, 'en'), cue_tokens(sdh, 'en')
    lcs, la, lb = blockwise_lcs(a, b)
    m = min(lcs / la if la else 0, lcs / lb if lb else 0)
    return {'use': 'normal' if m >= same_thr else 'sdh', 'lcs_min': round(m, 3)}
