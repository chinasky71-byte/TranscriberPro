# -*- coding: utf-8 -*-
"""
Pipeline CLI - Entrypoint subprocess isolato per l'elaborazione di UN film.
File: core/pipeline_cli.py

Esegue ProcessingPipeline.process() in un processo Python SEPARATO, così che
tutta la RAM/VRAM trattenuta dagli allocatori nativi ML (PyTorch, ctranslate2,
CUDA, NLLB) venga restituita all'OS quando il processo termina. Su code lunghe
questo evita l'accumulo di RAM di sistema che gc + EmptyWorkingSet non liberano
(vedi memory project_ram_commit_accumulo).

Vantaggio collaterale: essendo headless (niente PyQt6), un eventuale crash di
ctranslate2 (std::abort) resta confinato a questo processo → il film va in
'failed' e la coda prosegue, invece di abbattere la GUI.

Uso (chiamato dal ProcessingWorker, NON manuale):
    python -m core.pipeline_cli <args.json>

Formato args.json:
    { "video_path": "...", "target_language": "ita",
      "files_processed": 0, "result_path": "path/to/result.json" }

result.json (scritto a fine elaborazione, in result_path FUORI dalla temp dir
del video così il cleanup della pipeline non lo rimuove):
    { "success": true, "last_output_path": "..." }

Exit code: 0 = ok, 1 = fallimento pipeline, 2 = argomenti invalidi.
Stdout: log della pipeline, riemessi dal worker via log_message (line-buffered).
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

    video_path = args.get('video_path')
    target_language = args.get('target_language') or 'ita'
    files_processed = int(args.get('files_processed') or 0)
    result_path = args.get('result_path')

    if not video_path:
        _emit("ERRORE CLI: video_path obbligatorio")
        return 2

    # Import LAZY: il costo di torch/moduli ML si paga solo qui, non al check args.
    try:
        from core.pipeline import ProcessingPipeline
    except Exception as e:
        _emit(f"ERRORE CLI: import ProcessingPipeline fallito: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1

    pipe = None
    success = False
    last_output_path = None
    try:
        pipe = ProcessingPipeline(video_path)
        pipe.set_log_callback(_emit)
        try:
            pipe.set_batch_context(files_processed=files_processed)
        except Exception:
            pass
        success = bool(pipe.process(target_language=target_language))
        try:
            last_output_path = (str(pipe.last_output_path)
                                if pipe.last_output_path else None)
        except Exception:
            last_output_path = None
    except Exception as e:
        _emit(f"ERRORE CLI: eccezione fatale pipeline: {e}")
        traceback.print_exc(file=sys.stderr)
        success = False

    # Scrive result.json PRIMA del cleanup: result_path è fuori dalla temp dir
    # del video, quindi pipe.cleanup() (che fa rmtree della temp dir) non lo tocca.
    if result_path:
        try:
            Path(result_path).write_text(
                json.dumps({"success": success,
                            "last_output_path": last_output_path},
                           ensure_ascii=False),
                encoding='utf-8')
        except Exception as e:
            _emit(f"WARN CLI: scrittura result.json fallita: {e}")

    # Cleanup pipeline: ridondante per la RAM (il processo muore comunque) ma
    # rimuove i file temporanei del video.
    if pipe is not None:
        try:
            pipe.cleanup()
        except Exception:
            pass

    return 0 if success else 1


if __name__ == '__main__':
    # Forza UTF-8 su stdout/stderr per evitare UnicodeEncodeError su Windows.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # Garantisce che la root del progetto sia importabile (lanciato con
    # `python -m core.pipeline_cli`, ma robusto anche con path assoluto).
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    sys.exit(main(sys.argv))
