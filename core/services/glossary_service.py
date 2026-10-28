# -*- coding: utf-8 -*-
"""Glossario per show: nomi, candidati TMDB, richiesta di avvio, report e salvataggio, senza Qt.

Trasposizione fedele della logica di gui/glossary_dialog.py (le funzioni pure che il dialogo usava con i nomi `_slugify`,
`_name_candidates`, ...). Il lancio del sottoprocesso e' in core/jobs/glossary_run.py; il dialogo resta la vista."""
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "show"


# Librerie Plex (V:\Show\Season N\...): la cartella scelta puo' essere la
# sottocartella stagione, non lo show — il suo nome ("Season 2") non trova
# mai riscontro su TMDB e, peggio, degrada a "Season" dopo _clean_title
# facendo scrivere un tmdb_id SBAGLIATO nel glossario (bug reale). Ancorato
# ^...$ cosi' "Season of the Witch" non viene mai scambiato per una cartella
# stagione.
SEASON_DIR_RE = re.compile(
    r'^(?:season|stagione|saison|staffel|temporada|series|s)\s*[._-]?\s*\d{1,3}$'
    r'|^(?:specials?|speciali|extras?|bonus|special\s+features|featurettes?)$',
    re.IGNORECASE)

SXXEXX_RE = re.compile(r'[Ss]\d{1,2}[Ee]\d{1,3}|(?<![A-Za-z0-9])\d{1,2}x\d{1,3}(?![A-Za-z0-9])')

EP_EXT = {'.mkv', '.mp4', '.avi', '.m4v', '.ts', '.srt', '.ass', '.ssa'}


def title_from_episode_files(folder: Path, depth: int = 1) -> Optional[str]:
    """Titolo grezzo dal primo file con SxxExx trovato. Scansione LIMITATA
    (cartella scelta + un livello, niente os.walk su share di rete) — le
    cartelle Extras/Special Features si escludono da sole perche' i loro
    file non hanno un pattern SxxExx nel nome."""
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    subdirs = []
    for p in entries:
        if p.is_dir():
            subdirs.append(p)
            continue
        if p.suffix.lower() not in EP_EXT:
            continue
        m = SXXEXX_RE.search(p.name)
        if not m:
            continue
        raw = re.sub(r'[._]+', ' ', p.name[:m.start()])
        raw = re.sub(r'\s+', ' ', raw).strip(' -')
        if raw:
            return raw
    if depth > 0:
        for sub in subdirs:
            t = title_from_episode_files(sub, depth - 1)
            if t:
                return t
    return None


def name_candidates(folder: str) -> List[str]:
    """Candidati per la ricerca TMDB, in ordine di affidabilita'. Su una
    libreria Plex il nome della cartella show e' curato a mano: batte il
    nome del file (release dotted/lowercase, romanizzazioni anime diverse
    dal titolo TMDB)."""
    p = Path(folder)
    out = []
    if SEASON_DIR_RE.match(p.name):
        out.append(p.parent.name)  # V:\Show\Season 2 -> "Show"
        out.append(title_from_episode_files(p))
    else:
        out.append(p.name)  # cartella show gia' pulita, o cartella film
        out.append(title_from_episode_files(p))
        out.append(p.parent.name)  # ultima spiaggia
    seen, res = set(), []
    for c in out:
        c = (c or '').strip()
        k = c.lower()
        if c and k not in seen and not SEASON_DIR_RE.match(c):
            seen.add(k)
            res.append(c)
    return res


@dataclass(frozen=True)
class RunRequest:
    args_payload: dict
    work_dir: Path


def build_run_request(show_dir: str, name_text: str, tmdb_id, candidates: Sequence[str], config,
                      llm_preference=None) -> RunRequest:
    """args.json e cartella di lavoro di un run. `name_text`: nome digitato (anche vuoto); `candidates`: candidati gia' calcolati."""
    # Fallback se il campo nome e' vuoto: mai il nome della cartella scelta as-is (se e' "Season 2" lo slug collide tra show diversi,
    # vedi nota sotto) — preferisci il primo candidato gia' risolto.
    _fallback = (candidates or [Path(show_dir).name])[0]
    name = slugify(name_text.strip() or _fallback)
    if tmdb_id is not None:
        # Il solo slug del nome puo' collidere tra show diversi (stesso titolo comune, o traslitterazioni che si normalizzano uguali)
        # sovrascrivendo report/work_dir a vicenda — il TMDB id, quando c'e', li rende univoci (bug reale segnalato in revisione).
        name = f"{name}_{tmdb_id}"

    exclude_episodes = []
    if tmdb_id is not None:
        try:
            from core.glossary_state import load_used
            exclude_episodes = [list(k) for k in load_used(tmdb_id)]
        except Exception as e:
            logger.warning(f"Lettura used_episodes fallita: {e}")

    qwen_model_path, qwen_ngl = config.resolve_llm_model('gender_correction_model_path', llm_preference)
    if qwen_model_path and qwen_ngl == 0:
        # Scelta automatica senza GPU utilizzabile: il canale Qwen su sola CPU richiederebbe ore, non si accende da solo.
        logger.info(f"Canale Qwen del glossario non attivato (nessuna GPU rilevata): {qwen_model_path}")
        qwen_model_path = None
    elif qwen_model_path:
        logger.info(f"Canale Qwen del glossario: {qwen_model_path} (n_gpu_layers={qwen_ngl})")
    qwen_model_path = qwen_model_path or None

    args_payload = {
        "show_dir": show_dir,
        "name": name,
        "tmdb_id": tmdb_id,
        "min_freq": 3,
        "min_episodes": 6,
        "min_blocks": 6000,
        "use_align": True,
        "use_qwen": bool(qwen_model_path),
        "qwen_model_path": qwen_model_path,
        "align_device": "cpu",
        "qwen_n_gpu_layers": qwen_ngl,
        "exclude_episodes": exclude_episodes,
    }
    return RunRequest(args_payload, PROJECT_ROOT / 'glossary_engine' / 'glossary_work' / name)


def load_report(report_path: str) -> dict:
    """Legge il report JSON del run (solleva se illeggibile)."""
    return json.loads(Path(report_path).read_text(encoding='utf-8'))


def approved_terms(rows: Sequence[Tuple[str, bool, str]]) -> Dict[str, str]:
    """rows: (termine, approvato, resa digitata). Solo gli approvati con una resa non vuota."""
    out = {}
    for term, approved, rendering in rows:
        if approved:
            rendering = rendering.strip()
            if rendering:
                out[term] = rendering
    return out


def save_terms(tmdb_id, new_terms: Dict[str, str], episodes_used: Sequence) -> Path:
    """Unisce i termini nel glossario dello show e marca gli episodi usati. Ritorna il percorso del glossario."""
    from core.glossary import merge_glossary
    from core.glossary_state import mark_used
    path = merge_glossary(tmdb_id, new_terms)
    episodes_used = [tuple(k) for k in episodes_used]
    if episodes_used:
        mark_used(tmdb_id, episodes_used)
    return path
