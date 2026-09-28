"""
Selezione dei film TEDESCHI (lingua originale tedesca in Radarr) per la prova dello split per frasi in tedesco
(piano_split_frasi_fr_de, 28/09/2026). Materiale dal lavoro preliminare (de_prelim/materiale_de.md, probe ffprobe in
de_prelim/work/probe_de.json). Scelta FISSA (non casuale: il materiale utilizzabile e' poco):
  TARATURA (3): Sophie Scholl (gia' visto: de1), La sala professori, Il cielo brucia. Le ultime due non hanno
    sottotitoli tedeschi: il riferimento e' il sottotitolo ITALIANO, usato SOLO per la forma dei blocchi (criterio f).
  CONFERMA (8, mai visti): i 7 film con sottotitoli tedeschi di testo non forzati (Lola corre, Downfall, Toni
    Erdmann, Der Tiger, Il suono di una caduta, Mangia prega abbaia, Aguirre) + Funny Games (riferimento ITA).
Controllo dei titoli gia' usati in banchi precedenti (select_full.is_excluded): mancato nella selezione francese,
qui obbligatorio (un titolo escluso ferma la selezione). Scrive work_de/selection_de.json.
Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe select_de.py [--dry-run]
"""
import argparse
import json
import re
import sys

import select_full as SF

WORK = SF.HERE / 'work_de'
PROBE = SF.HERE / 'de_prelim' / 'work' / 'probe_de.json'
# (titolo Radarr, indice audio tedesco, indice sottotitolo, lingua del riferimento, set)
PLAN = [
    ('La rosa bianca - Sophie Scholl', 1, 11, 'de', 'taratura'),
    ('La sala professori', 2, 3, 'it', 'taratura'),
    ('Il cielo brucia', 2, 3, 'it', 'taratura'),
    ('Lola corre', 4, 12, 'de', 'conferma'),
    ('La caduta - Gli ultimi giorni di Hitler', 3, 7, 'de', 'conferma'),
    ('Vi presento Toni Erdmann', 2, 5, 'de', 'conferma'),
    ("Der Tiger - Viaggio all'inferno", 3, 9, 'de', 'conferma'),
    ('Il suono di una caduta', 1, 3, 'de', 'conferma'),
    ('Mangia prega abbaia', 3, 10, 'de', 'conferma'),
    ('Aguirre, furore di Dio', 2, 6, 'de', 'conferma'),
    ('Funny Games', 2, 3, 'it', 'conferma'),
]
# titoli gia' usati come spezzoni nei banchi di TRADUZIONE di oggi (non nei banchi split): ammessi solo in taratura
SEEN_OK_IN_TUNING = ('sophie scholl',)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sel_path = WORK / 'selection_de.json'
    if sel_path.exists() and not a.dry_run:
        print("selection_de.json esiste gia': campione congelato.")
        return 0
    probe = json.loads(PROBE.read_text(encoding='utf-8'))
    words = SF.excluded_words()
    items, bad = [], []
    for k, (title, aidx, sidx, ref_lang, st) in enumerate(PLAN):
        cand = [p for p in probe if p['title'] == title or title.startswith(p['title']) or p['title'].startswith(title)]
        if not cand:
            bad.append(f'{title}: non trovato nel probe')
            continue
        p = cand[0]
        if SF.is_excluded(p['title'], words) and not (st == 'taratura' and any(x in p['title'].lower() for x in SEEN_OK_IN_TUNING)):
            bad.append(f"{p['title']}: titolo gia' usato in un banco precedente")
        au = {x['index']: x for x in p['audio']}
        su = {x['index']: x for x in p['subs']}
        if aidx not in au or au[aidx]['lang'] not in ('ger', 'deu', 'de'):
            bad.append(f"{p['title']}: audio #{aidx} non tedesco")
        if sidx not in su or su[sidx]['codec'] not in ('subrip', 'srt', 'ass', 'mov_text'):
            bad.append(f"{p['title']}: sottotitolo #{sidx} non testuale")
        info = SF.probe(__import__('pathlib').Path(p['path']))
        it = {'kind': 'film', 'title': p['title'], 'file': p['path'], 'duration': info['duration'] if info else 0,
              'audio_index': aidx, 'sub_index': sidx, 'ref_lang': ref_lang,
              'sub': {'index': sidx, 'title': su.get(sidx, {}).get('title', ''), 'frames': 0}}
        it['id'] = f"{k + 1:02d}-" + re.sub(r'[^A-Za-z0-9]+', '-', p['title']).strip('-').lower()[:50]
        it['set'] = st
        items.append(it)
    for it in items:
        print(f"  {it['id']:45s} {it['set']:9s} {it['duration'] / 60:5.0f} min audio#{it['audio_index']} "
              f"sub#{it['sub_index']} rif {it['ref_lang']}")
    if bad:
        print('PROBLEMI:\n  ' + '\n  '.join(bad))
        return 1
    if not a.dry_run:
        WORK.mkdir(parents=True, exist_ok=True)
        sel_path.write_text(json.dumps({'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
