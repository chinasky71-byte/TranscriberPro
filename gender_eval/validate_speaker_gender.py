# -*- coding: utf-8 -*-
"""
Fase 1 — Validazione automatica della Speaker Gender Map.

Per ogni candidato del ground-truth film (build_film_groundtruth.py) confronta
il genere dedotto DALL'AUDIO (core/speaker_gender.py: diarization pyannote +
ECAPA gender) con il genere codificato dal traduttore professionale nel
sottotitolo italiano. Nessuna verifica manuale: 220+ punti di test gratuiti.

Metriche:
  - accuracy  = match / (match + mismatch)   [sui candidati con predizione]
  - coverage  = (match + mismatch) / totale  [quanti candidati ricevono un genere]

Le mappe vengono cacheate in film_groundtruth/_maps/<stem>.json: la diarization
è il passo costoso (~1-2 min/episodio su GPU) e si paga una sola volta.

Uso (venv APP):
    ./venv/Scripts/python.exe gender_eval/validate_speaker_gender.py            # tutti i TSV
    ./venv/Scripts/python.exe gender_eval/validate_speaker_gender.py --episode S01E01
    ./venv/Scripts/python.exe gender_eval/validate_speaker_gender.py --threshold 0.85
"""
import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = SCRIPT_DIR / "film_groundtruth"
MAPS_DIR = GT_DIR / "_maps"
RESULTS = SCRIPT_DIR / "results"
VIDEO_ROOTS = [Path("V:/Veronica Mars")]

# finestra di ricerca del parlante attorno allo start della cue italiana
CUE_WINDOW_SEC = 3.5


def _load_module(name: str, path: Path):
    """Import diretto dal file, senza eseguire core/__init__ (pipeline)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# core.ecapa_gender e core.diarizer vengono importati da speaker_gender:
# registriamo i moduli 'core.*' a mano per evitare il side-effect di core/__init__
def load_speaker_gender_module():
    import types
    if 'core' not in sys.modules:
        pkg = types.ModuleType('core')
        pkg.__path__ = [str(PROJECT_ROOT / 'core')]
        sys.modules['core'] = pkg
    _load_module('core.ecapa_gender', PROJECT_ROOT / 'core' / 'ecapa_gender.py')
    _load_module('core.diarizer', PROJECT_ROOT / 'core' / 'diarizer.py')
    return _load_module('core.speaker_gender', PROJECT_ROOT / 'core' / 'speaker_gender.py')


def ts_to_sec(ts: str) -> float:
    h, m, rest = ts.split(':')
    return int(h) * 3600 + int(m) * 60 + float(rest)


def find_video(stem: str):
    for root in VIDEO_ROOTS:
        for p in root.rglob(f"{stem}.mkv"):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--episode', default=None, help='filtra i TSV per pattern (es. S01E01)')
    ap.add_argument('--threshold', type=float, default=0.75)
    ap.add_argument('--force', action='store_true', help='ricalcola le mappe cacheate')
    args = ap.parse_args()

    sg = load_speaker_gender_module()
    from utils.config import get_config
    hf_token = get_config().get('huggingface_token', '')
    if not hf_token:
        sys.exit("huggingface_token mancante in config (serve per pyannote)")

    MAPS_DIR.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)

    tsvs = sorted(GT_DIR.glob("*.tsv"))
    if args.episode:
        tsvs = [t for t in tsvs if args.episode.lower() in t.stem.lower()]
    if not tsvs:
        sys.exit("Nessun TSV trovato")

    def log(msg):
        print(msg, flush=True)

    mapper = sg.SpeakerGenderMapper(hf_token, log_callback=log,
                                    conf_threshold=args.threshold)

    tot = {'match': 0, 'mismatch': 0, 'unknown': 0}
    detail_path = RESULTS / "speaker_gender_validation.tsv"
    det = open(detail_path, 'w', encoding='utf-8')
    det.write("episode\tstart\tgt_gender\tpred_gender\tconfidence\tesito\tita_reference\n")

    for tsv in tsvs:
        stem = tsv.stem
        video = find_video(stem)
        if video is None:
            log(f"⚠️ Video non trovato per {stem}, salto")
            continue

        cache = MAPS_DIR / f"{stem}.json"
        if cache.exists() and not args.force:
            gmap = sg.SpeakerGenderMap.from_json(cache.read_text(encoding='utf-8'))
            gmap.conf_threshold = args.threshold
            log(f"\n=== {stem[:55]} (mappa da cache)")
        else:
            log(f"\n=== {stem[:55]}")
            gmap = mapper.build_map(str(video))
            cache.write_text(gmap.to_json(), encoding='utf-8')

        ep = {'match': 0, 'mismatch': 0, 'unknown': 0}
        with open(tsv, encoding='utf-8') as f:
            for row in csv.DictReader(f, delimiter='\t'):
                if row['gender'] not in ('F', 'M'):
                    continue
                t0 = ts_to_sec(row['start'])
                t1 = ts_to_sec(row['end']) if row.get('end') else t0 + CUE_WINDOW_SEC
                pred, conf = gmap.gender_for_range(t0, t1)
                if pred is None:
                    esito = 'UNKNOWN'
                    ep['unknown'] += 1
                elif pred == row['gender']:
                    esito = 'MATCH'
                    ep['match'] += 1
                else:
                    esito = 'MISMATCH'
                    ep['mismatch'] += 1
                det.write(f"{stem[:40]}\t{row['start']}\t{row['gender']}\t"
                          f"{pred or '-'}\t{conf:.3f}\t{esito}\t"
                          f"{row['ita_reference'][:80]}\n")
        for k in tot:
            tot[k] += ep[k]
        meas = ep['match'] + ep['mismatch']
        acc = ep['match'] / meas * 100 if meas else 0
        log(f"   {ep['match']}/{meas} match ({acc:.0f}%), {ep['unknown']} unknown")

    det.close()
    mapper.cleanup()

    meas = tot['match'] + tot['mismatch']
    n_all = meas + tot['unknown']
    print()
    print("=" * 60)
    print("  VALIDAZIONE SPEAKER GENDER MAP (vs sub professionali)")
    print("=" * 60)
    print(f"  Accuracy : {tot['match']/meas*100 if meas else 0:6.2f}%  "
          f"({tot['match']}/{meas} misurabili)")
    print(f"  Coverage : {meas/n_all*100 if n_all else 0:6.2f}%  "
          f"({tot['unknown']} unknown su {n_all})")
    print(f"  Soglia confidenza: {args.threshold}")
    print("=" * 60)
    print(f"  Dettaglio: {detail_path}")

    with open(RESULTS / "results_speaker_gender_validation.json", 'w',
              encoding='utf-8') as f:
        json.dump({'threshold': args.threshold, **tot,
                   'accuracy': tot['match'] / meas if meas else 0,
                   'coverage': meas / n_all if n_all else 0},
                  f, indent=2)


if __name__ == '__main__':
    main()
