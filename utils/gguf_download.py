# -*- coding: utf-8 -*-
"""Download dei GGUF di TranslateGemma-12B dall'installer (install.sh / install.ps1).

Solo libreria standard piu' `utils` (il pacchetto importa psutil e altro): l'installer lo lancia col Python del venv principale, dopo il pip install. Regole:
  - quale quantizzazione scaricare lo decide `utils.translator_path_select.choose_translator_path` (stesse soglie del router
    a runtime: nessuna copia dei numeri qui). Con bf16 (cuda/rocm, VRAM sufficiente) o sotto la soglia di IQ3_M (NLLB-FT): nessun download.
    Su Vulkan non esiste bf16: il GGUF e' l'unica via, quindi si scarica anche con molta VRAM.
  - mai senza dirlo: l'installer lo chiama solo se l'utente ha chiesto i modelli, mostra file e dimensione e chiede
    conferma (--yes la salta);
  - anonimo (nessun token), RIPRENDIBILE (file `.part` + intestazione Range), con controllo di dimensione e SHA-256
    sul valore del manifesto; il file finale compare solo con la rinomina atomica a controllo superato;
  - un file gia' presente con lo stesso nome ma diverso dal manifesto NON viene toccato (puo' essere un GGUF dell'utente);
  - NON accende `llm_translator_gguf_enabled`: scrive solo i file.

CLI:  python utils/gguf_download.py --gguf auto|q4|iq3|q3|none [--dest DIR] [--yes] [--no-gpu] [--dry-run]
Codici di uscita: 0 = fatto o nulla da fare, 1 = download fallito, 2 = argomenti errati.
"""
import argparse
import hashlib
import http.client
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, NamedTuple, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import translator_path_select as sel  # noqa: E402

HF_REPO = 'Chinasky71/translategemma-12b-it-subtitles-gguf'
DEFAULT_BASE_URL = 'https://huggingface.co/' + HF_REPO + '/resolve/main'
DEFAULT_DEST = ROOT / 'models' / 'translategemma-12b-gguf'
CHUNK = 1 << 20
DISK_MARGIN = 1 << 30            # 1 GiB liberi oltre al file
GGUF_CHOICES = ('auto', 'q4', 'iq3', 'q3', 'none')
_QUANT_OF = {'q4': 'Q4_K_M', 'iq3': 'IQ3_M', 'q3': 'Q3_K_M'}


class GGUFFile(NamedTuple):
    name: str
    size: int
    sha256: str


# Dai metadati LFS del repository pubblico (verificati anonimamente il 24/10/2026). Q3_K_M e' un'alternativa: solo su richiesta.
MANIFEST: Dict[str, GGUFFile] = {
    'Q4_K_M': GGUFFile('translategemma-12b-it-finale-Q4_K_M.gguf', 7300793824,
                       '330c4e297bf3d274fbdefd3f42042d37dbfbbba3fcfee743aaa8b55b6140172c'),
    'IQ3_M': GGUFFile('translategemma-12b-it-finale-IQ3_M.gguf', 5655737824,
                      '17ac3d684d6a4eac6371096d2263a41bcd4c990718299bba96121b7c69b79532'),
    'Q3_K_M': GGUFFile('translategemma-12b-it-finale-Q3_K_M.gguf', 6008833504,
                       '9b369252c5eea7ad87c59075b86d9e57d23064fc57525f476c96139e8d2a5d97'),
}


class DownloadError(Exception):
    pass


class _BadChecksum(Exception):
    pass


def _tr(key: str, **kw) -> str:
    """Testo tradotto (IT/EN) se `utils.translations` si importa; altrimenti la chiave. Mai solleva."""
    try:
        from utils.translations import tr
        s = tr(key)
        return s.format(**kw) if kw else s
    except Exception:
        return key + (' ' + repr(kw) if kw else '')


def _gib(n: float) -> str:
    return f'{n / (1 << 30):.1f} GiB'


# ------------------------------------------------------------------ scelta
def quant_for_vram(vram_gib: Optional[float], backend: str) -> Optional[str]:
    """Quantizzazione da scaricare per una GPU con `vram_gib` GiB, o None (bf16, NLLB-FT, nessuna GPU).

    Chiede al selettore come se tutti i GGUF ci fossero e con il GGUF davanti a NF4 (e' la fascia 12-20 GB che lo vuole):
    lo stesso codice e le stesse soglie del router. La VRAM e' quella TOTALE (a installazione non c'e' un desktop da
    misurare): al piu' si scarica un file che a runtime il router non usa se la VRAM libera non basta."""
    c = sel.choose_translator_path(vram_gib, backend, gguf_available=sel.QUANT_PREFERENCE, gguf_before_nf4=True)
    return c.quant if c.kind == sel.GGUF else None


def resolve_choice(gguf: str, vram_gib: Optional[float], backend: str) -> Tuple[Optional[str], str]:
    """(quant o None, motivo). Il motivo e' un codice stabile per i test."""
    g = (gguf or 'auto').lower()
    if g not in GGUF_CHOICES:
        raise ValueError(g)
    if g == 'none':
        return None, 'none'
    if g in _QUANT_OF:
        return _QUANT_OF[g], 'explicit'
    q = quant_for_vram(vram_gib, backend)
    if q:
        return q, 'vram'
    if not vram_gib or backend == 'cpu':
        return None, 'no_gpu'
    if backend in ('cuda', 'rocm') and vram_gib >= sel.DEFAULT_BF16_MIN_FREE_GIB:
        return None, 'bf16'
    return None, 'vram_too_low'


# ------------------------------------------------------------------ download
def _hash_prefix(path: Path, h) -> int:
    n = 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                return n
            h.update(b)
            n += len(b)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    _hash_prefix(path, h)
    return h.hexdigest()


def _open(url: str, start: int, timeout: float):
    req = urllib.request.Request(url, headers={'User-Agent': 'TranscriberPro-installer'})
    if start:
        req.add_header('Range', f'bytes={start}-')
    return urllib.request.urlopen(req, timeout=timeout)


def download_file(base_url: str, entry: GGUFFile, dest_dir: Path, *, retries: int = 4, timeout: float = 60.0,
                  progress: Optional[Callable[[int, int], None]] = None, sleep: Callable[[float], None] = time.sleep) -> str:
    """Scarica `entry` in `dest_dir`. Restituisce 'present' (gia' valido) o 'downloaded'. Solleva DownloadError."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / entry.name
    part = dest_dir / (entry.name + '.part')
    if final.exists():
        if final.stat().st_size == entry.size and _sha256_file(final) == entry.sha256:
            return 'present'
        raise DownloadError(_tr('gd_err_existing_differs', path=str(final)))
    free = shutil.disk_usage(dest_dir).free
    have = part.stat().st_size if part.exists() else 0
    if free < entry.size - have + DISK_MARGIN:
        raise DownloadError(_tr('gd_err_disk', need=_gib(entry.size - have + DISK_MARGIN), free=_gib(free), path=str(dest_dir)))
    url = base_url.rstrip('/') + '/' + entry.name
    last = ''
    bad = 0
    for attempt in range(retries + 1):
        if attempt:
            sleep(min(30.0, 2.0 ** attempt))
        try:
            _fetch(url, entry, part, timeout, progress)
            break
        except _BadChecksum as exc:        # contenuto sbagliato: il parziale non vale, si ricomincia da zero
            part.unlink(missing_ok=True)
            bad += 1
            last = str(exc)
            if bad >= 2:                   # l'impronta e' deterministica: un terzo giro scaricherebbe altri GB per niente
                raise DownloadError(last)
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                if exc.code == 416:        # il parziale non e' compatibile col file del server: si riparte da zero
                    part.unlink(missing_ok=True)
                elif exc.code in (401, 403, 404):
                    raise DownloadError(_tr('gd_err_http', code=exc.code, url=url))
            last = str(exc)
    else:
        raise DownloadError(_tr('gd_err_failed', name=entry.name, err=last))
    _replace(part, final, sleep)           # rinomina atomica: il nome finale esiste solo se il file e' valido
    return 'downloaded'


def _replace(src: Path, dst: Path, sleep) -> None:
    """os.replace con qualche ripetizione: su Windows un antivirus o l'indicizzatore possono tenere aperto per un attimo il .part appena chiuso."""
    for i in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == 4:
                raise DownloadError(_tr('gd_err_rename', path=str(dst)))
            sleep(1.0 + i)


def _fetch(url: str, entry: GGUFFile, part: Path, timeout: float, progress) -> None:
    h = hashlib.sha256()
    start = part.stat().st_size if part.exists() else 0
    if start > entry.size:
        part.unlink()
        start = 0
    if start == entry.size:                 # tutto scaricato ma non ancora verificato/rinominato
        if _hash_prefix(part, h) == entry.size and h.hexdigest() == entry.sha256:
            return
        part.unlink()
        raise _BadChecksum(_tr('gd_err_checksum', name=entry.name))
    if start:
        _hash_prefix(part, h)               # prima di aprire la connessione: su un disco lento non la lascia ferma
    with _open(url, start, timeout) as r:
        code = getattr(r, 'status', None) or r.getcode()
        if start and code != 206:           # il server ignora Range: si riparte da capo
            start = 0
            h = hashlib.sha256()
        mode = 'ab' if start else 'wb'
        done = start
        with open(part, mode) as f:
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                f.write(b)
                h.update(b)
                done += len(b)
                if progress:
                    progress(done, entry.size)
            f.flush()
            os.fsync(f.fileno())            # il contenuto e' su disco prima della rinomina
    if done != entry.size:
        raise OSError(_tr('gd_err_size', name=entry.name, got=done, want=entry.size))
    if h.hexdigest() != entry.sha256:
        raise _BadChecksum(_tr('gd_err_checksum', name=entry.name))


# ------------------------------------------------------------------ CLI
def _detect(no_gpu: bool) -> Tuple[Optional[float], str]:
    if no_gpu:
        return None, 'cpu'
    try:
        from utils import gpu_detect
        rep = gpu_detect.detect_gpus(force=True)
        b = gpu_detect.recommended_backend(rep)
        mib = gpu_detect.usable_vram_mib(rep, b)
        return (mib / 1024.0 if mib else None), b
    except Exception:
        return None, 'cpu'


def _progress_printer() -> Callable[[int, int], None]:
    state = {'t': 0.0}

    def p(done: int, total: int) -> None:
        now = time.monotonic()
        if now - state['t'] >= 5 or done >= total:
            state['t'] = now
            print(f'    {_gib(done)} / {_gib(total)} ({100 * done // max(1, total)}%)', flush=True)
    return p


def main(argv=None, *, detect=_detect, input_fn=input, is_tty: Optional[bool] = None, sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description='Scarica i GGUF di TranslateGemma-12B.')
    ap.add_argument('--gguf', default='auto', choices=GGUF_CHOICES)
    ap.add_argument('--dest', default='')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--no-gpu', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--base-url', default=os.environ.get('TP_GGUF_BASE_URL', '') or DEFAULT_BASE_URL)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')     # Windows con stdout in pipe: mai UnicodeEncodeError per un percorso con caratteri strani
        except Exception:
            pass
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        from utils.translations import init_language_headless
        init_language_headless()
    except Exception:
        pass
    dest = Path(a.dest) if a.dest else DEFAULT_DEST
    vram, backend = detect(a.no_gpu)
    quant, why = resolve_choice(a.gguf, vram, backend)
    if quant is None:
        print('  ' + _tr('gd_none_' + why, vram=f'{vram:.1f}' if vram else '0', backend=backend))
        return 0
    entry = MANIFEST[quant]
    print(_tr('gd_plan', quant=quant, name=entry.name, size=_gib(entry.size), dest=str(dest)))
    print(_tr('gd_flag_off'))
    if a.dry_run:
        return 0
    if not a.yes:
        tty = sys.stdin.isatty() if is_tty is None else is_tty
        if not tty:
            print(_tr('gd_need_yes'))
            return 0
        if input_fn(_tr('gd_ask') + ' [s/N] ').strip().lower() not in ('s', 'si', 'y', 'yes'):
            print('  ' + _tr('gd_declined'))
            return 0
    try:
        res = download_file(a.base_url, entry, dest, progress=_progress_printer(), sleep=sleep)
    except DownloadError as exc:
        print('  [KO]  ' + str(exc), flush=True)
        return 1
    print(_tr('gd_present' if res == 'present' else 'gd_done', name=entry.name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
