import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import _common

SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import sandbox
    work, real = Path(sys.argv[3]), Path(sys.argv[4])
    cfg = sandbox.activate(work, real_config=real)
    import utils.config as uc
    out = {}
    out['file'] = str(uc.get_config().CONFIG_FILE)
    out['same_instance'] = uc.get_config() is cfg
    out['profile'] = cfg.get('transcription_profile')
    out['kept_user_key'] = cfg.get('user_only_key')
    cfg.set('diarization_num_speakers', 7)
    cfg.save()
    out['set_in_memory'] = cfg.get('diarization_num_speakers')
    out['set_calls'] = sandbox.set_calls()
    real.write_text(real.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    try:
        sandbox.check_real_config()
        out['detects_change'] = False
    except sandbox.SandboxError:
        out['detects_change'] = True
    print(json.dumps(out))
''')

SCRIPT_TOO_LATE = textwrap.dedent(r'''
    import sys
    from pathlib import Path
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import utils.config as uc
    uc.Config.CONFIG_DIR = Path(sys.argv[3]) / 'pre'
    uc.Config.CONFIG_FILE = uc.Config.CONFIG_DIR / 'config.json'
    uc.get_config()
    import sandbox
    try:
        sandbox.activate(Path(sys.argv[3]), real_config=Path(sys.argv[4]))
        print('NO_ERROR')
    except sandbox.SandboxError:
        print('REFUSED')
''')


class TestSandbox(unittest.TestCase):
    def _run(self, script):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            real = td / 'real' / 'config.json'
            real.parent.mkdir()
            original = {'transcription_profile': 'balanced', 'user_only_key': 42}
            real.write_text(json.dumps(original), encoding='utf-8')
            sp = td / 's.py'
            sp.write_text(script, encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8', CUDA_VISIBLE_DEVICES='-1')
            r = subprocess.run([sys.executable, str(sp), str(_common.BENCH), str(_common.ROOT),
                                str(td / 'work'), str(real)], capture_output=True, text=True,
                               encoding='utf-8', env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            copied = json.loads((td / 'work' / '_cfg' / 'config.json').read_text(encoding='utf-8')) \
                if (td / 'work' / '_cfg' / 'config.json').exists() else None
            return r.stdout.strip().splitlines()[-1], copied, original

    def test_redirect_and_no_write(self):
        line, copied, original = self._run(SCRIPT)
        out = json.loads(line)
        self.assertTrue(out['file'].endswith(str(Path('work') / '_cfg' / 'config.json')))
        self.assertTrue(out['same_instance'])
        self.assertEqual(out['profile'], 'maximum')
        self.assertEqual(out['kept_user_key'], 42)
        self.assertEqual(out['set_in_memory'], 7)
        self.assertEqual(out['set_calls'], [['diarization_num_speakers', 7]])
        self.assertTrue(out['detects_change'])
        self.assertEqual(copied, original, "la copia in _cfg non deve essere riscritta (save no-op)")

    def test_refuses_if_config_already_loaded(self):
        line, _, _ = self._run(SCRIPT_TOO_LATE)
        self.assertEqual(line, 'REFUSED')


if __name__ == '__main__':
    unittest.main()
