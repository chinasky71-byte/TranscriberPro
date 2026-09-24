"""Verifica STATICA (ast, niente import di core/translator.py ne' torch) che
le firme e i dettagli di produzione su cui il banco si appoggia esistano
davvero nel sorgente."""
import ast
import re
import unittest

import _common
from split_eval import split_metrics, srtio, translate_arms

CORE = _common.ROOT / 'core'


def tree(rel):
    return ast.parse((CORE / rel).read_text(encoding='utf-8'))


def cls(t, name):
    return next(n for n in ast.walk(t) if isinstance(n, ast.ClassDef) and n.name == name)


def fn(scope, name):
    body = scope.body if hasattr(scope, 'body') else []
    return next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == name)


def args(f):
    return [a.arg for a in f.args.args]


class TestTranslatorSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls_):
        cls_.src = (CORE / 'translator.py').read_text(encoding='utf-8')
        cls_.t = ast.parse(cls_.src)

    def test_get_translator(self):
        f = fn(self.t, 'get_translator')
        self.assertEqual(args(f), ['model_type', 'context', 'use_aya', 'glossary'])
        # ripiego silenzioso su NLLBTranslator se l'FT fallisce: il banco lo intercetta
        self.assertIn("return NLLBFineTunedTranslator(context=context, glossary=glossary)", self.src)
        bases = [b.id for b in cls(self.t, 'NLLBFineTunedTranslator').bases]
        self.assertEqual(bases, ['NLLBTranslator'])
        self.assertEqual(set(translate_arms.EXPECTED_CLASS.values()),
                         {'NLLBFineTunedTranslator', 'LLMSubtitleTranslator'})

    def test_translate_file_signatures(self):
        for c in ('NLLBTranslator', 'LLMSubtitleTranslator'):
            self.assertEqual(args(fn(cls(self.t, c), 'translate_file')),
                             ['self', 'input_path', 'output_path', 'src_lang', 'tgt_lang', 'context', 'glossary'])
        for c in ('NLLBTranslator', 'LLMSubtitleTranslator'):
            fn(cls(self.t, c), 'cleanup')
        fn(cls(self.t, 'BaseTranslator'), 'set_log_callback')

    def test_srt_pattern_is_a_literal_copy(self):
        f = fn(cls(self.t, 'BaseTranslator'), '_parse_srt')
        lits = [n.value for n in ast.walk(f) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and '-->' in n.value]
        self.assertEqual(lits, [srtio.TRANSLATOR_SRT_PATTERN])
        self.assertIn('re.finditer(pattern, content, re.MULTILINE)', self.src)

    def test_audit_line_and_norm(self):
        self.assertIn('Traduzione completata | {parts} | ', self.src)
        self.assertIn('inglese residuo: {len(flagged)}', self.src)
        self.assertIn("_AUDIT_NORM_RE = re.compile(r'[^0-9a-zàèéìòóù]')", self.src)
        self.assertIn("r'[^0-9a-zàèéìòóù]'", (_common.PKG / 'split_metrics.py').read_text(encoding='utf-8'))
        lines = ["  Traduzione completata | riparati L1: 2 | recuperati L2: 1 | serbatoio L3: 0 | "
                 "identici confermati: 3 | inglese residuo: 4"]
        self.assertEqual(translate_arms.parse_audit(lines),
                         {'riparati L1': 2, 'recuperati L2': 1, 'serbatoio L3': 0, 'identici confermati': 3,
                          'inglese residuo': 4})

    def test_polish_uses_process_with_order(self):
        self.assertIn('postprocess.process(\n                {i: t for i, t in enumerate(texts)},\n'
                      '                order=list(range(len(texts))),', self.src)


class TestOtherSources(unittest.TestCase):
    def test_formatter(self):
        c = cls(tree('subtitle_formatter.py'), 'SubtitleFormatter')
        self.assertIn('readability', args(fn(c, '__init__')))
        self.assertEqual(args(fn(c, 'format_srt')), ['self', 'segments'])

    def test_cleaner(self):
        c = cls(tree('subtitle_cleaner.py'), 'SubtitleCleaner')
        self.assertEqual(args(fn(c, 'clean_file')), ['input_path', 'output_path'])

    def test_postprocess(self):
        t = tree('llm_subtitle_translator/postprocess.py')
        self.assertEqual(args(fn(t, 'process'))[:2], ['blocks', 'order'])
        imports = {a.name for n in ast.walk(t) if isinstance(n, (ast.Import, ast.ImportFrom))
                   for a in n.names}
        self.assertFalse(imports & {'torch', 'transformers'})

    def test_prompt_builder_budget(self):
        src = (CORE / 'llm_subtitle_translator' / 'prompt_builder.py').read_text(encoding='utf-8')
        self.assertIn('return max(12, min(int(self.duration * CPS_MAX), CPL_MAX * 2))', src)
        self.assertRegex(src, r'(?m)^CPL_MAX = 42$')
        self.assertRegex(src, r'(?m)^CPS_MAX = 17\.0$')
        tsrc = (CORE / 'llm_subtitle_translator' / 'translator.py').read_text(encoding='utf-8')
        self.assertIn('builder(unit.text, budget=unit.budget)', tsrc)

    def test_pipeline_call(self):
        src = (CORE / 'pipeline.py').read_text(encoding='utf-8')
        self.assertIn('src_lang=source_language_639_1', src)
        self.assertIn('input_path=str(subtitle_path)', src)
        self.assertIn('SubtitleCleaner.clean_file(subtitle_path, cleaned_srt_path)', src)
        self.assertTrue(re.search(r"readability=bool\(self\.config\.get\(\s*'subtitle_readability_enabled', True\)\)",
                                  src))


if __name__ == '__main__':
    unittest.main()
