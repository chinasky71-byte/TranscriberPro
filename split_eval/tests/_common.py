import os
import sys
from pathlib import Path

os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
HERE = Path(__file__).resolve().parent
PKG = HERE.parent
ROOT = PKG.parent
ASR = ROOT / 'asr_eval'
for p in (str(ASR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

REAL_SUBS = ASR / 'work' / 'subs' / 'office-romance-2026'


def srt(cues):
    """[(s, e, testo)] -> testo SRT."""
    def ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    out = []
    for i, (s, e, t) in enumerate(cues, 1):
        out += [str(i), f"{ts(s)} --> {ts(e)}", t, '']
    return '\n'.join(out)


def blk(s, e, text, **kw):
    return {'start': s, 'end': e, 'text': text, **kw}
