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


class ServerLock:
    def __init__(self, path: Optional[Path] = None, is_server: Callable[[int], bool] = _is_tpweb_process):
        self.path = Path(path) if path else HOME / 'tpweb.lock'
        self._is_server = is_server

    def holder(self) -> Optional[int]:
        """Pid del server che tiene il lock, None se libero o orfano."""
        try:
            pid = int(json.loads(self.path.read_text(encoding='utf-8')).get('pid', 0))
        except Exception:
            return None
        return pid if pid and pid != os.getpid() and self._is_server(pid) else None

    def acquire(self) -> bool:
        if self.holder() is not None:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'pid': os.getpid(), 'since': time.strftime('%Y-%m-%dT%H:%M:%S')}), encoding='utf-8')
        except Exception:
            pass
        return True

    def release(self) -> None:
        try:
            if int(json.loads(self.path.read_text(encoding='utf-8')).get('pid', 0)) == os.getpid():
                self.path.unlink()
        except Exception:
            pass


def conflicts(home: Optional[Path] = None) -> List[str]:
    """Altri programmi che possiedono la stessa coda (stessa GPU, stessa cache dei modelli): GUI Qt o coda headless."""
    out: List[str] = []
    home = Path(home) if home else HOME
    try:
        import psutil
        me = os.getpid()
        for p in psutil.process_iter(['pid', 'cmdline']):
            if p.info['pid'] == me:
                continue
            cl = ' '.join(p.info.get('cmdline') or [])
            if 'main.py' in cl and 'Transcriber' in cl and 'queue_runner' not in cl and '--ui web' not in cl and 'tpweb' not in cl:
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
