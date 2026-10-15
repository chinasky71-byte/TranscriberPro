# -*- coding: utf-8 -*-
"""
Eventi strutturati della pipeline (accanto al log testuale, mai al suo posto).

Perche': l'avanzamento del file, l'ETA e lo stato della coda headless leggevano il TESTO del log
("Traduzione: [", "OCR — Analisi bitmap", "6. Salto traduzione"...): cambiare una frase o un'emoji rompeva
in silenzio la barra. Qui la pipeline dichiara direttamente cosa sta facendo.

Trasporto: una riga su stdout del processo figlio (`core.pipeline_cli`) con un prefisso inconfondibile e un
JSON. E' ATTIVO SOLO se il genitore imposta `TP_EVENTS=1` nell'ambiente del figlio: un genitore vecchio non
li vede mai (niente JSON nel log a schermo). Il genitore toglie queste righe prima del log.

Uso nei produttori:   from utils.events import emit ;  emit('phase', name='asr', engine='qwen3')
Senza sink (Library Scanner, chiamate in-process, test) `emit` non fa nulla e non solleva mai.

Eventi (campo `k`):
  phase      name=<fase di gui/file_progress>, [engine=<motore ASR>], [fraction=0..1 solo per 'final']
  route      path='ocr', translate=<bool>        ramo bitmap (1b): con o senza traduzione
  audio_lang lang=<codice lingua dell'audio>
  embedded   lang=<codice>                       sottotitoli embedded scelti: audio non serve
  skip       phases=[...]                        fasi che non avverranno
  ocr_leave                                      OCR non riuscito: si torna a testo/audio
  bar        phase=demucs|asr|translate|gender, pct=0..100
"""
import json
import os
from typing import Any, Callable, Dict, Optional, Tuple

PREFIX = '@@TPEV@@ '
ENV_VAR = 'TP_EVENTS'

_sink: Optional[Callable[[str, Dict[str, Any]], None]] = None


def enabled() -> bool:
    return os.environ.get(ENV_VAR) == '1'


def set_sink(fn: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
    global _sink
    _sink = fn


def emit(kind: str, **fields: Any) -> None:
    """Invia un evento al sink, se c'e'. Non solleva mai: un evento perso non deve fermare il lavoro."""
    fn = _sink
    if fn is None:
        return
    try:
        fn(kind, fields)
    except Exception:
        pass


def format_line(kind: str, fields: Dict[str, Any]) -> str:
    return PREFIX + json.dumps({'k': kind, **fields}, ensure_ascii=True, separators=(',', ':'))


def parse_line(line: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(kind, campi) se la riga e' un evento, altrimenti None. Una riga con prefisso ma non valida
    ritorna ('', {}) cosi' il genitore la scarta comunque senza mostrarla."""
    if not line or not line.startswith(PREFIX):
        return None
    try:
        obj = json.loads(line[len(PREFIX):])
        kind = str(obj.pop('k'))
        return kind, obj
    except Exception:
        return '', {}


def install_stdout_sink() -> None:
    """Nel figlio: se il genitore lo ha chiesto, gli eventi vanno su stdout (stessa coda del log)."""
    if enabled():
        import sys

        def _write(k, f):
            # una sola scrittura (riga + a capo): un altro thread non puo' inserirsi tra prefisso e newline
            sys.stdout.write(format_line(k, f) + '\n')
            sys.stdout.flush()
        set_sink(_write)
