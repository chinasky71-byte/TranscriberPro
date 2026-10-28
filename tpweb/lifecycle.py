# -*- coding: utf-8 -*-
"""Ciclo di vita del server (fetta 1f): un solo server per utente, convivenza con la GUI Qt e con la coda headless, arresto
ordinato. Senza Qt. Il lock e' un file `tpweb.lock` ({pid, since}); un lock orfano (processo morto o altro programma) si
sovrascrive, come fa `QueueLock` della coda headless."""
import json
import os
import time
from pathlib import Path
from typing import Callable, List, Optional

HOME = Path.home() / '.transcriberpro'


def _is_tpweb_process(pid: int) -> bool:
    """Il processo e' un server web: `python -m tpweb` oppure `main.py --ui web`."""
    try:
        import psutil
        cl = ' '.join(psutil.Process(pid).cmdline())
        return 'tpweb' in cl or ('main.py' in cl and '--ui' in cl and 'web' in cl)
    except Exception:
        return False


def _create_time(pid: int) -> Optional[float]:
    try:
        import psutil
        return psutil.Process(pid).create_time()
    except Exception:
        return None


class ServerLock:
    """Il lock porta il pid e l'ORA DI CREAZIONE del processo: il server e' quel processo se esiste ancora con la stessa ora di creazione
    (cosi' vale per qualunque modo di avvio, anche `python main.py` senza flag, e un pid riusato da un altro programma non inganna).
    Un lock senza ora di creazione (vecchio formato) si riconosce dalla riga di comando, come prima."""

    def __init__(self, path: Optional[Path] = None, is_server: Optional[Callable[[int], bool]] = None):
        self.path = Path(path) if path else HOME / 'tpweb.lock'
        self._is_server = is_server

    def _holds(self, pid: int, data: dict) -> bool:
        if self._is_server is not None:
            return self._is_server(pid)
        created = data.get('created')
        if created:
            now = _create_time(pid)
            return now is not None and abs(now - float(created)) < 2.0
        return _is_tpweb_process(pid)

    def holder(self) -> Optional[int]:
        """Pid del server che tiene il lock, None se libero o orfano."""
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            pid = int(data.get('pid', 0))
        except Exception:
            return None
        return pid if pid and pid != os.getpid() and self._holds(pid, data) else None

    def acquire(self) -> bool:
        if self.holder() is not None:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            info = {'pid': os.getpid(), 'since': time.strftime('%Y-%m-%dT%H:%M:%S')}
            created = _create_time(os.getpid())
            if created:
                info['created'] = created
            self.path.write_text(json.dumps(info), encoding='utf-8')
        except Exception:
            pass
        return True

    def release(self) -> None:
        try:
            if int(json.loads(self.path.read_text(encoding='utf-8')).get('pid', 0)) == os.getpid():
                self.path.unlink()
        except Exception:
            pass


def is_qt_gui_cmdline(cmdline: List[str], default_ui: str = 'qt') -> bool:
    """La riga di comando di un processo e' quella della GUI Qt di Transcriber Pro? (non la web UI, non la coda headless)
    Senza `--ui` vale `default_ui` (l'interfaccia predefinita, `ui` del config)."""
    cl = ' '.join(cmdline or [])
    if 'main.py' not in cl or 'Transcriber' not in cl or 'queue_runner' in cl or 'tpweb' in cl:
        return False
    from tpweb.ui_choice import ui_from_args
    try:
        explicit = ui_from_args(list(cmdline or []))
    except ValueError:
        return False
    return (explicit or default_ui) == 'qt'


def _related_pids(psutil, me: int) -> set:
    """Il processo stesso e i suoi antenati: su Windows il venv avvia python.exe come launcher PADRE dell'interprete
    vero (stessa riga di comando), che non e' un'altra istanza."""
    related = {me}
    try:
        proc = psutil.Process(me)
        related.update(p.pid for p in proc.parents())
    except Exception:
        pass
    return related


def _default_ui() -> str:
    """Interfaccia che un `main.py` senza `--ui` avvierebbe su questo computer (chiave `ui` del config; altrimenti il predefinito)."""
    from tpweb.ui_choice import requested_ui
    try:
        from utils.config import get_config
        return requested_ui([], get_config().get)
    except Exception:
        return requested_ui([])


def conflicts(home: Optional[Path] = None) -> List[str]:
    """Altri programmi che possiedono la stessa coda (stessa GPU, stessa cache dei modelli): GUI Qt o coda headless."""
    out: List[str] = []
    home = Path(home) if home else HOME
    try:
        import psutil
        related = _related_pids(psutil, os.getpid())
        default_ui = _default_ui()
        for p in psutil.process_iter(['pid', 'cmdline']):
            if p.info['pid'] in related:
                continue
            if is_qt_gui_cmdline(p.info.get('cmdline') or [], default_ui):
                out.append('gui')
                break
    except Exception:
        pass
    try:
        pid = int(json.loads((home / 'queue.lock').read_text(encoding='utf-8')).get('pid', 0))
        import psutil
        if pid and pid != os.getpid() and psutil.pid_exists(pid) and 'queue_runner' in ' '.join(psutil.Process(pid).cmdline()):
            out.append('headless')
    except Exception:
        pass
    return out
