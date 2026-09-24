"""Funzioni comuni del controllo alla cieca (percorsi, JSON, ffprobe)."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = HERE / 'work'
for _p in (str(ROOT), str(ROOT / 'asr_eval'), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NO_WINDOW = {'creationflags': 0x08000000} if os.name == 'nt' else {}


def sha256_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding='utf-8'))


def write_json_atomic(p, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)


def slug(text: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-').lower()
    return s[:60] or 'file'


def ffprobe(path) -> dict:
    """{'duration': s, 'audio': [{'lang','channels','index'}], 'subs': n} o {} se fallisce."""
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=index,codec_type:stream_tags=language',
           '-of', 'json', str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=90, **NO_WINDOW)
        if r.returncode != 0:
            return {}
        j = json.loads(r.stdout)
    except Exception:
        return {}
    audio = [{'index': s.get('index'), 'lang': (s.get('tags') or {}).get('language', '')}
             for s in j.get('streams', []) if s.get('codec_type') == 'audio']
    subs = sum(1 for s in j.get('streams', []) if s.get('codec_type') == 'subtitle')
    try:
        dur = float((j.get('format') or {}).get('duration') or 0)
    except ValueError:
        dur = 0.0
    return {'duration': dur, 'audio': audio, 'subs': subs}


def has_english_audio(info: dict) -> bool:
    return any(a['lang'].lower() in ('eng', 'en') for a in info.get('audio', []))


def bench_film_keys():
    """Titoli gia' usati dal banco ASR (asr_eval/work/windows.jsonl): da escludere."""
    p = ROOT / 'asr_eval' / 'work' / 'windows.jsonl'
    keys = set()
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                keys.add(json.loads(line).get('film', ''))
    return keys
