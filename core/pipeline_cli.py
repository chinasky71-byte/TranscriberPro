# -*- coding: utf-8 -*-
"""
Pipeline CLI - Entrypoint subprocess isolato per l'elaborazione di UN film.
File: core/pipeline_cli.py

Esegue ProcessingPipeline.process() in un processo Python SEPARATO, così che
tutta la RAM/VRAM trattenuta dagli allocatori nativi ML (PyTorch, CUDA,
llama.cpp) venga restituita all'OS quando il processo termina. Su code lunghe
questo evita l'accumulo di RAM di sistema che gc + EmptyWorkingSet non liberano
(vedi memory project_ram_commit_accumulo).

Vantaggio collaterale: essendo headless (niente PyQt6), un crash di una libreria
nativa (in passato ctranslate2, oggi llama.cpp) resta confinato a questo
processo → il film va in 'failed' e la coda prosegue, invece di abbattere la GUI.

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
from utils.translations import tr


def _emit(msg: str) -> None:
    """Stampa una riga su stdout con flush immediato (line-buffered)."""
    print(msg, flush=True)


def _suppress_subprocess_windows() -> None:
    """Su Windows forza CREATE_NO_WINDOW su TUTTE le subprocess lanciate nel child.

    Le nostre classi (audio_processor, ecc.) già lo usano, ma le librerie
    (torchaudio che invoca ffmpeg, o Demucs) no: senza
    questo una finestra console lampeggia a schermo. Il monkeypatch di
    Popen.__init__ copre ogni subprocess, nostra o di libreria.
    """
    if sys.platform != 'win32':
        return
    import subprocess as _sp
    flag = getattr(_sp, 'CREATE_NO_WINDOW', 0)
    if not flag:
        return
    _orig_init = _sp.Popen.__init__

    def _patched_init(self, *args, **kwargs):
        try:
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | flag
        except Exception:
            pass
        _orig_init(self, *args, **kwargs)

    _sp.Popen.__init__ = _patched_init


def main(argv: list) -> int:
    # Nessun bootstrap di ctranslate2: con ADR-008 (solo Qwen3-ASR) non c'e' piu'
    # un secondo runtime GPU da inizializzare prima di torch.
    if len(argv) < 2:
        _emit(tr('gcl_error_cli_args_json_argument'))
        return 2

    args_path = Path(argv[1])
    if not args_path.exists():
        _emit(tr('gcl_error_cli_args_json_not').format(args_path=args_path))
        return 2

    try:
        args = json.loads(args_path.read_text(encoding='utf-8'))
    except Exception as e:
        _emit(tr('gcl_error_cli_args_json_parsing').format(e=e))
        return 2

    video_path = args.get('video_path')
    target_language = args.get('target_language') or 'ita'
    files_processed = int(args.get('files_processed') or 0)
    result_path = args.get('result_path')

    if not video_path:
        _emit(tr('pc_error_cli_video_path_is'))
        return 2

    # Eccezioni per file alle opzioni job: sovrapposizione IN MEMORIA sulla configurazione (mai scritta su disco).
    # Senza la chiave 'overrides' (code headless, versioni precedenti) non cambia nulla.
    try:
        from utils.job_overrides import clean as _clean_ov
        _ov = _clean_ov(args.get('overrides'))
        if _ov:
            from utils.config import get_config as _gc
            _gc().set_overlay(_ov)
            _emit(tr('pc_options_specific_to_this_file').format(ov=_ov))
    except Exception as e:
        _emit(tr('pc_warn_cli_per_file_exceptions').format(e=e))

    # Import LAZY: il costo di torch/moduli ML si paga solo qui, non al check args.
    try:
        from core.pipeline import ProcessingPipeline
    except Exception as e:
        _emit(tr('pc_error_cli_processingpipeline_import_failed').format(e=e))
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
        _emit(tr('pc_error_cli_fatal_pipeline_exception').format(e=e))
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
            _emit(tr('pc_warn_cli_result_json_writing').format(e=e))

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

    # Eventi strutturati su stdout (utils/events.py) SOLO se il genitore ha impostato TP_EVENTS=1 e solo quando
    # questo modulo e' il programma: un processo che lo importa non li emette.
    try:
        from utils.events import install_stdout_sink as _tp_install_sink
        _tp_install_sink()
    except Exception:
        pass

    # Nessuna finestra console per le subprocess annidate (es. ffmpeg lanciato
    # da whisperx/torchaudio durante l'alignment).
    _suppress_subprocess_windows()

    # Lingua dei log: stessa regola della GUI (config 'language'), senza Qt.
    try:
        from utils.translations import init_language_headless as _tp_init_lang
        _tp_init_lang()
    except Exception:
        pass

    sys.exit(main(sys.argv))
