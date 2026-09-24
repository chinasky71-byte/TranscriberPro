"""
Test CPU del modulo di produzione core/sentence_recompose.py (caricato PER
PERCORSO: core/__init__ importa utils.cache_bootstrap e non serve qui) e
della sua integrazione opt-in in core/pipeline.py (controllo statico: la
pipeline importa torch e non si carica nei test).
"""
import ast
import importlib.util
import json
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import _common  # noqa: F401
from split_eval import recompose as RC

ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = ROOT / 'core' / 'sentence_recompose.py'
WORK_CONF = ROOT / 'split_eval' / 'work_conf'


def _load_core():
    name = '_test_core_sentence_recompose'
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(CORE_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SR = _load_core()


def ts(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_src(path, cues):
    path.write_text(SR.render_srt([(i, ts(s), ts(e), t) for i, (s, e, t) in enumerate(cues, 1)]),
                    encoding='utf-8')


class FakeTranslator:
    """translate_file finto: traduce blocco per blocco con `fn(testo)` e
    registra le chiamate. `hook(call_no, blocks) -> blocks` altera l'uscita."""

    def __init__(self, fn, hook=None, raise_on=None):
        self.fn, self.hook, self.raise_on = fn, hook, raise_on or {}
        self.calls = []

    def __call__(self, inp, out):
        n = len(self.calls)
        blocks = SR.read_srt(inp)
        self.calls.append([b[3] for b in blocks])
        if n in self.raise_on:
            raise self.raise_on[n]
        res = [(i, s, e, self.fn(t)) for i, s, e, t in blocks]
        if self.hook:
            res = self.hook(n, res)
            if res is False:
                return False
        Path(out).write_text(SR.render_srt(res), encoding='utf-8')
        return True


REAL_IT = {
    'Sure, she is a bitch. But can you blame her? After all, Dad tried to send her husband to jail.':
        'Certo, è una stronza. Ma puoi biasimarla? Dopo tutto, papà ha cercato di mandare suo marito in prigione.',
    'Whatever.': 'Come vuoi.',
}


def real_fn(t):
    return REAL_IT.get(' '.join(t.split()), 'IT ' + t)


class TestCoreRecompose(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_it(self, cues, fake, **kw):
        src, out = self.d / 'src.srt', self.d / 'out.srt'
        write_src(src, cues)
        logs = []
        res = SR.translate_srt_with_recompose(src, out, fake, log=logs.append, **kw)
        return src, out, res, logs

    def assert_same_frame(self, src, out):
        a, b = SR.read_srt(src), SR.read_srt(out)
        self.assertEqual([(x[0], x[1], x[2]) for x in a], [(x[0], x[1], x[2]) for x in b])
        self.assertTrue(all(x[3].strip() for x in b))
        return b

    def test_real_example(self):
        cues = [(10.0, 13.5, 'Sure, she is a bitch. But can you blame her?\nAfter all, Dad tried to send her'),
                (13.6, 15.2, 'husband to jail.'), (16.0, 17.0, 'Whatever.')]
        fake = FakeTranslator(real_fn)
        src, out, res, logs = self.run_it(cues, fake)
        self.assertEqual((res['ok'], res['mode'], res['n_merged_units'], res['n_merged_blocks']),
                         (True, 'recompose', 1, 2))
        self.assertEqual(len(fake.calls), 1)                       # una sola traduzione (le unita')
        self.assertEqual(len(fake.calls[0]), 2)                    # 2 unita' per 3 blocchi
        b = self.assert_same_frame(src, out)
        self.assertIn('papà', b[0][3])
        self.assertIn('marito', b[1][3])
        self.assertEqual(b[2][3], 'Come vuoi.')
        unit_it = REAL_IT[' '.join(fake.calls[0][0].split())]
        self.assertTrue(SR.check_invariant(unit_it, [b[0][3], b[1][3]]))   # nessuna parola persa/duplicata
        self.assertTrue(any('ATTIVA' in l and '1 frasi spezzate' in l for l in logs))
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ['out.srt', 'src.srt'])   # temporanei rimossi

    def test_dash_blocks_never_merged(self):
        for first in ('- Hi.\n- I think', '- I think', '<i>- I think</i>', '– I think', 'Hi.\n- I think'):
            for second in ('so too.', '- so too.'):
                fake = FakeTranslator(lambda t: 'IT ' + t)
                src, out, res, _ = self.run_it([(0, 1, first), (1.1, 2, second)], fake)
                self.assertEqual(res['n_merged_units'], 0, (first, second))
                self.assertEqual(res['mode'], 'passthrough')
                self.assertEqual(fake.calls, [[first, second]])      # percorso normale, SRT originale

    def test_tags_music_gap_not_merged(self):
        for cues in ([(0, 1, '<i>I think</i>'), (1.1, 2, 'so too.')],
                     [(0, 1, '♪ I think'), (1.1, 2, 'so too.')],
                     [(0, 1, 'I think'), (2.5, 3, 'so too.')],
                     [(0, 1, 'I think'), (1.1, 2, 'Larry is here.')]):
            fake = FakeTranslator(lambda t: 'IT ' + t)
            _, _, res, _ = self.run_it(cues, fake)
            self.assertEqual(res['n_merged_units'], 0, cues)

    def test_fallback_wrong_unit_count(self):
        cues = [(0, 1, 'I think that'), (1.1, 2, 'we should go.'), (3, 4, 'Now.')]
        drop_one = lambda n, blocks: blocks[:-1] if n == 0 else blocks
        fake = FakeTranslator(lambda t: 'IT ' + t, hook=drop_one)
        src, out, res, logs = self.run_it(cues, fake)
        self.assertEqual((res['ok'], res['mode']), (True, 'fallback'))
        self.assertIn('unità tradotte', res['reason'])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[1], ['I think that', 'we should go.', 'Now.'])   # SRT originale
        b = self.assert_same_frame(src, out)
        self.assertEqual([x[3] for x in b], ['IT I think that', 'IT we should go.', 'IT Now.'])
        self.assertTrue(any('percorso normale' in l for l in logs))

    def test_fallback_on_exception_and_false(self):
        cues = [(0, 1, 'I think that'), (1.1, 2, 'we should go.')]
        fake = FakeTranslator(lambda t: 'IT ' + t, raise_on={0: RuntimeError('CUDA boom')})
        src, out, res, _ = self.run_it(cues, fake)
        self.assertEqual((res['ok'], res['mode']), (True, 'fallback'))
        self.assertIn('CUDA boom', res['reason'])
        self.assert_same_frame(src, out)
        fake = FakeTranslator(lambda t: 'IT ' + t, hook=lambda n, b: False if n == 0 else b)
        _, _, res, _ = self.run_it(cues, fake)
        self.assertEqual((res['ok'], res['mode'], len(fake.calls)), (True, 'fallback', 2))
        # unita' tradotta vuota -> ripiego
        fake = FakeTranslator(lambda t: 'IT ' + t,
                              hook=lambda n, b: [(i, s, e, '' if n == 0 else t) for i, s, e, t in b])
        _, _, res, _ = self.run_it(cues, fake)
        self.assertEqual(res['mode'], 'fallback')

    def test_interrupted_propagates(self):
        cues = [(0, 1, 'I think that'), (1.1, 2, 'we should go.')]
        fake = FakeTranslator(lambda t: 'IT ' + t, raise_on={0: InterruptedError()})
        with self.assertRaises(InterruptedError):
            self.run_it(cues, fake)
        self.assertEqual(len(fake.calls), 1)                         # nessun ripiego dopo l'annullamento

    def test_normal_path_errors_propagate_once(self):
        # errore anche nel percorso normale: si propaga come oggi (la pipeline
        # lo tratta come traduzione fallita), senza doppi tentativi
        cues = [(0, 1, 'I think that'), (1.1, 2, 'we should go.')]
        fake = FakeTranslator(lambda t: 'IT ' + t, raise_on={0: RuntimeError('a'), 1: RuntimeError('b')})
        with self.assertRaises(RuntimeError):
            self.run_it(cues, fake)
        self.assertEqual(len(fake.calls), 2)

    def test_unsplittable_unit_retranslated_per_block(self):
        cues = [(0, 1, 'Come'), (1.1, 2, 'in.'), (3, 4, 'Now.')]
        fn = lambda t: {'Come in.': 'Entra.', 'Come': 'Vieni', 'in.': 'dentro.'}.get(t, 'IT ' + t)
        fake = FakeTranslator(fn)
        src, out, res, _ = self.run_it(cues, fake)
        self.assertEqual((res['mode'], res['n_retranslated_units']), ('recompose', 1))
        self.assertEqual(fake.calls[1], ['Come', 'in.'])
        b = self.assert_same_frame(src, out)
        self.assertEqual([x[3] for x in b], ['Vieni', 'dentro.', 'IT Now.'])

    def test_polish_fn(self):
        cues = [(0, 1, 'I think that'), (1.1, 2, 'we should go.')]
        fake = FakeTranslator(lambda t: 'penso che dovremmo andare.' if t == 'I think that we should go.' else t)
        seen = []
        _, out, res, _ = self.run_it(cues, fake, polish_fn=lambda ts_: seen.append(list(ts_)) or [x + '!' for x in ts_])
        self.assertEqual(len(seen[0]), 2)
        self.assertTrue(all(x[3].endswith('!') for x in SR.read_srt(out)))
        # polish che solleva o restituisce un vuoto: ignorato
        fake = FakeTranslator(lambda t: 'penso che dovremmo andare.' if t == 'I think that we should go.' else t)

        def bad(_):
            raise ValueError('x')
        _, out, res, logs = self.run_it(cues, fake, polish_fn=bad)
        self.assertEqual(res['mode'], 'recompose')
        self.assertTrue(any('rifinitura finale ignorata' in l for l in logs))

    def test_invariants_fuzz(self):
        rng = random.Random(11)
        vocab = 'and the house go to we you know that is it'.split()
        for _ in range(40):
            cues, t = [], 0.0
            for _ in range(rng.randint(1, 8)):
                words = [rng.choice(vocab) for _ in range(rng.randint(1, 6))]
                if rng.random() < 0.4:
                    words[-1] += '.'
                if rng.random() < 0.1:
                    words[0] = '- ' + words[0]
                cues.append((t, t + rng.uniform(0.5, 2), ' '.join(words)))
                t = cues[-1][1] + rng.uniform(0.05, 1.5)
            fake = FakeTranslator(lambda s: ' '.join(w.upper() for w in s.split() if rng.random() > 0.2) or 'X')
            src, out, res, _ = self.run_it(cues, fake)
            self.assertTrue(res['ok'])
            self.assert_same_frame(src, out)

    def test_config_prod_keys(self):
        with self.assertRaises(KeyError):
            SR.make_config({'skip_tagged': True})        # chiave di produzione, non del banco
        cues = [(0, 1, 'I think that'), (1.1, 2, 'we should go.')]
        _, _, res, _ = self.run_it(cues, FakeTranslator(lambda t: 'IT ' + t), config={'skip_tagged': False})
        self.assertEqual(res['mode'], 'recompose')


class TestCoherenceWithBench(unittest.TestCase):
    """core/sentence_recompose e split_eval/recompose devono restare allineati."""

    def test_config_and_tables(self):
        self.assertEqual(SR.DEFAULT_CONFIG, RC.DEFAULT_CONFIG)
        for name in ('BAD_END', 'CONJ_START', 'DANGLING_SRC', 'APOCOPE'):
            self.assertEqual(getattr(SR, name), getattr(RC, name), name)
        from split_eval import midcut as MC
        self.assertEqual(SR.CONT_WORDS, MC.CONT_WORDS)

    def test_split_text_fuzz(self):
        rng = random.Random(5)
        vocab = "il la di che e non un per è con mi si ma lo casa, porta. sempre? ciao! l' po' 20 dollari".split()
        src_vocab = ['and', 'the', 'house', 'go', 'to', 'I', "It's", 'we', 'you.', 'but,']
        for _ in range(400):
            k = rng.randint(2, 3)
            src = [' '.join(rng.choice(src_vocab) for _ in range(rng.randint(1, 8))) for _ in range(k)]
            text = ' '.join(rng.choice(vocab) for _ in range(rng.randint(0, 30)))
            durs = [rng.uniform(0.3, 4) for _ in range(k)]
            for pol in ('force', 'first'):
                self.assertEqual(SR.split_text(text, src, durs, {'fallback': pol}),
                                 RC.split_text(text, src, durs, {'fallback': pol}))

    def test_recompose_fuzz(self):
        rng = random.Random(9)
        vocab = ['and', 'The', 'house', 'go.', 'to', '- I', 'we', 'you?', 'but,', '<i>so</i>', '♪', 'Larry']
        for _ in range(200):
            bl, t = [], 0.0
            for _ in range(rng.randint(0, 9)):
                txt = ' '.join(rng.choice(vocab) for _ in range(rng.randint(1, 5)))
                bl.append({'start': t, 'end': t + 1, 'text': txt})
                t += 1 + rng.uniform(0, 1.5)
            self.assertEqual(SR.recompose(bl)[0], RC.recompose(bl)[0])

    def test_real_saved_units(self):
        """Sulle traduzioni REALI salvate del banco v2 (sola lettura): stessa
        ridivisione e stesse unita' (anche con la guardia di produzione sui tag)."""
        out_dir = WORK_CONF / 'out' / 'nllb_finetuned'
        if not out_dir.exists():
            self.skipTest('work_conf assente')
        n = 0
        for p in sorted(out_dir.glob('*.json')):
            res = json.loads(p.read_text(encoding='utf-8'))
            if res.get('status') != 'ok':
                continue
            bdir = WORK_CONF / 'build' / res['win_id']
            mapping = json.loads((bdir / 'mapping.json').read_text(encoding='utf-8'))
            ut = {int(k): v for k, v in res['units_translated'].items()}
            cfg = dict(RC.DEFAULT_CONFIG)
            cfg.update({k: v for k, v in mapping['config'].items() if k in ('lang', 'max_gap_s', 'max_blocks',
                                                                           'max_chars', 'max_span_s')})
            self.assertEqual(SR.resplit(ut, mapping, cfg)[0], RC.resplit(ut, mapping, cfg)[0])
            src = SR.read_srt(bdir / 'src.srt')
            bl = [{'start': SR.ts_to_s(s), 'end': SR.ts_to_s(e), 'text': t} for _, s, e, t in src]
            got = [u['blocks'] for u in SR.recompose(bl, skip_tagged=True)[0]]
            self.assertEqual(got, [u['blocks'] for u in mapping['units']], res['win_id'])
            n += 1
        self.assertGreater(n, 100)


class TestPipelineIntegrationStatic(unittest.TestCase):
    """La pipeline importa torch: controllo statico del ramo opt-in."""

    @classmethod
    def setUpClass(cls):
        cls.pipe = (ROOT / 'core' / 'pipeline.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.pipe)

    def test_default_off(self):
        tree = ast.parse((ROOT / 'utils' / 'config.py').read_text(encoding='utf-8'))
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'DEFAULTS' for t in node.targets):
                d = node.value
                for k, v in zip(d.keys, d.values):
                    if isinstance(k, ast.Constant) and k.value == 'translation_recompose_sentences':
                        found = v.value
        self.assertIs(found, False)

    def _step6_if(self):
        """L'if/else del ramo nuovo dentro run()."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == '_recompose' \
                    and node.orelse:
                return node
        self.fail('ramo _recompose non trovato')

    def test_off_branch_is_the_original_call(self):
        node = self._step6_if()
        self.assertEqual(len(node.orelse), 1)
        call = ast.unparse(node.orelse[0])
        want = ("_translation_ok = self._translator.translate_file(input_path=str(subtitle_path), "
                "output_path=str(translated_srt_path), src_lang=source_language_639_1, "
                "tgt_lang=target_language_639_1, context=translation_context)")
        self.assertEqual(call, want)
        # il ramo nuovo si attiva solo con la chiave E il predicato del modulo
        self.assertIn("_recompose = bool(self.config.get('translation_recompose_sentences', False))", self.pipe)
        self.assertIn("recompose_enabled(\n", self.pipe.replace('\r\n', '\n'))
        self.assertIn("raise InterruptedError()", self.pipe)          # annullamento prima di ogni chiamata

    def test_activation_predicate(self):
        """Il predicato REALE che la pipeline chiama (solo con l'opzione accesa)."""
        ok = lambda *a: SR.recompose_enabled(*a)[0]
        self.assertTrue(ok('nllb_finetuned', 'en', 'it'))
        self.assertTrue(ok('nllb', 'en', 'it'))
        for m in ('llm', 'claude', 'openai', 'opensubtitles', 'aya'):
            self.assertFalse(ok(m, 'en', 'it'))
            self.assertIn('solo NLLB', SR.recompose_enabled(m, 'en', 'it')[1])
        self.assertFalse(ok('nllb', 'es', 'it'))
        self.assertFalse(ok('nllb', 'en', 'fr'))
        # con l'opzione spenta la pipeline non importa nemmeno il modulo:
        # l'import sta DENTRO `if _recompose:` (primo if dopo la lettura)
        node = next(n for n in ast.walk(self.tree) if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                    and n.test.id == '_recompose' and 'recompose_enabled' in ast.unparse(n))
        self.assertIn('from core.sentence_recompose import recompose_enabled', ast.unparse(node.body[0]))

    def test_inside_translation_try(self):
        """Il ramo sta nel try esistente, prima dell'except InterruptedError."""
        node = self._step6_if()
        for t in ast.walk(self.tree):
            if isinstance(t, ast.Try) and node in t.body:
                names = [ast.unparse(h.type) for h in t.handlers if h.type is not None]
                self.assertEqual(names[:2], ['InterruptedError', 'Exception'])
                return
        self.fail('ramo non dentro il try della traduzione')

    def test_compiles(self):
        import py_compile
        for p in ('core/pipeline.py', 'core/sentence_recompose.py', 'utils/config.py'):
            py_compile.compile(str(ROOT / p), doraise=True)

    def test_core_module_stdlib_only(self):
        tree = ast.parse(CORE_PATH.read_text(encoding='utf-8'))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split('.')[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or '').split('.')[0])
        self.assertLessEqual(mods, {'__future__', 'copy', 're', 'pathlib', 'typing'})


if __name__ == '__main__':
    unittest.main()
