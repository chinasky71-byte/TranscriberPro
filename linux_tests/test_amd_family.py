# -*- coding: utf-8 -*-
"""Famiglie AMD (RDNA1..4, CDNA, GCN) in utils/gpu_detect.py e scelta del percorso (ROCm / override RDNA2 / Vulkan+CPU).
Nessuna GPU: rocminfo, sysfs (PCI e KFD) e lspci sono finti."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gpu_detect import GiB, Runner, ctx, kfd, sysfs_dev  # noqa: E402

from utils import gpu_detect as gd  # noqa: E402

OVR = 'HSA_OVERRIDE_GFX_VERSION'


@pytest.fixture(autouse=True)
def _pulito(monkeypatch):
    gd.clear_cache()
    for k in ('TP_GPU_DETECT', 'TP_GPU_FORCE_BACKEND', OVR):
        monkeypatch.delenv(k, raising=False)
    yield
    gd.clear_cache()


def rocminfo(gfx):
    return ('*******\nAgent 1\n*******\n  Name:                    AMD Ryzen 9 5950X\n  Device Type:             CPU\n'
            f'*******\nAgent 2\n*******\n  Name:                    {gfx}\n  Device Type:             GPU\n')


def lspci(name, dev='73bf'):
    return ('0000:03:00.0 "VGA compatible controller [0300]" "Advanced Micro Devices, Inc. [AMD/ATI] [1002]" '
            f'"{name} [{dev}]" -rc1 "Sapphire [1da2]" "Device [e471]"\n')


def card(tmp_path, dev='0x73bf', driver='amdgpu'):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:03:00.0', '0x030000', '0x1002', dev, driver,
              {'mem_info_vram_total': 16 * GiB, 'mem_info_vram_used': 1 * GiB})
    return sys_


def kfd_node(sys_, idx, version, vendor=4098, device=0x73bf):
    d = sys_ / 'class' / 'kfd' / 'kfd' / 'topology' / 'nodes' / str(idx)
    d.mkdir(parents=True)
    (d / 'properties').write_text(f'cpu_cores_count 0\nvendor_id {vendor}\ndevice_id {device}\n'
                                  f'gfx_target_version {version}\ndrm_render_minor 128\n')


def detect(tmp_path, gfx=None, sys_=None, name=None, with_kfd=True, libs=('vulkan',), env=None):
    sys_ = sys_ or card(tmp_path)
    table, tools = {}, set()
    if gfx:
        table['rocminfo'], tools = (0, rocminfo(gfx)), {'rocminfo'}
    if name:
        table['lspci'] = (0, lspci(name))
        tools.add('lspci')
    return gd.detect_gpus(force=True, ctx=ctx('linux', tools=tools, runner=Runner(table), sysfs=sys_,
                                              dev=kfd(tmp_path) if with_kfd else None, libs=libs, env=env))


# ---------------------------------------------------------------------------------------------------- classificazione
@pytest.mark.parametrize('gfx,fam,sup', [
    ('gfx1201', 'RDNA4', 'official'), ('gfx1200', 'RDNA4', 'official'), ('gfx1100', 'RDNA3', 'official'),
    ('gfx1102', 'RDNA3', 'official'), ('gfx1103', 'RDNA3', 'unofficial'), ('gfx1151', 'RDNA3', 'official'),
    ('gfx1030', 'RDNA2', 'unofficial'), ('gfx1031', 'RDNA2', 'unofficial'), ('gfx1034', 'RDNA2', 'unofficial'),
    ('gfx1010', 'RDNA1', 'unsupported'), ('gfx1012', 'RDNA1', 'unsupported'),
    ('gfx908', 'CDNA', 'official'), ('gfx90a', 'CDNA', 'official'), ('gfx942', 'CDNA', 'official'), ('gfx950', 'CDNA', 'official'),
    ('gfx900', 'GCN', 'unsupported'), ('gfx906', 'GCN', 'unsupported'), ('gfx90c', 'GCN', 'unsupported'), ('gfx803', 'GCN', 'unsupported'),
    ('gfx1300', 'unknown', 'unknown'), (None, 'unknown', 'unknown'), ('', 'unknown', 'unknown'), ('boh', 'unknown', 'unknown'),
])
def test_classify_gfx(gfx, fam, sup):
    assert gd.classify_gfx(gfx) == (fam, sup)


@pytest.mark.parametrize('ver,gfx', [(100300, 'gfx1030'), (100301, 'gfx1031'), (110000, 'gfx1100'), (120001, 'gfx1201'),
                                     (90010, 'gfx90a'), (90012, 'gfx90c'), (90000, 'gfx900'), (90008, 'gfx908'),
                                     (90402, 'gfx942'), (100100, 'gfx1010'), ('100300', 'gfx1030'),
                                     (0, None), (None, None), ('x', None), (-5, None), (999999, None)])
def test_gfx_da_versione_kfd(ver, gfx):
    assert gd._gfx_from_kfd_version(ver) == gfx


@pytest.mark.parametrize('name,gfx', [
    ('Navi 21 [Radeon RX 6800/6800 XT / 6900 XT]', 'gfx1030'), ('Navi 22 [Radeon RX 6700/6700 XT/6750 XT]', 'gfx1031'),
    ('Navi 23 [Radeon RX 6600/6600 XT/6600M]', 'gfx1032'), ('Navi 24 [Radeon RX 6500 XT/6500M]', 'gfx1034'),
    ('Navi 10 [Radeon RX 5600 OEM/5600 XT / 5700/5700 XT]', 'gfx1010'), ('Navi 31 [Radeon RX 7900 XT/7900 XTX]', 'gfx1100'),
    ('Navi 48 [Radeon RX 9070/9070 XT]', 'gfx1201'), ('Vega 20 [Radeon VII]', 'gfx906'),
    ('Aldebaran/MI200 [Instinct MI250X]', 'gfx90a'), ('Radeon RX 7600', 'gfx1102'), ('Qualcosa di strano', None), ('', None), (None, None)])
def test_gfx_dal_nome(name, gfx):
    assert gd._gfx_from_name(name) == gfx


# ------------------------------------------------------------------------------------------- una scheda per famiglia
CASES = [   # gfx rocminfo, famiglia, supporto, percorso, override, 'rocm' tra i backend
    ('gfx1201', 'RDNA4', 'official', 'rocm', None, True),
    ('gfx1100', 'RDNA3', 'official', 'rocm', None, True),
    ('gfx1030', 'RDNA2', 'unofficial', 'rocm_override', '10.3.0', True),
    ('gfx1031', 'RDNA2', 'unofficial', 'rocm_override', '10.3.0', True),
    ('gfx1032', 'RDNA2', 'unofficial', 'rocm_override', '10.3.0', True),
    ('gfx1010', 'RDNA1', 'unsupported', 'vulkan_cpu', None, False),
    ('gfx90a', 'CDNA', 'official', 'rocm', None, True),
    ('gfx942', 'CDNA', 'official', 'rocm', None, True),
    ('gfx900', 'GCN', 'unsupported', 'vulkan_cpu', None, False),
]


@pytest.mark.parametrize('gfx,fam,sup,path,ovr,rocm', CASES)
def test_famiglia_da_rocminfo(tmp_path, gfx, fam, sup, path, ovr, rocm):
    r = detect(tmp_path, gfx=gfx)
    g = r.gpus[0]
    assert (g.gfx, g.gfx_source, g.amd_family, g.rocm_support) == (gfx, 'rocminfo', fam, sup)
    assert ('rocm' in g.backends) is rocm
    p = gd.amd_runtime_plan(r, env={})
    assert (p['path'], p['hsa_override_gfx_version'], p['amd_family'], p['rocm_support']) == (path, ovr, fam, sup)
    assert p['message']
    assert (gd.recommended_backend(r) == 'rocm') is rocm
    if not rocm:                                               # ripiego: Vulkan se c'e' il loader, la CPU per il resto
        assert gd.recommended_backend(r) == 'vulkan'
        assert 'Vulkan' in p['message'] and 'CPU' in p['message']
        altra = tmp_path / 'senza_vulkan'
        altra.mkdir()
        assert gd.recommended_backend(detect(altra, gfx=gfx, libs=())) == 'cpu'
    if ovr:
        assert gd.RDNA2_OVERRIDE_SOURCE in p['override_source'] and 'bf16' in p['message']


def test_rdna1_rocm_non_disponibile_nel_report(tmp_path):
    r = detect(tmp_path, gfx='gfx1010')
    assert r.backends['rocm']['available'] is False and 'RDNA1' in r.backends['rocm']['detail']
    assert gd.usable_vram_mib(r) == 16384                      # VRAM contata dal backend vulkan


# ---------------------------------------------------------------------------------------- fonti alternative a rocminfo
@pytest.mark.parametrize('ver,gfx,fam', [(100300, 'gfx1030', 'RDNA2'), (110000, 'gfx1100', 'RDNA3'), (120001, 'gfx1201', 'RDNA4'),
                                         (100100, 'gfx1010', 'RDNA1'), (90010, 'gfx90a', 'CDNA')])
def test_famiglia_da_sysfs_kfd_senza_rocminfo(tmp_path, ver, gfx, fam):
    sys_ = card(tmp_path)
    kfd_node(sys_, 0, 0, vendor=4098, device=0)                # nodo CPU: gfx_target_version 0, ignorato
    kfd_node(sys_, 1, ver)
    r = detect(tmp_path, sys_=sys_)
    g = r.gpus[0]
    assert (g.gfx, g.gfx_source, g.amd_family) == (gfx, 'kfd', fam)
    assert 'rocminfo assente' in r.backends['rocm']['detail'] or fam in ('RDNA1',)


def test_kfd_abbina_per_pci_id_con_due_schede(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:03:00.0', '0x030000', '0x1002', '0x744c', 'amdgpu', {'mem_info_vram_total': 24 * GiB})
    sysfs_dev(sys_, '0000:08:00.0', '0x030000', '0x1002', '0x73bf', 'amdgpu', {'mem_info_vram_total': 16 * GiB})
    kfd_node(sys_, 0, 100300, device=0x73bf)                   # elencato prima, ma e' la scheda 08:00.0
    kfd_node(sys_, 1, 110000, device=0x744c)
    r = detect(tmp_path, sys_=sys_)
    by = {g.pci_id: g.gfx for g in r.gpus}
    assert by == {'1002:744c': 'gfx1100', '1002:73bf': 'gfx1030'}


@pytest.mark.parametrize('name,fam', [('Navi 21 [Radeon RX 6800/6800 XT / 6900 XT]', 'RDNA2'), ('Navi 23 [Radeon RX 6600/6600 XT]', 'RDNA2'),
                                      ('Navi 10 [Radeon RX 5700 XT]', 'RDNA1'), ('Navi 31 [Radeon RX 7900 XTX]', 'RDNA3'),
                                      ('Navi 48 [Radeon RX 9070 XT]', 'RDNA4'), ('Vega 10 [Radeon RX Vega 64]', 'GCN')])
def test_famiglia_dal_nome_lspci_senza_rocminfo_ne_kfd(tmp_path, name, fam):
    r = detect(tmp_path, name=name, with_kfd=False)
    g = r.gpus[0]
    assert (g.gfx_source, g.amd_family) == ('name', fam) and g.gfx
    assert 'rocm' not in g.backends                            # senza /dev/kfd ROCm non parte
    p = gd.amd_runtime_plan(r, env={})
    assert p['path'] == 'vulkan_cpu' and 'ROCm non parte' in p['message'] + ('ROCm non parte' if fam in ('RDNA1', 'GCN') else '')


def test_rocminfo_ha_la_precedenza_su_kfd_e_nome(tmp_path):
    sys_ = card(tmp_path)
    kfd_node(sys_, 1, 100100)
    r = detect(tmp_path, gfx='gfx1100', sys_=sys_, name='Navi 10 [Radeon RX 5700]')
    assert (r.gpus[0].gfx, r.gpus[0].gfx_source) == ('gfx1100', 'rocminfo')


# ------------------------------------------------------------------------------------- nessuna scheda / dati parziali
def test_nessuna_scheda_amd(tmp_path):
    r = gd.detect_gpus(force=True, ctx=ctx('linux', sysfs=tmp_path / 'sys', dev=tmp_path / 'dev'))
    assert r.gpus == [] and r.errors == []
    p = gd.amd_runtime_plan(r, env={})
    assert p['path'] is None and p['gfx'] is None and p['amd_family'] is None and p['message']
    assert gd.subprocess_env_overrides(r, {}) == {}


def test_scheda_senza_nessun_dato_gfx(tmp_path):
    r = detect(tmp_path)                                       # sysfs senza nome, KFD presente, niente rocminfo/lspci
    g = r.gpus[0]
    assert (g.gfx, g.amd_family, g.rocm_support) == (None, 'unknown', 'unknown')
    assert r.errors == []
    p = gd.amd_runtime_plan(r, env={})
    assert p['path'] == 'rocm' and p['hsa_override_gfx_version'] is None      # famiglia ignota: nessun override inventato


@pytest.mark.parametrize('props', ['', 'gfx_target_version\n', 'gfx_target_version abc\n', 'gfx_target_version 99999999999\n',
                                   '\x00\x01 garbage\n'])
def test_kfd_con_dati_corrotti_non_solleva(tmp_path, props):
    sys_ = card(tmp_path)
    d = sys_ / 'class' / 'kfd' / 'kfd' / 'topology' / 'nodes' / '0'
    d.mkdir(parents=True)
    (d / 'properties').write_text(props)
    r = detect(tmp_path, sys_=sys_)
    assert r.gpus[0].gfx is None and r.errors == []


def test_rocminfo_con_due_gpu_in_ordine(tmp_path):
    sys_ = tmp_path / 'sys'
    sysfs_dev(sys_, '0000:03:00.0', '0x030000', '0x1002', '0x744c', 'amdgpu', {'mem_info_vram_total': 24 * GiB})
    sysfs_dev(sys_, '0000:08:00.0', '0x030000', '0x1002', '0x73bf', 'amdgpu', {'mem_info_vram_total': 16 * GiB})
    out = rocminfo('gfx1100') + '  Name:                    gfx1030\n'
    r = gd.detect_gpus(force=True, ctx=ctx('linux', tools={'rocminfo'}, runner=Runner({'rocminfo': (0, out)}), sysfs=sys_, dev=kfd(tmp_path)))
    assert sorted(g.gfx for g in r.gpus) == ['gfx1030', 'gfx1100']


def test_nvidia_e_altri_fornitori_senza_campi_amd(tmp_path):
    r = gd.detect_gpus(force=True, ctx=ctx('linux', sysfs=tmp_path / 'sys', dev=tmp_path / 'dev'))
    d = r.to_dict()
    assert d['gpus'] == []
    g = gd.GpuInfo(vendor='nvidia', name='RTX')
    assert (g.gfx, g.amd_family, g.rocm_support) == (None, None, None)


# --------------------------------------------------------------------- regola: mai sovrascrivere HSA_OVERRIDE_GFX_VERSION
def test_override_gia_impostato_dall_utente_non_si_tocca(tmp_path):
    r = detect(tmp_path, gfx='gfx1031')
    for user in ('10.3.0', '10.3.2', '9.0.0'):
        p = gd.amd_runtime_plan(r, env={OVR: user})
        assert p['path'] == 'rocm' and p['hsa_override_gfx_version'] is None and p['user_override'] == user
        assert user in p['message']
        assert gd.subprocess_env_overrides(r, {OVR: user}) == {}
    child = {OVR: '10.3.2', 'PATH': '/bin'}
    gd.apply_subprocess_env(child)
    assert child[OVR] == '10.3.2'


def test_override_applicato_solo_ai_sottoprocessi(tmp_path, monkeypatch):
    r = detect(tmp_path, gfx='gfx1032')
    monkeypatch.setattr(gd, 'detect_gpus', lambda *a, **k: r)
    monkeypatch.delenv(OVR, raising=False)
    assert gd.subprocess_env_overrides(r, {}) == {OVR: '10.3.0'}
    child = {'PATH': '/bin'}
    gd.apply_subprocess_env(child)
    assert child[OVR] == '10.3.0'
    assert OVR not in os.environ                               # il processo corrente non viene mai toccato
    vuota = {OVR: ''}                                          # variabile vuota = non impostata dall'utente
    gd.apply_subprocess_env(vuota)
    assert vuota[OVR] == '10.3.0'


@pytest.mark.parametrize('gfx', ['gfx1100', 'gfx1201', 'gfx90a', 'gfx1010', 'gfx900'])
def test_nessun_override_per_altre_famiglie(tmp_path, monkeypatch, gfx):
    r = detect(tmp_path, gfx=gfx)
    monkeypatch.setattr(gd, 'detect_gpus', lambda *a, **k: r)
    child = {}
    gd.apply_subprocess_env(child)
    assert child == {} and gd.subprocess_env_overrides(r, {}) == {}


def test_override_con_rocm_che_non_parte(tmp_path):
    r = detect(tmp_path, gfx='gfx1030', with_kfd=False)        # RDNA2 ma niente /dev/kfd
    p = gd.amd_runtime_plan(r, env={})
    assert p['path'] == 'vulkan_cpu' and p['hsa_override_gfx_version'] is None and '/dev/kfd' in p['message']


def test_apply_senza_rilevamento_possibile_non_solleva(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('x')
    monkeypatch.setattr(gd, 'detect_gpus', boom)
    child = {'A': '1'}
    assert gd.apply_subprocess_env(child) == {'A': '1'}


# ------------------------------------------------------------------------------------------------------------ CLI
def test_json_ha_i_campi_amd(tmp_path, monkeypatch, capsys):
    r = detect(tmp_path, gfx='gfx1031')
    monkeypatch.setattr(gd, 'detect_gpus', lambda *a, **k: r)
    monkeypatch.delenv(OVR, raising=False)
    assert gd._main(['--json']) == 0
    d = json.loads(capsys.readouterr().out)
    assert (d['amd_gfx'], d['amd_family'], d['rocm_support'], d['amd_path']) == ('gfx1031', 'RDNA2', 'unofficial', 'rocm_override')
    assert d['amd_hsa_override_gfx_version'] == '10.3.0' and d['amd_user_hsa_override'] is None and d['amd_message']
    assert d['gpus'][0]['amd_family'] == 'RDNA2' and d['gpus'][0]['gfx'] == 'gfx1031'


def test_json_senza_gpu_ha_campi_null(tmp_path, monkeypatch, capsys):
    r = gd.detect_gpus(force=True, ctx=ctx('linux', sysfs=tmp_path / 's', dev=tmp_path / 'd'))
    monkeypatch.setattr(gd, 'detect_gpus', lambda *a, **k: r)
    assert gd._main(['--json']) == 0
    d = json.loads(capsys.readouterr().out)
    assert d['amd_family'] is None and d['rocm_support'] is None and d['amd_path'] is None


def test_describe_mostra_gfx(tmp_path):
    assert 'gfx1030 RDNA2' in gd.describe(detect(tmp_path, gfx='gfx1030'))


# ------------------------------------------------------------------------------------------------- amd_smoke_test.py
def _smoke():
    import importlib.util
    spec = importlib.util.spec_from_file_location('amd_smoke_test', Path(__file__).resolve().parents[1] / 'scripts_manutenzione' / 'amd_smoke_test.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize('gfx,user,needle,in_env', [
    ('gfx1031', None, 'APPLICATO', '10.3.0'), ('gfx1031', '10.3.2', 'NON applicato', '10.3.2'),
    ('gfx1100', None, 'non applicato (non serve', None), ('gfx1010', None, 'vulkan_cpu', None)])
def test_smoke_report_famiglia_percorso_override(tmp_path, monkeypatch, gfx, user, needle, in_env):
    r = detect(tmp_path, gfx=gfx)
    monkeypatch.setattr(gd, 'detect_gpus', lambda *a, **k: r)
    monkeypatch.delenv(OVR, raising=False)
    if user:
        monkeypatch.setenv(OVR, user)
    m = _smoke()
    status, text = m.amd_family_section()
    assert status == 'OK' and f'gfx: {gfx}' in text and needle in text and 'famiglia: ' in text and 'percorso scelto: ' in text
    assert m.CHILD_ENV.get(OVR) == in_env
    assert os.environ.get(OVR) == user                         # il processo dello script non viene modificato
