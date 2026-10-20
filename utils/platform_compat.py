# -*- coding: utf-8 -*-
"""
Differenze tra sistemi operativi in un posto solo.

Su Windows ogni funzione restituisce ESATTAMENTE il valore che il codice cablava prima (percorso `Scripts/python.exe`,
flag 0x08000000, ...): nessun cambio di comportamento. Su Linux/macOS restituisce l'equivalente POSIX.
Il parametro `windows` serve ai test (simulare l'altro sistema senza toccare `sys.platform`); in produzione si omette.

Regola per il codice nuovo: niente `Scripts/python.exe`, `taskkill`, `0x08000000`, `windll` o `os.startfile` fuori da qui
(lo fa rispettare ui_bench/tests/test_platform_lint.py).
"""
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

IS_WINDOWS = sys.platform == 'win32'

_CREATE_NO_WINDOW_WIN = 0x08000000   # subprocess.CREATE_NO_WINDOW (esiste solo su Windows)


_DRIVE_PATH = re.compile(r'^[A-Za-z]:[\\/]')


def is_foreign_windows_path(value, windows: Optional[bool] = None) -> bool:
    """True se `value` e' un percorso con lettera di unita' (`V:\\...`) e questo NON e' Windows: un percorso salvato in una
    config copiata da Windows, inutilizzabile qui. Su Windows e' sempre False."""
    if _is_win(windows):
        return False
    return isinstance(value, str) and bool(_DRIVE_PATH.match(value))


def _is_win(windows: Optional[bool]) -> bool:
    return IS_WINDOWS if windows is None else windows


def venv_python(venv_dir: Union[str, Path], windows: Optional[bool] = None) -> Path:
    """Interprete di un venv: `<venv>/Scripts/python.exe` su Windows, `<venv>/bin/python` altrove."""
    base = Path(venv_dir)
    return base / 'Scripts' / 'python.exe' if _is_win(windows) else base / 'bin' / 'python'


def no_window_flags(windows: Optional[bool] = None) -> int:
    """`creationflags` per Popen/run: niente finestra di console su Windows, 0 altrove (dove un valore diverso da 0
    farebbe alzare ValueError a Popen)."""
    if not _is_win(windows):
        return 0
    return getattr(subprocess, 'CREATE_NO_WINDOW', _CREATE_NO_WINDOW_WIN)


def kill_tree(pid: int, wait: float = 5.0) -> bool:
    """Uccide il processo e tutti i discendenti (ffmpeg, sottoprocessi GPU...) con psutil: stesso comportamento su
    ogni sistema. True se il processo principale e' stato terminato (o non esisteva piu'), False se non e' stato
    possibile ucciderlo. `wait` = secondi di attesa della morte effettiva; 0 = non bloccante (dal thread della GUI),
    nel qual caso il risultato e' solo indicativo."""
    try:
        import psutil
    except ImportError:
        return False
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True
    except Exception:
        return False
    victims = []
    try:
        victims = parent.children(recursive=True)
    except Exception:
        pass
    victims.append(parent)
    for p in victims:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
        except Exception:
            pass
    _gone, alive = psutil.wait_procs(victims, timeout=wait)
    return all(p.pid != pid for p in alive)
