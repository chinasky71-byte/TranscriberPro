# -*- coding: utf-8 -*-
"""
Gender Correction CLI - Entrypoint subprocess isolato
File: core/gender_corrector_cli.py

Esegue la correzione di genere V2 (deterministica, audio-driven) in un
processo separato: pyannote/ECAPA usano la GPU su contesto CUDA vergine
e alla fine il processo muore restituendo tutta la RAM/VRAM all'OS.
Il selettore spaCy gira in un ULTERIORE subprocess col suo venv dedicato.

Uso (chiamato dalla pipeline, non manuale):
    python -m core.gender_corrector_cli <args.json>

Formato args.json (v2):
    {
      "input_srt": "path/to/translated.srt",
      "output_srt": "path/to/corrected.srt",
      "video_path": "path/to/video.mkv"   # serve per la speaker gender map
    }
    (le chiavi original_srt/character_context del vecchio motore sono ignorate)

Exit code:
    0 = correzione completata (anche con 0 patch applicate)
    1 = errore fatale
    2 = argomenti CLI invalidi

Stdout: log leggibili dall'utente, riemessi dal parent via self._log.
"""
import json
import sys
import traceback
from pathlib import Path


def _emit(msg: str) -> None:
    """Stampa una riga su stdout con flush immediato (line-buffered)."""
    print(msg, flush=True)


def main(argv: list) -> int:
    if len(argv) < 2:
        _emit("ERRORE CLI: argomento args.json mancante")
        return 2

    args_path = Path(argv[1])
    if not args_path.exists():
        _emit(f"ERRORE CLI: args.json non trovato: {args_path}")
        return 2

    try:
        args = json.loads(args_path.read_text(encoding='utf-8'))
    except Exception as e:
        _emit(f"ERRORE CLI: parsing args.json fallito: {e}")
        return 2

    input_srt = args.get('input_srt')
    output_srt = args.get('output_srt')
    video_path = args.get('video_path')
    diarization_json = args.get('diarization_json')
    character_context = args.get('character_context') or {}

    if not input_srt or not output_srt:
        _emit("ERRORE CLI: input_srt e output_srt sono obbligatori")
        return 2

    input_path = Path(input_srt)
    output_path = Path(output_srt)

    if not input_path.exists():
        _emit(f"ERRORE CLI: input SRT non trovato: {input_path}")
        return 2

    # Import LAZY: il check args.json non paga il costo di torch/pyannote
    try:
        from core.gender_corrector_v2 import GenderCorrectorV2
    except Exception as e:
        _emit(f"ERRORE CLI: import gender_corrector_v2 fallito: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1

    try:
        diarization = None
        if diarization_json and Path(diarization_json).exists():
            try:
                diarization = json.loads(
                    Path(diarization_json).read_text(encoding='utf-8'))
                diarization = [tuple(t) for t in diarization]
                _emit(f"   Riuso diarization della trascrizione "
                      f"({len(diarization)} turni)")
            except Exception as e:
                _emit(f"WARN CLI: diarization_json illeggibile: {e}")
        engine = GenderCorrectorV2(log_callback=_emit)
        ok = engine.correct_file(
            srt_path=input_path,
            output_path=output_path,
            video_path=Path(video_path) if video_path else None,
            diarization=diarization,
            character_context=character_context,
        )

        try:
            engine.cleanup()
        except Exception as e:
            _emit(f"WARN CLI: cleanup engine fallito: {e}")

        if ok and output_path.exists():
            return 0
        _emit("ERRORE CLI: correzione completata ma output mancante")
        return 1

    except Exception as e:
        _emit(f"ERRORE CLI: eccezione fatale: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == '__main__':
    # Forza UTF-8 su stdout/stderr per evitare UnicodeEncodeError su Windows
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # Garantisce che la root del progetto sia importabile
    # (quando lanciato con `python -m core.gender_corrector_cli` cwd e' la root,
    # ma se lanciato con path assoluto serve un fix esplicito)
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    sys.exit(main(sys.argv))
