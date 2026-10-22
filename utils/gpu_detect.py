# -*- coding: utf-8 -*-
"""Rilevamento GPU indipendente dal fornitore (NVIDIA, AMD, Intel, Apple) su Windows, Linux, WSL e macOS.

SOLO libreria standard: niente torch/ctranslate2/llama_cpp, quindi non inizializza mai CUDA e gira anche con il Python
di sistema prima che esista il venv (installer):  python utils/gpu_detect.py [--json | --backend | --vram]

API
    detect_gpus(force=False) -> GpuReport      (cache in memoria per CACHE_TTL_S, solo report "puliti": vedi CACHE)
    max_vram_mib(report=None, vendor=None)     VRAM totale massima (MiB) tra le GPU, None se nessun dato
    usable_vram_mib(report=None, backend=None) VRAM della GPU piu' grande USABILE dal backend consigliato (vedi sotto)
    recommended_backend(report=None)           'cuda' | 'rocm' | 'vulkan' | 'cpu'
    describe(report)                           una riga leggibile per i log

FONTI (in ordine di affidabilita'; ognuna e' una funzione `_src_*` isolata, con tutto l'esterno passato da DetectContext):
    nvidia-smi  -> NVML via ctypes (solo se nvidia-smi non ha dato GPU) -> sysfs Linux (/sys/bus/pci/devices)
    -> registro di Windows (HKLM\\HARDWARE\\DEVICEMAP\\VIDEO, ripiego sulla chiave Class) -> CIM via PowerShell (solo se il
    registro non da' nulla) -> lspci (solo nomi, Linux non WSL) -> rocm-smi (solo VRAM AMD mancante) -> vulkaninfo.
    La VRAM di una GPU vista da piu' fonti viene dalla PRIMA fonte di questo ordine che la conosce (nvidia-smi/NVML >
    sysfs/rocm-smi > registro); i campi mancanti si completano con le fonti successive, mai sovrascritti.

REGOLE DI ABBINAMENTO (deduplicazione) di una GPU vista da piu' fonti, abbinamento uno-a-uno (due schede identiche
restano due):
    1) stesso bus PCI ('dddd:bb:dd.f') se entrambe lo conoscono (bus diversi = GPU diverse; se entrambe conoscono anche
       il PCI id, deve coincidere pure quello);
    2) altrimenti stesso PCI id 'vvvv:dddd';
    3) se a una delle due manca il PCI id: stesso fornitore e stesso nome normalizzato.
    vulkaninfo NON aggiunge GPU se un'altra fonte ne ha trovate (con due driver Vulkan installati, es. RADV e AMDVLK, la
    stessa scheda compare due volte): completa solo il campo `integrated`. Se e' l'unica fonte, aggiunge una GPU per PCI id.

REGOLE `integrated` (solo segnali certi, altrimenti None): nvidia-smi/NVML -> False; vulkaninfo deviceType
INTEGRATED_GPU -> True, DISCRETE_GPU -> False; Intel su Linux: bus 0000:00:02.0 (posizione fissa dell'iGPU Intel) -> True,
file lmem_total_bytes presente (memoria locale = scheda Arc discreta) -> False; Apple Silicon -> True.
Nessuna soglia di VRAM: le APU AMD possono avere una memoria riservata grande quanto una scheda discreta.

BACKEND PER GPU (campo GpuInfo.backends) e backend consigliato:
    'cuda'   GPU NVIDIA vista da nvidia-smi o NVML (= driver che risponde). Una NVIDIA vista solo dal registro/sysfs NO.
    'rocm'   GPU AMD, Linux nativo (non WSL), /dev/kfd presente e leggibile/scrivibile, driver amdgpu (se noto), e
             rocminfo (se installato) che elenca almeno un agente gfx. Senza rocminfo basta il KFD (le ruote pip di torch
             ROCm portano il loro runtime). Windows/WSL/macOS: mai.
    'vulkan' GPU NVIDIA/AMD/Intel con integrated diverso da True, e: se vulkaninfo ha risposto, la GPU deve comparire tra
             i suoi dispositivi fisici (llvmpipe/lavapipe/SwiftShader = CPU, esclusi); se vulkaninfo manca, serve la
             libreria del loader Vulkan e la GPU deve essere AMD/Intel oppure una NVIDIA con driver verificato ('cuda').
    recommended_backend: TP_GPU_FORCE_BACKEND (se valido) -> 'cuda' se una GPU lo ha -> 'rocm' -> 'vulkan' -> 'cpu'.
    usable_vram_mib: massimo della VRAM tra le GPU che hanno il backend richiesto (default il consigliato); 'cpu' -> None.
    Se nvidia-smi risponde ma dice [N/A] per memory.total, la VRAM della GPU viene dal registro/sysfs (campo completato
    nella fusione): la GPU resta 'cuda' e la sua VRAM e' quella del registro.

CACHE: un report va in cache (CACHE_TTL_S) solo se ha almeno una GPU, NESSUN errore e nessuna GPU NVIDIA senza 'cuda'
(NVIDIA vista solo da registro/sysfs = nvidia-smi in timeout o driver che si sta caricando): altrimenti la chiamata
successiva riprova. Due chiamanti in parallelo non lanciano due rilevazioni (lock: il secondo aspetta e usa la cache).

PROGRAMMI ESTERNI: su Windows si provano PRIMA i percorsi assoluti noti (System32, NVSMI...); il risultato di which si
accetta solo se e' un percorso assoluto e NON sta direttamente nella cartella corrente (Windows cerca anche li': un
nvidia-smi.exe/powershell.exe/vulkaninfo.exe lasciato nella cartella di lavoro verrebbe eseguito al posto di quello di
sistema). Su Linux: which con la stessa regola, poi i percorsi noti.

ROBUSTEZZA: ogni comando ha un timeout di SOURCE_TIMEOUT_S, nvidia-smi SMI_TIMEOUT_S (unica fonte che puo' attivare
CUDA; il primo avvio a freddo e' lento); meno se il budget totale DEADLINE_S (~9 s) sta finendo, e a budget esaurito le
fonti restanti si saltano. Niente finestre di console su Windows; nessuna eccezione esce verso il chiamante (ogni fonte
e' isolata: un suo guasto finisce in report.errors e le altre proseguono); nessuna stampa su stderr. Un programma
assente NON e' un errore (es. nvidia-smi su un PC AMD).
Variabili d'ambiente (lette da DetectContext.env, default os.environ): TP_GPU_DETECT=off (report vuoto, per prove),
TP_GPU_FORCE_BACKEND=cuda|rocm|vulkan|cpu (salvata nel report al rilevamento: GpuReport.forced_backend).
"""
from __future__ import annotations

import copy
import ctypes
import ctypes.util
import json
import os
import platform as _platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

try:
    from .platform_compat import no_window_flags
except Exception:
    # Eseguito come script (python utils/gpu_detect.py): utils/ e' in sys.path[0] e platform_compat (solo libreria
    # standard) si importa da solo, SENZA utils/__init__.py (che carica config, psutil, client TMDB... e stampa avvisi).
    try:
        from platform_compat import no_window_flags
    except Exception:
        def no_window_flags(windows=None):          # ultimo ripiego: stesso valore di platform_compat
            return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0

SOURCE_TIMEOUT_S = 3.0      # timeout di ogni singolo comando esterno / chiamata NVML (tranne nvidia-smi)
SMI_TIMEOUT_S = 6.0         # nvidia-smi: solo lui (o NVML) attiva CUDA; a freddo su Linux senza persistence mode e' lento
DEADLINE_S = 9.0            # budget totale di detect_gpus nel caso peggiore (nvidia-smi 6 s + le altre fonti nel resto)
MIN_SLICE_S = 0.3           # sotto questo residuo di budget la fonte successiva si salta
CACHE_TTL_S = 60.0          # durata della cache in memoria (solo report con almeno una GPU)

BACKENDS = ('cuda', 'rocm', 'vulkan', 'cpu')
VENDOR_IDS = {0x10de: 'nvidia', 0x1002: 'amd', 0x1022: 'amd', 0x8086: 'intel', 0x106b: 'apple'}
# Adattatori virtuali / di gestione, mai GPU di calcolo: Microsoft (Hyper-V/WSL), VMware, QEMU/Bochs, virtio, Cirrus,
# ASPEED (BMC dei server), Matrox (BMC), VirtualBox, Red Hat QXL.
IGNORED_VENDOR_IDS = {0x1414, 0x15ad, 0x1234, 0x1af4, 0x1013, 0x1a03, 0x102b, 0x80ee, 0x1b36}
GPU_PCI_CLASSES = ('0300', '0302', '0380')      # VGA, 3D controller, display controller
SOFTWARE_VULKAN = re.compile(r'(?i)llvmpipe|lavapipe|swiftshader|softpipe')
_VENDOR_ORDER = {'nvidia': 0, 'amd': 1, 'intel': 2, 'apple': 3, 'other': 4}

# `name` per ULTIMO: e' l'unico campo che puo' contenere virgole; la riga si divide con split(',', n-1).
_SMI_FIELDS = ['memory.total', 'memory.free', 'driver_version', 'pci.bus_id', 'pci.device_id', 'compute_cap', 'name']
_SMI_FIELDS_OLD = [f for f in _SMI_FIELDS if f != 'compute_cap']      # nvidia-smi vecchi: compute_cap sconosciuto
_SMI_BAD_FIELD = re.compile(r'(?i)not a valid field|invalid field|unknown field')
_WIN_DISPLAY_CLASS = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
_WIN_DEVICEMAP = r'HARDWARE\DEVICEMAP\VIDEO'


# ----------------------------------------------------------------------------------------------------------- modello
@dataclass
class GpuInfo:
    vendor: str                                 # 'nvidia' | 'amd' | 'intel' | 'apple' | 'other'
    name: str = ''
    vram_mib: Optional[int] = None              # memoria DEDICATA totale
    vram_free_mib: Optional[int] = None
    driver: Optional[str] = None                # versione del driver (Linux sysfs: nome del modulo del kernel)
    integrated: Optional[bool] = None
    pci_id: Optional[str] = None                # 'vvvv:dddd' minuscolo
    compute_cap: Optional[str] = None           # solo NVIDIA (es. '8.6')
    source: str = ''                            # fonti che l'hanno vista, la prima e' quella principale ('nvidia-smi+registry')
    bus_id: Optional[str] = None                # 'dddd:bb:dd.f' minuscolo, se noto
    backends: List[str] = field(default_factory=list)   # backend che possono usare questa GPU (vedi docstring)


@dataclass
class GpuReport:
    gpus: List[GpuInfo] = field(default_factory=list)
    backends: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # 'cuda'/'rocm'/'vulkan' -> {'available','detail'}
    errors: List[str] = field(default_factory=list)
    platform: str = ''
    in_wsl: bool = False
    forced_backend: Optional[str] = None        # TP_GPU_FORCE_BACKEND valido al momento del rilevamento

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------------------------- contesto iniettabile
def _real_runner(cmd: List[str], timeout: float) -> Tuple[int, str]:
    """Esegue un comando: (codice di uscita, stdout). stderr catturato e scartato, stdin chiuso, nessuna console."""
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout, creationflags=no_window_flags(), text=True, encoding='utf-8',
                       errors='replace')
    out = p.stdout or ''
    if p.returncode != 0 and p.stderr:              # i messaggi d'errore (es. campo non valido) servono a chi decide
        out = (out + '\n' + p.stderr) if out else p.stderr
    return p.returncode, out


def _real_nvml_loader(candidates: List[str]):
    """Prima libreria NVML caricabile tra i candidati (ctypes.CDLL, come pynvml), None se nessuna."""
    for c in candidates:
        try:
            return ctypes.CDLL(c)
        except Exception:
            continue
    return None


class _WinRegistry:
    """Lettore minimo di HKLM con winreg (libreria standard, nessun sottoprocesso)."""

    def __init__(self):
        import winreg
        self._w = winreg

    def _open(self, path):
        return self._w.OpenKey(self._w.HKEY_LOCAL_MACHINE, path, 0, self._w.KEY_READ)

    def subkeys(self, path: str) -> List[str]:
        out = []
        with self._open(path) as k:
            i = 0
            while True:
                try:
                    out.append(self._w.EnumKey(k, i))
                except OSError:
                    break
                i += 1
        return out

    def values(self, path: str) -> Dict[str, Any]:
        out = {}
        with self._open(path) as k:
            i = 0
            while True:
                try:
                    name, data, _typ = self._w.EnumValue(k, i)
                except OSError:
                    break
                out[name] = data
                i += 1
        return out


def _default_registry(plat: str):
    if not plat.startswith('win'):
        return None
    try:
        return _WinRegistry()
    except Exception:
        return None


def _default_access(path: str) -> bool:
    try:
        return os.access(path, os.R_OK | os.W_OK)
    except Exception:
        return False


@dataclass
class DetectContext:
    """Tutto cio' che detect_gpus legge dall'esterno: i test sostituiscono questi campi (nessuna GPU/processo reale)."""
    platform: str = sys.platform
    machine: str = ''
    env: Optional[Mapping[str, str]] = None
    runner: Callable[[List[str], float], Tuple[int, str]] = _real_runner
    which: Callable[[str], Optional[str]] = shutil.which
    is_file: Callable[[str], bool] = os.path.isfile
    exists: Callable[[str], bool] = os.path.exists
    access_rw: Callable[[str], bool] = _default_access
    sysfs_root: str = '/sys'
    dev_root: str = '/dev'
    proc_version: str = '/proc/version'
    registry: Any = 'default'                   # oggetto con subkeys(path)/values(path), None = nessun registro
    nvml_loader: Callable[[List[str]], Any] = _real_nvml_loader
    find_library: Callable[[str], Optional[str]] = ctypes.util.find_library
    clock: Callable[[], float] = time.monotonic
    deadline_s: float = DEADLINE_S
    cwd: Optional[str] = None                   # cartella corrente (regola sui risultati di which)

    def __post_init__(self):
        if self.env is None:
            self.env = os.environ
        if self.cwd is None:
            try:
                self.cwd = os.getcwd()
            except Exception:
                self.cwd = ''
        if not self.machine:
            try:
                self.machine = _platform.machine()
            except Exception:
                self.machine = ''
        if self.registry == 'default':
            self.registry = _default_registry(self.platform)


class _State:
    def __init__(self, ctx: DetectContext):
        self.ctx = ctx
        self.start = ctx.clock()
        self.errors: List[str] = []
        self.notes: Dict[str, str] = {}

    def remaining(self) -> float:
        return self.ctx.deadline_s - (self.ctx.clock() - self.start)

    def slice(self, limit: float = SOURCE_TIMEOUT_S) -> float:
        return min(limit, self.remaining())

    def err(self, msg: str):
        self.errors.append(_ascii(msg)[:300])


def _run(st: _State, cmd: List[str], label: str, limit: float = SOURCE_TIMEOUT_S) -> Optional[Tuple[int, str]]:
    """Esegue un comando con il timeout della fonte. None (e nota in errors se e' un guasto) se non e' andato."""
    t = st.slice(limit)
    if t < MIN_SLICE_S:
        st.err(f'{label}: saltato, tempo totale esaurito')
        return None
    try:
        return st.ctx.runner(cmd, t)
    except FileNotFoundError:
        return None                                  # programma assente: normale, non e' un errore
    except subprocess.TimeoutExpired:
        st.err(f'{label}: timeout dopo {t:.1f} s')
    except Exception as e:
        st.err(f'{label}: {type(e).__name__}: {e}')
    return None


def _call_with_timeout(fn: Callable[[], Any], timeout: float) -> Tuple[bool, Any, Optional[BaseException]]:
    """Esegue fn in un thread demone: (finito, risultato, eccezione). Per le chiamate in-process (NVML)."""
    box: Dict[str, Any] = {}

    def target():
        try:
            box['r'] = fn()
        except BaseException as e:                   # noqa: BLE001 - riportato al chiamante, mai rilanciato
            box['e'] = e
    t = threading.Thread(target=target, name='gpu_detect_nvml', daemon=True)
    t.start()
    t.join(max(0.0, timeout))
    if t.is_alive():
        return False, None, None
    return True, box.get('r'), box.get('e')


# --------------------------------------------------------------------------------------------------------- utilita'
def _ascii(s: Any) -> str:
    return str(s).encode('ascii', 'replace').decode('ascii')


def _num(s: Any) -> Optional[float]:
    """Numero tollerante: '12288', ' 12288 MiB', '8,6', '[N/A]' -> None, '[Not Supported]' -> None."""
    if s is None:
        return None
    t = str(s).strip().replace('\u00a0', '').replace(' ', '')
    if not t or t.startswith('[') or t.upper() in ('N/A', 'NA', 'NONE', '-'):
        return None
    m = re.match(r'^(\d+)(?:[.,](\d+))?', t)
    if not m:
        return None
    return float(m.group(1) + ('.' + m.group(2) if m.group(2) else ''))


def _int(s: Any) -> Optional[int]:
    v = _num(s)
    return int(v) if v is not None else None


def _clean(s: Any) -> Optional[str]:
    if s is None:
        return None
    t = str(s).strip()
    if not t or t.startswith('[') or t.upper() == 'N/A':
        return None
    return t


def _norm_bus(s: Any) -> Optional[str]:
    """'00000000:01:00.0' / '01:00.0' / '0000:03:00.0' -> 'dddd:bb:dd.f' minuscolo."""
    if not s:
        return None
    m = re.match(r'^\s*(?:([0-9a-fA-F]+):)?([0-9a-fA-F]{1,2}):([0-9a-fA-F]{1,2})\.([0-7])\s*$', str(s))
    if not m:
        return None
    dom = int(m.group(1), 16) if m.group(1) else 0
    return f'{dom & 0xffff:04x}:{int(m.group(2), 16):02x}:{int(m.group(3), 16):02x}.{m.group(4)}'


def _pci(vendor: Optional[int], device: Optional[int]) -> Optional[str]:
    if vendor is None or device is None:
        return None
    return f'{vendor & 0xffff:04x}:{device & 0xffff:04x}'


def _hex(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip(), 16)
    except Exception:
        return None


def _vendor_of(vid: Optional[int]) -> str:
    return VENDOR_IDS.get(vid, 'other') if vid is not None else 'other'


def _norm_name(s: str) -> str:
    t = re.sub(r'(?i)\((r|tm)\)|[\u00ae\u2122]', '', s or '').lower()
    return re.sub(r'[^a-z0-9]+', '', t)


def _read(path) -> Optional[str]:
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace').strip()
    except Exception:
        return None


def _mib_from_bytes(v: Any) -> Optional[int]:
    """Byte (int, stringa o REG_BINARY little-endian) -> MiB. 0 o illeggibile -> None."""
    try:
        if isinstance(v, (bytes, bytearray)):
            v = int.from_bytes(bytes(v), 'little')
        n = int(v)
    except Exception:
        return None
    return n // (1024 * 1024) if n > 0 else None


def _reg_str(v: Any) -> Optional[str]:
    """Stringa di registro (REG_SZ, REG_MULTI_SZ o REG_BINARY UTF-16)."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ''
    if isinstance(v, (bytes, bytearray)):
        try:
            v = bytes(v).decode('utf-16-le', errors='replace')
        except Exception:
            return None
    t = str(v).replace('\x00', '').strip()
    return t or None


def _pci_from_pnp(s: Any) -> Optional[str]:
    m = re.search(r'(?i)ven_([0-9a-f]{4})&dev_([0-9a-f]{4})', str(s or ''))
    return f'{m.group(1).lower()}:{m.group(2).lower()}' if m else None


def _is_windows(p: str) -> bool:
    return p.startswith('win')


def _is_linux(p: str) -> bool:
    return p.startswith('linux')


# ------------------------------------------------------------------------------------------- programmi esterni
def _which_ok(ctx: DetectContext, found: Any) -> bool:
    """Regola sui risultati di which: percorso ASSOLUTO (Windows: lettera di unita' o UNC; altrove '/...') e NON
    direttamente nella cartella corrente (Windows la cerca prima del PATH; su Linux succede con '.' nel PATH)."""
    if not found:
        return False
    s = str(found)
    win = _is_windows(ctx.platform)
    if win and not re.match(r'^(?:[A-Za-z]:[\\/]|\\\\)', s):
        return False
    if not win and not s.startswith('/'):
        return False
    if ctx.cwd:
        if win:
            norm = lambda x: x.replace('/', '\\').rstrip('\\').lower()      # noqa: E731
            parent = norm(s).rsplit('\\', 1)[0]
        else:
            norm = lambda x: x.rstrip('/') or '/'                           # noqa: E731
            parent = s.rsplit('/', 1)[0] or '/'
        if parent == norm(ctx.cwd):
            return False
    return True


def _find_exe(ctx: DetectContext, name: str, known: Tuple[str, ...] = ()) -> Optional[str]:
    """Windows: prima i percorsi assoluti noti, poi which (filtrato da _which_ok). Altrove: which filtrato, poi i noti."""
    def known_hit():
        for c in known:
            try:
                if ctx.is_file(c):
                    return c
            except Exception:
                pass
        return None
    win = _is_windows(ctx.platform)
    if win:
        hit = known_hit()
        if hit:
            return hit
    try:
        found = ctx.which(name)
    except Exception:
        found = None
    if _which_ok(ctx, found):
        return found
    return None if win else known_hit()


def _sysroot(ctx: DetectContext) -> str:
    return ctx.env.get('SystemRoot') or ctx.env.get('windir') or r'C:\Windows'


# ----------------------------------------------------------------------------------------------------------- NVIDIA
def _find_nvidia_smi(ctx: DetectContext) -> Optional[str]:
    """Windows: System32 e NVSMI, poi PATH; Linux/WSL: PATH, poi /usr/lib/wsl/lib, /usr/bin, /usr/local/bin."""
    if _is_windows(ctx.platform):
        pf = ctx.env.get('ProgramW6432') or ctx.env.get('ProgramFiles') or r'C:\Program Files'
        known = (_sysroot(ctx) + r'\System32\nvidia-smi.exe', pf + r'\NVIDIA Corporation\NVSMI\nvidia-smi.exe')
    else:
        known = ('/usr/lib/wsl/lib/nvidia-smi', '/usr/bin/nvidia-smi', '/usr/local/bin/nvidia-smi')
    return _find_exe(ctx, 'nvidia-smi', known)


def _parse_nvidia_smi(out: str, fields: List[str]) -> List[GpuInfo]:
    """Una riga CSV per GPU; `name` e' l'ultimo campo e prende tutto il resto della riga (puo' contenere virgole).
    Le righe con meno campi (avvisi, intestazioni) si ignorano."""
    gpus = []
    for line in (out or '').splitlines():
        parts = [p.strip() for p in line.split(',', len(fields) - 1)]
        if len(parts) != len(fields):
            continue
        row = dict(zip(fields, parts))
        name = _clean(row.get('name'))
        if not name:
            continue
        pci = None
        dev_id = _hex(row.get('pci.device_id', ''))     # 0xDDDDVVVV: device nei 16 bit alti, vendor nei bassi
        if dev_id:
            pci = _pci(dev_id & 0xffff, dev_id >> 16)
        gpus.append(GpuInfo(
            vendor='nvidia', name=name, vram_mib=_int(row.get('memory.total')),
            vram_free_mib=_int(row.get('memory.free')), driver=_clean(row.get('driver_version')),
            integrated=False, pci_id=pci, compute_cap=_clean(row.get('compute_cap')),
            source='nvidia-smi', bus_id=_norm_bus(row.get('pci.bus_id'))))
    return gpus


def _src_nvidia_smi(st: _State) -> List[GpuInfo]:
    """nvidia-smi --query-gpu (timeout SMI_TIMEOUT_S). Le versioni vecchie non conoscono compute_cap: SOLO se l'uscita
    dice che un campo non e' valido (_SMI_BAD_FIELD) si ripete UNA volta senza quel campo. Timeout o altro codice != 0
    (driver che non risponde) -> nessun nuovo tentativo, errore registrato."""
    exe = _find_nvidia_smi(st.ctx)
    if not exe:
        st.notes['nvidia-smi'] = 'nvidia-smi non trovato'
        return []
    rc, last = 0, ''
    for fields in (_SMI_FIELDS, _SMI_FIELDS_OLD):
        res = _run(st, [exe, '--query-gpu=' + ','.join(fields), '--format=csv,noheader,nounits'], 'nvidia-smi',
                   SMI_TIMEOUT_S)
        if res is None:
            return []
        rc, out = res
        if rc == 0:
            gpus = _parse_nvidia_smi(out, fields)
            if not gpus:
                st.notes['nvidia-smi'] = 'nvidia-smi non elenca GPU'
            return gpus
        last = (out or '').strip().splitlines()[0] if (out or '').strip() else ''
        st.notes['nvidia-smi'] = f'nvidia-smi codice {rc}'
        if 'compute_cap' not in fields or not _SMI_BAD_FIELD.search(out or ''):
            break
    st.err(f'nvidia-smi: codice di uscita {rc}' + (f': {last}' if last else ''))
    return []


class _NvmlMemory(ctypes.Structure):
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


class _NvmlPciInfo(ctypes.Structure):
    _fields_ = [('busIdLegacy', ctypes.c_char * 16), ('domain', ctypes.c_uint), ('bus', ctypes.c_uint),
                ('device', ctypes.c_uint), ('pciDeviceId', ctypes.c_uint), ('pciSubSystemId', ctypes.c_uint),
                ('busId', ctypes.c_char * 32)]


def _nvml_candidates(ctx: DetectContext) -> List[str]:
    if _is_windows(ctx.platform):
        sysroot = _sysroot(ctx)
        pf = ctx.env.get('ProgramW6432') or ctx.env.get('ProgramFiles') or r'C:\Program Files'
        return ['nvml.dll', sysroot + r'\System32\nvml.dll', pf + r'\NVIDIA Corporation\NVSMI\nvml.dll']
    return ['libnvidia-ml.so.1', '/usr/lib/wsl/lib/libnvidia-ml.so.1']


def _nvml_query(lib) -> Tuple[List[GpuInfo], Optional[str]]:
    """Interroga NVML (ctypes). Restituisce (gpu, errore). Non crea contesti CUDA."""
    rc = lib.nvmlInit_v2()
    if rc != 0:
        return [], f'NVML: nvmlInit_v2 codice {rc}'
    gpus = []
    try:
        drv = None
        buf = ctypes.create_string_buffer(96)
        try:
            if lib.nvmlSystemGetDriverVersion(buf, 96) == 0:
                drv = buf.value.decode('utf-8', 'replace') or None
        except Exception:
            pass
        n = ctypes.c_uint(0)
        if lib.nvmlDeviceGetCount_v2(ctypes.byref(n)) != 0:
            return [], 'NVML: nvmlDeviceGetCount_v2 fallita'
        for i in range(n.value):
            h = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) != 0:
                continue
            nb = ctypes.create_string_buffer(96)
            name = nb.value.decode('utf-8', 'replace') if lib.nvmlDeviceGetName(h, nb, 96) == 0 else ''
            mem = _NvmlMemory()
            total = free = None
            if lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)) == 0:
                total, free = mem.total // (1024 * 1024) or None, mem.free // (1024 * 1024)
            cc = None
            try:
                ma, mi = ctypes.c_int(0), ctypes.c_int(0)
                if lib.nvmlDeviceGetCudaComputeCapability(h, ctypes.byref(ma), ctypes.byref(mi)) == 0:
                    cc = f'{ma.value}.{mi.value}'
            except Exception:
                pass
            pci = bus = None
            try:
                pi = _NvmlPciInfo()
                if lib.nvmlDeviceGetPciInfo_v3(h, ctypes.byref(pi)) == 0:
                    pci = _pci(pi.pciDeviceId & 0xffff, pi.pciDeviceId >> 16) if pi.pciDeviceId else None
                    bus = _norm_bus(pi.busId.decode('ascii', 'replace'))
            except Exception:
                pass
            gpus.append(GpuInfo(vendor='nvidia', name=name or 'NVIDIA GPU', vram_mib=total, vram_free_mib=free,
                                driver=drv, integrated=False, pci_id=pci, compute_cap=cc, source='nvml', bus_id=bus))
    finally:
        try:
            lib.nvmlShutdown()
        except Exception:
            pass
    return gpus, None


def _src_nvml(st: _State) -> List[GpuInfo]:
    """Ripiego quando nvidia-smi manca o non elenca GPU: NVML via ctypes in un thread con timeout."""
    try:
        lib = st.ctx.nvml_loader(_nvml_candidates(st.ctx))
    except Exception:
        lib = None
    if lib is None:
        return []
    t = st.slice()
    if t < MIN_SLICE_S:
        st.err('NVML: saltato, tempo totale esaurito')
        return []
    done, res, exc = _call_with_timeout(lambda: _nvml_query(lib), t)
    if not done:
        st.err(f'NVML: timeout dopo {t:.1f} s')
        return []
    if exc is not None:
        st.err(f'NVML: {type(exc).__name__}: {exc}')
        return []
    gpus, e = res
    if e:
        st.err(e)
    return gpus


# ------------------------------------------------------------------------------------------------------------ Linux
def _detect_wsl(ctx: DetectContext) -> bool:
    """WSL: /proc/version contiene 'microsoft' oppure esiste /dev/dxg (paravirtualizzazione GPU di WSL2)."""
    if not _is_linux(ctx.platform):
        return False
    v = (_read(ctx.proc_version) or '').lower()
    if 'microsoft' in v:
        return True
    try:
        return bool(ctx.exists(os.path.join(ctx.dev_root, 'dxg')))
    except Exception:
        return False


def _uevent(dev: Path) -> Dict[str, str]:
    """Righe CHIAVE=valore di device/uevent (DRIVER, PCI_ID, PCI_SLOT_NAME...)."""
    out = {}
    for line in (_read(dev / 'uevent') or '').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def _driver_name(dev: Path, uev: Dict[str, str]) -> Optional[str]:
    """Nome del driver del kernel: riga DRIVER= di uevent, poi il link simbolico device/driver."""
    if uev.get('DRIVER'):
        return uev['DRIVER']
    try:
        return os.path.basename(os.readlink(str(dev / 'driver'))) or None
    except Exception:
        return None


def _src_sysfs(st: _State) -> List[GpuInfo]:
    """Linux: /sys/bus/pci/devices/* con classe display. Vede anche schede senza driver caricato.
    AMD (amdgpu): mem_info_vram_total/used (VRAM dedicata; la GTT, memoria di sistema condivisa, NON si conta).
    Intel: lmem_total_bytes (in device/drm/cardN/ o device/) = memoria locale di una scheda discreta.
    NVIDIA: il driver proprietario non espone la VRAM in sysfs (la da' nvidia-smi)."""
    base = Path(st.ctx.sysfs_root) / 'bus' / 'pci' / 'devices'
    try:
        devs = sorted(base.iterdir(), key=lambda p: p.name)
    except Exception:
        return []
    gpus = []
    for d in devs:
        cls = (_read(d / 'class') or '').lower().replace('0x', '')
        if cls[:4] not in GPU_PCI_CLASSES:
            continue
        vid, did = _hex(_read(d / 'vendor')), _hex(_read(d / 'device'))
        if vid is None or vid in IGNORED_VENDOR_IDS:
            continue
        vendor = _vendor_of(vid)
        uev = _uevent(d)
        bus = _norm_bus(uev.get('PCI_SLOT_NAME') or d.name)      # PCI_SLOT_NAME = nome della cartella in sysfs
        drv = _driver_name(d, uev)
        g = GpuInfo(vendor=vendor, name=_read(d / 'product_name') or '', driver=drv, pci_id=_pci(vid, did),
                    source='sysfs', bus_id=bus)
        if vendor == 'amd':
            tot = _mib_from_bytes(_read(d / 'mem_info_vram_total'))
            used = _mib_from_bytes(_read(d / 'mem_info_vram_used'))
            g.vram_mib = tot
            if tot is not None:
                g.vram_free_mib = max(0, tot - (used or 0))
        elif vendor == 'intel':
            cards = []
            try:
                cards = sorted(p for p in (d / 'drm').iterdir() if re.match(r'^card\d+$', p.name))
            except Exception:
                pass
            lmem = None
            for p in [c / 'lmem_total_bytes' for c in cards] + [d / 'lmem_total_bytes']:
                lmem = _mib_from_bytes(_read(p))
                if lmem:
                    break
            if lmem:
                g.vram_mib, g.integrated = lmem, False
            elif bus == '0000:00:02.0':
                g.integrated = True                       # posizione PCI fissa dell'iGPU Intel
        gpus.append(g)
    return gpus


def _parse_lspci(out: str) -> List[GpuInfo]:
    """`lspci -mm -nn -D`: slot "classe [cccc]" "vendor [vvvv]" "device [dddd]" ... (solo classi display)."""
    gpus = []
    for line in (out or '').splitlines():
        try:
            tok = shlex.split(line)
        except ValueError:
            continue
        if len(tok) < 4:
            continue
        slot, cls, ven, dev = tok[0], tok[1], tok[2], tok[3]
        mc, mv, md = (re.search(r'\[([0-9a-fA-F]{4})\]\s*$', x) for x in (cls, ven, dev))
        if not (mc and mv and md) or mc.group(1).lower() not in GPU_PCI_CLASSES:
            continue
        vid = int(mv.group(1), 16)
        if vid in IGNORED_VENDOR_IDS:
            continue
        name = dev[:md.start()].strip()
        br = re.search(r'\[([^\[\]]+)\]\s*$', name)          # "Navi 31 [Radeon RX 7900 XT/7900 XTX]" -> nome commerciale
        if br:
            name = br.group(1).strip()
        gpus.append(GpuInfo(vendor=_vendor_of(vid), name=name, pci_id=_pci(vid, int(md.group(1), 16)),
                            source='lspci', bus_id=_norm_bus(slot)))
    return gpus


def _src_lspci(st: _State) -> List[GpuInfo]:
    exe = _find_exe(st.ctx, 'lspci', ('/usr/bin/lspci', '/sbin/lspci', '/usr/sbin/lspci'))
    if not exe:
        return []
    res = _run(st, [exe, '-mm', '-nn', '-D'], 'lspci')
    if res is None:
        return []
    rc, out = res
    if rc != 0:
        st.err(f'lspci: codice di uscita {rc}')
        return []
    return _parse_lspci(out)


def _parse_rocm_smi(out: str) -> List[Tuple[Optional[str], Optional[int], Optional[int]]]:
    """rocm-smi --showmeminfo vram --showbus --json -> [(bus, total_mib, used_mib)] per scheda (chiavi 'card*')."""
    try:
        data = json.loads(out)
    except Exception:
        return []
    if not isinstance(data, dict):                  # uscita inattesa (lista, numero...): fonte ignorata
        return []
    rows = []
    for key in sorted(k for k in data if str(k).lower().startswith('card')):
        v = data[key] if isinstance(data[key], dict) else {}
        tot = used = bus = None
        for k2, val in v.items():
            kl = str(k2).lower()
            if 'vram total memory' in kl:
                tot = _mib_from_bytes(_int(val))
            elif 'vram total used memory' in kl:
                used = _mib_from_bytes(_int(val))
            elif 'pci bus' in kl:
                bus = _norm_bus(val)
        rows.append((bus, tot, used))
    return rows


def _enrich_rocm_smi(st: _State, gpus: List[GpuInfo]):
    """Solo se una GPU AMD non ha VRAM da sysfs: rocm-smi. Abbinamento per bus PCI; senza bus solo se c'e' esattamente
    una GPU AMD senza VRAM e una sola scheda nell'uscita."""
    missing = [g for g in gpus if g.vendor == 'amd' and g.vram_mib is None]
    if not missing:
        return
    exe = _find_exe(st.ctx, 'rocm-smi', ('/opt/rocm/bin/rocm-smi',))
    if not exe:
        return
    res = _run(st, [exe, '--showmeminfo', 'vram', '--showbus', '--json'], 'rocm-smi')
    if res is None:
        return
    rc, out = res
    if rc != 0:
        st.err(f'rocm-smi: codice di uscita {rc}')
        return
    rows = _parse_rocm_smi(out)
    for bus, tot, used in rows:
        target = None
        if bus:
            target = next((g for g in missing if g.bus_id == bus), None)
        elif len(rows) == 1 and len(missing) == 1:
            target = missing[0]
        if target is not None and tot:
            target.vram_mib = tot
            target.vram_free_mib = max(0, tot - (used or 0))
            if 'rocm-smi' not in target.source:
                target.source += '+rocm-smi'


def _rocm_backend(st: _State, gpus: List[GpuInfo], in_wsl: bool) -> Tuple[bool, str]:
    """Regole del backend ROCm (vedi docstring del modulo)."""
    ctx = st.ctx
    amd = [g for g in gpus if g.vendor == 'amd']
    if not _is_linux(ctx.platform):
        return False, 'ROCm gestito solo su Linux'
    if in_wsl:
        return False, 'WSL: GPU AMD/ROCm non supportate'
    if not amd:
        return False, 'nessuna GPU AMD'
    if not any(g.driver in (None, 'amdgpu') for g in amd):
        return False, 'GPU AMD senza driver amdgpu'
    kfd = os.path.join(ctx.dev_root, 'kfd')
    if not ctx.exists(kfd):
        return False, '/dev/kfd assente (driver amdgpu senza KFD)'
    if not ctx.access_rw(kfd):
        return False, "/dev/kfd senza permessi: aggiungere l'utente ai gruppi render e video"
    exe = _find_exe(ctx, 'rocminfo', ('/opt/rocm/bin/rocminfo',))
    if not exe:
        return True, '/dev/kfd pronto; rocminfo assente (runtime ROCm di sistema non installato)'
    res = _run(st, [exe], 'rocminfo')
    if res is None:
        return False, 'rocminfo non ha risposto'
    rc, out = res
    targets = sorted(set(re.findall(r'(?m)^\s*Name:\s+(gfx[0-9a-z]+)\s*$', out or '')))
    if rc != 0 or not targets:
        st.err(f'rocminfo: codice {rc}, agenti gfx: {len(targets)}')
        return False, 'rocminfo non elenca agenti GPU'
    return True, 'rocminfo: ' + ', '.join(targets)


# ---------------------------------------------------------------------------------------------------------- Windows
def _gpu_from_reg_values(vals: Dict[str, Any], source: str) -> Optional[GpuInfo]:
    """Valori della chiave di un adattatore -> GpuInfo. Senza MatchingDeviceId PCI (BasicDisplay, adattatori remoti)
    o con fornitore virtuale -> None. VRAM: HardwareInformation.qwMemorySize (64 bit); MemorySize (32 bit, si ferma a
    4 GB) solo se qwMemorySize manca."""
    pci = _pci_from_pnp(_reg_str(vals.get('MatchingDeviceId')))
    if not pci:
        return None
    vid = int(pci[:4], 16)
    if vid in IGNORED_VENDOR_IDS:
        return None
    mem = _mib_from_bytes(vals.get('HardwareInformation.qwMemorySize'))
    if mem is None:
        mem = _mib_from_bytes(vals.get('HardwareInformation.MemorySize'))
    name = _reg_str(vals.get('DriverDesc')) or _reg_str(vals.get('HardwareInformation.AdapterString')) or ''
    return GpuInfo(vendor=_vendor_of(vid), name=name, vram_mib=mem, driver=_reg_str(vals.get('DriverVersion')),
                   pci_id=pci, source=source)


def _src_registry(st: _State) -> List[GpuInfo]:
    """Windows, senza sottoprocessi. 1) HKLM\\HARDWARE\\DEVICEMAP\\VIDEO: chiave volatile ricreata a ogni avvio, elenca
    SOLO gli adattatori presenti; piu' voci (\\Device\\VideoN, una per uscita) puntano allo stesso Control\\Video\\{GUID}:
    una GPU per GUID. 2) Ripiego se la 1 non da' nulla: Class\\{4d36e968-...}\\NNNN (puo' contenere schede rimosse)."""
    reg = st.ctx.registry
    if reg is None:
        return []
    gpus: List[GpuInfo] = []
    try:
        vals = reg.values(_WIN_DEVICEMAP)
    except Exception:
        vals = {}
    seen = set()
    rx = re.compile(r'(?i)^\\registry\\machine\\(.+\\video\\(\{[^}]+\}))\\(\d{4})$')
    for key in sorted(vals, key=lambda k: (len(k), k)):
        if not re.match(r'(?i)^\\device\\video\d+$', key):
            continue
        m = rx.match(_reg_str(vals[key]) or '')
        if not m or m.group(2).lower() in seen:
            continue
        seen.add(m.group(2).lower())
        try:
            g = _gpu_from_reg_values(reg.values(m.group(1) + '\\' + m.group(3)), 'registry')
        except Exception:
            g = None
        if g:
            gpus.append(g)
    if gpus:
        return gpus
    try:
        subs = sorted(k for k in reg.subkeys(_WIN_DISPLAY_CLASS) if re.match(r'^\d{4}$', k))
    except Exception as e:
        st.err(f'registro: {type(e).__name__}: {e}')
        return []
    for k in subs:
        try:
            g = _gpu_from_reg_values(reg.values(_WIN_DISPLAY_CLASS + '\\' + k), 'registry-class')
        except Exception:
            g = None
        if g:
            gpus.append(g)
    return gpus


def _src_cim(st: _State) -> List[GpuInfo]:
    """Ultimo ripiego su Windows (registro illeggibile): Win32_VideoController via PowerShell. NON si usa AdapterRAM
    (32 bit, si ferma a 4 GB): la VRAM resta None."""
    ctx = st.ctx
    exe = _find_exe(ctx, 'powershell', (_sysroot(ctx) + r'\System32\WindowsPowerShell\v1.0\powershell.exe',))
    if not exe:
        return []
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_VideoController | "
              "ForEach-Object { $_.Name + '|' + $_.PNPDeviceID + '|' + $_.DriverVersion }")
    res = _run(st, [exe, '-NoProfile', '-NonInteractive', '-Command', script], 'CIM')
    if res is None:
        return []
    rc, out = res
    if rc != 0:
        st.err(f'CIM: codice di uscita {rc}')
        return []
    gpus = []
    for line in (out or '').splitlines():
        parts = line.strip().split('|')
        if len(parts) != 3:
            continue
        pci = _pci_from_pnp(parts[1])
        if not pci or int(pci[:4], 16) in IGNORED_VENDOR_IDS:
            continue
        gpus.append(GpuInfo(vendor=_vendor_of(int(pci[:4], 16)), name=parts[0].strip(),
                            driver=parts[2].strip() or None, pci_id=pci, source='cim'))
    return gpus


# ----------------------------------------------------------------------------------------------------------- Vulkan
def _parse_vulkaninfo(out: str) -> List[Dict[str, str]]:
    """Blocchi 'GPUn:' di `vulkaninfo --summary` -> dizionari chiave=valore."""
    devs: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None
    for line in (out or '').splitlines():
        if re.match(r'^\s*GPU\d+\s*:\s*$', line):
            cur = {}
            devs.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r'^\s*([A-Za-z]+)\s*=\s*(.*?)\s*$', line)
        if m:
            cur.setdefault(m.group(1), m.group(2))
        elif line.strip() and not line.startswith((' ', '\t')):
            cur = None                                   # fine della sezione dispositivi
    return devs


def _src_vulkaninfo(st: _State) -> Tuple[Optional[List[GpuInfo]], int]:
    """(GPU fisiche, n. dispositivi software esclusi). None se vulkaninfo manca o non risponde (non verificato)."""
    known = (_sysroot(st.ctx) + r'\System32\vulkaninfo.exe',) if _is_windows(st.ctx.platform) else ('/usr/bin/vulkaninfo',)
    exe = _find_exe(st.ctx, 'vulkaninfo', known)
    if not exe:
        return None, 0
    res = _run(st, [exe, '--summary'], 'vulkaninfo')
    if res is None:
        return None, 0
    rc, out = res
    devs = _parse_vulkaninfo(out)
    if rc != 0 and not devs:
        st.notes['vulkaninfo'] = f'vulkaninfo codice {rc}'
        return None, 0
    gpus, soft = [], 0
    for d in devs:
        typ = d.get('deviceType', '').upper()
        name = d.get('deviceName', '')
        if 'CPU' in typ or SOFTWARE_VULKAN.search(name):
            soft += 1
            continue
        vid, did = _hex(d.get('vendorID')), _hex(d.get('deviceID'))
        if vid is None or vid in IGNORED_VENDOR_IDS:
            continue
        integ = True if 'INTEGRATED' in typ else False if 'DISCRETE' in typ else None
        gpus.append(GpuInfo(vendor=_vendor_of(vid), name=name, integrated=integ, pci_id=_pci(vid, did),
                            driver=d.get('driverInfo') or None, source='vulkaninfo'))
    return gpus, soft


def _vulkan_loader(ctx: DetectContext) -> bool:
    """Libreria del loader Vulkan: vulkan-1.dll in System32 (Windows) o libvulkan.so.1 nei percorsi noti / find_library."""
    if _is_windows(ctx.platform):
        try:
            return bool(ctx.is_file(_sysroot(ctx) + r'\System32\vulkan-1.dll'))
        except Exception:
            return False
    if not _is_linux(ctx.platform):
        return False
    for p in ('/usr/lib/x86_64-linux-gnu/libvulkan.so.1', '/usr/lib64/libvulkan.so.1', '/usr/lib/libvulkan.so.1',
              '/usr/lib/aarch64-linux-gnu/libvulkan.so.1'):
        try:
            if ctx.is_file(p):
                return True
        except Exception:
            pass
    try:
        return bool(ctx.find_library('vulkan'))
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------- fusione e ordine
def _matches(a: GpuInfo, b: GpuInfo) -> bool:
    if a.bus_id and b.bus_id:
        return a.bus_id == b.bus_id and (not (a.pci_id and b.pci_id) or a.pci_id == b.pci_id)
    if a.pci_id and b.pci_id:
        return a.pci_id == b.pci_id
    return a.vendor == b.vendor and bool(a.name) and _norm_name(a.name) == _norm_name(b.name)


_FILL = ('vram_mib', 'vram_free_mib', 'driver', 'integrated', 'pci_id', 'compute_cap', 'bus_id')


def _fill(dst: GpuInfo, src: GpuInfo):
    """Completa i campi mancanti di dst con src (mai sovrascrivere: dst viene da una fonte piu' affidabile)."""
    if not dst.name and src.name:
        dst.name = src.name
    for f in _FILL:
        if getattr(dst, f) is None and getattr(src, f) is not None:
            setattr(dst, f, getattr(src, f))
    if src.source and src.source not in dst.source.split('+'):
        dst.source = (dst.source + '+' + src.source) if dst.source else src.source


def _merge(final: List[GpuInfo], new: List[GpuInfo], add: bool = True):
    """Abbinamento uno-a-uno: ogni GPU gia' in `final` si abbina al piu' a una GPU di questa fonte."""
    used = set()
    for g in new:
        idx = next((i for i, f in enumerate(final) if i not in used and _matches(f, g)), None)
        if idx is not None:
            _fill(final[idx], g)
            used.add(idx)
        elif add:
            final.append(copy.copy(g))
            used.add(len(final) - 1)


def _sort_key(g: GpuInfo):
    integ = 0 if g.integrated is False else 1 if g.integrated is None else 2
    return (integ, -(g.vram_mib or 0), _VENDOR_ORDER.get(g.vendor, 9), g.name.lower(), g.bus_id or '', g.pci_id or '')


def _env_off(env: Mapping[str, str]) -> bool:
    return str(env.get('TP_GPU_DETECT', '')).strip().lower() in ('off', '0', 'false', 'no')


def _forced(env: Mapping[str, str]) -> Optional[str]:
    """TP_GPU_FORCE_BACKEND se e' uno dei BACKENDS (maiuscole ammesse), altrimenti None (valore ignorato)."""
    try:
        v = str(env.get('TP_GPU_FORCE_BACKEND', '')).strip().lower()
    except Exception:
        return None
    return v if v in BACKENDS else None


def _guard(st: _State, label: str, fn: Callable[[], Any], default: Any) -> Any:
    """Isola una fonte: un'eccezione imprevista finisce in errors e la fonte vale `default`; le altre proseguono."""
    try:
        return fn()
    except Exception as e:
        st.err(f'{label}: {type(e).__name__}: {e}')
        return default


def _empty_backends(detail: str) -> Dict[str, Dict[str, Any]]:
    return {b: {'available': False, 'detail': detail} for b in ('cuda', 'rocm', 'vulkan')}


def _detect(ctx: DetectContext) -> GpuReport:
    st = _State(ctx)
    plat = ctx.platform
    rep = GpuReport(platform=plat, forced_backend=_forced(ctx.env))
    if _env_off(ctx.env):
        rep.backends = _empty_backends('TP_GPU_DETECT=off')
        return rep

    if plat == 'darwin':
        # macOS: Metal non gestito dall'app. Apple Silicon -> una GPU integrata senza VRAM; Mac Intel -> nessuna GPU.
        if ctx.machine.lower() in ('arm64', 'aarch64'):
            rep.gpus.append(GpuInfo(vendor='apple', name='Apple Silicon GPU', integrated=True, source='platform'))
        rep.backends = _empty_backends('macOS: backend GPU non gestiti')
        return rep
    if not (_is_windows(plat) or _is_linux(plat)):
        rep.backends = _empty_backends(f'piattaforma {plat} non gestita')
        return rep

    in_wsl = _detect_wsl(ctx)
    rep.in_wsl = in_wsl
    gpus: List[GpuInfo] = []

    smi = _guard(st, 'nvidia-smi', lambda: _src_nvidia_smi(st), [])
    _merge(gpus, smi)
    if not smi:
        _merge(gpus, _guard(st, 'NVML', lambda: _src_nvml(st), []))

    if _is_linux(plat):
        sysfs = _guard(st, 'sysfs', lambda: _src_sysfs(st), [])
        _merge(gpus, sysfs)
        # lspci solo per i nomi: se sysfs non ha trovato nulla o qualche GPU e' senza nome. In WSL mostra solo
        # l'adattatore virtuale Microsoft: si salta.
        if not in_wsl and (not sysfs or any(not g.name for g in gpus)):
            _merge(gpus, _guard(st, 'lspci', lambda: _src_lspci(st), []), add=not sysfs)
        _guard(st, 'rocm-smi', lambda: _enrich_rocm_smi(st, gpus), None)
    else:
        reg = _guard(st, 'registro', lambda: _src_registry(st), [])
        _merge(gpus, reg)
        if not reg:
            _merge(gpus, _guard(st, 'CIM', lambda: _src_cim(st), []))

    vk, soft = _guard(st, 'vulkaninfo', lambda: _src_vulkaninfo(st), (None, 0))
    if vk is not None:
        if gpus:
            _merge(gpus, vk, add=False)
        else:                                            # unica fonte: una GPU per PCI id (due driver = stessa scheda)
            uniq: Dict[Any, GpuInfo] = {}
            for g in vk:
                uniq.setdefault(g.pci_id or id(g), g)
            _merge(gpus, list(uniq.values()))

    # --- backend per GPU (regole nel docstring del modulo)
    for g in gpus:
        g.backends = []
        if g.vendor == 'nvidia' and any(s in ('nvidia-smi', 'nvml') for s in g.source.split('+')):
            g.backends.append('cuda')
    rocm_ok, rocm_detail = _guard(st, 'ROCm', lambda: _rocm_backend(st, gpus, in_wsl), (False, 'controllo ROCm fallito'))
    if rocm_ok:
        for g in gpus:
            if g.vendor == 'amd' and g.driver in (None, 'amdgpu'):
                g.backends.append('rocm')
    loader = _guard(st, 'loader Vulkan', lambda: _vulkan_loader(ctx), False) if vk is None else True
    for g in gpus:
        if g.vendor not in ('nvidia', 'amd', 'intel') or g.integrated is True:
            continue
        if vk is not None:
            ok = 'vulkaninfo' in g.source.split('+')
        else:
            ok = loader and (g.vendor in ('amd', 'intel') or 'cuda' in g.backends)
        if ok:
            g.backends.append('vulkan')

    gpus.sort(key=_sort_key)
    rep.gpus = gpus

    nv = [g for g in gpus if 'cuda' in g.backends]
    if nv:
        cuda_detail = f'driver NVIDIA {nv[0].driver or "?"} ({nv[0].source.split("+")[0]})'
    else:
        cuda_detail = st.notes.get('nvidia-smi', 'nessuna GPU NVIDIA con driver funzionante')
        if 'nvidia-smi' not in st.notes and not any(g.vendor == 'nvidia' for g in gpus):
            cuda_detail = 'nessuna GPU NVIDIA'
    if vk is not None:
        vk_detail = f'vulkaninfo: {len(vk)} GPU fisiche' + (f', {soft} dispositivi software esclusi' if soft else '')
    elif loader:
        vk_detail = 'loader Vulkan presente, dispositivi non verificati (vulkaninfo assente)'
    else:
        vk_detail = 'loader Vulkan non trovato'
    rep.backends = {
        'cuda': {'available': bool(nv), 'detail': cuda_detail},
        'rocm': {'available': rocm_ok, 'detail': rocm_detail},
        'vulkan': {'available': any('vulkan' in g.backends for g in gpus), 'detail': vk_detail},
    }
    rep.errors = st.errors
    return rep


# ------------------------------------------------------------------------------------------------------------- API
_CACHE: Optional[Tuple[float, GpuReport]] = None
_LOCK = threading.Lock()            # protegge _CACHE
_DETECT_LOCK = threading.Lock()     # una rilevazione alla volta: chi arriva durante una rilevazione aspetta e usa la cache


def _cacheable(rep: GpuReport) -> bool:
    """Regola della cache: almeno una GPU, nessun errore, nessuna NVIDIA senza 'cuda' (vista solo da registro/sysfs)."""
    if not rep.gpus or rep.errors:
        return False
    return not any(g.vendor == 'nvidia' and 'cuda' not in g.backends for g in rep.gpus)


def clear_cache():
    global _CACHE
    with _LOCK:
        _CACHE = None


def detect_gpus(force: bool = False, ctx: Optional[DetectContext] = None) -> GpuReport:
    """Report delle GPU. Mai eccezioni: un guasto imprevisto finisce in report.errors. Cache (CACHE_TTL_S) solo per i
    report che passano _cacheable: un report vuoto, con errori o con una NVIDIA senza CUDA si riprova alla chiamata
    successiva. Rilevazioni serializzate da _DETECT_LOCK."""
    global _CACHE
    try:
        ctx = ctx or DetectContext()
        if _env_off(ctx.env):
            return _detect(ctx)
        with _DETECT_LOCK:
            now = ctx.clock()
            with _LOCK:
                cached = _CACHE
            if not force and cached is not None and now - cached[0] < CACHE_TTL_S:
                rep = copy.deepcopy(cached[1])
                rep.forced_backend = _forced(ctx.env)       # l'override vale per chi chiama adesso
                return rep
            rep = _detect(ctx)
            if _cacheable(rep):
                with _LOCK:
                    _CACHE = (ctx.clock(), copy.deepcopy(rep))
            return rep
    except Exception as e:                               # rete di sicurezza: nessuna eccezione verso il chiamante
        rep = GpuReport(platform=sys.platform, errors=[_ascii(f'gpu_detect: {type(e).__name__}: {e}')])
        rep.backends = _empty_backends('rilevamento fallito')
        return rep


def max_vram_mib(report: Optional[GpuReport] = None, vendor: Optional[str] = None) -> Optional[int]:
    """VRAM totale massima (MiB) tra le GPU (filtrate per fornitore se indicato); None se nessun valore noto."""
    rep = report if report is not None else detect_gpus()
    vals = [g.vram_mib for g in rep.gpus if g.vram_mib and (vendor is None or g.vendor == vendor)]
    return max(vals) if vals else None


def recommended_backend(report: Optional[GpuReport] = None) -> str:
    """report.forced_backend (TP_GPU_FORCE_BACKEND letto da DetectContext.env al rilevamento, come TP_GPU_DETECT) ->
    quello; altrimenti il primo tra cuda, rocm, vulkan che almeno una GPU puo' usare; altrimenti 'cpu'."""
    rep = report if report is not None else detect_gpus()
    if rep.forced_backend in BACKENDS:
        return rep.forced_backend
    for b in ('cuda', 'rocm', 'vulkan'):
        if any(b in g.backends for g in rep.gpus):
            return b
    return 'cpu'


def usable_vram_mib(report: Optional[GpuReport] = None, backend: Optional[str] = None) -> Optional[int]:
    """VRAM totale (MiB) della GPU piu' grande tra quelle che possono usare `backend` (default: il consigliato).
    'cpu' -> None. Con una GPU NVIDIA funzionante = max memory.total di nvidia-smi (valore storico)."""
    rep = report if report is not None else detect_gpus()
    b = backend or recommended_backend(rep)
    if b == 'cpu':
        return None
    vals = [g.vram_mib for g in rep.gpus if g.vram_mib and b in g.backends]
    return max(vals) if vals else None


def describe(report: GpuReport) -> str:
    """Una riga per i log, es. 'GPU: NVIDIA GeForce RTX 3060 [nvidia, 12288 MiB, ...] | backend: cuda si ... -> cuda'."""
    parts = []
    for g in report.gpus:
        info = [g.vendor]
        if g.vram_mib:
            info.append(f'{g.vram_mib} MiB' + (f' (liberi {g.vram_free_mib})' if g.vram_free_mib is not None else ''))
        if g.integrated:
            info.append('integrata')
        if g.driver:
            info.append(f'driver {g.driver}')
        if g.compute_cap:
            info.append(f'cc {g.compute_cap}')
        if g.pci_id:
            info.append(g.pci_id)
        info.append(f'da {g.source}')
        parts.append(f'{g.name or "?"} [{", ".join(info)}]')
    head = ('GPU: ' + '; '.join(parts)) if parts else 'Nessuna GPU rilevata'
    bk = ', '.join(f'{b} {"si" if report.backends.get(b, {}).get("available") else "no"}'
                   for b in ('cuda', 'rocm', 'vulkan'))
    line = f'{head} | backend: {bk} -> consigliato {recommended_backend(report)}'
    if report.in_wsl:
        line += ' | WSL'
    if report.errors:
        line += ' | errori: ' + '; '.join(report.errors)
    return line


def _main(argv: List[str]) -> int:
    """CLI per gli installer (Python di sistema). Esce sempre con 0 e non scrive su stderr.
    --json      report completo + recommended_backend + usable_vram_mib
    --backend   solo il backend consigliato
    --vram      solo usable_vram_mib (riga vuota se nessuna)"""
    rep = detect_gpus(force=True)
    if '--json' in argv:
        d = rep.to_dict()
        d['recommended_backend'] = recommended_backend(rep)
        d['usable_vram_mib'] = usable_vram_mib(rep)
        d['max_vram_mib'] = max_vram_mib(rep)
        out = json.dumps(d, ensure_ascii=True, indent=2)
    elif '--backend' in argv:
        out = recommended_backend(rep)
    elif '--vram' in argv:
        v = usable_vram_mib(rep)
        out = '' if v is None else str(v)
    else:
        out = describe(rep)
    try:
        sys.stdout.write(_ascii(out) + '\n')
        sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
