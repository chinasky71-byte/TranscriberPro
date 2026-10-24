# -*- coding: utf-8 -*-
"""Motore GGUF in sottoprocesso pulito (gguf_worker.py / gguf_subprocess.py).

Crash Windows: `llama_supports_gpu_offload()` va in access violation se `llama_cpp` e' importato DOPO `utils`/PyQt6.
Il processo di lavoro deve avere `llama_cpp` come primo import nativo. Le prove con un GGUF vero (tiny, CPU) usano
TP_TEST_GGUF_GEMMA3 come in test_gguf_engine.py.
"""
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from core.llm_subtitle_translator import gguf_engine as ge  # noqa: E402
from core.llm_subtitle_translator import gguf_subprocess as gs  # noqa: E402

GEMMA3 = os.environ.get('TP_TEST_GGUF_GEMMA3', '')
WORKER = ROOT / 'core' / 'llm_subtitle_translator' / 'gguf_worker.py'


def _need_gemma3():
    pytest.importorskip('llama_cpp')
    if not GEMMA3 or not Path(GEMMA3).is_file():
        pytest.skip('TP_TEST_GGUF_GEMMA3 non impostata')


def test_get_gguf_engine_restituisce_il_sottoprocesso_di_default(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, '_gguf_engine', None)
    monkeypatch.setattr(gs.GGUFSubprocessEngine, 'load', lambda self: None)
    e = ge.get_gguf_engine(str(tmp_path / 'x-Q3_K_M.gguf'), 'Q3_K_M')
    assert type(e) is gs.GGUFSubprocessEngine and isinstance(e, ge.GGUFEngine)
    monkeypatch.setattr(ge, '_gguf_engine', None)
    monkeypatch.setattr(ge.GGUFEngine, 'load', lambda self: None)
    e2 = ge.get_gguf_engine(str(tmp_path / 'x-Q3_K_M.gguf'), 'Q3_K_M', in_process=True)
    assert type(e2) is ge.GGUFEngine


def test_stessa_interfaccia_e_stesso_prompt_del_motore_in_processo():
    a = gs.GGUFSubprocessEngine('/x/y-Q3_K_M.gguf', 'Q3_K_M', n_parallel=3)
    b = ge.GGUFEngine('/x/y-Q3_K_M.gguf', 'Q3_K_M', n_parallel=3)
    assert a.spec == b.spec and a.spec.max_batch == 3
    assert a.mt_messages("Where are you going?", budget=30) == b.mt_messages("Where are you going?", budget=30)


def test_worker_importa_llama_cpp_prima_di_utils_e_pyqt(tmp_path):
    """Windows-like: tracciamo il PRIMO fra llama_cpp / utils / PyQt6 / core importato dal processo di lavoro.
    Una finta `llama_cpp` (nessuna ruota richiesta) basta: conta l'ordine, non il contenuto."""
    fake = tmp_path / 'fake'
    fake.mkdir()
    (fake / 'llama_cpp.py').write_text('def llama_backend_init():\n    pass\n', encoding='utf-8')
    code = textwrap.dedent(f'''
        import sys, runpy
        order = []
        class Spy:
            def find_spec(self, name, path=None, target=None):
                top = name.split('.')[0]
                if top in ('llama_cpp', 'utils', 'PyQt6', 'core') and top not in order:
                    order.append(top)
                return None
        sys.meta_path.insert(0, Spy())
        sys.path.insert(0, {str(fake)!r})
        sys.argv = ['gguf_worker.py']
        try:
            runpy.run_path({str(WORKER)!r}, run_name='__main__')
        except SystemExit:
            pass
        sys.stderr.write('ORDER=' + ','.join(order))
    ''')
    p = subprocess.run([sys.executable, '-c', code], input=json.dumps({'op': 'unload'}) + '\n', capture_output=True,
                       text=True, timeout=120)
    ev = [json.loads(l) for l in p.stdout.splitlines() if l.strip().startswith('{')]
    assert ev and ev[0]['ev'] == 'ready', (p.stdout, p.stderr[-800:])
    order = p.stderr.rsplit('ORDER=', 1)[1].split(',')
    assert order[0] == 'llama_cpp' and 'utils' in order and order.index('llama_cpp') < order.index('utils'), order


def test_worker_il_protocollo_non_si_sporca_con_le_stampe_native(tmp_path):
    """Il fd 1 e' deviato sull'stderr: una print dopo l'avvio non deve comparire fra gli eventi."""
    fake = tmp_path / 'fake'
    fake.mkdir()
    (fake / 'llama_cpp.py').write_text("import os\nos.write(1, b'RUMORE NATIVO\\n')\ndef llama_backend_init():\n    pass\n",
                                       encoding='utf-8')
    code = f"import sys,runpy\nsys.path.insert(0,{str(fake)!r})\nsys.argv=['w']\nrunpy.run_path({str(WORKER)!r}, run_name='__main__')"
    p = subprocess.run([sys.executable, '-c', code], input=json.dumps({'op': 'unload'}) + '\n', capture_output=True,
                       text=True, timeout=120)
    assert 'RUMORE' not in p.stdout and json.loads(p.stdout.splitlines()[0])['ev'] == 'ready' and 'RUMORE' in p.stderr


def test_worker_che_muore_da_errore_chiaro(tmp_path, monkeypatch):
    bad = tmp_path / 'worker.py'
    bad.write_text("import sys\nsys.stderr.write('boom nativo')\nsys.exit(3)\n", encoding='utf-8')
    monkeypatch.setattr(gs, 'WORKER_SCRIPT', bad)
    e = gs.GGUFSubprocessEngine('/x/y-Q3_K_M.gguf', 'Q3_K_M')
    with pytest.raises(RuntimeError) as ex:
        e.load()
    assert 'boom nativo' in str(ex.value) and e._proc is None
    e.unload()            # idempotente


def test_worker_che_non_si_avvia(monkeypatch, tmp_path):
    monkeypatch.setattr(gs.subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(OSError('no exe')))
    with pytest.raises(RuntimeError) as ex:
        gs.GGUFSubprocessEngine('/x/y-Q3_K_M.gguf', 'Q3_K_M').load()
    assert 'no exe' in str(ex.value)


# ------------------------------------------------------------------------------------------------ GGUF vero (tiny, CPU)
LINES = ["Where are you going?", "I don't know.", "Get out of here!", "We have to leave now.", "Did you see that?"]


def test_gguf_vero_il_sottoprocesso_da_lo_stesso_testo_del_motore_in_processo():
    _need_gemma3()
    inproc = ge.GGUFEngine(GEMMA3, 'Q8_0', n_parallel=2, ctx_per_seq=256, n_gpu_layers=0)
    sub = gs.GGUFSubprocessEngine(GEMMA3, 'Q8_0', n_parallel=2, ctx_per_seq=256, n_gpu_layers=0)
    logs = []
    sub.log_callback = logs.append
    try:
        convs = [inproc.mt_messages(t, budget=30) for t in LINES]
        want = inproc.generate(convs, max_new_tokens=16)
        got = sub.generate(convs, max_new_tokens=16)               # carica da solo
        assert got == want and len(got) == len(LINES)
        assert sub.generate(convs[:1], max_new_tokens=16) == want[:1]   # il modello resta caricato fra una chiamata e l'altra
        assert any('pronto' in m or 'ready' in m for m in logs)         # i log del processo di lavoro arrivano al chiamante
        pid = sub._proc.pid
        sub.unload()
        assert sub._proc is None
        assert sub.generate(convs[:1], max_new_tokens=16) == want[:1] and sub._proc.pid != pid   # riparte
    finally:
        inproc.unload()
        sub.unload()


def test_gguf_vero_n_gpu_layers_diverso_da_zero_su_ruota_cpu_da_errore_non_crash():
    """Ramo "ruota senza GPU" con n_gpu_layers != 0, attraverso il processo di lavoro. NON copre il ramo con GPU (quello del
    crash Windows): lo puo' provare solo una macchina con GPU e ruota CUDA/Vulkan."""
    _need_gemma3()
    sub = gs.GGUFSubprocessEngine(GEMMA3, 'Q8_0', n_gpu_layers=-1)
    try:
        import llama_cpp
        llama_cpp.llama_backend_init()
        if llama_cpp.llama_supports_gpu_offload():
            pytest.skip('questa ruota ha il supporto GPU')
    except Exception:
        pass
    with pytest.raises(RuntimeError) as ex:
        sub.load()
    assert 'GPU' in str(ex.value) and sub._proc is None


def test_gguf_vero_codice_lingua_sconosciuto_arriva_come_unknown_language():
    _need_gemma3()
    sub = gs.GGUFSubprocessEngine(GEMMA3, 'Q8_0', n_parallel=1, n_gpu_layers=0)
    try:
        conv = [{'role': 'user', 'content': [{'type': 'text', 'source_lang_code': 'xx-nope', 'target_lang_code': 'it',
                                                'text': 'Hi'}]}]
        with pytest.raises(ge.UnknownLanguageError):
            sub.generate([conv], max_new_tokens=8)
        assert sub._proc is not None and sub._proc.poll() is None       # il processo sopravvive a un errore di richiesta
        ok = sub.generate([sub.mt_messages('Hello.', budget=30)], max_new_tokens=8)
        assert len(ok) == 1
    finally:
        sub.unload()


# ------------------------------------------------------------------------------------------------ robustezza (worker finto)
FAKE = """
import json, sys, os, time
mode = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mode.txt')).read().strip()
def out(ev): sys.stdout.write(json.dumps(ev) + '\\n'); sys.stdout.flush()
out({'ev': 'ready'})
if mode == 'dieafterready':
    sys.stderr.write('boom nativo'); sys.stderr.flush()
    sys.exit(4)
for line in sys.stdin:
    r = json.loads(line)
    if r['op'] == 'unload':
        break
    if r['op'] == 'load':
        out({'ev': 'log', 'msg': 'lang=' + str(r.get('lang'))})
        if mode == 'slowload':
            time.sleep(60)
        if mode == 'noise':
            sys.stdout.write('RUMORE NON JSON\\n'); sys.stdout.flush()
            sys.stdout.buffer.write('RUMORE NON ASCII \\u00e8\\n'.encode('utf-8')); sys.stdout.buffer.flush(); out({'ev': 'result', 'id': 999, 'outputs': ['arretrato']})
        out({'ev': 'loaded', 'id': r['id']})
    elif r['op'] == 'generate':
        if mode == 'hang':
            time.sleep(60)
        if mode == 'die':
            sys.stderr.write('boom nativo'); sys.stderr.flush()
            sys.exit(3)
        if mode == 'noise':
            out({'ev': 'result', 'id': r['id'] - 1, 'outputs': ['arretrato']})
        out({'ev': 'result', 'id': r['id'], 'outputs': ['ok:%d' % len(r['conversations'])]})
"""


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    script = tmp_path / 'fakeworker.py'
    script.write_text(FAKE, encoding='utf-8')
    monkeypatch.setattr(gs, 'WORKER_SCRIPT', script)

    def make(mode):
        (tmp_path / 'mode.txt').write_text(mode, encoding='utf-8')
        e = gs.GGUFSubprocessEngine('/x/y-Q3_K_M.gguf', 'Q3_K_M')
        e.logs = []
        e.log_callback = e.logs.append
        return e
    yield make


def test_righe_non_json_e_risposte_arretrate_non_sfalsano_i_risultati(fake_engine):
    e = fake_engine('noise')
    try:
        assert e.generate([['a'], ['b']]) == ['ok:2']
        assert e.generate([['a']]) == ['ok:1']          # niente slittamento di un blocco
    finally:
        e.unload()


def test_la_lingua_dell_app_arriva_al_processo_di_lavoro(fake_engine):
    from utils.translations import get_translations
    e = fake_engine('ok')
    try:
        e.load()
        assert f'lang={get_translations().current_language}' in e.logs
    finally:
        e.unload()


def test_worker_che_non_risponde_scade_e_viene_chiuso(fake_engine, monkeypatch):
    monkeypatch.setattr(gs, 'GENERATE_TIMEOUT_S', 1)
    e = fake_engine('hang')
    try:
        e.load()
        t0 = time.time()
        with pytest.raises(RuntimeError) as ex:
            e.generate([['a']])
        assert time.time() - t0 < 10 and e._proc is None and ' 1 s' in str(ex.value)
    finally:
        e.unload()


def test_unload_durante_generate_chiude_il_worker_senza_aspettare(fake_engine, monkeypatch):
    monkeypatch.setattr(gs, 'UNLOAD_WAIT_S', 0.3)
    e = fake_engine('hang')
    e.load()
    res = {}

    def run():
        try:
            e.generate([['a']])
        except Exception as exc:
            res['exc'] = exc
    th = threading.Thread(target=run)
    th.start()
    time.sleep(0.5)
    t0 = time.time()
    e.unload()                                    # annullo dalla GUI
    th.join(10)
    assert not th.is_alive() and time.time() - t0 < 10 and isinstance(res.get('exc'), RuntimeError) and e._proc is None


def test_worker_che_muore_ripetutamente_non_ricarica_il_modello_a_ogni_blocco(fake_engine, monkeypatch):
    e = fake_engine('die')
    starts = []
    orig = e._start
    monkeypatch.setattr(e, '_start', lambda: (starts.append(1), orig())[1])
    e.load()
    for _ in range(2):                            # morte, riavvio (consentito una volta), morte
        with pytest.raises(RuntimeError):
            e.generate([['a']])
    n = len(starts)
    with pytest.raises(RuntimeError):
        e.generate([['a']])                       # ora niente nuovo avvio
    assert len(starts) == n == 2
    e.load()                                      # un load esplicito riparte da zero
    assert e._proc is not None
    e.unload()


def test_conversazione_non_serializzabile_non_uccide_il_worker(fake_engine):
    e = fake_engine('ok')
    try:
        with pytest.raises(RuntimeError):
            e.generate([[object()]])
        assert e._proc is not None and e._proc.poll() is None
        assert e.generate([['a']]) == ['ok:1']
    finally:
        e.unload()


# ------------------------------------------------------------------------------------------------ ciclo di vita e invarianti
def test_statico_nel_worker_llama_cpp_precede_utils_pyqt_torch_core():
    """AST: a livello di modulo il worker importa solo libreria standard; `main()` chiama `_prepare_llama()` (che importa
    llama_cpp) PRIMA di qualunque import di core/utils/PyQt6/torch."""
    import ast
    tree = ast.parse(WORKER.read_text(encoding='utf-8'))
    heavy = ('utils', 'PyQt6', 'torch', 'core', 'transformers', 'bitsandbytes', 'numpy')

    def top(node):
        if isinstance(node, ast.Import):
            return [a.name.split('.')[0] for a in node.names]
        if isinstance(node, ast.ImportFrom):
            return [(node.module or '').split('.')[0]]
        return []
    module_level = [n for node in tree.body for n in top(node)]
    assert not set(module_level) & set(heavy), module_level
    funcs = {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}
    prep = [n for node in ast.walk(funcs['_prepare_llama']) for n in top(node)]
    assert 'llama_cpp' in prep and not set(prep) & set(heavy)
    main_nodes = sorted((n for n in ast.walk(funcs['main']) if isinstance(n, (ast.Import, ast.ImportFrom, ast.Call))),
                        key=lambda n: (n.lineno, n.col_offset))
    seq = []
    for n in main_nodes:
        if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == '_prepare_llama':
            seq.append('llama_cpp')
        else:
            seq.extend(x for x in top(n) if x in heavy)
    assert seq and seq[0] == 'llama_cpp' and 'core' in seq and seq.index('llama_cpp') < seq.index('core'), seq


def test_il_genitore_non_importa_mai_llama_cpp():
    pytest.importorskip('llama_cpp')          # senza la ruota il test passerebbe a vuoto
    code = ("import sys\n"
            "import core.llm_subtitle_translator.gguf_subprocess, core.llm_subtitle_translator.path_router\n"
            "from core.llm_subtitle_translator import path_router as pr\n"
            "pr.runtime_inputs(torch_cuda=False, torch_hip=False, marker='cpu')\n"
            "assert 'llama_cpp' not in sys.modules, 'il genitore ha importato llama_cpp'\n")
    p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert p.returncode == 0, p.stderr[-800:]


def test_worker_che_muore_durante_la_traduzione_non_blocca_ne_rompe_la_pipeline(fake_engine):
    """Il traduttore a blocchi completa il file anche se il worker muore: i blocchi restano vuoti (e' compito del chiamante, L2/L3,
    recuperarli: qui `fallback=None`, quel passaggio NON e' provato), la causa e' nel log dell'utente."""
    from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
    from core.llm_subtitle_translator.translator import SubtitleLLMTranslator
    e = fake_engine('die')
    units = [SubtitleUnit(id=i + 1, text=t, duration=2.0, is_dialogue=False) for i, t in enumerate(LINES)]
    lt = SubtitleLLMTranslator(engine=e, fallback=None, batch_size=2, log_callback=e.logs.append)
    try:
        res = lt.translate(units)                         # nessuna eccezione
        assert set(res) == {u.id for u in units} and all(not v for v in res.values())
        assert any('boom nativo' in m for m in e.logs)
    finally:
        e.unload()


def test_stop_dell_utente_cleanup_del_traduttore_uccide_il_figlio(fake_engine, monkeypatch, tmp_path):
    monkeypatch.setattr(ge, '_gguf_engine', None)
    fake_engine('ok')                                     # imposta WORKER_SCRIPT e la modalita'
    eng = ge.get_gguf_engine(str(tmp_path / 'x-Q3_K_M.gguf'), 'Q3_K_M')
    proc = eng._proc
    assert proc is not None and proc.poll() is None
    import importlib
    from types import SimpleNamespace
    from unittest import mock
    for m in ('torch', 'transformers', 'huggingface_hub'):          # solo per importare core.translator senza torch
        try:
            importlib.import_module(m)
        except Exception:
            monkeypatch.setitem(sys.modules, m, mock.MagicMock())
    had = 'core.translator' in sys.modules
    T = importlib.import_module('core.translator')
    T.LLMSubtitleTranslator.cleanup(SimpleNamespace(_engine=None))      # come lo chiama la pipeline allo Stop
    assert proc.poll() is not None and eng._proc is None
    if not had:
        sys.modules.pop('core.translator', None)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='controllo del pid con /proc')
def test_morte_del_genitore_non_lascia_il_worker_orfano(tmp_path):
    script = tmp_path / 'fakeworker.py'
    script.write_text(FAKE, encoding='utf-8')
    (tmp_path / 'mode.txt').write_text('ok', encoding='utf-8')
    code = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        from core.llm_subtitle_translator import gguf_subprocess as gs
        gs.WORKER_SCRIPT = __import__('pathlib').Path({str(script)!r})
        e = gs.GGUFSubprocessEngine('/x/y-Q3_K_M.gguf', 'Q3_K_M')
        e.load()
        print(e._proc.pid, flush=True)
        os._exit(0)                                  # il genitore muore senza cleanup
    """)
    p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
    pid = int(p.stdout.split()[-1])
    for _ in range(50):
        if not Path(f'/proc/{pid}').exists() or Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z':
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail('worker orfano dopo la morte del genitore')


# ------------------------------------------------------------------------------------------------ annullo, avvio difettoso, orfani
def test_stop_durante_il_caricamento_chiude_subito_il_figlio(fake_engine, monkeypatch, tmp_path):
    monkeypatch.setattr(ge, '_gguf_engine', None)
    fake_engine('slowload')
    res = {}

    def run():
        try:
            ge.get_gguf_engine(str(tmp_path / 'x-Q3_K_M.gguf'), 'Q3_K_M')
        except Exception as exc:
            res['exc'] = exc
    th = threading.Thread(target=run)
    th.start()
    time.sleep(1.0)
    t0 = time.time()
    ge.unload_gguf_engine()                          # Stop mentre get_gguf_engine tiene _gguf_lock
    th.join(15)
    assert not th.is_alive() and time.time() - t0 < 15 and isinstance(res.get('exc'), RuntimeError)
    assert ge.current_gguf_engine() is None


def test_dopo_uno_stop_nessun_riavvio_del_modello(fake_engine):
    e = fake_engine('ok')
    e.load()
    starts = []
    orig = e._start
    e._start = lambda: (starts.append(1), orig())[1]
    e.abort()
    with pytest.raises(RuntimeError):
        e.generate([['a']])
    assert starts == [] and e._proc is None
    e.load()                                         # un load esplicito riparte
    assert e.generate([['a']]) == ['ok:1']
    e.unload()


def test_worker_che_muore_dopo_ready_da_la_causa_non_un_broken_pipe(fake_engine):
    e = fake_engine('dieafterready')
    with pytest.raises(RuntimeError) as ex:
        e.load()
    assert 'boom nativo' in str(ex.value) and 'Errno' not in str(ex.value) and e._proc is None


def test_rumore_non_ascii_sul_canale_non_uccide_il_worker(fake_engine):
    e = fake_engine('noise')
    try:
        assert e.generate([['a']]) == ['ok:1']
        assert e._proc is not None and e._proc.poll() is None
    finally:
        e.unload()


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='controllo del pid con /proc')
def test_morte_del_genitore_il_worker_vero_esce_da_solo_anche_senza_eof_su_stdin(tmp_path):
    """Il caso reale del watchdog: stdin NON si chiude (lo tiene aperto un altro processo) e il genitore muore: il worker esce da solo."""
    fake = tmp_path / 'fake'
    fake.mkdir()
    (fake / 'llama_cpp.py').write_text('def llama_backend_init():\n    pass\n', encoding='utf-8')
    code = textwrap.dedent(f"""
        import os, subprocess, sys
        r, w = os.pipe()
        env = dict(os.environ, PYTHONPATH={str(fake)!r} + os.pathsep + {str(ROOT)!r})
        worker = subprocess.Popen([sys.executable, {str(WORKER)!r}], stdin=r, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'], pass_fds=(w,))
        os.close(r)
        assert worker.stdout.readline()                 # 'ready'
        print(worker.pid, holder.pid, flush=True)
        os._exit(0)
    """)
    p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
    wpid, hpid = (int(x) for x in p.stdout.split()[-2:])

    def gone(pid):
        return not Path(f'/proc/{pid}').exists() or Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z'
    try:
        for _ in range(150):
            if gone(wpid):
                break
            time.sleep(0.1)
        else:
            pytest.fail('il worker vero non e\' uscito dopo la morte del genitore')
    finally:
        for pid in (wpid, hpid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
