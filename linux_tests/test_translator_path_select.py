# -*- coding: utf-8 -*-
"""utils/translator_path_select.py: scelta bf16 / nf4 / gguf / nllb per VRAM libera e backend. Funzione pura: nessuna GPU."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from utils import translator_path_select as sel  # noqa: E402

ALL = ('Q4_K_M', 'Q3_K_M', 'IQ3_M')


def pick(free, backend='cuda', avail=ALL, **kw):
    return sel.choose_translator_path(free, backend, gguf_available=avail, **kw)


def legacy_kind(free):
    """Regola del motore storico (engine.py): bf16 se la VRAM libera raggiunge bf16_min_free_gb, altrimenti NF4."""
    from core.llm_subtitle_translator.engine import MODEL_SPECS
    return sel.BF16 if free >= MODEL_SPECS['translategemma-12b'].bf16_min_free_gb else sel.NF4


def test_soglia_bf16_uguale_a_quella_del_motore_storico():
    from core.llm_subtitle_translator.engine import MODEL_SPECS
    assert sel.DEFAULT_BF16_MIN_FREE_GIB == MODEL_SPECS['translategemma-12b'].bf16_min_free_gb


@pytest.mark.parametrize('with_gguf', [True, False])
def test_con_gguf_before_nf4_spento_il_percorso_e_quello_di_oggi(with_gguf):
    """Regola storica (config llm_translator_gguf_before_nf4 = False): da 10,5 GiB liberi in su, su NVIDIA, e' bf16/NF4 come nel
    motore storico, anche con i GGUF presenti."""
    avail = ALL if with_gguf else ()
    for tenth in range(105, 481):                         # 10,5 ... 48,0 GiB
        free = tenth / 10
        assert pick(free, 'cuda', avail, gguf_before_nf4=False).kind == legacy_kind(free), free


def test_default_gguf_preferito_a_nf4_fra_10_5_e_20_gib_e_bf16_oltre():
    """Dopo il banco di fase 3 (PROPOSTA, da confermare): 12-20 GiB -> Q4_K_M; da 20 GiB bf16 come oggi."""
    assert sel.DEFAULT_GGUF_BEFORE_NF4 is True
    for free in (10.6, 11.0, 11.4, 11.9, 15.0, 19.99):
        c = pick(free)
        assert (c.kind, c.quant) == (sel.GGUF, 'Q4_K_M'), free
    for tenth in range(200, 481):
        assert pick(tenth / 10).kind == sel.BF16


def test_default_senza_gguf_utilizzabile_ripiega_su_nf4_come_oggi():
    for free in (10.5, 11.0, 15.0, 19.99):
        c = pick(free, avail=())
        assert (c.kind, c.reason) == (sel.NF4, 'vram_nf4'), free
    assert pick(10.4, avail=()).kind == sel.NLLB                                    # sotto la soglia NF4 e senza GGUF
    assert pick(11.0, avail=('Q4_K_M',), quant='IQ3_M').kind == sel.NF4          # quant richiesta assente: NF4, non NLLB
    assert pick(9.0, avail=('Q4_K_M',), n_parallel=64).kind == sel.NLLB          # nessun GGUF entra e NF4 no


def test_scheda_da_12gb_reale_storica_su_nf4_nuova_su_q4():
    # 12 GB = 12,0 GiB totali: con il desktop acceso ne restano 10,6-11,6 liberi.
    for free in (10.6, 11.0, 11.4, 11.9):
        assert pick(free, gguf_before_nf4=False).kind == sel.NF4
        assert pick(free).quant == 'Q4_K_M'


@pytest.mark.parametrize('free,exp', [(19.99, sel.NF4), (20.0, sel.BF16), (10.5, sel.NF4)])
def test_confini_bf16_nf4_storici(free, exp):
    assert pick(free, gguf_before_nf4=False).kind == exp


def test_pesi_e_ingombri_misurati_dal_banco():
    """Picco misurato (oltre la base) a 4 sequenze: 8.528 / 7.277 / 6.807 MiB. Il modello deve stare sopra il picco misurato."""
    assert sel.QUANT_WEIGHTS_GIB == {'Q4_K_M': 6.80, 'Q3_K_M': 5.60, 'IQ3_M': 5.27}
    for q, mib in (('Q4_K_M', 8528), ('Q3_K_M', 7277), ('IQ3_M', 6807)):
        stima = sel.gguf_need_gib(q, 4) - sel.SAFETY_MARGIN_GIB
        assert mib / 1024 <= stima <= mib / 1024 + 0.2, (q, stima)      # sopra il misurato, di poco


def test_8gb_va_su_gguf_con_la_migliore_che_entra():
    # scheda da 8 GB: ~7,0-7,6 GiB liberi
    c = pick(7.6)
    assert c.kind == sel.GGUF and c.quant == 'Q3_K_M'            # Q4_K_M (8,75 GiB con l'ingombro) non entra
    c = pick(7.3)
    assert (c.kind, c.quant) == (sel.GGUF, 'IQ3_M')
    assert pick(7.1).kind == sel.NLLB                             # IQ3_M ne chiede 7,22: una scheda da 8 GB molto occupata non entra
    assert pick(10.0).quant == 'Q4_K_M'                           # 10 GiB: entra la migliore


def test_sotto_8gb_nllb_con_motivo():
    c = pick(5.0)
    assert c.kind == sel.NLLB and c.reason == 'vram_too_low' and c.need_gib > 5.0


def test_quant_forzata_non_ripiega_su_un_altra_in_silenzio():
    assert pick(7.6, quant='iq3_m').quant == 'IQ3_M'
    c = pick(6.0, quant='Q4_K_M')                                 # non entra: NON scende su IQ3_M
    assert c.kind == sel.NLLB and c.reason == 'vram_too_low'
    assert pick(7.6, avail=('IQ3_M',), quant='Q3_K_M').reason == 'gguf_missing'
    assert pick(7.6, quant='Q2_K').reason == 'quant_unknown'


def test_nessun_gguf_presente():
    assert pick(7.6, avail=()).reason == 'gguf_missing'
    assert pick(7.6, avail=('Q3_K_M',)).quant == 'Q3_K_M'


@pytest.mark.parametrize('free', [None, 0, -1])
def test_vram_sconosciuta_o_assente(free):
    assert pick(free).reason == 'no_gpu'


def test_backend_cpu_o_sconosciuto_nllb():
    assert pick(24.0, 'cpu').kind == sel.NLLB
    assert pick(24.0, 'metal').kind == sel.NLLB


def test_amd_vulkan_solo_gguf_mai_bf16_ne_nf4():
    # Vulkan: bitsandbytes non c'e' e torch non usa la GPU. Anche con tanta VRAM, solo GGUF.
    for free in (7.6, 12.0, 24.0, 48.0):
        c = pick(free, 'vulkan')
        assert c.kind == sel.GGUF, free
    assert pick(24.0, 'vulkan').quant == 'Q4_K_M'
    assert pick(5.0, 'vulkan').kind == sel.NLLB


def test_rocm_bf16_se_entra_mai_nf4():
    assert pick(24.0, 'rocm').kind == sel.BF16
    assert pick(12.0, 'rocm').kind == sel.GGUF                    # niente bitsandbytes: NF4 non e' una strada
    assert pick(12.0, 'rocm', avail=()).kind == sel.NLLB


def test_soglie_configurabili():
    assert pick(11.0, nf4_min_free_gib=12.0, gguf_before_nf4=False).kind == sel.GGUF
    assert pick(11.0, nf4_min_free_gib=11.0, gguf_before_nf4=False).kind == sel.NF4
    assert pick(15.0, bf16_min_free_gib=14.0).kind == sel.BF16


def test_ingombro_cresce_con_le_sequenze_parallele():
    assert sel.gguf_need_gib('Q3_K_M', 8) > sel.gguf_need_gib('Q3_K_M', 4) > sel.gguf_need_gib('Q3_K_M', 1)
    # meno sequenze parallele = un quant migliore puo' entrare
    assert pick(8.5, n_parallel=1).quant == 'Q4_K_M'
    assert pick(8.5, n_parallel=4).quant == 'Q3_K_M'


def test_label():
    assert sel.PathChoice(sel.GGUF, 'IQ3_M').label == 'gguf:IQ3_M'
    assert sel.PathChoice(sel.NF4).label == 'nf4'
