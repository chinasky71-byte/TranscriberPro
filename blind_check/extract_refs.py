"""
Passo 3b — RIFERIMENTO PROFESSIONALE per il foglio cieco (rete/CPU).

Dai file ORIGINALI (non dagli estratti, che non hanno sottotitoli) ricava, per
la stessa finestra di 20 minuti, il sottotitolo italiano REGOLARE embedded
(testuale, non forced, non per non udenti). I tempi risultano relativi
all'inizio dell'estratto, come quelli dell'SRT trascritto. Scrive
work/refs/<id>.ita.srt e work/refs/index.json. Se la traccia manca, contiene la
firma di Transcriber Pro o e' vuota, il riferimento resta assente.

Il riferimento e' UGUALE per A e B: non rompe la cecita'.
Uso: venv\\Scripts\\python.exe blind_check\\extract_refs.py
"""
import json
import re
import subprocess
import sys

import common as C
import decision_rule as R

SIGNATURE = re.compile(r'transcriber|ai generated|generated subtitles|nllb|chinasky', re.I)


def ita_streams(path):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 's', '-show_entries',
           'stream=index,codec_name:stream_tags=language,title:stream_disposition=forced,hearing_impaired',
           '-of', 'json', str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=90, **C.NO_WINDOW)
    if r.returncode != 0:
        return []
    return [s for s in json.loads(r.stdout).get('streams', [])
            if (s.get('tags') or {}).get('language', '').lower() in ('ita', 'it') and s.get('codec_name') in ('subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt')]


def pick_track(streams):
    """Regolare: non forced, non per non udenti/CC/dubtitle. Ritorna lo stream o None."""
    bad = re.compile(r'forced|sdh|non udenti|hearing|\bcc\b|dubtitle', re.I)
    ok = [s for s in streams
          if not s.get('disposition', {}).get('forced') and not s.get('disposition', {}).get('hearing_impaired')
          and not bad.search((s.get('tags') or {}).get('title', ''))]
    if not ok:
        return None
    pref = [s for s in ok if re.search(r'regular|^ita$|^italian$|^italiano$', (s.get('tags') or {}).get('title', ''), re.I)]
    return (pref or ok)[0]


def main():
    sel = C.read_json(C.WORK / 'selection.json')
    (C.WORK / 'refs').mkdir(parents=True, exist_ok=True)
    index = {}
    for it in sel['items']:
        out = C.WORK / 'refs' / f"{it['id']}.ita.srt"
        st = pick_track(ita_streams(it['file']))
        if st is None:
            index[it['id']] = {'ref': None, 'why': "nessun sottotitolo italiano regolare testuale nel file"}
            print(f"{it['id']:38s} nessun riferimento")
            continue
        start = int(it['excerpt_start_s'])
        cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', str(start), '-i', it['file'], '-t', str(R.EXCERPT_MIN * 60),
               '-map', f"0:{st['index']}", '-c:s', 'srt', str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **C.NO_WINDOW)
        txt = out.read_text(encoding='utf-8', errors='replace') if out.exists() else ''
        n = len(re.findall(r'-->', txt))
        why = None
        if r.returncode != 0 or n == 0:
            why = f"estrazione fallita o vuota ({r.stderr[-120:]})"
        elif SIGNATURE.search(txt):
            why = "firma di Transcriber Pro nel sottotitolo: scartato (circolarita')"
        if why:
            index[it['id']] = {'ref': None, 'why': why}
            print(f"{it['id']:38s} scartato: {why}")
            continue
        index[it['id']] = {'ref': str(out), 'track': st['index'], 'title': (st.get('tags') or {}).get('title', ''), 'cues': n}
        print(f"{it['id']:38s} traccia {st['index']} '{(st.get('tags') or {}).get('title', '')}': {n} sottotitoli nella finestra")
    C.write_json_atomic(C.WORK / 'refs' / 'index.json', index)
    return 0


if __name__ == '__main__':
    sys.exit(main())
