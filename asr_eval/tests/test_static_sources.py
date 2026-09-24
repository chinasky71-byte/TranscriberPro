"""Verifica statica (ast, senza importare core/* ne' torch) che firme e
attributi usati dal banco esistano davvero nel sorgente di produzione."""
import ast
import inspect
import unittest
from pathlib import Path

import _common

CORE = _common.ROOT / 'core'
SITE = _common.ROOT / 'venv' / 'Lib' / 'site-packages'


def tree(path: Path):
    return ast.parse(path.read_text(encoding='utf-8'))


def cls(t, name):
    return next(n for n in ast.walk(t) if isinstance(n, ast.ClassDef) and n.name == name)


def method(c, name):
    return next(n for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name)


def args_of(fn):
    return [a.arg for a in fn.args.args]


def assigned_attrs(c):
    out = set()
    for n in ast.walk(c):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
                    out.add(t.attr)
    return out


class TestEngines(unittest.TestCase):
    def test_base(self):
        c = cls(tree(CORE / 'engines' / 'base_engine.py'), 'TranscriptionEngine')
        self.assertIn('_last_segments', assigned_attrs(c))
        prop = method(c, 'last_segments')
        self.assertTrue(any(isinstance(d, ast.Name) and d.id == 'property' for d in prop.decorator_list))
        self.assertEqual(args_of(method(c, 'transcribe_chunks')), ['self', 'audio_chunks', 'output_path', 'language'])

    def test_whisper(self):
        src = (CORE / 'engines' / 'faster_whisper_engine.py').read_text(encoding='utf-8')
        c = cls(ast.parse(src), 'FasterWhisperEngine')
        self.assertEqual(args_of(method(c, '__init__')), ['self', 'log_callback'])
        self.assertEqual(args_of(method(c, 'load')), ['self'])
        self.assertEqual(args_of(method(c, 'transcribe_chunks')), ['self', 'audio_chunks', 'output_path', 'language'])
        self.assertIn('batch_size_for_transcription', assigned_attrs(c))
        self.assertIn('faster_whisper_model', assigned_attrs(c))
        self.assertIn('len(audio_chunks) == 1 and self.batch_size_for_transcription is not None', src)
        self.assertIn('❌ Errore trascrizione', src)
        self.assertIn("if output_path and all_segments", src)

    def test_qwen3(self):
        src = (CORE / 'engines' / 'qwen3_asr_engine.py').read_text(encoding='utf-8')
        c = cls(ast.parse(src), 'Qwen3AsrEngine')
        self.assertEqual(args_of(method(c, 'transcribe_chunks')), ['self', 'audio_chunks', 'output_path', 'language'])
        self.assertIn("Completato con {failed_chunks} chunks falliti", src)
        self.assertIn("failed_chunks > total_chunks * 0.5", src)
        self.assertIn("if output_path and all_segments", src)
        for m in ('_attach_punct_words', '_words_to_segments'):
            method(c, m)

    def test_canary(self):
        src = (CORE / 'engines' / 'canary_engine.py').read_text(encoding='utf-8')
        c = cls(ast.parse(src), 'CanaryEngine')
        self.assertEqual(args_of(method(c, 'transcribe_chunks')), ['self', 'audio_chunks', 'output_path', 'language'])
        self.assertIn('temp_dir = Path(output_path).parent', src)
        self.assertIn("'batch_size': self._batch_size()", src)
        self.assertIn("Aligner fallito su {failed_chunks} chunk", src)
        self.assertIn('all_segments.extend(Qwen3AsrEngine._words_to_segments(words))', src)

    def test_canary_cli_does_not_read_config(self):
        t = tree(CORE / 'engines' / 'canary_cli.py')
        mods = {(n.module or '') for n in ast.walk(t) if isinstance(n, ast.ImportFrom)}
        mods |= {a.name for n in ast.walk(t) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse(any(m.startswith(('utils', 'core')) for m in mods), mods)


class TestAudio(unittest.TestCase):
    def test_audio_processor(self):
        src = (CORE / 'audio_processor.py').read_text(encoding='utf-8')
        t = ast.parse(src)
        c = cls(t, 'AudioProcessor')
        self.assertEqual(args_of(method(c, 'separate_vocals')), ['self', 'audio_path'])
        self.assertEqual(args_of(method(c, 'chunk_audio_intelligent')), ['self', 'audio_path'])
        self.assertEqual(args_of(method(c, '_create_physical_chunks')),
                         ['self', 'audio_path', 'chunk_times', 'output_dir'])
        self.assertEqual(args_of(method(c, 'set_log_callback')), ['self', 'callback'])
        method(c, 'cleanup_model')
        attrs = assigned_attrs(c)
        for a in ('CHUNK_TARGET_DURATION', 'CHUNK_MIN_DURATION', 'CHUNK_MAX_DURATION'):
            self.assertIn(a, attrs)
        self.assertIn('f"{audio_path.stem}_vocals.wav"', src)
        self.assertIn('chunk_filename = f"chunk_{chunk_num:04d}.wav"', src)
        cap = next(n for n in t.body if isinstance(n, ast.Assign)
                   and any(isinstance(x, ast.Name) and x.id == 'ENGINE_CHUNK_CAP_S' for x in n.targets))
        import asr_bench
        self.assertEqual(ast.literal_eval(cap.value), asr_bench.DEFAULT_ENGINE_CHUNK_CAP_S)
        self.assertIn('effective_target = min(self.CHUNK_TARGET_DURATION, effective_max * 0.8)', src)
        self.assertIn('effective_min = min(self.CHUNK_MIN_DURATION, effective_target * 0.5)', src)

    def test_extract_params(self):
        src = (CORE / 'audio_track_selector.py').read_text(encoding='utf-8')
        for tok in ("'-acodec', 'pcm_s16le'", "'-ar', '16000'", "'-ac', '1'", "'-vn'"):
            self.assertIn(tok, src)

    def test_demucs_defaults(self):
        t = tree(SITE / 'demucs' / 'apply.py')
        fn = next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == 'apply_model')
        names = [a.arg for a in fn.args.args]
        defaults = dict(zip(names[-len(fn.args.defaults):], [ast.literal_eval(d) if not isinstance(d, ast.Name)
                                                              else d.id for d in fn.args.defaults]))
        self.assertEqual((defaults['split'], defaults['overlap']), (True, 0.25))


class TestConfigAndLibs(unittest.TestCase):
    def test_config_class(self):
        t = tree(_common.ROOT / 'utils' / 'config.py')
        c = cls(t, 'Config')
        cls_attrs = {x.id for n in c.body if isinstance(n, ast.Assign) for x in n.targets if isinstance(x, ast.Name)}
        self.assertTrue({'CONFIG_DIR', 'CONFIG_FILE', 'DEFAULTS'} <= cls_attrs)
        for m in ('save', 'set', 'get', 'load'):
            method(c, m)
        src = (_common.ROOT / 'utils' / 'config.py').read_text(encoding='utf-8')
        self.assertIn('_config_instance = None', src)
        self.assertIn('self.save()', inspect.cleandoc(ast.get_source_segment(src, method(c, 'load'))))

    def test_faster_whisper_api(self):
        t = tree(SITE / 'faster_whisper' / 'transcribe.py')
        wm = cls(t, 'WhisperModel')
        self.assertEqual(args_of(method(wm, 'detect_language'))[:2], ['self', 'audio'])
        bip = cls(t, 'BatchedInferencePipeline')
        self.assertIn('model', assigned_attrs(bip))


if __name__ == '__main__':
    unittest.main()
