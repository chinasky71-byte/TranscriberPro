# -*- coding: utf-8 -*-
"""utils/gpu_detect.py: rilevamento GPU NVIDIA/AMD/Intel/Apple. Nessuna GPU, nessun sottoprocesso, nessun registro reale:
ogni fonte passa da un DetectContext finto (runner, which, sysfs in tmp_path, registro, NVML, clock)."""
import ast
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from utils import gpu_detect as gd  # noqa: E402

GiB = 1024 ** 3
MiB = 1024 ** 2


@pytest.fixture(autouse=True)
def _pulito(monkeypatch):
    gd.clear_cache()
    for k in ('TP_GPU_DETECT', 'TP_GPU_FORCE_BACKEND'):
        monkeypatch.delenv(k, raising=False)
    yield
    gd.clear_cache()


# ------------------------------------------------------------------------------------------------------- finti
class Runner:
    """Risposte per nome del programma: (rc, stdout), un'eccezione, o una lista consumata in ordine."""

    def __init__(self, table=None, clock=None, step=0.0):
        self.table = dict(table or {})
        self.calls = []
        self.clock, self.step = clock, step

    def __call__(self, cmd, timeout):
        assert timeout <= max(gd.SOURCE_TIMEOUT_S, gd.SMI_TIMEOUT_S) + 1e-9
        name = re.split(r'[\\/]', cmd[0])[-1]
        name = name[:-4] if name.endswith('.exe') else name
        self.calls.append((name, list(cmd), timeout))
        if self.clock is not None:
            self.clock.t += self.step
        if name not in self.table:
            raise FileNotFoundError(cmd[0])
        r = self.table[name]
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, BaseException):
            raise r
        return r

    def names(self):
        return [c[0] for c in self.calls]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeReg:
    """Registro HKLM finto: {percorso: {valore: dato}}; un dato eccezione = chiave illeggibile."""

    def __init__(self, keys):
        self.keys = {k.lower(): v for k, v in keys.items()}
        self.orig = list(keys)

    def values(self, path):
        v = self.keys.get(path.lower())
        if v is None:
            raise FileNotFoundError(path)
        if isinstance(v, BaseException):
            raise v
        return v

    def subkeys(self, path):
        pre = path.lower() + '\\'
        out = []
        for k in self.orig:
            if k.lower().startswith(pre):
                head = k[len(pre):].split('\\')[0]
                if head not in out:
                    out.append(head)
        if not out and path.lower() not in self.keys:
            raise FileNotFoundError(path)
        return out


class FakeNvml:
    def __init__(self, devs, init_rc=0):
        self.devs, self.init_rc, self.shut = devs, init_rc, False

    def nvmlInit_v2(self):
        return self.init_rc

    def nvmlShutdown(self):
        self.shut = True
        return 0

    def nvmlSystemGetDriverVersion(self, buf, n):
        buf.value = b'550.54.15'
        return 0

    def nvmlDeviceGetCount_v2(self, p):
        p._obj.value = len(self.devs)
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, i, p):
        p._obj.value = i + 1
        return 0

    def nvmlDeviceGetName(self, h, buf, n):
        buf.value = self.devs[h.value - 1]['name'].encode()
        return 0

    def nvmlDeviceGetMemoryInfo(self, h, p):
        d = self.devs[h.value - 1]
        p._obj.total, p._obj.free, p._obj.used = d['total'], d['free'], d['total'] - d['free']
        return 0

    def nvmlDeviceGetCudaComputeCapability(self, h, a, b):
        a._obj.value, b._obj.value = 8, 6
        return 0

    def nvmlDeviceGetPciInfo_v3(self, h, p):
        p._obj.pciDeviceId = 0x250410DE
        p._obj.busId = b'00000000:0%d:00.0' % h.value
        return 0


def ctx(platform='win32', tools=(), runner=None, registry=None, files=(), nvml=None, env=None, sysfs=None,
        dev=None, proc_version=None, access=True, libs=(), machine='x86_64', clock=None, which=None, cwd=None):
    """`tools` = programmi trovati da which (percorso assoluto finto fuori dalla cartella corrente)."""
    tools = set(tools)
    win = platform.startswith('win')
    if which is None:
        def which(n):
            if n not in tools:
                return None
            return f'C:\\fake\\{n}.exe' if win else f'/fake/{n}'
    return gd.DetectContext(
        platform=platform, machine=machine, env=dict(env or {}), runner=runner or Runner(),
        which=which, cwd=cwd or ('C:\\work' if win else '/work'),
        is_file=lambda p: p in set(files),
        exists=lambda p: Path(p).exists(),
        access_rw=lambda p: access,
        sysfs_root=str(sysfs) if sysfs else '/nonexistent_sys_tp',
        dev_root=str(dev) if dev else '/nonexistent_dev_tp',
        proc_version=str(proc_version) if proc_version else '/nonexistent_proc_tp',
        registry=registry, nvml_loader=lambda c: nvml,
        find_library=lambda n: ('libvulkan.so.1' if n in libs else None),
        clock=clock or Clock())


# nvidia-smi --query-gpu=memory.total,memory.free,driver_version,pci.bus_id,pci.device_id,compute_cap,name (name ULTIMO)
SMI_3060 = '12288, 11465, 617.42, 00000000:01:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n'
SMI_DUE = ('24564, 23000, 560.94, 00000000:01:00.0, 0x268410DE, 8.9, NVIDIA GeForce RTX 4090\n'
           '12288, 12000, 560.94, 00000000:02:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n')
SMI_NA = '[N/A], [N/A], 535.54.03, 00000000:07:00.0, 0x20B010DE, 8.0, NVIDIA A100-SXM4-40GB\n'
SMI_OLD_ERR = 'Field "compute_cap" is not a valid field to query.\n\n'
SMI_OLD_OK = '8192, 7900, 470.82, 00000000:01:00.0, 0x1B8010DE, GeForce GTX 1080\n'
SMI_WARN = 'WARNING: infoROM is corrupted at gpu 0000:01:00.0\n' + SMI_3060 + '\n'
SMI_DRIVER_KO = "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n"

VK_NV = """==========
VULKANINFO
==========
Devices:
========
GPU0:
\tapiVersion         = 1.4.351
\tvendorID           = 0x10de
\tdeviceID           = 0x2504
\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
\tdeviceName         = NVIDIA GeForce RTX 3060
\tdriverInfo         = 617.42
"""
VK_AMD_INTEL = """Devices:
========
GPU0:
\tvendorID           = 0x1002
\tdeviceID           = 0x747e
\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
\tdeviceName         = AMD Radeon RX 7800 XT
GPU1:
\tvendorID           = 0x8086
\tdeviceID           = 0x4680
\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
\tdeviceName         = Intel(R) UHD Graphics 770
"""
VK_LLVMPIPE = """Devices:
========
GPU0:
\tvendorID           = 0x10005
\tdeviceID           = 0x0000
\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU
\tdeviceName         = llvmpipe (LLVM 15.0.7, 256 bits)
"""

def vk_block(i, vid, did, typ, name):
    return (f'GPU{i}:\n\tvendorID = {vid}\n\tdeviceID = {did}\n\tdeviceType = PHYSICAL_DEVICE_TYPE_{typ}\n'
            f'\tdeviceName = {name}\n')


LSPCI = (
    '0000:00:02.0 "VGA compatible controller [0300]" "Intel Corporation [8086]" "Alder Lake-S GT1 [UHD Graphics 770] '
    '[4680]" -r0c -p00 "ASUSTeK Computer Inc. [1043]" "Device [8694]"\n'
    '0000:03:00.0 "VGA compatible controller [0300]" "Advanced Micro Devices, Inc. [AMD/ATI] [1002]" "Navi 31 '
    '[Radeon RX 7900 XT/7900 XTX/7900M] [744c]" -rc8 "Sapphire Technology Limited [1da2]" "Device [e471]"\n'
    '0000:03:00.1 "Audio device [0403]" "Advanced Micro Devices, Inc. [AMD/ATI] [1002]" "Navi 31 HDMI/DP Audio [ab30]" '
    '"Sapphire Technology Limited [1da2]" "Device [e471]"\n'
    '0000:00:01.0 "VGA compatible controller [0300]" "Microsoft Corporation [1414]" "Hyper-V virtual VGA [5353]"\n')

ROCMINFO = """*******
Agent 1
*******
  Name:                    AMD Ryzen 9 7950X
  Device Type:             CPU
*******
Agent 2
*******
  Name:                    gfx1100
  Marketing Name:          AMD Radeon RX 7900 XTX
  Device Type:             GPU
"""


def sysfs_dev(root, slot, cls, vendor, device, driver=None, files=None, cards=()):
    """Una periferica PCI finta: cartella con ':' sostituiti (NTFS), slot vero in uevent come nel sysfs reale."""
    d = root / 'bus' / 'pci' / 'devices' / slot.replace(':', '_')
    d.mkdir(parents=True)
    (d / 'class').write_text(cls + '\n')
    (d / 'vendor').write_text(vendor + '\n')
    (d / 'device').write_text(device + '\n')
    uev = f'PCI_SLOT_NAME={slot}\n' + (f'DRIVER={driver}\n' if driver else '')
    (d / 'uevent').write_text(uev)
    for k, v in (files or {}).items():
        p = d / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(v) + '\n')
    for c, cf in cards:
        cd = d / 'drm' / c
        cd.mkdir(parents=True)
        for k, v in cf.items():
            (cd / k).write_text(str(v) + '\n')
    return d


def rx7900(root):
    return sysfs_dev(root, '0000:03:00.0', '0x030000', '0x1002', '0x744c', 'amdgpu',
                     {'mem_info_vram_total': 24 * GiB, 'mem_info_vram_used': 1 * GiB})


def kfd(tmp_path):
    dev = tmp_path / 'dev'
    dev.mkdir(exist_ok=True)
    (dev / 'kfd').write_text('')
    return dev


VIDEO = r'System\CurrentControlSet\Control\Video'


def win_reg(adapters, devicemap=True):
    """adapters: [(guid, valori)]. Con devicemap=True piu' voci \\Device\\VideoN per adattatore (come nel reale)."""
    keys = {}
    dm = {}
    n = 0
    for guid, vals in adapters:
        for idx in ('0000', '0001'):
            keys[f'{VIDEO}\\{{{guid}}}\\{idx}'] = vals
            dm[f'\\Device\\Video{n}'] = f'\\Registry\\Machine\\{VIDEO}\\{{{guid}}}\\{idx}'
            n += 1
    dm[f'\\Device\\Video{n}'] = r'\REGISTRY\MACHINE\SYSTEM\ControlSet001\Services\BasicDisplay'
    dm['MaxObjectNumber'] = n
    if devicemap:
        keys[r'HARDWARE\DEVICEMAP\VIDEO'] = dm
    return FakeReg(keys)


AMD_16 = {'DriverDesc': 'AMD Radeon RX 7800 XT', 'MatchingDeviceId': 'pci\\ven_1002&dev_747e',
          'DriverVersion': '32.0.12011.1036', 'HardwareInformation.qwMemorySize': 16 * GiB,
          'HardwareInformation.MemorySize': 0xFFFFFFFF}
NV_REG = {'DriverDesc': 'NVIDIA GeForce RTX 3060', 'MatchingDeviceId': 'pci\\ven_10de&dev_2504',
          'DriverVersion': '32.0.16.1742', 'HardwareInformation.qwMemorySize': 12000 * MiB}
INTEL_REG = {'DriverDesc': 'Intel(R) UHD Graphics 770', 'MatchingDeviceId': 'PCI\\VEN_8086&DEV_4680',
             'DriverVersion': '31.0.101.4502',
             'HardwareInformation.qwMemorySize': (128 * MiB).to_bytes(8, 'little')}   # REG_BINARY


# --------------------------------------------------------------------------------------------- NVIDIA (nvidia-smi)
def test_nvidia_smi_singola_gpu():
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_3060)})))
    assert len(r.gpus) == 1
    g = r.gpus[0]
    assert (g.vendor, g.name, g.vram_mib, g.vram_free_mib, g.driver) == ('nvidia', 'NVIDIA GeForce RTX 3060', 12288,
                                                                         11465, '617.42')
    assert (g.pci_id, g.bus_id, g.compute_cap, g.integrated) == ('10de:2504', '0000:01:00.0', '8.6', False)
    assert g.backends == ['cuda'] and r.backends['cuda']['available'] and r.errors == []
    assert gd.recommended_backend(r) == 'cuda' and gd.usable_vram_mib(r) == 12288 == gd.max_vram_mib(r)


def test_nvidia_smi_due_gpu_ordinate_per_vram():
    rev = ''.join(reversed(SMI_DUE.splitlines(True)))            # 3060 per prima: l'ordine finale e' per VRAM
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, rev)})))
    assert [g.vram_mib for g in r.gpus] == [24564, 12288]
    assert gd.max_vram_mib(r) == 24564 == gd.usable_vram_mib(r)


def test_nvidia_smi_na_e_avvisi():
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_NA)})))
    assert len(r.gpus) == 1 and r.gpus[0].vram_mib is None and r.gpus[0].vram_free_mib is None
    assert r.gpus[0].pci_id == '10de:20b0' and gd.usable_vram_mib(r) is None
    r = gd.detect_gpus(force=True, ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_WARN)})))
    assert len(r.gpus) == 1 and r.gpus[0].vram_mib == 12288          # la riga di avviso si ignora


def test_nvidia_smi_vecchio_senza_compute_cap_riprova_una_volta():
    run = Runner({'nvidia-smi': [(2, SMI_OLD_ERR), (0, SMI_OLD_OK)]})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=run))
    assert run.names() == ['nvidia-smi', 'nvidia-smi']
    assert 'compute_cap' in run.calls[0][1][1] and 'compute_cap' not in run.calls[1][1][1]
    g = r.gpus[0]
    assert (g.name, g.vram_mib, g.compute_cap, g.pci_id) == ('GeForce GTX 1080', 8192, None, '10de:1b80')
    assert r.errors == []


def test_nvidia_smi_errore_e_timeout():
    run = Runner({'nvidia-smi': (9, SMI_DRIVER_KO)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=run))
    assert r.gpus == [] and gd.recommended_backend(r) == 'cpu' and gd.usable_vram_mib(r) is None
    assert any('nvidia-smi' in e and '9' in e for e in r.errors)
    assert run.names() == ['nvidia-smi']                 # driver guasto (nessun 'campo non valido'): niente 2o tentativo
    run = Runner({'nvidia-smi': subprocess.TimeoutExpired('nvidia-smi', 3)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=run))
    assert r.gpus == [] and run.names() == ['nvidia-smi']               # dopo un timeout non si riprova
    assert any('timeout' in e for e in r.errors) and run.calls[0][2] == gd.SMI_TIMEOUT_S


def test_nvidia_smi_nomi_con_virgole_non_scartano_la_riga():
    out = ('4096, 3900, 560.94, 00000000:02:00.0, 0x25B210DE, 8.6, NVIDIA RTX A400, Rev. B\n'
           '12288, 12000, 560.94, 00000000:01:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n')
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, out)})))
    assert [(g.name, g.vram_mib) for g in r.gpus] == [('NVIDIA GeForce RTX 3060', 12288), ('NVIDIA RTX A400, Rev. B', 4096)]


def test_nvidia_smi_na_prende_la_vram_dal_registro():
    na = '[N/A], [N/A], 560.94, 00000000:01:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n'
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, na)}),
                               registry=win_reg([('CCCC-3', NV_REG)])))
    g = r.gpus[0]
    assert (g.vram_mib, g.backends, g.source) == (12000, ['cuda'], 'nvidia-smi+registry')
    assert gd.usable_vram_mib(r, backend='cuda') == 12000


def test_which_solo_percorsi_assoluti_fuori_dalla_cartella_corrente():
    run = Runner({'nvidia-smi': (0, SMI_3060)})
    for found in ('nvidia-smi.exe', r'.\nvidia-smi.exe', r'C:\work\nvidia-smi.exe', r'c:/WORK/nvidia-smi.exe'):
        r = gd.detect_gpus(force=True, ctx=ctx(runner=run, which=lambda n, f=found: f if n == 'nvidia-smi' else None))
        assert r.gpus == [] and run.calls == [], found
    r = gd.detect_gpus(force=True, ctx=ctx(runner=run, which=lambda n: r'C:\Tools\nvidia-smi.exe' if n == 'nvidia-smi' else None))
    assert run.calls[-1][1][0] == r'C:\Tools\nvidia-smi.exe' and r.gpus
    # Windows: il percorso noto di System32 vince su quello del PATH
    sys32 = r'C:\Windows\System32\nvidia-smi.exe'
    gd.detect_gpus(force=True, ctx=ctx(runner=run, files={sys32}, which=lambda n: r'D:\Altro\nvidia-smi.exe' if n == 'nvidia-smi' else None))
    assert run.calls[-1][1][0] == sys32
    # Linux: relativo o nella cartella corrente -> scartato; poi i percorsi noti
    run = Runner({'nvidia-smi': (0, SMI_3060)})
    for found in ('nvidia-smi', './nvidia-smi', '/work/nvidia-smi'):
        r = gd.detect_gpus(force=True, ctx=ctx('linux', runner=run, which=lambda n, f=found: f))
        assert r.gpus == [] and run.calls == [], found
    gd.detect_gpus(force=True, ctx=ctx('linux', runner=run, which=lambda n: './nvidia-smi', files={'/usr/bin/nvidia-smi'}))
    assert run.calls[-1][1][0] == '/usr/bin/nvidia-smi'


def test_nvidia_smi_assente_non_e_un_errore_e_percorsi_noti_windows():
    r = gd.detect_gpus(ctx=ctx())
    assert r.gpus == [] and r.errors == [] and gd.recommended_backend(r) == 'cpu'
    smi = r'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe'
    run = Runner({'nvidia-smi': (0, SMI_3060)})
    r = gd.detect_gpus(force=True, ctx=ctx(files={smi}, env={'ProgramFiles': r'C:\Program Files'}, runner=run))
    assert run.calls[0][1][0] == smi and r.gpus[0].vram_mib == 12288


def test_runner_reale_senza_console_e_senza_stderr(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout='ok', stderr='rumore')
    monkeypatch.setattr(gd.subprocess, 'run', fake_run)
    assert gd._real_runner(['x'], 2.0) == (0, 'ok')                 # successo: stderr scartato
    assert seen['creationflags'] == gd.no_window_flags() and seen['timeout'] == 2.0
    assert seen['stdin'] is subprocess.DEVNULL and seen['stderr'] is subprocess.PIPE
    monkeypatch.setattr(gd.subprocess, 'run',
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, stdout='', stderr='Field x is not a valid field'))
    assert gd._real_runner(['x'], 2.0) == (2, 'Field x is not a valid field')   # errore: il messaggio serve


# ------------------------------------------------------------------------------------------------------------ NVML
def test_nvml_quando_nvidia_smi_manca():
    nv = FakeNvml([{'name': 'NVIDIA GeForce RTX 3060', 'total': 12 * GiB, 'free': 11 * GiB}])
    r = gd.detect_gpus(ctx=ctx(nvml=nv))
    g = r.gpus[0]
    assert (g.vram_mib, g.vram_free_mib, g.driver, g.compute_cap) == (12288, 11264, '550.54.15', '8.6')
    assert (g.pci_id, g.bus_id, g.source) == ('10de:2504', '0000:01:00.0', 'nvml') and nv.shut
    assert gd.recommended_backend(r) == 'cuda'


def test_nvml_non_usato_se_nvidia_smi_risponde_e_init_fallita():
    nv = FakeNvml([{'name': 'X', 'total': GiB, 'free': GiB}])
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_3060)}), nvml=nv))
    assert r.gpus[0].source == 'nvidia-smi' and not nv.shut
    r = gd.detect_gpus(force=True, ctx=ctx(nvml=FakeNvml([], init_rc=9)))
    assert r.gpus == [] and any('NVML' in e for e in r.errors)


def test_nvidia_smi_in_errore_con_nvml_presente():
    nv = FakeNvml([{'name': 'NVIDIA GeForce RTX 3060', 'total': 12 * GiB, 'free': 11 * GiB}])
    run = Runner({'nvidia-smi': (9, SMI_DRIVER_KO)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=run, nvml=nv))
    assert run.names() == ['nvidia-smi'] and r.gpus[0].source == 'nvml' and r.gpus[0].vram_mib == 12288
    assert gd.recommended_backend(r) == 'cuda' and any('nvidia-smi' in e for e in r.errors)


# ------------------------------------------------------------------------------------------------- Linux sysfs AMD
def test_linux_amd_rx7900_rocm(tmp_path):
    sys_ = tmp_path / 'sys'
    rx7900(sys_)
    run = Runner({'lspci': (0, LSPCI), 'rocminfo': (0, ROCMINFO)})
    r = gd.detect_gpus(ctx=ctx('linux', tools={'lspci', 'rocminfo'}, runner=run, sysfs=sys_, dev=kfd(tmp_path)))
    assert len(r.gpus) == 1                                    # l'Intel di lspci non si aggiunge: sysfs ha gia' risposto
    g = r.gpus[0]
    assert (g.vendor, g.vram_mib, g.vram_free_mib, g.driver) == ('amd', 24576, 23552, 'amdgpu')
    assert (g.pci_id, g.bus_id) == ('1002:744c', '0000:03:00.0')
    assert g.name == 'Radeon RX 7900 XT/7900 XTX/7900M' and 'lspci' in g.source
    assert r.backends['rocm'] == {'available': True, 'detail': 'rocminfo: gfx1100'}
    assert gd.recommended_backend(r) == 'rocm' and gd.usable_vram_mib(r) == 24576


def test_linux_amd_regole_rocm(tmp_path):
    sys_ = tmp_path / 'sys'
    rx7900(sys_)
    (sys_ / 'bus/pci/devices/0000_03_00.0/product_name').write_text('AMD Radeon RX 7900 XTX\n')
    # senza rocminfo: basta il KFD
    r = gd.detect_gpus(ctx=ctx('linux', sysfs=sys_, dev=kfd(tmp_path)))
    assert r.gpus[0].name == 'AMD Radeon RX 7900 XTX' and r.backends['rocm']['available']
    assert 'rocminfo assente' in r.backends['rocm']['detail']
    # KFD senza permessi
    r = gd.detect_gpus(force=True, ctx=ctx('linux', sysfs=sys_, dev=kfd(tmp_path), access=False))
    assert not r.backends['rocm']['available'] and 'render' in r.backends['rocm']['detail']
    # senza /dev/kfd: niente ROCm; libvulkan presente e vulkaninfo assente -> vulkan
    r = gd.detect_gpus(force=True, ctx=ctx('linux', sysfs=sys_, libs={'vulkan'}))
    assert not r.backends['rocm']['available'] and gd.recommended_backend(r) == 'vulkan'
    assert gd.usable_vram_mib(r) == 24576
    # niente kfd e niente loader Vulkan -> cpu
    r = gd.detect_gpus(force=True, ctx=ctx('linux', sysfs=sys_))
    assert gd.recommended_backend(r) == 'cpu' and gd.usable_vram_mib(r) is None
    # rocminfo che non elenca agenti gfx -> niente ROCm
    run = Runner({'rocminfo': (1, 'HSA_STATUS_ERROR_OUT_OF_RESOURCES')})
    r = gd.detect_gpus(force=True, ctx=ctx('linux', tools={'rocminfo'}, runner=run, sysfs=sys_, dev=kfd(tmp_path)))
    assert not r.backends['rocm']['available'] and any('rocminfo' in e for e in r.errors)


def test_linux_igpu_amd_e_discreta_ordine(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:c4:00.0', '0x030000', '0x1002', '0x15bf', 'amdgpu',
              {'mem_info_vram_total': 512 * MiB, 'mem_info_vram_used': 100 * MiB})
    rx7900(sys_)
    vk = ('Devices:\n========\nGPU0:\n\tvendorID = 0x1002\n\tdeviceID = 0x15bf\n'
          '\tdeviceType = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n\tdeviceName = AMD Radeon 780M (RADV PHOENIX)\n'
          'GPU1:\n\tvendorID = 0x1002\n\tdeviceID = 0x744c\n\tdeviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n'
          '\tdeviceName = AMD Radeon RX 7900 XTX (RADV NAVI31)\n')
    r = gd.detect_gpus(ctx=ctx('linux', tools={'vulkaninfo'}, runner=Runner({'vulkaninfo': (0, vk)}), sysfs=sys_))
    assert [g.pci_id for g in r.gpus] == ['1002:744c', '1002:15bf']
    assert [g.integrated for g in r.gpus] == [False, True]
    assert r.gpus[0].backends == ['vulkan'] and r.gpus[1].backends == []      # l'integrata non conta per Vulkan
    assert gd.usable_vram_mib(r) == 24576 and gd.max_vram_mib(r, vendor='amd') == 24576


def test_linux_solo_igpu_amd_senza_segnali_resta_none(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:c4:00.0', '0x030000', '0x1002', '0x15bf', 'amdgpu', {'mem_info_vram_total': 512 * MiB})
    r = gd.detect_gpus(ctx=ctx('linux', sysfs=sys_))
    assert r.gpus[0].integrated is None and r.gpus[0].vram_mib == 512          # nessuna soglia di VRAM


# ----------------------------------------------------------------------------------------------- Linux sysfs Intel
def test_linux_intel_arc_e_igpu(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:00:02.0', '0x030000', '0x8086', '0x4680', 'i915', cards=[('card0', {})])
    sysfs_dev(sys_, '0000:03:00.0', '0x030000', '0x8086', '0x56a0', 'i915',
              cards=[('card1', {'lmem_total_bytes': 16 * GiB})])
    run = Runner({'lspci': (0, LSPCI)})
    r = gd.detect_gpus(ctx=ctx('linux', tools={'lspci'}, runner=run, sysfs=sys_, libs={'vulkan'}))
    arc, igpu = r.gpus
    assert (arc.pci_id, arc.vram_mib, arc.integrated, arc.backends) == ('8086:56a0', 16384, False, ['vulkan'])
    assert (igpu.pci_id, igpu.vram_mib, igpu.integrated, igpu.backends) == ('8086:4680', None, True, [])
    assert igpu.name == 'UHD Graphics 770'                     # nome da lspci (abbinato per bus)
    assert arc.name == ''                                       # 03:00.0 di lspci e' un'AMD: PCI id diverso, niente nome
    assert gd.recommended_backend(r) == 'vulkan' and gd.usable_vram_mib(r) == 16384


def test_linux_nvidia_in_sysfs_si_fonde_con_nvidia_smi(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:01:00.0', '0x030000', '0x10de', '0x2504', 'nvidia')
    sysfs_dev(sys_, '0000:00:1f.3', '0x040300', '0x8086', '0x7ad0', 'snd_hda_intel')   # audio: non e' una GPU
    run = Runner({'nvidia-smi': (0, SMI_3060)})
    r = gd.detect_gpus(ctx=ctx('linux', tools={'nvidia-smi'}, runner=run, sysfs=sys_))
    assert len(r.gpus) == 1 and r.gpus[0].source == 'nvidia-smi+sysfs' and r.gpus[0].driver == '617.42'
    # driver NVIDIA guasto: la scheda si vede (sysfs) ma senza CUDA ne' VRAM
    r = gd.detect_gpus(force=True, ctx=ctx('linux', tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (9, '')}),
                                           sysfs=sys_))
    assert len(r.gpus) == 1 and r.gpus[0].backends == [] and gd.recommended_backend(r) == 'cpu'


def test_lspci_quando_sysfs_non_ha_nulla(tmp_path):
    r = gd.detect_gpus(ctx=ctx('linux', tools={'lspci'}, runner=Runner({'lspci': (0, LSPCI)})))
    assert [(g.vendor, g.bus_id) for g in r.gpus] == [('amd', '0000:03:00.0'), ('intel', '0000:00:02.0')]
    assert all(g.vram_mib is None for g in r.gpus)               # audio e Hyper-V esclusi


def test_rocm_smi_completa_la_vram_mancante(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:03:00.0', '0x030000', '0x1002', '0x744c', 'amdgpu')     # nessun mem_info_*
    js = json.dumps({'card0': {'PCI Bus': '0000:03:00.0', 'VRAM Total Memory (B)': str(24 * GiB),
                               'VRAM Total Used Memory (B)': str(2 * GiB)}})
    r = gd.detect_gpus(ctx=ctx('linux', tools={'rocm-smi'}, runner=Runner({'rocm-smi': (0, js)}), sysfs=sys_))
    assert (r.gpus[0].vram_mib, r.gpus[0].vram_free_mib) == (24576, 22528) and 'rocm-smi' in r.gpus[0].source


def test_rocm_smi_json_inatteso_o_guasto_resta_confinato(tmp_path, monkeypatch):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:03:00.0', '0x030000', '0x1002', '0x744c', 'amdgpu')
    for js in ('[1, 2]', '42', 'non json'):
        r = gd.detect_gpus(force=True, ctx=ctx('linux', tools={'rocm-smi'}, runner=Runner({'rocm-smi': (0, js)}),
                                               sysfs=sys_))
        assert len(r.gpus) == 1 and r.gpus[0].vram_mib is None and r.errors == []

    def boom(out):
        raise TypeError('rotto')
    monkeypatch.setattr(gd, '_parse_rocm_smi', boom)
    r = gd.detect_gpus(force=True, ctx=ctx('linux', tools={'rocm-smi'}, runner=Runner({'rocm-smi': (0, '{}')}),
                                           sysfs=sys_))
    assert len(r.gpus) == 1 and any(e.startswith('rocm-smi: TypeError') for e in r.errors)   # le altre fonti restano


# ------------------------------------------------------------------------------------------------ registro Windows
def test_registro_amd_16gb_e_intel_con_vulkaninfo():
    reg = win_reg([('AAAA-1', AMD_16), ('BBBB-2', INTEL_REG)])
    run = Runner({'vulkaninfo': (0, VK_AMD_INTEL)})
    r = gd.detect_gpus(ctx=ctx(tools={'vulkaninfo'}, runner=run, registry=reg))
    assert len(r.gpus) == 2                                      # 2 voci DEVICEMAP per GUID -> una GPU per GUID
    amd, intel = r.gpus
    assert (amd.vendor, amd.vram_mib, amd.driver, amd.pci_id) == ('amd', 16384, '32.0.12011.1036', '1002:747e')
    assert amd.integrated is False and amd.backends == ['vulkan'] and amd.source == 'registry+vulkaninfo'
    assert (intel.vram_mib, intel.integrated, intel.pci_id) == (128, True, '8086:4680')   # REG_BINARY letto
    assert gd.recommended_backend(r) == 'vulkan' and gd.usable_vram_mib(r) == 16384
    assert not r.backends['cuda']['available'] and not r.backends['rocm']['available']


def test_registro_amd_senza_vulkaninfo_loader_o_nulla():
    reg = win_reg([('AAAA-1', AMD_16)])
    dll = r'C:\Windows\System32\vulkan-1.dll'
    r = gd.detect_gpus(ctx=ctx(registry=reg, files={dll}, env={'SystemRoot': r'C:\Windows'}))
    assert gd.recommended_backend(r) == 'vulkan' and 'non verificati' in r.backends['vulkan']['detail']
    r = gd.detect_gpus(force=True, ctx=ctx(registry=reg))
    assert r.gpus[0].vram_mib == 16384 and gd.recommended_backend(r) == 'cpu' and gd.usable_vram_mib(r) is None


def test_registro_nvidia_si_fonde_con_nvidia_smi_che_vince_sulla_vram():
    reg = win_reg([('CCCC-3', NV_REG)])
    run = Runner({'nvidia-smi': (0, SMI_3060), 'vulkaninfo': (0, VK_NV)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi', 'vulkaninfo'}, runner=run, registry=reg))
    assert len(r.gpus) == 1
    g = r.gpus[0]
    assert g.vram_mib == 12288 and g.driver == '617.42' and g.source == 'nvidia-smi+registry+vulkaninfo'
    assert g.backends == ['cuda', 'vulkan'] and gd.usable_vram_mib(r) == 12288


def test_registro_nvidia_senza_driver_funzionante_non_da_vram():
    """Valore storico: driver NVIDIA guasto -> None, anche se il registro conosce la VRAM."""
    reg = win_reg([('CCCC-3', NV_REG)])
    dll = r'C:\Windows\System32\vulkan-1.dll'
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (9, SMI_DRIVER_KO)}),
                               registry=reg, files={dll}, env={'SystemRoot': r'C:\Windows'}))
    assert r.gpus[0].vram_mib == 12000 and r.gpus[0].backends == []
    assert gd.recommended_backend(r) == 'cpu' and gd.usable_vram_mib(r) is None


def test_registro_ripiego_chiave_class_e_chiavi_illeggibili():
    cls = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    reg = FakeReg({cls: {}, cls + r'\0000': INTEL_REG, cls + r'\0001': AMD_16,
                   cls + r'\Configuration': {}, cls + r'\Properties': PermissionError('accesso negato'),
                   cls + r'\0002': {'DriverDesc': 'Microsoft Basic Display Adapter'}})
    r = gd.detect_gpus(ctx=ctx(registry=reg))
    assert [(g.vendor, g.source) for g in r.gpus] == [('amd', 'registry-class'), ('intel', 'registry-class')]


def test_cim_solo_se_il_registro_non_da_nulla():
    out = ('AMD Radeon RX 7900 XTX|PCI\\VEN_1002&DEV_744C&SUBSYS_E4711DA2&REV_C8\\6&1|32.0.12011.1036\n'
           'Microsoft Remote Display Adapter|SWD\\REMOTEDISPLAYENUM\\1|10.0.1\n')
    run = Runner({'powershell': (0, out)})
    r = gd.detect_gpus(ctx=ctx(tools={'powershell'}, runner=run, registry=FakeReg({})))
    assert [(g.pci_id, g.vram_mib, g.source) for g in r.gpus] == [('1002:744c', None, 'cim')]
    run = Runner({'powershell': (0, out)})
    gd.detect_gpus(force=True, ctx=ctx(tools={'powershell'}, runner=run, registry=win_reg([('A', AMD_16)])))
    assert 'powershell' not in run.names()


# ---------------------------------------------------------------------------------------------------- Vulkan / WSL
def test_vulkaninfo_llvmpipe_non_conta(tmp_path):
    run = Runner({'vulkaninfo': (0, VK_LLVMPIPE)})
    r = gd.detect_gpus(ctx=ctx('linux', tools={'vulkaninfo'}, runner=run, libs={'vulkan'}))
    assert r.gpus == [] and not r.backends['vulkan']['available']
    assert '1 dispositivi software esclusi' in r.backends['vulkan']['detail']
    assert gd.recommended_backend(r) == 'cpu'


def test_vulkaninfo_unica_fonte_aggiunge_per_pci_id():
    radv_e_amdvlk = VK_AMD_INTEL + vk_block(2, '0x1002', '0x747e', 'DISCRETE_GPU', 'AMD Radeon RX 7800 XT (AMDVLK)')
    r = gd.detect_gpus(ctx=ctx(tools={'vulkaninfo'}, runner=Runner({'vulkaninfo': (0, radv_e_amdvlk + VK_LLVMPIPE)})))
    assert [(g.vendor, g.integrated) for g in r.gpus] == [('amd', False), ('intel', True)]
    assert gd.recommended_backend(r) == 'vulkan' and gd.usable_vram_mib(r) is None


def test_wsl_nvidia(tmp_path):
    pv = tmp_path / 'version'
    pv.write_text('Linux version 5.15.153.1-microsoft-standard-WSL2 (root@...)\n')
    run = Runner({'nvidia-smi': (0, SMI_3060), 'lspci': (0, LSPCI)})
    r = gd.detect_gpus(ctx=ctx('linux', tools={'lspci'}, files={'/usr/lib/wsl/lib/nvidia-smi'}, runner=run,
                               proc_version=pv))
    assert r.in_wsl and 'lspci' not in run.names() and run.calls[0][1][0] == '/usr/lib/wsl/lib/nvidia-smi'
    assert gd.recommended_backend(r) == 'cuda' and gd.usable_vram_mib(r) == 12288


def test_wsl_amd_niente_errori(tmp_path):
    dev = tmp_path / 'dev'
    dev.mkdir()
    (dev / 'dxg').write_text('')
    r = gd.detect_gpus(ctx=ctx('linux', dev=dev))
    assert r.in_wsl and r.gpus == [] and r.errors == [] and gd.recommended_backend(r) == 'cpu'


def test_macos():
    r = gd.detect_gpus(ctx=ctx('darwin', machine='arm64'))
    assert [(g.vendor, g.vram_mib, g.integrated) for g in r.gpus] == [('apple', None, True)]
    assert gd.recommended_backend(r) == 'cpu' and gd.usable_vram_mib(r) is None
    assert gd.detect_gpus(force=True, ctx=ctx('darwin', machine='x86_64')).gpus == []


# --------------------------------------------------------------------------------- dedup, ordine, robustezza, cache
def test_due_schede_identiche_restano_due():
    smi = ('12288, 11000, 560.94, 00000000:01:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n'
           '12288, 12000, 560.94, 00000000:02:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n')
    reg = win_reg([('A', NV_REG), ('B', NV_REG)])
    vk = VK_NV + vk_block(1, '0x10de', '0x2504', 'DISCRETE_GPU', 'NVIDIA GeForce RTX 3060')
    run = Runner({'nvidia-smi': (0, smi), 'vulkaninfo': (0, vk)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi', 'vulkaninfo'}, runner=run, registry=reg))
    assert len(r.gpus) == 2 and all(g.source == 'nvidia-smi+registry+vulkaninfo' for g in r.gpus)
    assert [g.bus_id for g in r.gpus] == ['0000:01:00.0', '0000:02:00.0']


def test_portatile_ibrido_discreta_prima():
    reg = win_reg([('I', INTEL_REG), ('N', NV_REG)])
    vk = VK_NV + vk_block(1, '0x8086', '0x4680', 'INTEGRATED_GPU', 'Intel(R) UHD Graphics 770')
    run = Runner({'nvidia-smi': (0, SMI_3060), 'vulkaninfo': (0, vk)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi', 'vulkaninfo'}, runner=run, registry=reg))
    assert [g.vendor for g in r.gpus] == ['nvidia', 'intel'] and r.gpus[1].integrated is True
    assert gd.max_vram_mib(r, vendor='intel') == 128 and gd.usable_vram_mib(r) == 12288


def test_nessuna_eccezione_verso_il_chiamante():
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi', 'vulkaninfo'}, runner=Runner({'nvidia-smi': RuntimeError('boom'),
                                                                                 'vulkaninfo': OSError('x')}),
                               registry=FakeReg({r'HARDWARE\DEVICEMAP\VIDEO': RuntimeError('reg')})))
    assert r.gpus == [] and any('boom' in e for e in r.errors)
    assert gd.recommended_backend(r) == 'cpu' and isinstance(gd.describe(r), str)
    bad = ctx()
    bad.clock = None                                             # guasto imprevisto dentro detect
    r = gd.detect_gpus(force=True, ctx=bad)
    assert r.gpus == [] and r.errors and 'gpu_detect' in r.errors[0]


def test_budget_totale_e_timeout_per_fonte():
    assert gd.DEADLINE_S <= 9.0 and gd.SMI_TIMEOUT_S <= 6.0 and gd.SOURCE_TIMEOUT_S <= 3.0
    clk = Clock()
    run = Runner({'nvidia-smi': (9, ''), 'powershell': (0, ''), 'vulkaninfo': (0, VK_NV)}, clock=clk, step=6.0)
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi', 'powershell', 'vulkaninfo'}, runner=run, clock=clk))
    assert [(n, t) for n, _c, t in run.calls] == [('nvidia-smi', gd.SMI_TIMEOUT_S), ('powershell', gd.SOURCE_TIMEOUT_S)]
    assert any('vulkaninfo' in e and 'saltato' in e for e in r.errors)      # budget finito: fonte saltata


def test_tp_gpu_detect_off():
    run = Runner({'nvidia-smi': (0, SMI_3060)})
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=run, env={'TP_GPU_DETECT': 'off'}))
    assert r.gpus == [] and run.calls == [] and gd.recommended_backend(r) == 'cpu'
    assert r.backends['cuda']['detail'] == 'TP_GPU_DETECT=off'


def test_cache_solo_report_con_gpu(monkeypatch):
    clk = Clock()
    run = Runner({'nvidia-smi': (0, SMI_3060)})
    c = ctx(tools={'nvidia-smi'}, runner=run, clock=clk)
    a = gd.detect_gpus(ctx=c)
    b = gd.detect_gpus(ctx=c)
    assert len(run.calls) == 1 and a == b and a is not b         # copia: chi la modifica non sporca la cache
    clk.t += gd.CACHE_TTL_S + 1
    gd.detect_gpus(ctx=c)
    assert len(run.calls) == 2                                   # scaduta
    gd.detect_gpus(ctx=c, force=True)
    assert len(run.calls) == 3
    gd.clear_cache()
    run = Runner({'nvidia-smi': (9, '')})
    c = ctx(tools={'nvidia-smi'}, runner=run)
    gd.detect_gpus(ctx=c)
    gd.detect_gpus(ctx=c)
    assert len(run.calls) == 2                                   # vuoto: non in cache


def test_cache_mai_con_errori_o_nvidia_senza_cuda():
    # GPU trovata ma vulkaninfo in timeout -> errore -> non in cache
    run = Runner({'nvidia-smi': (0, SMI_3060), 'vulkaninfo': subprocess.TimeoutExpired('vulkaninfo', 3)})
    c = ctx(tools={'nvidia-smi', 'vulkaninfo'}, runner=run)
    assert gd.detect_gpus(ctx=c).errors
    gd.detect_gpus(ctx=c)
    assert run.names().count('nvidia-smi') == 2
    # NVIDIA vista solo dal registro (nvidia-smi assente, nessun errore): niente CUDA fissato per 60 s
    run = Runner({'vulkaninfo': (0, VK_NV)})
    c = ctx(tools={'vulkaninfo'}, runner=run, registry=win_reg([('CCCC-3', NV_REG)]))
    r = gd.detect_gpus(ctx=c)
    assert r.errors == [] and r.gpus[0].backends == ['vulkan']
    gd.detect_gpus(ctx=c)
    assert run.names() == ['vulkaninfo', 'vulkaninfo']
    # nvidia-smi in timeout + registro: la chiamata dopo riprova e trova CUDA
    run = Runner({'nvidia-smi': [subprocess.TimeoutExpired('nvidia-smi', 6), (0, SMI_3060)]})
    c = ctx(tools={'nvidia-smi'}, runner=run, registry=win_reg([('CCCC-3', NV_REG)]))
    assert gd.recommended_backend(gd.detect_gpus(ctx=c)) == 'cpu'
    assert gd.recommended_backend(gd.detect_gpus(ctx=c)) == 'cuda'


def test_due_chiamanti_in_parallelo_una_sola_rilevazione():
    class Lento(Runner):
        def __call__(self, cmd, timeout):
            time.sleep(0.2)
            return super().__call__(cmd, timeout)
    run = Lento({'nvidia-smi': (0, SMI_3060)})
    c = ctx(tools={'nvidia-smi'}, runner=run)
    out = []
    ths = [threading.Thread(target=lambda: out.append(gd.detect_gpus(ctx=c))) for _ in range(2)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(5)
    assert len(run.calls) == 1 and len(out) == 2 and all(r.gpus[0].vram_mib == 12288 for r in out)


def test_recommended_backend_override():
    def rep(env):
        return gd.detect_gpus(force=True, ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_3060)}),
                                                  env=env))
    for b in ('cuda', 'rocm', 'vulkan', 'cpu'):
        assert gd.recommended_backend(rep({'TP_GPU_FORCE_BACKEND': b.upper()})) == b
    assert gd.usable_vram_mib(rep({'TP_GPU_FORCE_BACKEND': 'cpu'})) is None
    assert gd.usable_vram_mib(rep({'TP_GPU_FORCE_BACKEND': 'rocm'})) is None      # nessuna GPU ROCm
    assert gd.recommended_backend(rep({'TP_GPU_FORCE_BACKEND': 'boh'})) == 'cuda'  # valore non valido: ignorato
    # dalla cache: l'override e' quello di chi chiama adesso
    c = ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_3060)}))
    gd.detect_gpus(ctx=c)
    c.env = {'TP_GPU_FORCE_BACKEND': 'vulkan'}
    assert gd.recommended_backend(gd.detect_gpus(ctx=c)) == 'vulkan'


def test_parsing_tollerante():
    assert gd._num(' 12 288 ') == 12288 and gd._num('8,6') == 8.6 and gd._num('12288 MiB') == 12288
    assert gd._num('[N/A]') is None and gd._num('[Not Supported]') is None and gd._num('') is None
    assert gd._norm_bus('00000000:0A:00.0') == '0000:0a:00.0' and gd._norm_bus('01:00.0') == '0000:01:00.0'
    assert gd._mib_from_bytes(b'\x00\x00\x00\x80\x03\x00\x00\x00') == 14336 and gd._mib_from_bytes(0) is None
    assert gd._reg_str('AMD\x00'.encode('utf-16-le')) == 'AMD'


def test_describe_e_cli(monkeypatch, capsys):
    r = gd.detect_gpus(ctx=ctx(tools={'nvidia-smi'}, runner=Runner({'nvidia-smi': (0, SMI_3060)})))
    s = gd.describe(r)
    assert 'NVIDIA GeForce RTX 3060' in s and '12288 MiB' in s and 'consigliato cuda' in s
    assert gd.describe(gd.GpuReport()).startswith('Nessuna GPU rilevata')
    r.gpus[0].name = 'Radeon\u2122 RX'
    monkeypatch.setattr(gd, 'detect_gpus', lambda force=False, ctx=None: r)
    assert gd._main(['--json']) == 0
    out = capsys.readouterr()
    d = json.loads(out.out)
    assert out.err == '' and out.out.isascii()
    assert d['recommended_backend'] == 'cuda' and d['usable_vram_mib'] == 12288 and d['gpus'][0]['pci_id']
    gd._main(['--vram'])
    gd._main(['--backend'])
    assert capsys.readouterr().out.split() == ['12288', 'cuda']


def test_modulo_solo_libreria_standard():
    """Ogni import del modulo (anche dentro try/funzioni) e' libreria standard, oppure platform_compat (relativo o, da
    script, come modulo vicino: anch'esso solo libreria standard)."""
    tree = ast.parse((ROOT / 'utils' / 'gpu_detect.py').read_text(encoding='utf-8'))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            assert node.module == 'platform_compat'
    extra = names - set(sys.stdlib_module_names) - {'__future__', 'platform_compat'}
    assert not extra, extra
    assert {'ctypes', 'subprocess', 'winreg'} <= names            # il controllo vede davvero gli import
    pc = ast.parse((ROOT / 'utils' / 'platform_compat.py').read_text(encoding='utf-8'))
    top = {a.name.split('.')[0] for n in pc.body if isinstance(n, ast.Import) for a in n.names}
    top |= {n.module.split('.')[0] for n in pc.body if isinstance(n, ast.ImportFrom) and n.level == 0}
    assert top <= set(sys.stdlib_module_names) | {'__future__'}, top
