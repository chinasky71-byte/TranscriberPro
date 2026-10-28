# -*- coding: utf-8 -*-
"""
Gender Selector CLI — subprocess spaCy usa-e-getta.
File: core/gender_selector_cli.py

Gira nel venv NLP SEPARATO (spaCy + it_core_news_lg), NON nel venv
principale dell'app: il modello linguistico non deve entrare nel venv del
runtime GPU, e alla fine del processo l'OS recupera TUTTA la RAM di
spaCy — niente unload manuale.

Uso:  <venv_nlp>/python.exe core/gender_selector_cli.py <in.json> <out.json>
  in.json  = {"lines": ["riga 1", "riga 2", ...]}
  out.json = {"tokens": [...1ª persona...], "tokens_p2": [...2ª persona...]}

Exit: 0 ok; 1 spaCy non disponibile; 2 argomenti invalidi.
"""
import importlib.util
import json
import sys
from pathlib import Path


def main(argv):
    if len(argv) < 3:
        print("Uso: gender_selector_cli.py <in.json> <out.json>", flush=True)
        return 2
    in_path, out_path = Path(argv[1]), Path(argv[2])
    if not in_path.exists():
        print(f"Input non trovato: {in_path}", flush=True)
        return 2

    # Carica il selettore per file-path: core/__init__ importerebbe la
    # pipeline (torch), che in questo venv non esiste.
    sel_path = Path(__file__).resolve().parent / 'gender_line_selector.py'
    spec = importlib.util.spec_from_file_location('gender_line_selector', sel_path)
    sel = importlib.util.module_from_spec(spec)
    sys.modules['gender_line_selector'] = sel
    spec.loader.exec_module(sel)

    if not sel.available():
        print("spaCy/it_core_news_lg non disponibile in questo ambiente", flush=True)
        return 1

    lines = json.loads(in_path.read_text(encoding='utf-8'))['lines']
    tokens = [sel.speaker_gendered_tokens(line) for line in lines]
    tokens_p2 = [sel.addressee_gendered_tokens(line) for line in lines]
    out_path.write_text(json.dumps({'tokens': tokens, 'tokens_p2': tokens_p2},
                                   ensure_ascii=False), encoding='utf-8')
    n1 = sum(1 for t in tokens if t)
    n2 = sum(1 for t in tokens_p2 if t)
    print(f"Selettore: {n1} righe 1ª persona, {n2} righe 2ª persona "
          f"su {len(lines)}", flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    # Lingua dei log: stessa regola della GUI (config 'language'), senza Qt.
    try:
        from utils.translations import init_language_headless as _tp_init_lang
        _tp_init_lang()
    except Exception:
        pass

    sys.exit(main(sys.argv))
