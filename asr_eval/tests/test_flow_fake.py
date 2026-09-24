"""Flusso completo run -> score -> report -> gold con motori FINTI (nessun
modello, nessuna GPU): ripresa, errori, raggruppamento Canary, verdetto."""
import argparse
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import _common  # noqa: F401
import asr_bench as AB
import runners as RN
import sandbox

WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike".split()


class FakeCfg:
    def __init__(self):
        self.settings = dict(sandbox.BENCH_SETTINGS)

    def get(self, k, d=None):
        return self.settings.get(k, d)


REFS = {}
FAIL = set()


def _win_of(path):
    parts = Path(path).parts
    return parts[parts.index('win') + 1]


def make_engine(drop_every, name):
    class E:
        def __init__(self, log_callback=None):
            self.log_callback = log_callback
            self._last_segments = []
            self.batch_size_for_transcription = 2
            self.loaded = False

        @property
        def last_segments(self):
            return self._last_segments

        def load(self):
            self.loaded = True

        def unload(self):
            pass

        def transcribe_chunks(self, audio_chunks, output_path, language=None):
            segs = []
            for p, s, e in audio_chunks:
                wid = _win_of(p)
                if (name, wid) in FAIL:
                    raise RuntimeError(f"guasto finto su {wid}")
                arm_raw = 'raw' in Path(p).parts or Path(p).name == 'raw.wav'
                for c in REFS[wid]:
                    ws = c['text'].split()
                    k = drop_every - (2 if arm_raw else 0)
                    ws = [w for i, w in enumerate(ws, 1) if not (k and i % k == 0)]
                    if ws:
                        segs.append({'start': s + c['s'], 'end': s + c['e'], 'text': ' '.join(ws), 'words': []})
            self._last_segments = segs
            return bool(segs), language
    return E


def build_work(work: Path):
    import random
    rng = random.Random(0)
    rows = []
    films = [('en', f"film{i}", 'main') for i in range(9)] + [('en', f"sec{i}", 'secondary') for i in range(3)] \
        + [('it', 'itfilm0', 'main'), ('it', 'itfilm1', 'main')]
    for lang, film, grp in films:
        for idx in range(1, 5):
            wid = f"{lang}__{film}__{idx:02d}"
            cues = []
            t = 1.0
            for _ in range(20):
                text = ' '.join(rng.choice(WORDS) for _ in range(8))
                cues.append({'s': t, 'e': t + 3, 'text': text, 'music': False, 'sound_only': False, 'italic': False})
                t += 4
            REFS[wid] = cues
            d = work / 'win' / wid
            d.mkdir(parents=True)
            rows.append({'win_id': wid, 'film': film, 'lang': lang, 'role': 'test', 'tag': f"{idx:02d}",
                         'idx': idx, 't0': 0, 't1': 90, 'dur': 90.0, 'group': grp,
                         'origin': 'doppiato' if film == 'itfilm0' else ('nato_ita' if lang == 'it' else None),
                         'sha': {'raw': f"r{wid}", 'vocals': f"v{wid}"},
                         'chunks': {'t20_m10_x25': [[0.0, 90.0]]}, 'names': ['alpha'], 'cues': cues})
    AB.write_jsonl_atomic(work / 'windows.jsonl', rows)
    RN.write_json_atomic(work / 'films.json', {})


class TestFlow(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.work = Path(self.td.name) / 'work'
        build_work(self.work)
        self.saved = {k: sys.modules.get(k) for k in
                      ('core', 'core.engines', 'core.engines.faster_whisper_engine',
                       'core.engines.qwen3_asr_engine', 'core.engines.canary_engine')}
        fake = {'core': types.ModuleType('core'), 'core.engines': types.ModuleType('core.engines')}
        m = types.ModuleType('fw'); m.FasterWhisperEngine = make_engine(0, 'whisper')
        fake['core.engines.faster_whisper_engine'] = m
        m = types.ModuleType('q3'); m.Qwen3AsrEngine = make_engine(5, 'qwen3')
        fake['core.engines.qwen3_asr_engine'] = m
        m = types.ModuleType('ca'); m.CanaryEngine = make_engine(6, 'canary')
        fake['core.engines.canary_engine'] = m
        sys.modules.update(fake)
        self.orig = (AB.require_gpu_free, sandbox.activate, RN.VramMonitor)
        AB.require_gpu_free = lambda: None
        sandbox.activate = lambda work, **kw: FakeCfg()

        class FakeMon:
            baseline = 1000.0

            def start(self):
                return self

            def take_peak(self):
                return 2345.0

            def stop(self):
                pass
        RN.VramMonitor = FakeMon

    def tearDown(self):
        AB.require_gpu_free, sandbox.activate, RN.VramMonitor = self.orig
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        FAIL.clear()
        self.td.cleanup()

    def args(self, **kw):
        base = dict(work=self.work, lang=None, limit=0, verbose=False, canary_group=5)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_full_flow(self):
        FAIL.add(('qwen3', 'en__film3__02'))
        rc = AB.cmd_run(self.args(engine='whisper', arm='vocals'))
        self.assertEqual(rc, 0)
        hyp = self.work / 'hyp' / 'whisper__vocals'
        self.assertEqual(len(list(hyp.glob('*.json'))), 56)
        rc = AB.cmd_run(self.args(engine='qwen3', arm='vocals'))
        self.assertEqual(rc, 6)
        h = json.loads((self.work / 'hyp' / 'qwen3__vocals' / 'en__film3__02.json').read_text(encoding='utf-8'))
        self.assertEqual(h['status'], 'failed')
        FAIL.clear()
        AB.cmd_run(self.args(engine='qwen3', arm='vocals'))
        with open(self.work / 'runs.csv', encoding='utf-8') as f:
            last = list(AB.csv.DictReader(f))[-1]
        self.assertEqual((last['n_done'], last['n_skipped']), ('1', '55'))
        self.assertEqual(AB.cmd_run(self.args(engine='canary', arm='vocals')), 0)
        self.assertEqual(len(list((self.work / 'hyp' / 'canary__vocals').glob('*.json'))), 48)
        self.assertEqual(len(list((self.work / '_canary' / 'vocals').iterdir())), 10)
        for eng in ('whisper', 'qwen3', 'canary'):
            AB.cmd_run(self.args(engine=eng, arm='raw'))
        self.assertEqual(len(list((self.work / 'hyp' / 'canary__raw').glob('*.json'))), 24)
        self.assertEqual(AB.cmd_run(self.args(engine='w2v', arm='vocals')), 5)

        rows = [r for r in AB.read_jsonl(self.work / 'windows.jsonl')]
        rows[0]['sha']['vocals'] = 'CHANGED'
        AB.write_jsonl_atomic(self.work / 'windows.jsonl', rows)
        AB.cmd_run(self.args(engine='whisper', arm='vocals'))
        with open(self.work / 'runs.csv', encoding='utf-8') as f:
            last = list(AB.csv.DictReader(f))[-1]
        self.assertEqual(last['n_done'], '1')

        AB.cmd_score(self.args())
        scores = AB.load_scores(self.work)
        w = [r for r in scores if r['engine'] == 'whisper' and r['arm'] == 'vocals']
        self.assertTrue(all(float(r['werc']) == 0.0 for r in w))
        c = [r for r in scores if r['engine'] == 'canary' and r['arm'] == 'vocals']
        stale = [r['win_id'] for r in c if r['status'] == 'stale']
        self.assertEqual(stale, ['en__film0__01'])
        self.assertTrue(all(float(r['werc']) > 0.05 for r in c if r['status'] == 'ok'))
        report = AB.build_report(self.work)
        self.assertIn('whisper vs canary: ', report)
        self.assertIn('LINGUA IT', report)
        self.assertIn('SOLO INDICATIVO', report)
        self.assertIn('Demucs: vocals contro raw', report)
        self.assertIn("oro: non ancora valutato", report)

        AB.cmd_gold_make(argparse.Namespace(work=self.work, per_lang=10, force=False))
        idx = json.loads((self.work / 'gold' / 'index.json').read_text(encoding='utf-8'))
        self.assertEqual(sum(1 for v in idx.values() if v['lang'] == 'en'), 10)
        self.assertEqual(len({k.split('__')[1] for k, v in idx.items() if v['lang'] == 'en'}), 10)
        first = next(iter(idx.values()))
        p = Path(first['path'])
        p.write_text(p.read_text(encoding='utf-8').replace('alpha', 'zulu'), encoding='utf-8')
        AB.cmd_gold_score(argparse.Namespace(work=self.work))
        verdict = json.loads((self.work / 'gold' / 'gold_verdict.json').read_text(encoding='utf-8'))
        self.assertEqual(verdict['en']['rank_gold'][0], 'whisper')
        self.assertTrue(verdict['en']['agree'])
        self.assertEqual(verdict['en']['n_untouched'], 9 if first['lang'] == 'en' else 10)
        report = AB.build_report(self.work)
        self.assertIn('-> CONCORDA', report)

    def test_rankings_agree(self):
        self.assertTrue(AB.rankings_agree({'a': 0.10, 'b': 0.20}, {'a': 0.12, 'b': 0.25}))
        self.assertFalse(AB.rankings_agree({'a': 0.10, 'b': 0.20}, {'a': 0.25, 'b': 0.12}))
        self.assertTrue(AB.rankings_agree({'a': 0.100, 'b': 0.101}, {'a': 0.25, 'b': 0.12}))

    def test_chunk_profile(self):
        cfg = FakeCfg()
        self.assertEqual(AB.chunk_profile('qwen3', cfg)[0], 't20_m10_x25')
        cfg.settings.update(asr_chunk_target_duration=60, asr_chunk_min_duration=20, asr_chunk_max_duration=120)
        self.assertEqual(AB.chunk_profile('canary', cfg), ('t28_m14_x35', (28.0, 14.0, 35.0)))
        self.assertEqual(AB.chunk_profile('qwen3', cfg)[0], 't60_m20_x120')
        cfg.settings.update(asr_chunk_min_duration=70)
        self.assertEqual(AB.chunk_profile('qwen3', cfg)[0], 't20_m10_x25')


if __name__ == '__main__':
    unittest.main()
