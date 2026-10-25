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
from utils.eta import EtaEstimator
from utils.events import emit as _tp_emit
from utils.logger import setup_logger
from utils.platform_compat import venv_python
from utils.translations import tr

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


# Peso delle fasi sulla barra (selettore spaCy, mappa genere dall'audio, riscrittura delle righe).
# Il selettore e la mappa non danno avanzamento interno fino alla loro fine, tranne i parlanti classificati.
_BAR_SELECTOR_END = 0.10
_BAR_MAP_END = 0.90


class _GenderBar:
    """Barra della correzione di genere: riga di log (si aggiorna sul posto nella card) ed evento `bar` con ETA.

    `set(frazione)` accetta 0..1 monotona; emette solo quando la percentuale intera cambia. Va creata
    all'inizio del lavoro: l'ETA conta dal momento della creazione."""

    def __init__(self, log: Callable[[str], None]):
        self._log = log
        self._eta = EtaEstimator()
        self._last = -1

    def set(self, fraction: float) -> None:
        pct = int(max(0.0, min(float(fraction), 1.0)) * 100)
        if pct <= self._last:
            return
        self._last = pct
        eta_s = None
        if pct < 100:
            self._eta.update(pct / 100.0)
            eta_s = self._eta.eta_seconds()
        _tp_emit('bar', phase='gender', pct=pct, eta_s=eta_s)
        if pct >= 100:
            self._log(tr('g2_progress_done'))
        else:
            bar = '\u2588' * (pct // 10) + '\u2591' * (10 - pct // 10)
            eta_str = "-" if eta_s is None else (f"~{eta_s}s" if eta_s < 60 else f"~{int(eta_s / 60 + 0.5)}m")
            self._log(tr('g2_progress_eta').format(bar=bar, progress=pct, eta_str=eta_str))

    def close_silently(self) -> None:
        """Fase conclusa senza lavoro reale (salti, selettore assente): chiude la barra della card senza
        la riga "100%" nel log, che direbbe una cosa non vera."""
        if self._last < 100:
            self._last = 100
            _tp_emit('bar', phase='gender', pct=100)


class GenderCorrectorV2:
    """Nuovo motore di correzione genere (deterministico, audio-driven)."""

    def __init__(self, log_callback: Optional[Callable] = None,
                 conf_threshold: float = 0.75):
        self._log_cb = log_callback
        self.conf_threshold = conf_threshold
        self._mapper = None
        self._bar = _GenderBar(self._log)       # rimpiazzata a ogni correct_file

    def _log(self, msg: str):
        if self._log_cb:
            self._log_cb(msg)
        logger.info(msg)

    # ── Selettore (subprocess venv NLP) ─────────────────────────────────

    def _run_selector(self, lines: List[str]) -> Optional[List[list]]:
        py = find_selector_python()
        if py is None:
            self._log(tr('g2_nlp_venv_spacy_not_found'))
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
                self._log(tr('g2_selector_failed').format(e=e))
                return None
            for line in (proc.stdout or '').splitlines():
                if line.strip():
                    self._log(f"   {line.strip()}")
            if proc.returncode != 0:
                self._log(tr('g2_selector_exit_code_skipping').format(returncode=proc.returncode))
                return None
            data = json.loads(out_p.read_text(encoding='utf-8'))
            return data['tokens'], data.get('tokens_p2', [[] for _ in lines])

    # ── Correzione ───────────────────────────────────────────────────────

    def correct_file(self, srt_path: Path, output_path: Path,
                     video_path: Optional[Path] = None,
                     diarization: Optional[list] = None,
                     character_context: Optional[dict] = None) -> bool:
        """Corregge il genere con barra di avanzamento ed ETA (v. _correct_file)."""
        self._bar = _GenderBar(self._log)
        self._bar.set(0.0)
        ok = self._correct_file(srt_path, output_path, video_path, diarization, character_context)
        if ok:
            self._bar.close_silently()      # no-op se il lavoro e' arrivato in fondo (100% gia' emesso)
        return ok

    def _correct_file(self, srt_path: Path, output_path: Path,
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
            self._log(tr('gc_no_subtitle_found_skipping_gender'))
            shutil.copy(srt_path, output_path)
            return True

        # 1. Selettore (subprocess spaCy). Testo appiattito per l'analisi.
        flat = [c[3].replace('\n', ' ') for c in cues]
        sel_out = self._run_selector(flat)
        if sel_out is None:
            shutil.copy(srt_path, output_path)
            return True
        tokens_per_line, tokens_p2_per_line = sel_out
        self._bar.set(_BAR_SELECTOR_END)

        from utils.config import get_config as _gc
        if not bool(_gc().get('gender_correction_second_person', True)):
            tokens_p2_per_line = [[] for _ in flat]

        candidates = [i for i, _t in enumerate(tokens_per_line)
                      if _t or tokens_p2_per_line[i]]
        n1 = sum(1 for t in tokens_per_line if t)
        n2 = sum(1 for t in tokens_p2_per_line if t)
        self._log(tr('g2_candidate_lines_in_1st_person').format(n1=n1, n2=n2, n=len(cues)))
        if not candidates:
            shutil.copy(srt_path, output_path)
            self._log(tr('g2_no_lines_to_correct'))
            return True

        if video_path is None:
            self._log(tr('g2_video_path_missing_cannot_build'))
            shutil.copy(srt_path, output_path)
            return True

        # 2. Speaker Gender Map dall'audio
        from core.speaker_gender import SpeakerGenderMapper
        from utils.config import get_config
        hf_token = get_config().get('huggingface_token', '')
        self._mapper = SpeakerGenderMapper(
            hf_token, log_callback=self._log,
            conf_threshold=self.conf_threshold)
        gmap = self._mapper.build_map(
            str(video_path), diarization=diarization,
            progress_callback=lambda f: self._bar.set(
                _BAR_SELECTOR_END + (_BAR_MAP_END - _BAR_SELECTOR_END) * f))
        self._bar.set(_BAR_MAP_END)
        for spk, sg in sorted(gmap.speakers.items()):
            logger.debug(
                f"Speaker {spk}: gender={sg.gender} conf={sg.confidence:.2f} "
                f"n_segments={sg.n_segments} speech_time={sg.speech_time:.1f}s")

        # 3. Riscrittura deterministica + validatore
        from core.gender_rewriter import RuleRewriter, apply_rewrite
        engine = RuleRewriter()
        cast_names = _build_cast_firstnames(character_context or {})
        if cast_names:
            self._log(tr('g2_tmdb_vocatives_active_cast_names').format(n=len(cast_names)))
        stats = {'rewritten': 0, 'unchanged': 0, 'rejected': 0,
                 'no_output': 0, 'unknown': 0, 'dialog': 0}
        diag = {'p1': {'no_turn': 0, 'low_confidence': 0, 'no_votes': 0},
                'p2': {'no_turn': 0, 'overlapping_scene': 0, 'no_addressee': 0,
                       'not_strict': 0, 'low_confidence': 0, 'no_votes': 0}}
        new_cues = list(cues)
        for n_done, i in enumerate(candidates):
            self._bar.set(_BAR_MAP_END + (1.0 - _BAR_MAP_END) * n_done / len(candidates))
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
            self._bar.set(_BAR_MAP_END + (1.0 - _BAR_MAP_END) * (n_done + 1) / len(candidates))
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
        self._bar.set(1.0)

        self._log(tr('g2_gender_correction_v2_lines_rewritten').format(rewritten=stats['rewritten'], unchanged=stats['unchanged'], unknown=stats['unknown'], dialog=stats['dialog'], rejected=stats['rejected']))
        if stats['unknown']:
            p1, p2 = diag['p1'], diag['p2']
            self._log(tr('g2_1st_person_uncertain_no_turn').format(no_turn=p1['no_turn'], low_confidence=p1['low_confidence'], no_votes=p1['no_votes']))
            self._log(tr('g2_2nd_person_uncertain_no_turn').format(no_turn=p2['no_turn'], overlapping_scene=p2['overlapping_scene'], no_addressee=p2['no_addressee'], not_strict=p2['not_strict'], low_confidence=p2['low_confidence'], no_votes=p2['no_votes']))
        return True

    def cleanup(self):
        if self._mapper is not None:
            self._mapper.cleanup()
            self._mapper = None
