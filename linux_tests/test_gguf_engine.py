# -*- coding: utf-8 -*-
"""Percorso GGUF del traduttore LLM: prompt identico al motore transformers, router, ripiego, flag spento.

Nessun modello pesante e nessuna GPU. Le prove con un GGUF vero (tiny, su CPU) partono solo se le variabili
d'ambiente indicano il file e llama-cpp-python e' installato: provano il PERCORSO del codice, non la qualita'.
  TP_TEST_GGUF_GEMMA3   un GGUF di architettura gemma3 (es. gemma-3-270m-it-Q8_0.gguf)
  TP_TEST_GGUF_OTHER    un GGUF di altra architettura (es. Qwen2.5-0.5B-Instruct Q4_K_M), per il controllo d'architettura
  TP_TEST_TG_TEMPLATE   chat_template.jinja ufficiale di TranslateGemma (+ jinja2): confronto riga per riga col template
"""
import importlib
import os
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from core.llm_subtitle_translator import gguf_engine as ge  # noqa: E402
from core.llm_subtitle_translator import path_router as pr  # noqa: E402
from core.llm_subtitle_translator.engine import SubtitleLLMEngine  # noqa: E402
from utils import translator_path_select as sel  # noqa: E402
from utils.translations import Translations  # noqa: E402

TEXTS = ["Where are you going?", "  padded \n", " Line one\nLine two ", "It's a \"test\" — àèé {x} {{y}}",
         "What the fuck is that?", "♪ la la ♪", "x"]
CODES = ['en', 'it', 'fr', 'de', 'es', 'pt', 'ru', 'ja', 'zh', 'ar', 'ko', 'hi', 'pl', 'tr', 'nl', 'sv', 'da', 'no', 'fi',
         'cs', 'hu', 'ro', 'uk', 'el', 'he', 'vi', 'th', 'pt_BR', 'pt-BR', 'en-GB']


def _gguf_engine(**kw):
    return ge.GGUFEngine('/nonexistent/x-Q3_K_M.gguf', 'Q3_K_M', **kw)


# ------------------------------------------------------------------------------------------------ prompt
def test_mt_messages_identico_al_motore_transformers():
    """Il motore GGUF eredita mt_messages: stesse regole di sottotitolo, budget e codice lingua, per costruzione."""
    ref = SubtitleLLMEngine('translategemma-12b')
    eng = _gguf_engine()
    for text in TEXTS:
        for code in CODES:
            for budget in (0, 35):
                assert eng.mt_messages(text, src_lang=code, budget=budget) == \
                    ref.mt_messages(text, src_lang=code, budget=budget)


def test_spec_gguf_eredita_tutto_tranne_batch_ed_etichetta():
    ref = SubtitleLLMEngine('translategemma-12b').spec
    spec = _gguf_engine(n_parallel=3).spec
    assert spec.max_batch == 3 and 'GGUF Q3_K_M' in spec.label
    for f in ('generation', 'mt_prefix', 'mt_prefix_when', 'mt_budget_rule', 'loader', 'context_window'):
        assert getattr(spec, f) == getattr(ref, f)


def test_render_prompt_en_it_esatto():
    msgs = SubtitleLLMEngine('translategemma-12b').mt_messages("Where are you going?")
    assert ge.render_prompt(msgs) == (
        "<bos><start_of_turn>user\n"
        "You are a professional English (en) to Italian (it) translator. Your goal is to accurately convey the "
        "meaning and nuances of the original English text while adhering to Italian grammar, vocabulary, and "
        "cultural sensitivities.\n"
        "Produce only the Italian translation, without any additional explanations or commentary. Please "
        "translate the following English text into Italian:\n\n\n"
        "Where are you going?<end_of_turn>\n<start_of_turn>model\n")


def test_render_prompt_porta_regole_e_budget_come_il_motore_storico():
    eng = SubtitleLLMEngine('translategemma-12b')
    p = ge.render_prompt(eng.mt_messages("What the fuck?", budget=20))
    assert "non più di 20 caratteri" in p and "Conserva le parolacce" in p and p.endswith("<start_of_turn>model\n")


def test_render_prompt_codice_lingua_sconosciuto_si_ferma_come_il_template_jinja():
    msgs = SubtitleLLMEngine('translategemma-12b').mt_messages("Hi", src_lang='xyz')
    with pytest.raises(ge.UnknownLanguageError):
        ge.render_prompt(msgs)
    try:
        import jinja2
    except ImportError:
        return
    # _translate_mt risolleva i jinja2.TemplateError invece di svuotare ogni batch
    assert issubclass(ge.UnknownLanguageError, jinja2.TemplateError)


def test_render_prompt_rifiuta_forme_non_previste():
    for bad in ([], [{'role': 'assistant', 'content': 'x'}],
                [{'role': 'user', 'content': 'testo semplice'}],
                [{'role': 'user', 'content': [{'type': 'image', 'source_lang_code': 'en', 'target_lang_code': 'it'}]}]):
        with pytest.raises(ValueError):
            ge.render_prompt(bad)


@pytest.mark.skipif(not os.environ.get('TP_TEST_TG_TEMPLATE'), reason='TP_TEST_TG_TEMPLATE non impostata')
def test_render_prompt_uguale_al_template_ufficiale():
    jinja2 = pytest.importorskip('jinja2')
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    env = ImmutableSandboxedEnvironment()

    def raise_exception(msg):
        raise ValueError(msg)
    env.globals['raise_exception'] = raise_exception
    tpl = env.from_string(Path(os.environ['TP_TEST_TG_TEMPLATE']).read_text(encoding='utf-8'))
    eng = SubtitleLLMEngine('translategemma-12b')
    n = 0
    for code in CODES:
        for text in TEXTS:
            for budget in (0, 35):
                m = eng.mt_messages(text, src_lang=code, budget=budget)
                ref = tpl.render(messages=m, bos_token='<bos>', add_generation_prompt=True)
                assert ge.render_prompt(m) == ref, (code, text, budget)
                n += 1
    assert n == len(CODES) * len(TEXTS) * 2


# ------------------------------------------------------------------------------------------------ file GGUF
def test_scan_gguf_dir(tmp_path):
    for n in ('translategemma-12b-it-finale-Q3_K_M.gguf', 'translategemma-12b-it-finale-iq3_m.gguf',
              'altro-Q8_0.gguf', 'x-Q4_K_M-00001-of-00002.gguf', 'note.txt'):
        (tmp_path / n).write_bytes(b'x')
    got = pr.scan_gguf_dir(tmp_path)
    assert set(got) == {'Q3_K_M', 'IQ3_M'}
    assert pr.scan_gguf_dir(tmp_path / 'non_esiste') == {}


# ------------------------------------------------------------------------------------------------ runtime_inputs
def _report(gpus):
    from utils.gpu_detect import GpuReport
    return GpuReport(gpus=gpus)


def _gpu(vram, free=None, backends=('vulkan',)):
    from utils.gpu_detect import GpuInfo
    return GpuInfo(vendor='amd', name='x', vram_mib=vram, vram_free_mib=free, backends=list(backends))


def test_runtime_inputs_nvidia_cuda():
    assert pr.runtime_inputs(True, False, marker='cuda', free_fn=lambda: 11.0) == ('cuda', 11.0, True)


def test_runtime_inputs_rocm_senza_ruota_vulkan_non_puo_usare_llama():
    assert pr.runtime_inputs(True, True, marker='cuda', free_fn=lambda: 11.0) == ('rocm', 11.0, False)
    assert pr.runtime_inputs(True, True, marker='vulkan', free_fn=lambda: 11.0) == ('rocm', 11.0, True)


def test_runtime_inputs_vulkan_usa_la_vram_libera_o_in_mancanza_la_totale():
    r = _report([_gpu(8176, 7000), _gpu(4096, 4000)])
    b, free, ok = pr.runtime_inputs(False, False, report=r, marker='vulkan')
    assert (b, ok) == ('vulkan', True) and abs(free - 7000 / 1024) < 1e-9
    b, free, ok = pr.runtime_inputs(False, False, report=_report([_gpu(8192, None)]), marker='vulkan')
    assert abs(free - 8.0) < 1e-9


def test_runtime_inputs_senza_gpu_utilizzabile():
    assert pr.runtime_inputs(False, False, report=_report([]), marker='vulkan') == ('cpu', None, True)
    assert pr.runtime_inputs(False, False, marker='cuda') == ('cpu', None, False)


# ------------------------------------------------------------------------------------------------ router
@pytest.fixture
def router_env(monkeypatch, tmp_path):
    """Router con motori finti: registra chi viene chiamato. llama_cpp 'installato' e GGUF presenti."""
    calls = []
    legacy_engine, gguf_engine = object(), object()

    def get_engine_fn(key, cb, adapter=None, model_path=None):
        calls.append(('legacy', key, adapter, model_path))
        return legacy_engine

    def get_gguf(path, quant, key, cb, n_parallel=4, ctx_per_seq=512):
        calls.append(('gguf', Path(path).name, quant, n_parallel))
        return gguf_engine

    from core.llm_subtitle_translator import engine as engine_mod
    monkeypatch.setattr(ge, 'get_gguf_engine', get_gguf)
    monkeypatch.setattr(ge, 'unload_gguf_engine', lambda: calls.append(('unload_gguf',)))
    monkeypatch.setattr(ge, 'current_gguf_engine', lambda: None)
    monkeypatch.setattr(engine_mod, 'unload_engine', lambda: calls.append(('unload_tf',)))
    monkeypatch.setattr(engine_mod, '_engine', None)
    monkeypatch.setattr(pr.importlib.util, 'find_spec', lambda name: object())
    for q in ('Q4_K_M', 'Q3_K_M', 'IQ3_M'):
        (tmp_path / f'translategemma-12b-it-finale-{q}.gguf').write_bytes(b'x')
    cfg = {'llm_translator_gguf_dir': str(tmp_path)}
    logs = []

    def acquire(inputs, key='translategemma-12b', adapter=None, model_path=None, cfg_over=None):
        c = dict(cfg, **(cfg_over or {}))
        return pr.acquire_engine(key, None, adapter, model_path, get_engine_fn=get_engine_fn,
                                 cfg_get=lambda k, d=None: c.get(k, d), log=logs.append, inputs=inputs)

    return types.SimpleNamespace(acquire=acquire, calls=calls, logs=logs, legacy=legacy_engine, gguf=gguf_engine,
                                 engine_mod=engine_mod, monkeypatch=monkeypatch)


def test_router_8gb_usa_il_gguf(router_env):
    e = router_env.acquire(('cuda', 7.6, True))
    assert e is router_env.gguf
    assert ('unload_tf',) in router_env.calls
    assert ('gguf', 'translategemma-12b-it-finale-Q3_K_M.gguf', 'Q3_K_M', 4) in router_env.calls
    assert any('gguf:Q3_K_M' in m for m in router_env.logs)


@pytest.mark.parametrize('free,backend', [(24.0, 'cuda'), (11.0, 'cuda'), (10.6, 'cuda'), (48.0, 'rocm')])
def test_router_schede_grandi_percorso_storico_con_gli_stessi_argomenti(router_env, free, backend):
    e = router_env.acquire((backend, free, True), adapter=None, model_path='/m')
    assert e is router_env.legacy
    assert ('legacy', 'translategemma-12b', None, '/m') in router_env.calls
    assert not any(c[0] == 'gguf' for c in router_env.calls)


def test_router_sotto_8gb_nllb_con_motivo_a_schermo(router_env):
    assert router_env.acquire(('cuda', 5.0, True)) is None
    assert not any(c[0] in ('gguf', 'legacy') for c in router_env.calls)
    text = '\n'.join(router_env.logs)
    assert 'NLLB' in text and '5.0' in text


def test_router_gguf_mancanti_nllb_non_nf4_che_non_regge(router_env, tmp_path):
    e = router_env.acquire(('cuda', 9.0, True), cfg_over={'llm_translator_gguf_dir': str(tmp_path / 'vuota')})
    assert e is None and 'GGUF' in '\n'.join(router_env.logs)


def test_router_caricamento_gguf_fallito_ripiega_dichiarato(router_env):
    def boom(*a, **k):
        raise RuntimeError('VRAM esaurita')
    router_env.monkeypatch.setattr(ge, 'get_gguf_engine', boom)
    assert router_env.acquire(('cuda', 7.6, True)) is None
    text = '\n'.join(router_env.logs)
    assert 'VRAM esaurita' in text and 'NLLB' in text


def test_router_adattatore_lora_esclude_il_gguf(router_env):
    assert router_env.acquire(('cuda', 7.6, True), adapter='/lora') is None
    assert not any(c[0] == 'gguf' for c in router_env.calls)


def test_router_llama_senza_gpu_o_assente(router_env):
    assert router_env.acquire(('cuda', 7.6, False)) is None
    router_env.monkeypatch.setattr(pr.importlib.util, 'find_spec', lambda name: None)
    assert router_env.acquire(('cuda', 7.6, True)) is None


def test_router_vulkan_amd_usa_il_gguf_senza_bitsandbytes(router_env):
    e = router_env.acquire(('vulkan', 24.0, True))
    assert e is router_env.gguf
    assert ('gguf', 'translategemma-12b-it-finale-Q4_K_M.gguf', 'Q4_K_M', 4) in router_env.calls


def test_router_altro_modello_non_ha_gguf(router_env):
    e = router_env.acquire(('cuda', 7.6, True), key='hunyuan-mt-7b')
    assert e is router_env.legacy


def test_router_motore_gia_caricato_si_riusa_senza_ridecidere(router_env):
    router_env.monkeypatch.setattr(router_env.engine_mod, '_engine', object())
    assert router_env.acquire(('cuda', 1.0, True)) is router_env.legacy        # VRAM "bassa" perche' il motore la occupa
    router_env.monkeypatch.setattr(router_env.engine_mod, '_engine', None)
    router_env.monkeypatch.setattr(ge, 'current_gguf_engine', lambda: router_env.gguf)
    assert router_env.acquire(('cuda', 1.0, True)) is router_env.gguf


def test_router_vram_non_leggibile_vale_il_percorso_storico(router_env):
    assert router_env.acquire(('cuda', 0.0, True)) is router_env.legacy
    assert router_env.acquire(('rocm', None, True)) is router_env.legacy


def test_router_nessun_messaggio_gguf_per_chi_finisce_su_bf16(router_env):
    router_env.monkeypatch.setattr(pr.importlib.util, 'find_spec', lambda name: None)
    assert router_env.acquire(('cuda', 24.0, True)) is router_env.legacy
    assert not any('llama' in m for m in router_env.logs)


def test_router_difetto_interno_torna_al_percorso_storico(router_env):
    router_env.monkeypatch.setattr(sel, 'choose_translator_path', mock.Mock(side_effect=RuntimeError('bug')))
    assert router_env.acquire(('cuda', 7.6, True)) is router_env.legacy
    assert 'bug' in '\n'.join(router_env.logs)


def test_router_sequenze_parallele_da_config(router_env):
    router_env.acquire(('cuda', 12.0, True), cfg_over={'llm_translator_nf4_min_free_gb': 14.0,
                                                       'llm_translator_gguf_parallel': 2})
    assert ('gguf', 'translategemma-12b-it-finale-Q4_K_M.gguf', 'Q4_K_M', 2) in router_env.calls


# ------------------------------------------------------------------------------------------------ i18n
GG_KEYS = ['gg_ready', 'gg_path_chosen', 'gg_adapter_blocks_gguf', 'gg_llama_missing', 'gg_llama_no_gpu',
           'gg_load_failed', 'gg_using_nllb', 'gg_reason_no_gpu', 'gg_reason_gguf_missing',
           'gg_reason_quant_unknown', 'gg_reason_vram_too_low', 'gg_reason_load_failed', 'gg_router_error',
           'gg_nllb_ft_unavailable', 'gg_err_llama', 'gg_err_file_missing', 'gg_err_no_gpu_offload', 'gg_err_load',
           'gg_err_arch', 'gg_err_no_context']


@pytest.mark.parametrize('key', GG_KEYS)
def test_chiavi_gg_in_en_e_it_con_gli_stessi_segnaposto(key):
    import re
    en, it = Translations.TEXTS['en'][key], Translations.TEXTS['it'][key]
    assert en != it
    ph = lambda s: sorted(re.findall(r'\{(\w+)(?:[:!][^}]*)?\}', s))  # noqa: E731
    assert ph(en) == ph(it)


def test_gg_tutte_le_chiavi_usate_nel_codice_esistono():
    import re
    used = set()
    for f in ('gguf_engine.py', 'path_router.py'):
        used |= set(re.findall(r"tr\('(gg_\w+)'\)", (ROOT / 'core/llm_subtitle_translator' / f).read_text(encoding='utf-8')))
    used |= set(re.findall(r"tr\('(gg_\w+)'\)", (ROOT / 'core/translator.py').read_text(encoding='utf-8')))
    src = (ROOT / 'core/llm_subtitle_translator/path_router.py').read_text(encoding='utf-8')
    indirect = {k for k in GG_KEYS if f"'{k}'" in src} - used     # chiavi passate a tr() tramite variabile
    assert used | indirect == set(GG_KEYS)


# ------------------------------------------------------------------------------------------------ flag spento
@pytest.fixture
def translator_module(monkeypatch):
    """core.translator importato anche senza torch/transformers (finti, solo per l'import) e con config finta."""
    stubbed = []
    for m in ('torch', 'transformers', 'huggingface_hub'):
        try:
            importlib.import_module(m)
        except Exception:
            monkeypatch.setitem(sys.modules, m, mock.MagicMock())
            stubbed.append(m)
    had = 'core.translator' in sys.modules
    t = importlib.import_module('core.translator')
    yield t
    if not had and stubbed:
        sys.modules.pop('core.translator', None)


class _Cfg:
    def __init__(self, **v):
        self.v = v

    def get(self, key, default=None):
        return self.v.get(key, default)


def _translator(t, monkeypatch, **cfg):
    monkeypatch.setattr(t, 'get_config', lambda: _Cfg(**cfg))
    tr_ = t.LLMSubtitleTranslator()
    tr_._get_engine = mock.Mock(return_value='motore-storico')
    return tr_


def test_flag_spento_e_la_chiamata_storica_e_il_router_non_viene_importato(translator_module, monkeypatch):
    for flag in ({}, {'llm_translator_gguf_enabled': False}):
        for m in ('core.llm_subtitle_translator.path_router', 'core.llm_subtitle_translator.gguf_engine'):
            monkeypatch.delitem(sys.modules, m, raising=False)
        tr_ = _translator(translator_module, monkeypatch, llm_translator_model_path='', **flag)
        probe = mock.Mock(side_effect=AssertionError('con il flag spento non si legge la GPU'))
        monkeypatch.setattr('utils.gpu_detect.detect_gpus', probe)
        assert tr_._acquire_engine() == 'motore-storico'
        tr_._get_engine.assert_called_once_with('translategemma-12b', None, adapter=None, model_path=None)
        assert 'core.llm_subtitle_translator.path_router' not in sys.modules
        assert 'core.llm_subtitle_translator.gguf_engine' not in sys.modules
        probe.assert_not_called()


def test_flag_spento_cleanup_identico(translator_module, monkeypatch):
    monkeypatch.delitem(sys.modules, 'core.llm_subtitle_translator.gguf_engine', raising=False)
    tr_ = _translator(translator_module, monkeypatch)
    from core.llm_subtitle_translator import engine as engine_mod
    unload = mock.Mock()
    monkeypatch.setattr(engine_mod, 'unload_engine', unload)
    tr_.cleanup()
    unload.assert_called_once_with()
    assert 'core.llm_subtitle_translator.gguf_engine' not in sys.modules


def test_flag_acceso_passa_dal_router_e_none_porta_a_nllb_ft(translator_module, monkeypatch, tmp_path):
    tr_ = _translator(translator_module, monkeypatch, llm_translator_gguf_enabled=True)
    seen = {}

    def fake_acquire(*a, **k):
        seen['k'] = k
        return None
    monkeypatch.setattr(pr, 'acquire_engine', fake_acquire)
    assert tr_._acquire_engine() is None
    assert seen['k']['get_engine_fn'] is tr_._get_engine

    src = tmp_path / 'a.srt'
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n", encoding='utf-8')
    out = tmp_path / 'b.srt'
    nllb = mock.Mock()
    nllb.translate_file.return_value = True
    monkeypatch.setattr(translator_module, 'NLLBFineTunedTranslator', mock.Mock(return_value=nllb))
    assert tr_.translate_file(src, out, 'eng', 'ita') is True
    nllb.translate_file.assert_called_once()
    nllb.cleanup.assert_called_once_with()
    tr_._get_engine.assert_not_called()


def test_nllb_ft_non_disponibile_ripiega_su_nllb_base(translator_module, monkeypatch, tmp_path):
    tr_ = _translator(translator_module, monkeypatch, llm_translator_gguf_enabled=True)
    monkeypatch.setattr(pr, 'acquire_engine', lambda *a, **k: None)
    base = mock.Mock()
    base.translate_file.return_value = True
    monkeypatch.setattr(translator_module, 'NLLBFineTunedTranslator', mock.Mock(side_effect=RuntimeError('manca')))
    monkeypatch.setattr(translator_module, 'NLLBTranslator', mock.Mock(return_value=base))
    logs = []
    tr_.log_callback = logs.append
    src = tmp_path / 'a.srt'
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n", encoding='utf-8')
    assert tr_.translate_file(src, tmp_path / 'b.srt', 'eng', 'ita') is True
    assert any('manca' in m for m in logs)


# ------------------------------------------------------------------------------------------------ GGUF vero (tiny, CPU)
GEMMA3 = os.environ.get('TP_TEST_GGUF_GEMMA3', '')
OTHER = os.environ.get('TP_TEST_GGUF_OTHER', '')


def _need_llama():
    pytest.importorskip('llama_cpp')


@pytest.fixture(scope='module')
def tiny_engine():
    _need_llama()
    if not GEMMA3 or not Path(GEMMA3).is_file():
        pytest.skip('TP_TEST_GGUF_GEMMA3 non impostata')
    e = ge.GGUFEngine(GEMMA3, 'Q8_0', n_parallel=4, ctx_per_seq=512, n_gpu_layers=0)
    e.load()
    yield e
    e.unload()


LINES = ["Where are you going?", "I don't know.", "Get out of here!", "We have to leave now.",
         "Did you see that?", "Never mind.", "Hello."]


def test_gguf_vero_ordine_e_numero_delle_risposte(tiny_engine):
    convs = [tiny_engine.mt_messages(t, budget=30) for t in LINES]       # 7 > n_parallel: due gruppi
    out = tiny_engine.generate(convs, max_new_tokens=24)
    assert len(out) == len(LINES) and all(isinstance(o, str) for o in out)


def test_gguf_vero_stesso_prompt_in_slot_diversi_stessa_risposta(tiny_engine):
    c = [tiny_engine.mt_messages(t) for t in LINES]
    out = tiny_engine.generate([c[0], c[2], c[0], c[4]], max_new_tokens=24)
    assert out[0] == out[2]
    assert out[1] == tiny_engine.generate([c[2]], max_new_tokens=24)[0]


def test_gguf_vero_uguale_al_riferimento_di_llama_cpp_python(tiny_engine):
    """La decodifica a basso livello coincide con quella greedy dell'API alta di llama-cpp-python."""
    from llama_cpp import Llama
    ref = Llama(GEMMA3, n_ctx=512, n_gpu_layers=0, verbose=False)
    convs = [tiny_engine.mt_messages(t, budget=30) for t in LINES[:4]]
    mine = tiny_engine.generate(convs, max_new_tokens=24)
    for conv, got in zip(convs, mine):
        toks = ref.tokenize(ge.render_prompt(conv).encode(), add_bos=False, special=True)
        want = ref.create_completion(toks, max_tokens=24, temperature=0.0)['choices'][0]['text'].strip()
        assert got == want


def test_gguf_vero_prompt_oltre_il_contesto_esce_vuoto_non_troncato():
    _need_llama()
    if not GEMMA3 or not Path(GEMMA3).is_file():
        pytest.skip('TP_TEST_GGUF_GEMMA3 non impostata')
    e = ge.GGUFEngine(GEMMA3, 'Q8_0', n_parallel=2, ctx_per_seq=96, n_gpu_layers=0)
    try:
        out = e.generate([e.mt_messages("word " * 200), e.mt_messages("Hi.")], max_new_tokens=8)
        assert out[0] == '' and isinstance(out[1], str)
    finally:
        e.unload()


def test_gguf_vero_architettura_diversa_rifiutata():
    _need_llama()
    if not OTHER or not Path(OTHER).is_file():
        pytest.skip('TP_TEST_GGUF_OTHER non impostata')
    e = ge.GGUFEngine(OTHER, 'Q4_K_M', n_gpu_layers=0)
    with pytest.raises(RuntimeError, match='gemma3'):
        e.load()
    assert e._ctx is None and e._llm_model is None          # nulla lasciato in memoria


def test_gguf_vero_scarico_e_ricarico():
    _need_llama()
    if not GEMMA3 or not Path(GEMMA3).is_file():
        pytest.skip('TP_TEST_GGUF_GEMMA3 non impostata')
    logs = []
    e = ge.GGUFEngine(GEMMA3, 'Q8_0', n_parallel=1, n_gpu_layers=0, log_callback=logs.append)
    e.load()
    e.unload()
    assert e._ctx is None
    assert e.generate([e.mt_messages("Hi.")], max_new_tokens=4)             # generate() ricarica da solo
    e.unload()
    assert len(logs) >= 4


def test_gguf_vero_dentro_il_traduttore_a_blocchi(tiny_engine):
    """SubtitleLLMTranslator (validatore, retry singolo, barra) lavora col motore GGUF come col transformers.
    Il modello da 270M non traduce: qui conta che il percorso giri e che ogni blocco abbia una riga nel risultato."""
    from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
    from core.llm_subtitle_translator.translator import SubtitleLLMTranslator
    units = [SubtitleUnit(id=i + 1, text=t, duration=2.0, is_dialogue=False) for i, t in enumerate(LINES)]
    lt = SubtitleLLMTranslator(engine=tiny_engine, fallback=None, batch_size=12, log_callback=lambda m: None)
    assert lt.batch_size <= 4                     # tetto = sequenze parallele del motore GGUF
    res = lt.translate(units)
    assert set(res) == {u.id for u in units}


# ------------------------------------------------------------------------------------------------ motore: errori e scarico (senza modello)
def test_unload_idempotente_senza_caricamento():
    e = _gguf_engine()
    e.unload()
    e.unload()


def test_load_file_mancante_messaggio_tradotto():
    e = _gguf_engine()
    with mock.patch.dict(sys.modules, {'llama_cpp': mock.MagicMock()}):
        with pytest.raises(RuntimeError, match='GGUF'):
            e.load()


def test_decode_fallito_solleva_e_pulisce_la_cache():
    e = _gguf_engine(n_parallel=2)
    ll = mock.MagicMock()
    ll.llama_decode.return_value = -1
    e._ll, e._ctx, e._batch, e._sampler = ll, object(), mock.MagicMock(), object()
    e._tokenize = lambda text: list(range(10))
    msgs = SubtitleLLMEngine('translategemma-12b').mt_messages("Hi")
    with pytest.raises(RuntimeError, match='llama_decode'):
        e._generate_group([msgs], 8)
    assert ll.llama_memory_clear.call_count == 2          # all'inizio e nel finally
    e._ctx = None


def test_generate_e_unload_si_escludono():
    import threading
    e = _gguf_engine()
    order = []
    started, release = threading.Event(), threading.Event()

    def slow_group(group, n):
        started.set()
        release.wait(2)
        order.append('generate')
        return [''] * len(group)
    e._generate_group = slow_group
    e._ctx = object()
    e._unload_locked = lambda quiet: order.append('unload')
    t = threading.Thread(target=lambda: e.generate([[]], 4))
    t.start()
    started.wait(2)
    u = threading.Thread(target=e.unload)
    u.start()
    release.set()
    t.join(3)
    u.join(3)
    assert order == ['generate', 'unload']
