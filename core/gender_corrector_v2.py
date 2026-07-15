# -*- coding: utf-8 -*-
"""
Gender Corrector V2 — orchestratore del nuovo STEP 6.5.
File: core/gender_corrector_v2.py

Pipeline deterministica (nessun LLM):
  1. selettore spaCy in SUBPROCESS separato (venv NLP dedicato) →
     forme di 1ª persona per ogni riga; il processo muore e libera la RAM;
  2. Speaker Gender Map dall'audio (core/speaker_gender: pyannote + ECAPA)
     — calcolata SOLO se ci sono righe candidate;
  3. per ogni candidata: genere del parlante dalla mappa (per timestamp);
     se il testo esprime il genere sbagliato → flip morfologico
     (core/gender_rewriter.RuleRewriter) + validatore deterministico.

Prudenza by design:
  - righe di dialogo doppio ("- ... - ...") mai toccate (due parlanti);
  - genere UNKNOWN (confidenza < soglia, nessun parlante) → riga intatta;
  - riscritture non plausibili respinte dal validatore → riga intatta.

Numeri di riferimento (VM S01, 268 righe): mappa audio 95,0%;
riscrittura F 19,3%→86,8%, M 89,3%→93,3%.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

SRT_CUE = Tuple[int, str, str, str]   # (index, start, end, text)

_TS_RE = re.compile(r'(\d+):(\d+):(\d+)[,.](\d+)')
_DIALOG_RE = re.compile(r'(?:^|\n)\s*[-–—]')


def _ts_to_sec(ts: str) -> float:
    m = _TS_RE.match(ts.strip())
    if not m:
        return 0.0
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def _parse_srt(path: Path) -> List[SRT_CUE]:
    content = path.read_text(encoding='utf-8', errors='replace')
    pattern = r'(\d+)\s*\n([\d:,\.]+)\s*-->\s*([\d:,\.]+)\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|\Z)'
    cues = []
    for m in re.finditer(pattern, content, re.MULTILINE):
        text = m.group(4).strip()
        if text:
            cues.append((int(m.group(1)), m.group(2).strip(),
                         m.group(3).strip(), text))
    return cues


def _generate_srt(cues: List[SRT_CUE]) -> str:
    out = []
    for idx, start, end, text in cues:
        out += [str(idx), f"{start} --> {end}", text, ""]
    return "\n".join(out)


def find_selector_python() -> Optional[Path]:
    """Trova il python del venv NLP (spaCy). Ordine:
    1. config 'gender_selector_python';
    2. <project>/venv_nlp/Scripts/python.exe;
    3. <project>/gender_eval/.venv_spacy/Scripts/python.exe."""
    try:
        from utils.config import get_config
        cfg_path = get_config().get('gender_selector_python', '')
        if cfg_path and Path(cfg_path).exists():
            return Path(cfg_path)
    except Exception:
        pass
    root = Path(__file__).resolve().parent.parent
    for cand in (root / 'venv_nlp' / 'Scripts' / 'python.exe',
                 root / 'gender_eval' / '.venv_spacy' / 'Scripts' / 'python.exe'):
        if cand.exists():
            return cand
    return None


class GenderCorrectorV2:
    """Nuovo motore di correzione genere (deterministico, audio-driven)."""

    def __init__(self, log_callback: Optional[Callable] = None,
                 conf_threshold: float = 0.75):
        self._log_cb = log_callback
        self.conf_threshold = conf_threshold
        self._mapper = None

    def _log(self, msg: str):
        if self._log_cb:
            self._log_cb(msg)
        logger.info(msg)

    # ── Selettore (subprocess venv NLP) ─────────────────────────────────

    def _run_selector(self, lines: List[str]) -> Optional[List[list]]:
        py = find_selector_python()
        if py is None:
            self._log("⚠️ Venv NLP (spaCy) non trovato — correzione saltata")
            return None
        cli = Path(__file__).resolve().parent / 'gender_selector_cli.py'
        with tempfile.TemporaryDirectory(prefix="gsel_") as td:
            in_p, out_p = Path(td) / "in.json", Path(td) / "out.json"
            in_p.write_text(json.dumps({'lines': lines}, ensure_ascii=False),
                            encoding='utf-8')
            try:
                proc = subprocess.run(
                    [str(py), str(cli), str(in_p), str(out_p)],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=600)
            except Exception as e:
                self._log(f"⚠️ Selettore fallito: {e}")
                return None
            for line in (proc.stdout or '').splitlines():
                if line.strip():
                    self._log(f"   {line.strip()}")
            if proc.returncode != 0:
                self._log(f"⚠️ Selettore exit code {proc.returncode} — salto")
                return None
            return json.loads(out_p.read_text(encoding='utf-8'))['tokens']

    # ── Correzione ───────────────────────────────────────────────────────

    def correct_file(self, srt_path: Path, output_path: Path,
                     video_path: Optional[Path] = None,
                     diarization: Optional[list] = None) -> bool:
        """Corregge il genere di 1ª persona in un SRT tradotto.

        Args:
            srt_path: SRT italiano tradotto
            output_path: dove salvare il risultato
            video_path: file video (serve per l'audio → speaker gender map)
            diarization: lista (start, end, speaker) già calcolata (opzionale)
        Returns: True se completato (anche con 0 correzioni).
        """
        import shutil

        cues = _parse_srt(Path(srt_path))
        if not cues:
            self._log("Nessun sottotitolo trovato. Salto correzione genere.")
            shutil.copy(srt_path, output_path)
            return True

        # 1. Selettore (subprocess spaCy). Testo appiattito per l'analisi.
        flat = [c[3].replace('\n', ' ') for c in cues]
        tokens_per_line = self._run_selector(flat)
        if tokens_per_line is None:
            shutil.copy(srt_path, output_path)
            return True

        candidates = [i for i, t in enumerate(tokens_per_line) if t]
        self._log(f"   Righe candidate (1ª persona con genere): "
                  f"{len(candidates)}/{len(cues)}")
        if not candidates:
            shutil.copy(srt_path, output_path)
            self._log("   Nessuna riga da correggere.")
            return True

        if video_path is None:
            self._log("⚠️ video_path mancante: impossibile costruire la "
                      "speaker gender map. Salto correzione.")
            shutil.copy(srt_path, output_path)
            return True

        # 2. Speaker Gender Map dall'audio
        from core.speaker_gender import SpeakerGenderMapper
        from utils.config import get_config
        hf_token = get_config().get('huggingface_token', '')
        self._mapper = SpeakerGenderMapper(
            hf_token, log_callback=self._log,
            conf_threshold=self.conf_threshold)
        gmap = self._mapper.build_map(str(video_path), diarization=diarization)

        # 3. Riscrittura deterministica + validatore
        from core.gender_rewriter import RuleRewriter, apply_rewrite
        engine = RuleRewriter()
        stats = {'rewritten': 0, 'unchanged': 0, 'rejected': 0,
                 'no_output': 0, 'unknown': 0, 'dialog': 0}
        new_cues = list(cues)
        for i in candidates:
            idx, start, end, text = cues[i]
            if _DIALOG_RE.search(text):
                stats['dialog'] += 1          # due parlanti: mai toccare
                continue
            t0, t1 = _ts_to_sec(start), _ts_to_sec(end)
            gender, conf = gmap.gender_for_range(t0, t1)
            if gender is None:
                stats['unknown'] += 1         # prudenza: riga intatta
                continue
            toks = [tuple(t) for t in tokens_per_line[i]]
            new_flat, esito = apply_rewrite(engine, flat[i], None, gender, toks)
            stats[esito] += 1
            if esito == 'rewritten':
                # riporta il testo su singola riga corretta preservando
                # gli a-capo originali quando possibile
                if '\n' in text and len(new_flat) == len(flat[i]):
                    rebuilt, pos = [], 0
                    for seg in text.split('\n'):
                        rebuilt.append(new_flat[pos:pos + len(seg)].strip())
                        pos += len(seg) + 1
                    new_text = '\n'.join(rebuilt)
                else:
                    new_text = new_flat
                new_cues[i] = (idx, start, end, new_text)
                logger.debug(f"Riga {idx}: '{text}' -> '{new_text}' ({gender})")

        output_path.write_text(_generate_srt(new_cues), encoding='utf-8')

        self._log(f"   ✅ Correzione genere v2: {stats['rewritten']} righe "
                  f"riscritte, {stats['unchanged']} già corrette, "
                  f"{stats['unknown']} parlante incerto, "
                  f"{stats['dialog']} dialoghi doppi saltati, "
                  f"{stats['rejected']} respinte dal validatore")
        return True

    def cleanup(self):
        if self._mapper is not None:
            self._mapper.cleanup()
            self._mapper = None
