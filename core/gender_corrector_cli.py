# -*- coding: utf-8 -*-
"""
Gender Correction CLI - Entrypoint subprocess isolato
File: core/gender_corrector_cli.py

Esegue la correzione di genere in un processo Python separato cosi'
che la VRAM occupata dal processo principale (CUDA context, cuBLAS
workspace, ctranslate2 leftovers) NON limiti il LLM. Quando questo
processo termina, l'OS recupera tutta la VRAM allocata.

Uso (chiamato dalla pipeline, non manuale):
    python -m core.gender_corrector_cli <args.json>

Formato args.json:
    {
      "input_srt": "path/to/translated.srt",
      "output_srt": "path/to/corrected.srt",
      "original_srt": "path/to/source.srt" | null,
      "character_context": {"Meredith Grey": "F", "Derek Shepherd": "M"}
    }

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
    original_srt = args.get('original_srt')
    character_context = args.get('character_context') or {}

    if not input_srt or not output_srt:
        _emit("ERRORE CLI: input_srt e output_srt sono obbligatori")
        return 2

    input_path = Path(input_srt)
    output_path = Path(output_srt)
    original_path = Path(original_srt) if original_srt else None

    if not input_path.exists():
        _emit(f"ERRORE CLI: input SRT non trovato: {input_path}")
        return 2

    # Import LAZY: cosi' il check args.json non paga il costo di llama_cpp
    try:
        from core.gender_corrector import GenderCorrectionEngine, LLAMA_CPP_AVAILABLE
    except Exception as e:
        _emit(f"ERRORE CLI: import gender_corrector fallito: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1

    if not LLAMA_CPP_AVAILABLE:
        _emit("ERRORE CLI: llama-cpp-python non installato nel subprocess")
        return 1

    try:
        engine = GenderCorrectionEngine(log_callback=_emit)
        if not engine.is_available():
            _emit("ERRORE CLI: modello GGUF non disponibile (controlla config)")
            return 1

        ok = engine.correct_file(
            srt_path=input_path,
            output_path=output_path,
            character_context=character_context,
            original_srt_path=original_path,
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
