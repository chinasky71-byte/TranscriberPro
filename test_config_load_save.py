"""Test CPU: Config() con un config.json a cui mancano chiavi di default le salva SUBITO, senza errori ne' attese
(regressione: il salvataggio atomico veniva chiamato con il file ancora aperto -> WinError 5 dopo 2,4 s di tentativi)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.config import Config  # noqa: E402


class TestConfigLoadSave(unittest.TestCase):
    def test_missing_defaults_are_saved_on_load(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            f = d / 'config.json'
            f.write_text(json.dumps({'language': 'it'}), encoding='utf-8')
            old = (Config.CONFIG_DIR, Config.CONFIG_FILE)
            Config.CONFIG_DIR, Config.CONFIG_FILE = d, f
            try:
                t = time.time()
                c = Config()
                dt = time.time() - t
            finally:
                Config.CONFIG_DIR, Config.CONFIG_FILE = old
            self.assertLess(dt, 1.5, 'il salvataggio non deve consumare i tentativi di retry')
            saved = json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(saved['language'], 'it')
            self.assertIn('whisper_split_sentence_langs', saved)
            self.assertEqual(len(saved), len(c.settings))
            self.assertEqual([p.name for p in d.iterdir()], ['config.json'])   # nessun .tmp residuo


if __name__ == '__main__':
    unittest.main()
