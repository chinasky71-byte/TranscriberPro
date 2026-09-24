import os
import sys
from pathlib import Path

os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
ROOT = BENCH.parent
for p in (str(BENCH), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

DESIGN = Path(os.environ.get(
    'ASR_DESIGN_DIR',
    r"C:\Users\fran_\AppData\Local\Temp\claude\C--Users-fran--Desktop-Transcriber-Pro"
    r"\c325e2fc-38ef-4a64-831a-e3dea60ac106\scratchpad\asr_design"))
REAL_WORK = BENCH / 'work'


def srt(cues):
    """[(s, e, testo)] -> testo SRT."""
    def ts(t):
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"
    out = []
    for i, (s, e, t) in enumerate(cues, 1):
        out += [str(i), f"{ts(s)} --> {ts(e)}", t, '']
    return '\n'.join(out)
