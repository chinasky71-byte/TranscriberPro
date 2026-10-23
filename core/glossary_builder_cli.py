# -*- coding: utf-8 -*-
"""
Glossario per-show CLI - Entrypoint subprocess isolato
File: core/glossary_builder_cli.py

Esegue glossary_engine/build_glossary_candidates.py:build_full_report() in un
processo separato, lanciato con l'interprete del venv dedicato
`venv_glossary/` (simalign/sentence-transformers/LaBSE sono incompatibili
con transformers==4.57.6 del venv principale — vedi
glossary_engine/glossary_align.py). Stesso pattern di isolamento di
core/gender_corrector_cli.py per il resto, MA lanciato come SCRIPT
diretto, non con `-m core....`: `-m` importerebbe `core/__init__.py` ->
`utils/__init__.py` (psutil, TMDBClient, ...), pacchetti NON installati
nel venv_glossary snello e non necessari qui. Questo file non importa
nulla dal package `core`, solo stdlib + glossary_engine.build_glossary_candidates.

Uso (chiamato dalla GUI, non manuale):
    venv_glossary\\Scripts\\python core\\glossary_builder_cli.py <args.json>

Formato args.json:
    {
      "show_dir": "V:\\The Ark",
      "name": "the_ark",
      "tmdb_id": 47663,
      "min_freq": 3,
      "min_episodes": 6,
      "min_blocks": 6000,
      "use_align": true,
      "use_qwen": true,
      "qwen_model_path": "C:\\...\\qwen2.5-14b.gguf",
      "align_device": "cpu",
      "qwen_n_gpu_layers": -1,
      "exclude_episodes": [[1, 1], [1, 2]]
    }

Stdout: una riga JSON per evento (vedi piano di sviluppo):
    {"ev":"gate","ok":false,"episodes":3,"blocks":3645,...}
    {"ev":"progress","phase":"collect|align|qwen|evaluate","done":N,"total":N,"msg":"..."}
    {"ev":"done","report":"<path assoluto>"}
    {"ev":"error","msg":"..."}

Exit code: 0 = completato (anche con gate non superato), 1 = errore
fatale, 2 = argomenti CLI invalidi.
"""
import json
import sys
from pathlib import Path


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def main(argv: list) -> int:
    if len(argv) < 2:
        _emit({"ev": "error", "msg": "argomento args.json mancante"})
        return 2

    args_path = Path(argv[1])
    if not args_path.exists():
        _emit({"ev": "error", "msg": f"args.json non trovato: {args_path}"})
        return 2

    try:
        args = json.loads(args_path.read_text(encoding='utf-8'))
    except Exception as e:
        _emit({"ev": "error", "msg": f"parsing args.json fallito: {e}"})
        return 2

    show_dir = args.get('show_dir')
    name = args.get('name')
    if not show_dir or not name:
        _emit({"ev": "error", "msg": "show_dir e name sono obbligatori"})
        return 2
    if not Path(show_dir).exists():
        _emit({"ev": "error", "msg": f"show_dir non trovato: {show_dir}"})
        return 2

    tmdb_id = args.get('tmdb_id')
    exclude_keys = {tuple(k) for k in args.get('exclude_episodes', [])}
    qwen_n_gpu_layers = args.get('qwen_n_gpu_layers')
    if qwen_n_gpu_layers is None:
        qwen_n_gpu_layers = -1

    engine_dir = str(Path(__file__).resolve().parent.parent / 'glossary_engine')
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)

    try:
        from build_glossary_candidates import build_full_report
    except Exception as e:
        _emit({"ev": "error", "msg": f"import motore glossario fallito: {e}"})
        return 1

    def _progress_cb(phase, done, total, msg):
        _emit({"ev": "progress", "phase": phase, "done": done, "total": total,
               "msg": msg})

    def _log(msg):
        _emit({"ev": "log", "msg": str(msg)})

    try:
        # build_full_report scrive SEMPRE il report su disco (gate non
        # superato incluso: e' un esito valido, non un errore) e onora
        # report_out se dato — un solo punto che decide il path, non piu'
        # duplicato qui (bug reale in revisione: il ramo gate-fallito e il
        # ramo successo calcolavano il path in due punti diversi del
        # codice, potendo divergere silenziosamente).
        report = build_full_report(
            show_dir=show_dir, name=name, tmdb_id=tmdb_id,
            min_freq=args.get('min_freq', 3),
            min_episodes=args.get('min_episodes', 6),
            min_blocks=args.get('min_blocks', 6000),
            use_align=args.get('use_align', True),
            use_qwen=args.get('use_qwen', True),
            qwen_model_path=args.get('qwen_model_path'),
            align_device=args.get('align_device', 'cpu'),
            qwen_n_gpu_layers=qwen_n_gpu_layers,
            exclude_keys=exclude_keys,
            max_candidates=args.get('max_candidates', 25),
            log=_log, progress_cb=_progress_cb,
            report_out=args.get('report_out'))
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        _emit({"ev": "error", "msg": f"eccezione fatale: {e}"})
        return 1

    if not report.get("gate", {}).get("ok", True) and "gate" in report:
        _emit({"ev": "gate", **report["gate"]})

    _emit({"ev": "done", "report": report["_report_path"]})
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    # Lingua dei log: stessa regola della GUI (config 'language'), senza Qt.
    try:
        from utils.translations import init_language_headless as _tp_init_lang
        _tp_init_lang()
    except Exception:
        pass

    sys.exit(main(sys.argv))
