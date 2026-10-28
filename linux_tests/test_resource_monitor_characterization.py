# -*- coding: utf-8 -*-
"""ResourceMonitor (gui/widgets.py): valori e testi mostrati, fissati PRIMA dell'estrazione in core/services/resource_sampler.py.
Si sostituiscono psutil, pynvml e l'orologio del modulo: lo stesso file passa identico sul codice vecchio e sul nuovo."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope='module')
def qt():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class FakePsutil:
    def __init__(self):
        self.cpu = 12.34
        self.ram = 56.78
        self.net = NS(bytes_sent=0, bytes_recv=0)
        self.fail_cpu = False

    def cpu_percent(self, interval=None):
        if self.fail_cpu:
            raise RuntimeError('cpu')
        return self.cpu

    def virtual_memory(self):
        return NS(percent=self.ram)

    def net_io_counters(self):
        return self.net


class FakeNvml:
    def __init__(self):
        self.util = 37
        self.used, self.total = 3 * 1024 ** 3, 12 * 1024 ** 3
        self.fail_mem = False

    def nvmlInit(self):
        pass

    def nvmlShutdown(self):
        pass

    def nvmlDeviceGetHandleByIndex(self, i):
        return 'H'

    def nvmlDeviceGetUtilizationRates(self, h):
        return NS(gpu=self.util)

    def nvmlDeviceGetMemoryInfo(self, h):
        if self.fail_mem:
            raise RuntimeError('mem')
        return NS(used=self.used, total=self.total)


@pytest.fixture
def mon(qt, monkeypatch):
    import gui.widgets as w
    ps, nv = FakePsutil(), FakeNvml()
    clock = [1000.0]
    monkeypatch.setattr(w, 'psutil', ps)
    monkeypatch.setattr(w, 'pynvml', nv, raising=False)
    monkeypatch.setattr(w, 'NVML_AVAILABLE', True)
    monkeypatch.setattr(w.time, 'time', lambda: clock[0])
    m = w.ResourceMonitor()
    m.ps, m.nv, m.clock = ps, nv, clock
    m.last_net_io = ps.net_io_counters()
    m.last_update_time = clock[0]
    yield m
    m.stop_monitoring()


def shown(m):
    return {'cpu': (m.cpu_bar.value(), m.cpu_value_label.text()), 'ram': (m.ram_bar.value(), m.ram_value_label.text()),
            'gpu': (m.gpu_bar.value(), m.gpu_value_label.text()), 'vram': (m.vram_bar.value(), m.vram_value_label.text()),
            'down': (m.download_label.text(), m.download_label.styleSheet()), 'up': (m.upload_label.text(), m.upload_label.styleSheet())}


def tick(m, seconds=1.0, sent=0, recv=0):
    m.clock[0] += seconds
    m.ps.net = NS(bytes_sent=m.ps.net.bytes_sent + sent, bytes_recv=m.ps.net.bytes_recv + recv)
    m.update_resources()
    return shown(m)


def test_valori_cpu_ram_gpu_vram(mon):
    s = tick(mon)
    assert s['cpu'] == (12, '12.3%') and s['ram'] == (56, '56.8%')
    assert s['gpu'] == (37, '37%') and s['vram'] == (25, '3.0GB')


def test_senza_gpu_non_ci_sono_barre_gpu_e_il_resto_funziona(qt, monkeypatch):
    import gui.widgets as w
    monkeypatch.setattr(w, 'psutil', FakePsutil())
    monkeypatch.setattr(w, 'NVML_AVAILABLE', False)
    m = w.ResourceMonitor()
    m.update_resources()
    assert m.gpu_initialized is False and not hasattr(m, 'gpu_bar') and not hasattr(m, 'vram_bar')
    assert (m.cpu_bar.value(), m.cpu_value_label.text()) == (12, '12.3%') and m.ram_value_label.text() == '56.8%'


def test_errore_nvml_sulla_memoria_lascia_la_gpu_aggiornata_e_la_vram_ferma(mon):
    mon.nv.fail_mem = True
    s = tick(mon)
    assert s['gpu'] == (37, '37%') and s['vram'] == (mon.vram_bar.value(), mon.vram_value_label.text())
    assert s['vram'][1] != '3.0GB'


def test_errore_della_cpu_salta_tutto_il_resto_compresa_la_rete(mon):
    mon.ps.fail_cpu = True
    before = shown(mon)
    s = tick(mon, 1.0, recv=10 * 1024 * 1024)
    assert s == before


@pytest.mark.parametrize('recv,sent,down,up', [
    (0, 0, '0.0 KB/s', '0.0 KB/s'),
    (50, 50, '0.0 KB/s', '0.0 KB/s'),                                     # <= 0.1 KB/s vale zero
    (1024, 2048, '1.0 KB/s', '2.0 KB/s'),
    (1024 * 1023, 1024 * 1024, '1023.0 KB/s', '1.00 MB/s'),               # da 1024 KB/s in su: MB/s, due decimali
    (5 * 1024 * 1024, 1024 * 1024 * 3 // 2, '5.00 MB/s', '1.50 MB/s'),
])
def test_velocita_di_rete_testo(mon, recv, sent, down, up):
    s = tick(mon, 1.0, sent=sent, recv=recv)
    assert s['down'][0] == down and s['up'][0] == up


def test_velocita_di_rete_colori(mon):
    from gui.design_tokens import T
    s = tick(mon, 1.0, sent=5 * 1024 * 1024, recv=5 * 1024 * 1024)
    assert T.success in s['down'][1] and T.warn in s['up'][1]
    s = tick(mon, 1.0)
    assert T.fg_4 in s['down'][1] and T.fg_4 in s['up'][1]


def test_la_velocita_divide_per_il_tempo_trascorso(mon):
    s = tick(mon, 2.0, recv=4096)
    assert s['down'][0] == '2.0 KB/s'


def test_primo_giro_senza_riferimento_non_scrive_la_rete(mon):
    mon.last_net_io = None
    mon.last_update_time = None
    s = tick(mon, 1.0, recv=10 * 1024 * 1024)
    assert s['down'][0] != '10.00 MB/s'
    s2 = tick(mon, 1.0, recv=1024 * 1024)            # dal giro dopo c'e' il riferimento
    assert s2['down'][0] == '1.00 MB/s'


def test_tempo_fermo_non_divide_per_zero(mon):
    before = shown(mon)
    s = tick(mon, 0.0, recv=1000)
    assert s['down'] == before['down']


def test_start_monitoring_prende_il_riferimento_e_avvia_il_timer(mon):
    mon.last_net_io = None
    mon.start_monitoring()
    assert mon.timer is not None and mon.timer.isActive() and mon.last_net_io is not None and mon.last_update_time == 1000.0
    t = mon.timer
    mon.start_monitoring()
    assert mon.timer is t
    mon.stop_monitoring()
    assert mon.timer is None


def test_dopo_un_giro_a_tempo_fermo_il_riferimento_e_aggiornato(mon):
    tick(mon, 0.0, recv=5000)                         # tempo fermo: niente velocita', ma il riferimento avanza
    s = tick(mon, 1.0, recv=1024)
    assert s['down'][0] == '1.0 KB/s'
