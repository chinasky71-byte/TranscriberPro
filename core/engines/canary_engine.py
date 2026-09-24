"""
Canary Engine - NVIDIA Canary-Qwen-2.5B via subprocess NeMo (solo inglese)
File: core/engines/canary_engine.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Canary-Qwen-2.5B eseguito in SUBPROCESS con venv dedicato (venv_canary):
   NeMo non è installabile nel venv di produzione senza rompere
   setuptools/lightning/protobuf → isolamento totale, VRAM restituita al 100%
   alla chiusura del processo (stesso pattern del Gender Corrector)
✅ Plugin opzionale a rilevamento runtime: assenza di venv_canary/NeMo NON
   rompe alcun import (is_available() = capability flag)
✅ SALM restituisce SOLO testo: i timestamp vengono generati col
   Qwen3-ForcedAligner-0.6B in-process (l'inglese è tra le sue 11 lingue),
   caricato DOPO l'uscita del subprocess (un solo modello GPU per volta)
✅ Richiede chunk classici (Canary è addestrato su audio ≤40s; i chunk della
   pipeline sono 10-25s) — il router pianifica il chunking di conseguenza
"""
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import torch

from core.engines.base_engine import TranscriptionEngine
from utils.logger import setup_logger
from utils.config import get_config
from utils.cache_bootstrap import HF_CACHE

logger = setup_logger()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def find_canary_python() -> Optional[Path]:
    """Trova il python del venv Canary: config 'canary_python_path' se
    impostata, altrimenti <project>/venv_canary/Scripts/python.exe."""
    try:
        cfg_path = get_config().get('canary_python_path', '') or ''
    except Exception:
        cfg_path = ''
    candidates = []
    if cfg_path:
        candidates.append(Path(cfg_path))
    candidates.append(PROJECT_ROOT / 'venv_canary' / 'Scripts' / 'python.exe')
    for c in candidates:
        if c.exists():
            return c
    return None


class CanaryEngine(TranscriptionEngine):
    """
    Engine Canary-Qwen-2.5B (NeMo SALM), SOLO trascrizioni dall'inglese.
    Testo dal subprocess venv_canary + timestamp dal Qwen3-ForcedAligner.
    """

    # Valore usato quando 'punctuation_restore_mode' == 'auto' (v. config.py).
    PUNCT_AUTO_MODE = 'missing'

    name = "canary"

    def __init__(self, log_callback: Optional[Callable] = None):
        super().__init__(log_callback=log_callback)
        self.config = get_config()
        self._proc: Optional[subprocess.Popen] = None
        self._aligner = None
        self._punct_restorer = None  # lazy, v. _maybe_restore_punctuation

    # ------------------------------------------------------------------
    # Capability detection
    # ------------------------------------------------------------------
    @classmethod
    def is_available(cls) -> bool:
        # Serve il venv Canary (subprocess) E qwen-asr (aligner per i timestamp)
        try:
            if find_canary_python() is None:
                return False
            from qwen_asr import Qwen3ForcedAligner  # noqa: F401
            return True
        except Exception:
            return False

    @classmethod
    def supports_language(cls, lang_639_1: Optional[str]) -> bool:
        return lang_639_1 == 'en'

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load(self):
        """Verifica prerequisiti (il modello vive nel subprocess: nessun
        caricamento in-process qui)."""
        if find_canary_python() is None:
            raise RuntimeError(
                "venv_canary non trovato (atteso in venv_canary/Scripts/python.exe "
                "o config 'canary_python_path')")

    def unload(self):
        """Termina l'eventuale subprocess e scarica l'aligner."""
        try:
            if self._proc is not None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None
            if self._aligner is not None:
                del self._aligner
                self._aligner = None
            if self._punct_restorer is not None:
                self._punct_restorer.unload()
                self._punct_restorer = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            logger.info("✅ CanaryEngine unload completato")
        except Exception as e:
            logger.error(f"Errore durante unload Canary: {e}")

    def cancel(self):
        """Cancella anche il subprocess attivo."""
        super().cancel()
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def _batch_size(self) -> int:
        """Chunk per chiamata a generate() nel subprocess. La chiave non ha
        un campo nelle Opzioni (si tocca solo a mano in config.json): un
        valore rovinato deve degradare a 1, non far fallire la trascrizione."""
        try:
            return max(1, int(self.config.get('canary_batch_size', 8) or 8))
        except (TypeError, ValueError):
            logger.warning("canary_batch_size non valido: uso 1 (nessun batching)")
            return 1

    def _maybe_restore_punctuation(self, words: List[dict], text: str,
                                    language: str, chunk_num: int) -> List[dict]:
        """Applica il ripristino punteggiatura (v. piano_fix_pipeline_
        trascrizione punto D) se il trigger di config lo richiede. 'off' =
        comportamento storico, nessun import né chiamata. Stessa logica di
        Qwen3AsrEngine._maybe_restore_punctuation (duplicata: le due classi
        non condividono un'istanza da cui riusare lo stato lazy)."""
        mode = self.config.get('punctuation_restore_mode', 'auto')
        if mode == 'auto':
            mode = self.PUNCT_AUTO_MODE
        if mode == 'off':
            return words

        from core.punctuation_restorer import PunctuationRestorer
        if language not in PunctuationRestorer.SUPPORTED_LANGS:
            return words  # lingua fuori dal modello: nessun log fuorviante

        min_density = float(self.config.get('punctuation_min_density', 0.0))
        trigger = (mode == 'all') or (
            mode == 'missing' and PunctuationRestorer.needs_restoration(text, min_density))
        if not trigger:
            return words

        if self._punct_restorer is None:
            self._punct_restorer = PunctuationRestorer(
                model_id=self.config.get('punctuation_model_id',
                                          'oliverguhr/fullstop-punctuation-multilang-large'),
                device=self.config.get('punctuation_device', 'cpu'),
                log_callback=self.log,
            )
        self.log(f"  ✍️ Ripristino punteggiatura chunk {chunk_num}...")
        return self._punct_restorer.restore_words(words, language)

    # ------------------------------------------------------------------
    # Trascrizione
    # ------------------------------------------------------------------
    def transcribe_chunks(
        self,
        audio_chunks: List[tuple],
        output_path: str,
        language: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Trascrive i chunk (inglese) con Canary nel subprocess, poi allinea
        i testi col ForcedAligner per i timestamp word-level.
        """
        from core.transcriber import save_srt_file

        if language not in (None, 'en', 'eng'):
            raise RuntimeError(f"CanaryEngine supporta solo l'inglese (richiesto: {language})")

        canary_python = find_canary_python()
        if canary_python is None:
            raise RuntimeError("venv_canary non trovato")

        total_chunks = len(audio_chunks)
        self.log(f"  📊 Trascrizione di {total_chunks} chunks audio (Canary subprocess)...")

        # ── FASE 1: testo dal subprocess Canary (VRAM dedicata al SALM) ──
        temp_dir = Path(output_path).parent
        args_path = temp_dir / "canary_args.json"
        out_path = temp_dir / "canary_out.json"
        args_payload = {
            'model_id': self.config.get('canary_model_id', 'nvidia/canary-qwen-2.5b'),
            'hf_cache': str(HF_CACHE),
            'output_json': str(out_path),
            'batch_size': self._batch_size(),
            'chunks': [
                {'path': str(c[0]), 'start': float(c[1]),
                 'end': float(c[2]) if len(c) > 2 else float(c[1])}
                for c in audio_chunks
            ],
        }
        args_path.write_text(json.dumps(args_payload, ensure_ascii=False), encoding='utf-8')

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        cli_path = Path(__file__).resolve().parent / 'canary_cli.py'
        t0 = time.time()
        self.log("  🚀 Avvio subprocess Canary (venv dedicato)...")
        try:
            # stderr separato: il rumore NeMo/lightning va solo nel file di log
            proc = subprocess.Popen(
                [str(canary_python), str(cli_path), str(args_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
                env=env,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
        except Exception as e:
            raise RuntimeError(f"Spawn subprocess Canary fallito: {e}")

        self._proc = proc

        import threading

        def _drain_stderr(stream):
            try:
                for eline in stream:
                    eline = eline.rstrip()
                    if eline:
                        logger.info(f"[canary-stderr] {eline}")
            except Exception:
                pass

        threading.Thread(target=_drain_stderr, args=(proc.stderr,), daemon=True).start()

        last_pct = -1
        try:
            for line in proc.stdout:
                if self._cancelled:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                line = line.rstrip()
                if not line:
                    continue
                if line.startswith("PROGRESS "):
                    try:
                        done, tot = line.split()[1].split('/')
                        pct = int((int(done) / max(int(tot), 1)) * 100)
                        if pct != last_pct:
                            bars = int(pct / 10)
                            bar = '█' * bars + '░' * (10 - bars)
                            self.log(f"  🎙️ Trascrizione: [{bar}] {pct:3d}% ({done}/{tot})")
                            last_pct = pct
                    except Exception:
                        pass
                elif line.startswith("LOAD_DONE"):
                    self.log(f"  ✅ Canary caricato nel subprocess ({line.split()[-1]})")
                elif line.startswith("ERRORE"):
                    self.log(f"  ❌ {line}")
            return_code = proc.wait()
        finally:
            self._proc = None

        if self._cancelled:
            return False, None
        if return_code != 0 or not out_path.exists():
            raise RuntimeError(f"Subprocess Canary fallito (exit code {return_code})")

        result = json.loads(out_path.read_text(encoding='utf-8'))
        if not result.get('ok'):
            raise RuntimeError(f"Canary CLI: {result.get('error', 'errore sconosciuto')}")

        texts = [c.get('text', '') for c in result.get('chunks', [])]
        # I testi si appaiano ai chunk per POSIZIONE (zip più sotto, che tronca
        # in silenzio): con il batching il numero di testi non è più garantito
        # dalla costruzione del loop: se non torna, ogni chunk successivo
        # prenderebbe i tempi di un altro senza che nulla se ne accorga.
        if len(texts) != total_chunks:
            raise RuntimeError(
                f"Canary ha restituito {len(texts)} testi per {total_chunks} chunk: "
                f"testi e tempi non sarebbero allineati")
        elapsed = time.time() - t0
        self.log(f"  ✅ Testi Canary ricevuti ({len(texts)} chunk, {elapsed:.0f}s)")

        # Cleanup file di scambio (best effort)
        for p in (args_path, out_path):
            try:
                p.unlink()
            except Exception:
                pass

        # ── FASE 2: timestamp col ForcedAligner (subprocess ormai chiuso) ──
        from qwen_asr import Qwen3ForcedAligner
        from core.engines.qwen3_asr_engine import Qwen3AsrEngine

        aligner_id = self.config.get('qwen3_aligner_model_id', 'Qwen/Qwen3-ForcedAligner-0.6B')
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

        t1 = time.time()
        self.log(f"  📦 Caricamento ForcedAligner per i timestamp...")
        self._aligner = Qwen3ForcedAligner.from_pretrained(
            aligner_id, dtype=dtype, device_map=device)
        self.log(f"  ✅ Aligner caricato in {time.time() - t1:.1f}s")

        all_segments = []
        failed_chunks = 0
        for i, (chunk, text) in enumerate(zip(audio_chunks, texts)):
            if self._cancelled:
                break
            text = (text or '').strip()
            if not text:
                continue
            chunk_path, start_time = str(chunk[0]), float(chunk[1])
            try:
                res = self._aligner.align(audio=chunk_path, text=text, language="English")
                # Riaggancio punteggiatura dal testo Canary alle parole allineate
                words = Qwen3AsrEngine._attach_punct_words(text, res[0], start_time, i + 1)
                if words:
                    words = self._maybe_restore_punctuation(words, text, 'en', i + 1)
                    all_segments.extend(Qwen3AsrEngine._words_to_segments(words))
                else:
                    all_segments.append({
                        'start': start_time,
                        'end': float(chunk[2]) if len(chunk) > 2 else start_time,
                        'text': text,
                    })
            except Exception as e:
                logger.error(f"❌ Aligner fallito sul chunk {i + 1}: {e}", exc_info=True)
                failed_chunks += 1
                # Ripiego: segmento unico sull'intervallo del chunk
                all_segments.append({
                    'start': start_time,
                    'end': float(chunk[2]) if len(chunk) > 2 else start_time,
                    'text': text,
                })

        # Scarica subito l'aligner (VRAM libera per gli step successivi)
        try:
            del self._aligner
        except Exception:
            pass
        self._aligner = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

        if failed_chunks > 0:
            self.log(f"  ⚠️ Aligner fallito su {failed_chunks} chunk (timestamp a livello chunk)")
        self.log(f"  📝 Totale segmenti trascritti: {len(all_segments)}")

        self._last_segments = all_segments

        if output_path and all_segments:
            save_success = save_srt_file(all_segments, Path(output_path))
            return save_success, 'en'

        return len(all_segments) > 0, 'en'
