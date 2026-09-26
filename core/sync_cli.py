# -*- coding: utf-8 -*-
"""
Sync CLI - Sincronizzazione di UNA coppia video/SRT esterno in un subprocess isolato.
File: core/sync_cli.py

Come core/pipeline_cli.py: esegue SubtitleSynchronizer.synchronize() in un processo Python SEPARATO, cosi' che
la coda multi-file parta ogni volta da un contesto CUDA vergine (Whisper del fallback S1 si carica PRIMA di ogni
altro uso CUDA, come richiede ctranslate2) e tutta la RAM/VRAM (NLLB, Qwen, Whisper) torni all'OS a fine coppia.
L'allineamento e' quello di SubtitleSynchronizer (motore 'timing' di default, oppure 'llm' con sync_engine).

Uso (chiamato da gui/sync_batch_worker.py, non a mano):
    python -m core.sync_cli <args.json>

args.json:  { "video_path": "...", "external_srt_path": "...", "output_path": null | "...", "result_path": "..." }
result.json (scritto a fine coppia): { "success": true|false, "output_path": "..." | null, "error": "..." | null }

Stdout, una riga per evento (line-buffered):
    <log del sincronizzatore, invariato: le righe "1. ..." .. "4. ..." indicano lo step>
    [SYNC-PCT] <0-100>          avanzamento percentuale segnalato dal sincronizzatore
Exit code: 0 = ok, 1 = fallimento, 2 = argomenti invalidi.
"""
import json
import sys
import traceback
from pathlib import Path

PCT_PREFIX = '[SYNC-PCT] '


def _emit(msg: str) -> None:
    print(msg, flush=True)


def _write_result(result_path, payload: dict) -> None:
    if not result_path:
        return
    try:
        Path(result_path).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        _emit(f"WARN CLI: scrittura result.json fallita: {e}")


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
    srt_path = args.get('external_srt_path')
    output_path = args.get('output_path') or None
    result_path = args.get('result_path')
    if not video_path or not srt_path:
        _emit("ERRORE CLI: video_path ed external_srt_path sono obbligatori")
        return 2

    try:
        from core.subtitle_synchronizer import SubtitleSynchronizer
    except Exception as e:
        _emit(f"ERRORE CLI: import SubtitleSynchronizer fallito: {e}")
        traceback.print_exc(file=sys.stderr)
        _write_result(result_path, {"success": False, "output_path": None, "error": f"import fallito: {e}"})
        return 1

    sync = None
    success = False
    out = None
    error = None
    try:
        sync = SubtitleSynchronizer(
            video_path=video_path,
            external_srt_path=srt_path,
            output_path=output_path,
            log_callback=_emit,
            progress_callback=lambda pct: _emit(f"{PCT_PREFIX}{int(pct)}"),
        )
        success = bool(sync.synchronize())
        out = str(sync._output_path) if success else None
        if not success:
            error = getattr(sync, 'last_error', None) or "sincronizzazione fallita (vedi il log)"
    except Exception as e:
        error = f"eccezione fatale: {e}"
        _emit(f"ERRORE CLI: {error}")
        traceback.print_exc(file=sys.stderr)
    _write_result(result_path, {"success": success, "output_path": out, "error": error})
    return 0 if success else 1


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))
    from core.pipeline_cli import _suppress_subprocess_windows
    _suppress_subprocess_windows()
    sys.exit(main(sys.argv))
