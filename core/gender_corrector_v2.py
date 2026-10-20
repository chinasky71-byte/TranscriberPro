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
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# NON logging.getLogger(__name__): il root logger non viene mai configurato
# durante l'esecuzione normale, quindi un logger "nudo" eredita il livello
# WARNING di default e ogni logger.debug() qui dentro veniva scartato PRIMA
# di raggiungere il file condiviso — stesso difetto già trovato e corretto
# in utils/adaptive_batch_manager.py.
from utils.logger import setup_logger
from utils.platform_compat import venv_python

logger = setup_logger(__name__)

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
    2. interprete di <project>/venv_nlp;
    3. interprete di <project>/gender_eval/.venv_spacy."""
    try:
        from utils.config import get_config
        cfg_path = get_config().get('gender_selector_python', '')
        if cfg_path and Path(cfg_path).exists():
            return Path(cfg_path)
    except Exception:
        pass
    root = Path(__file__).resolve().parent.parent
    for cand in (venv_python(root / 'venv_nlp'),
                 venv_python(root / 'gender_eval' / '.venv_spacy')):
        if cand.exists():
            return cand
    return None


def _build_cast_firstnames(character_context: dict) -> dict:
    """{nome_proprio_lower: 'F'|'M'} dai personaggi TMDB (primo nome di
    ogni personaggio; nomi ambigui — stesso nome, generi diversi — esclusi)."""
    names = {}
    ambiguous = set()
    for full_name, gender in character_context.items():
        if gender not in ('F', 'M'):
            continue
        first = full_name.strip().split()[0].lower() if full_name.strip() else ''
        if len(first) < 3:
            continue
        if first in names and names[first] != gender:
            ambiguous.add(first)
        names[first] = gender
    for a in ambiguous:
        names.pop(a, None)
    return names


_VOCATIVE_RE = re.compile(r"\b([A-ZÀ-Þ][a-zà-ÿ]{2,})\b")


def _vocative_gender(line: str, cast_names: dict) -> Optional[str]:
    """Se la riga contiene UN SOLO nome del cast (vocativo), ritorna il suo
    genere; più nomi o nessuno → None (ambiguo)."""
    if not cast_names:
        return None
    found = {cast_names[w.lower()] for w in _VOCATIVE_RE.findall(line)
             if w.lower() in cast_names}
    return found.pop() if len(found) == 1 else None


# ── Diagnostica Fase 1b (solo lettura, nessuna modifica a speaker_gender.py) ──
# gmap.gender_for_range()/addressee_gender_for_range() collassano ogni
# fallimento in (None, 0.0): qui si richiama la stessa API pubblica in due
# passi per esporre IL MOTIVO, cosa che il log finora non distingueva.

def _diag_speaker_gender(gmap, t0: float, t1: float):
    """Genere del PARLANTE (1ª persona). Ritorna (speaker_id, gender, conf,
    reason). reason: 'no_turn' (nessun turno diarizzato sovrapposto),
    'no_votes' (speaker senza segmenti classificabili), 'low_confidence'
    (sotto soglia), 'ok'."""
    spk = gmap.speaker_for_range(t0, t1)
    if spk is None:
        return None, None, 0.0, 'no_turn'
    sg = gmap.speakers.get(spk)
    if sg is None or sg.gender is None:
        return spk, None, 0.0, 'no_votes'
    if sg.confidence < gmap.conf_threshold:
        return spk, None, sg.confidence, 'low_confidence'
    return spk, sg.gender, sg.confidence, 'ok'


def _diag_addressee_gender(gmap, t0: float, t1: float):
    """Genere dell'INTERLOCUTORE (2ª persona), diagnostica fine (piano
    "Correzione di genere in 2ª persona", Fase 1): usa
    `addressee_gender_for_range_diag()` (speaker_gender.py) per distinguere
    'no_turn'/'no_addressee'/'ambiguous_group'/'not_strict_prev'/
    'not_strict_next'/'not_strict_both'/'low_confidence'/'no_votes'/'ok' —
    non più tutto appiattito su 'ambiguous_addressee'. Il metodo di
    produzione `addressee_gender_for_range()` resta invariato."""
    gender, conf, reason, addressee = gmap.addressee_gender_for_range_diag(t0, t1)
    spk = addressee if addressee is not None else gmap.speaker_for_range(t0, t1)
    return spk, gender, conf, reason


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
            data = json.loads(out_p.read_text(encoding='utf-8'))
            return data['tokens'], data.get('tokens_p2', [[] for _ in lines])

    # ── Correzione ───────────────────────────────────────────────────────

    def correct_file(self, srt_path: Path, output_path: Path,
                     video_path: Optional[Path] = None,
                     diarization: Optional[list] = None,
                     character_context: Optional[dict] = None) -> bool:
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
        sel_out = self._run_selector(flat)
        if sel_out is None:
            shutil.copy(srt_path, output_path)
            return True
        tokens_per_line, tokens_p2_per_line = sel_out

        from utils.config import get_config as _gc
        if not bool(_gc().get('gender_correction_second_person', True)):
            tokens_p2_per_line = [[] for _ in flat]

        candidates = [i for i, _t in enumerate(tokens_per_line)
                      if _t or tokens_p2_per_line[i]]
        n1 = sum(1 for t in tokens_per_line if t)
        n2 = sum(1 for t in tokens_p2_per_line if t)
        self._log(f"   Righe candidate: {n1} in 1ª persona, "
                  f"{n2} in 2ª persona su {len(cues)}")
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
        for spk, sg in sorted(gmap.speakers.items()):
            logger.debug(
                f"Speaker {spk}: gender={sg.gender} conf={sg.confidence:.2f} "
                f"n_segments={sg.n_segments} speech_time={sg.speech_time:.1f}s")

        # 3. Riscrittura deterministica + validatore
        from core.gender_rewriter import RuleRewriter, apply_rewrite
        engine = RuleRewriter()
        cast_names = _build_cast_firstnames(character_context or {})
        if cast_names:
            self._log(f"   Vocativi TMDB attivi: {len(cast_names)} nomi cast")
        stats = {'rewritten': 0, 'unchanged': 0, 'rejected': 0,
                 'no_output': 0, 'unknown': 0, 'dialog': 0}
        diag = {'p1': {'no_turn': 0, 'low_confidence': 0, 'no_votes': 0},
                'p2': {'no_turn': 0, 'overlapping_scene': 0, 'no_addressee': 0,
                       'not_strict': 0, 'low_confidence': 0, 'no_votes': 0}}
        new_cues = list(cues)
        for i in candidates:
            idx, start, end, text = cues[i]
            if _DIALOG_RE.search(text):
                stats['dialog'] += 1          # due parlanti: mai toccare
                continue
            t0, t1 = _ts_to_sec(start), _ts_to_sec(end)
            new_flat, esito = flat[i], 'unchanged'
            applied_gender = None    # genere usato per il log (P1 o P2)
            # 1ª persona: genere del PARLANTE
            toks = [tuple(t) for t in tokens_per_line[i]]
            if toks:
                spk, gender, conf, reason = _diag_speaker_gender(gmap, t0, t1)
                if gender is None:
                    stats['unknown'] += 1     # prudenza: riga intatta
                    diag['p1'][reason] += 1
                    logger.debug(
                        f"Riga {idx} P1 [{start}]: speaker={spk} gender=None "
                        f"conf={conf:.2f} esito=unknown reason={reason}")
                else:
                    new_flat, esito = apply_rewrite(
                        engine, new_flat, None, gender, toks)
                    stats[esito] += 1
                    applied_gender = gender
                    logger.debug(
                        f"Riga {idx} P1 [{start}]: speaker={spk} gender={gender} "
                        f"conf={conf:.2f} esito={esito} reason={reason}")
            # 2ª persona: genere dell'INTERLOCUTORE. Priorità:
            # 1. VOCATIVO col cast TMDB ("Sei cresciuta, Veronica") — alta
            #    precisione; 2. turni di dialogo adiacenti (strict).
            toks2 = [tuple(t) for t in tokens_p2_per_line[i]]
            if toks2:
                a_gender = _vocative_gender(flat[i], cast_names)
                if a_gender is not None:
                    a_spk, a_conf, a_reason = None, 1.0, 'vocative'
                else:
                    a_spk, a_gender, a_conf, a_reason = _diag_addressee_gender(
                        gmap, t0, t1)
                if a_gender is None:
                    stats['unknown'] += 1
                    if a_reason in diag['p2']:
                        diag['p2'][a_reason] += 1
                    logger.debug(
                        f"Riga {idx} P2 [{start}]: speaker={a_spk} gender=None "
                        f"conf={a_conf:.2f} esito=unknown reason={a_reason}")
                else:
                    new_flat, esito2 = apply_rewrite(
                        engine, new_flat, None, a_gender, toks2)
                    stats[esito2] += 1
                    logger.debug(
                        f"Riga {idx} P2 [{start}]: speaker={a_spk} gender={a_gender} "
                        f"conf={a_conf:.2f} esito={esito2} reason={a_reason}")
                    if esito2 == 'rewritten':
                        esito = 'rewritten'
                        applied_gender = a_gender
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
                logger.debug(
                    f"Riga {idx}: '{text}' -> '{new_text}' ({applied_gender})")

        output_path.write_text(_generate_srt(new_cues), encoding='utf-8')

        self._log(f"   ✅ Correzione genere v2: {stats['rewritten']} righe "
                  f"riscritte, {stats['unchanged']} già corrette, "
                  f"{stats['unknown']} parlante incerto, "
                  f"{stats['dialog']} dialoghi doppi saltati, "
                  f"{stats['rejected']} respinte dal validatore")
        if stats['unknown']:
            p1, p2 = diag['p1'], diag['p2']
            self._log(f"      ↳ 1ª persona incerta: no_turn={p1['no_turn']}, "
                      f"low_confidence={p1['low_confidence']}, "
                      f"no_votes={p1['no_votes']}")
            self._log(f"      ↳ 2ª persona incerta: no_turn={p2['no_turn']}, "
                      f"overlapping_scene={p2['overlapping_scene']}, "
                      f"no_addressee={p2['no_addressee']}, "
                      f"not_strict={p2['not_strict']}, "
                      f"low_confidence={p2['low_confidence']}, "
                      f"no_votes={p2['no_votes']}")
        return True

    def cleanup(self):
        if self._mapper is not None:
            self._mapper.cleanup()
            self._mapper = None
