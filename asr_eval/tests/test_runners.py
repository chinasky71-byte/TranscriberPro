import json
import tempfile
import threading
import unittest
from pathlib import Path

import _common  # noqa: F401
import runners as RN


class FakeEngine:
    """Imita l'interfaccia TranscriptionEngine (last_segments, _last_segments,
    transcribe_chunks(audio_chunks, output_path, language), log_callback)."""

    def __init__(self, log_callback, behaviour):
        self.log_callback = log_callback
        self._last_segments = [{'start': 0, 'end': 1, 'text': 'STALE', 'words': []}]
        self.behaviour = behaviour
        self.calls = []

    @property
    def last_segments(self):
        return self._last_segments

    def load(self):
        pass

    def log(self, m):
        self.log_callback(m)

    def transcribe_chunks(self, audio_chunks, output_path, language=None):
        self.calls.append((list(audio_chunks), output_path, language))
        return self.behaviour(self, audio_chunks)


def ok_behaviour(eng, chunks):
    segs = []
    for p, s, e in chunks:
        segs.append({'start': s + 0.1, 'end': s + 1.0, 'text': f"hello {Path(p).stem}",
                     'words': [{'start': s + 0.1, 'end': s + 0.5, 'word': ' hello'},
                               {'start': s + 0.5, 'end': s + 1.0, 'word': f" {Path(p).stem}"}]})
    eng._last_segments = segs
    return True, 'en'


def whisper_swallowed_error(eng, chunks):
    eng.log("  ❌ Errore trascrizione: CUDA failed")
    return False, None


def empty_behaviour(eng, chunks):
    eng._last_segments = []
    return False, 'it'


def raise_behaviour(eng, chunks):
    raise RuntimeError("Qwen3: 5/6 chunk falliti — fallback")


def partial_behaviour(eng, chunks):
    ok_behaviour(eng, chunks)
    eng.log("  ⚠️ Completato con 1 chunks falliti su 3")
    return True, 'it'


class TestTranscribeWindow(unittest.TestCase):
    def run_b(self, b):
        log = RN.LogCapture()
        eng = FakeEngine(log, b)
        return RN.transcribe_window(eng, [('c1.wav', 0.0, 10.0)], 'en', log), eng

    def test_ok(self):
        r, eng = self.run_b(ok_behaviour)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['segments'][0]['text'], 'hello c1')
        self.assertEqual(eng.calls[0][2], 'en')

    def test_swallowed_error_is_failure_not_stale(self):
        r, _ = self.run_b(whisper_swallowed_error)
        self.assertEqual(r['status'], 'failed')
        self.assertEqual(r['segments'], [])

    def test_empty_is_ok(self):
        r, _ = self.run_b(empty_behaviour)
        self.assertEqual((r['status'], r['segments']), ('ok', []))

    def test_exception(self):
        r, _ = self.run_b(raise_behaviour)
        self.assertEqual(r['status'], 'failed')
        self.assertIn('RuntimeError', r['error'])

    def test_partial(self):
        r, _ = self.run_b(partial_behaviour)
        self.assertEqual((r['status'], r['n_failed_chunks']), ('partial', 1))


class TestCanaryGroup(unittest.TestCase):
    def test_redistribution(self):
        with tempfile.TemporaryDirectory() as td:
            log = RN.LogCapture()
            eng = FakeEngine(log, ok_behaviour)
            group = [('w0', [('a0.wav', 0.0, 20.0), ('a1.wav', 20.0, 40.0)], 150.0),
                     ('w1', [('b0.wav', 0.5, 25.0)], 140.0),
                     ('w2', [('c0.wav', 3.0, 20.0)], 150.0)]
            res = RN.canary_group(eng, group, Path(td) / 'g1', log)
            chunks, out_path, lang = eng.calls[0]
            self.assertEqual(lang, 'en')
            self.assertEqual(Path(out_path).parent, Path(td) / 'g1')
            self.assertEqual([c[1] for c in chunks], [0.0, 20.0, 10000.5, 20003.0])
            self.assertEqual([s['text'] for s in res['w0']['segments']], ['hello a0', 'hello a1'])
            self.assertEqual(res['w1']['segments'][0]['start'], 0.6)
            self.assertEqual(res['w1']['segments'][0]['words'][0]['start'], 0.6)
            self.assertEqual(res['w2']['segments'][0]['start'], 3.1)
            self.assertTrue(all(r['status'] == 'ok' for r in res.values()))
            self.assertAlmostEqual(sum(r['elapsed_s'] for r in res.values()),
                                   res['w0']['group_elapsed_s'], places=2)

    def test_group_failure_marks_all(self):
        with tempfile.TemporaryDirectory() as td:
            log = RN.LogCapture()
            eng = FakeEngine(log, raise_behaviour)
            res = RN.canary_group(eng, [('w0', [('a.wav', 0, 5)], 100.0), ('w1', [('b.wav', 0, 5)], 100.0)],
                                  Path(td), log)
            self.assertEqual({r['status'] for r in res.values()}, {'failed'})

    def test_empty_window_in_group(self):
        def b(eng, chunks):
            ok_behaviour(eng, chunks[:1])
            return True, 'en'
        with tempfile.TemporaryDirectory() as td:
            log = RN.LogCapture()
            res = RN.canary_group(FakeEngine(log, b), [('w0', [('a.wav', 0, 5)], 100.0),
                                                       ('w1', [('b.wav', 0, 5)], 100.0)], Path(td), log)
            self.assertEqual(res['w1']['segments'], [])
            self.assertEqual(res['w1']['status'], 'ok')


class TestIO(unittest.TestCase):
    def test_atomic_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'h' / 'x.json'
            fp = {'engine': 'qwen3', 'settings': {'a': 1}}
            RN.write_json_atomic(p, {'schema': RN.SCHEMA_HYP, 'status': 'ok', 'wav_sha': 'abc', 'fingerprint': fp})
            self.assertEqual(list(p.parent.glob('*.tmp')), [])
            self.assertTrue(RN.hyp_is_current(p, 'abc', fp))
            self.assertFalse(RN.hyp_is_current(p, 'abd', fp))
            self.assertFalse(RN.hyp_is_current(p, 'abc', {**fp, 'settings': {'a': 2}}))
            RN.write_json_atomic(p, {'schema': RN.SCHEMA_HYP, 'status': 'failed', 'wav_sha': 'abc', 'fingerprint': fp})
            self.assertFalse(RN.hyp_is_current(p, 'abc', fp))
            with self.assertRaises(ValueError):
                RN.write_json_atomic(p, {'x': float('nan')})
            self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['status'], 'failed')
            self.assertEqual(list(p.parent.glob('*.tmp')), [])

    def test_vram_monitor(self):
        vals = iter([1000, 1500, 3000, 2000, 1200] + [1200] * 1000)
        lock = threading.Lock()

        def reader():
            with lock:
                return float(next(vals))
        mon = RN.VramMonitor(interval=0.01, reader=reader).start()
        import time
        time.sleep(0.2)
        peak = mon.take_peak()
        mon.stop()
        self.assertEqual(mon.baseline, 1000)
        self.assertEqual(peak, 3000)

    def test_gpu_guard_parsing(self):
        orig = RN._nvsmi
        try:
            RN._nvsmi = lambda args, timeout=15: ("123, C:\\Windows\\explorer.exe\n"
                                                  "456, C:\\Python311\\pythonw.exe\n")
            reasons = RN.gpu_busy_reasons(own_pids=set())
            self.assertTrue(any('456' in r for r in reasons))
            self.assertFalse(any('explorer' in r for r in reasons))
            RN._nvsmi = lambda args, timeout=15: None
            self.assertTrue(RN.gpu_busy_reasons())
        finally:
            RN._nvsmi = orig


if __name__ == '__main__':
    unittest.main()
