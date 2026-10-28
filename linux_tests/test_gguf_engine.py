# -*- coding: utf-8 -*-
"""Motore GGUF del traduttore: prompt di TranslateGemma, risoluzione del file, nessun ripiego (ADR-009).

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
from core.llm_subtitle_translator.engine import (DEFAULT_MODEL_KEY,  # noqa: E402
                                                 MODEL_SPECS, build_mt_messages)
from utils import gguf_quant  # noqa: E402
from utils.translations import Translations  # noqa: E402

REF = MODEL_SPECS[DEFAULT_MODEL_KEY]

TEXTS = ["Where are you going?", "  padded \n", " Line one\nLine two ", "It's a \"test\" — àèé {x} {{y}}",
         "What the fuck is that?", "♪ la la ♪", "x"]
CODES = ['en', 'it', 'fr', 'de', 'es', 'pt', 'ru', 'ja', 'zh', 'ar', 'ko', 'hi', 'pl', 'tr', 'nl', 'sv', 'da', 'no', 'fi',
         'cs', 'hu', 'ro', 'uk', 'el', 'he', 'vi', 'th', 'pt_BR', 'pt-BR', 'en-GB']


def _gguf_engine(**kw):
    return ge.GGUFEngine('/nonexistent/x-Q3_K_M.gguf', 'Q3_K_M', **kw)


# ------------------------------------------------------------------------------------------------ prompt
def test_mt_messages_usa_lo_spec_del_modello():
    """Il motore GGUF non ha un prompt proprio: chiede quello di `engine.build_mt_messages`."""
    eng = _gguf_engine()
    for text in TEXTS:
        for code in CODES:
            for budget in (0, 35):
                assert eng.mt_messages(text, src_lang=code, budget=budget) == \
                    build_mt_messages(text, src_lang=code, budget=budget, spec=REF)


def test_spec_gguf_porta_etichetta_e_tetto_del_parallelismo():
    spec = _gguf_engine(n_parallel=3).spec
    assert spec.max_batch == 3 and 'GGUF Q3_K_M' in spec.label
    for f in ('generation', 'mt_prefix', 'mt_prefix_when', 'mt_budget_rule', 'context_window'):
        assert getattr(spec, f) == getattr(REF, f)


def test_render_prompt_en_it_esatto():
    msgs = build_mt_messages("Where are you going?")
    assert ge.render_prompt(msgs) == (
        "<bos><start_of_turn>user\n"
        "You are a professional English (en) to Italian (it) translator. Your goal is to accurately convey the "
        "meaning and nuances of the original English text while adhering to Italian grammar, vocabulary, and "
        "cultural sensitivities.\n"
        "Produce only the Italian translation, without any additional explanations or commentary. Please "
        "translate the following English text into Italian:\n\n\n"
        "Where are you going?<end_of_turn>\n<start_of_turn>model\n")


def test_render_prompt_porta_regole_e_budget_come_il_motore_storico():
    p = ge.render_prompt(build_mt_messages("What the fuck?", budget=20))
    assert "non più di 20 caratteri" in p and "Conserva le parolacce" in p and p.endswith("<start_of_turn>model\n")


def test_render_prompt_codice_lingua_sconosciuto_si_ferma_come_il_template_jinja():
    msgs = build_mt_messages("Hi", src_lang='xyz')
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
    n = 0
    for code in CODES:
        for text in TEXTS:
            for budget in (0, 35):
                m = build_mt_messages(text, src_lang=code, budget=budget)
                ref = tpl.render(messages=m, bos_token='<bos>', add_generation_prompt=True)
                assert ge.render_prompt(m) == ref, (code, text, budget)
                n += 1
    assert n == len(CODES) * len(TEXTS) * 2


# ------------------------------------------------------------------------------------------------ file GGUF
def test_scan_gguf_dir(tmp_path):
    for n in ('translategemma-12b-it-finale-Q3_K_M.gguf', 'translategemma-12b-it-finale-iq3_m.gguf',
              'altro-Q8_0.gguf', 'x-Q4_K_M-00001-of-00002.gguf', 'note.txt'):
        (tmp_path / n).write_bytes(b'x')
    got = ge.scan_gguf_dir(tmp_path)
    assert set(got) == {'Q3_K_M', 'IQ3_M'}
    assert ge.scan_gguf_dir(tmp_path / 'non_esiste') == {}


# ------------------------------------------------------------------------------------------------ risoluzione del file
def _gguf_files(tmp_path, *quants):
    for q in quants:
        (tmp_path / f'translategemma-12b-it-finale-{q}.gguf').write_bytes(b'x')


def test_resolve_gguf_path_trova_la_quantizzazione_richiesta(tmp_path):
    _gguf_files(tmp_path, 'Q4_K_M', 'IQ3_M')
    path, quant = ge.resolve_gguf_path(tmp_path, 'iq3_m')
    assert quant == 'IQ3_M' and path.endswith('-IQ3_M.gguf')


def test_resolve_gguf_path_senza_quantizzazione_usa_il_default(tmp_path):
    _gguf_files(tmp_path, 'Q4_K_M', 'IQ3_M')
    path, quant = ge.resolve_gguf_path(tmp_path, None)
    assert quant == gguf_quant.DEFAULT_QUANT == 'Q4_K_M'
    assert path.endswith('-Q4_K_M.gguf')


def test_resolve_gguf_path_senza_file_nomina_cartella_e_file_trovati(tmp_path):
    _gguf_files(tmp_path, 'IQ3_M')
    with pytest.raises(RuntimeError) as exc:
        ge.resolve_gguf_path(tmp_path, 'Q4_K_M')
    msg = str(exc.value)
    assert str(tmp_path) in msg and 'Q4_K_M' in msg and 'IQ3_M' in msg


def test_resolve_gguf_path_cartella_vuota_dice_che_non_ce_ne_sono(tmp_path):
    with pytest.raises(RuntimeError) as exc:
        ge.resolve_gguf_path(tmp_path, 'Q4_K_M')
    assert str(tmp_path) in str(exc.value) and 'Q4_K_M' in str(exc.value)


def test_resolve_gguf_path_quantizzazione_sconosciuta_e_un_errore_non_un_ripiego(tmp_path):
    _gguf_files(tmp_path, 'Q4_K_M')
    with pytest.raises(ValueError):
        ge.resolve_gguf_path(tmp_path, 'Q9_Z')


def test_resolve_gguf_path_cartella_di_default():
    assert ge.DEFAULT_GGUF_DIR.name == 'translategemma-12b-gguf'
    assert Path(ge.resolve_gguf_path.__defaults__[0] or ge.DEFAULT_GGUF_DIR) == ge.DEFAULT_GGUF_DIR


# ------------------------------------------------------------------------------------------------ traduttore
@pytest.fixture
def translator_module(monkeypatch):
    """core.translator importato anche senza torch/transformers (finti, solo per l'import)."""
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
    return t.LLMSubtitleTranslator()


def test_acquire_engine_risolve_il_file_e_carica_il_gguf(translator_module, monkeypatch, tmp_path):
    _gguf_files(tmp_path, 'Q4_K_M')
    tr_ = _translator(translator_module, monkeypatch,
                      llm_translator_gguf_dir=str(tmp_path),
                      llm_translator_gguf_quant='Q4_K_M',
                      llm_translator_gguf_parallel=2)
    seen = {}

    def fake_get(path, quant, key, cb, n_parallel=4, ctx_per_seq=512):
        seen.update(path=path, quant=quant, key=key, n_parallel=n_parallel)
        return 'motore-gguf'

    monkeypatch.setattr(ge, 'get_gguf_engine', fake_get)
    assert tr_._acquire_engine() == 'motore-gguf'
    assert seen['quant'] == 'Q4_K_M' and seen['key'] == DEFAULT_MODEL_KEY
    assert seen['path'].endswith('-Q4_K_M.gguf') and seen['n_parallel'] == 2


def test_acquire_engine_senza_pesi_fallisce_invece_di_ripiegare(translator_module, monkeypatch, tmp_path):
    """ADR-009: nessun secondo motore. Un file mancante e' un errore del job, non una traduzione con un altro modello."""
    tr_ = _translator(translator_module, monkeypatch, llm_translator_gguf_dir=str(tmp_path))
    loaded = mock.Mock()
    monkeypatch.setattr(ge, 'get_gguf_engine', loaded)
    with pytest.raises(RuntimeError, match=str(tmp_path)):
        tr_._acquire_engine()
    loaded.assert_not_called()


def test_acquire_engine_avvisa_se_ce_un_adattatore_lora(translator_module, monkeypatch, tmp_path):
    _gguf_files(tmp_path, 'Q4_K_M')
    logs = []
    tr_ = _translator(translator_module, monkeypatch,
                      llm_translator_gguf_dir=str(tmp_path),
                      llm_translator_adapter='/tmp/una-cartella-lora')
    tr_.log_callback = logs.append
    monkeypatch.setattr(ge, 'get_gguf_engine', lambda *a, **k: 'motore-gguf')
    tr_._acquire_engine()
    assert any('LoRA' in m for m in logs)


def test_cleanup_scarica_il_motore_gguf(translator_module, monkeypatch):
    tr_ = _translator(translator_module, monkeypatch)
    unload = mock.Mock()
    monkeypatch.setattr(ge, 'unload_gguf_engine', unload)
    tr_.cleanup()
    unload.assert_called_once_with()


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
    msgs = build_mt_messages("Hi")
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


def test_backend_inizializzato_prima_di_supports_gpu_offload(tmp_path, monkeypatch):
    """Windows (backend caricati dinamicamente): llama_supports_gpu_offload() prima di qualunque Llama() va in access violation
    se llama_backend_init() non e' stato chiamato. Il motore lo chiama PRIMA del controllo."""
    import sys
    import types
    ordine = []
    fake = types.ModuleType('llama_cpp')
    fake.llama_backend_init = lambda: ordine.append('init')

    def supports():
        assert ordine == ['init'], 'llama_supports_gpu_offload chiamata prima di llama_backend_init'
        ordine.append('supports')
        return False                       # ruota solo-CPU: il motore deve rifiutare, non andare in crash
    fake.llama_supports_gpu_offload = supports
    monkeypatch.setitem(sys.modules, 'llama_cpp', fake)
    f = tmp_path / 'x.gguf'
    f.write_bytes(b'GGUF')
    e = ge.GGUFEngine(str(f), 'Q4_K_M', n_gpu_layers=1)
    with pytest.raises(RuntimeError):
        e.load()
    assert ordine == ['init', 'supports']
