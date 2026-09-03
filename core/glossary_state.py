# -*- coding: utf-8 -*-
"""
Stato "episodi gia' usati" per la costruzione del glossario per-show.
File: core/glossary_state.py

Evita l'auto-alimentazione sugli aggiornamenti: se un episodio e' gia'
stato incluso in una run di costruzione/validazione del glossario, gli
episodi successivi tradotti CON quel glossario confermerebbero sempre se
stessi nel clustering (il termine appare "consistente" solo perche' e'
gia' stato fissato). Ogni run usa solo episodi "freschi" mai analizzati
prima; la lista si aggiorna SOLO alla conferma umana del salvataggio in
GUI, mai a fine run automaticamente.

Dove vive: ~/.transcriberpro/glossary/tmdb_<id>.used_episodes.json —
stessa area di core/glossary.py, file companion del glossario stesso.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Set, Tuple, Union

logger = logging.getLogger(__name__)

EpisodeKey = Tuple[int, int]  # (season, episode)


def _glossary_dir() -> Path:
    return Path.home() / '.transcriberpro' / 'glossary'


def used_episodes_path(tmdb_id: Union[int, str]) -> Path:
    return _glossary_dir() / f"tmdb_{tmdb_id}.used_episodes.json"


def load_used(tmdb_id: Union[int, str]) -> Set[EpisodeKey]:
    """{} se assente o illeggibile — mai un'eccezione: uno stato mancante
    equivale a "nessun episodio ancora usato", non a un errore."""
    path = used_episodes_path(tmdb_id)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        episodes = data.get('episodes', [])
        return {(int(s), int(e)) for s, e in episodes}
    except Exception as e:
        logger.warning(f"Stato episodi usati {path} illeggibile, ignorato: {e}")
        return set()


def mark_used(tmdb_id: Union[int, str], keys: Iterable[EpisodeKey]) -> Path:
    """Aggiunge `keys` alla lista esistente (unione, mai una sostituzione)
    e riscrive in modo atomico. Chiamato SOLO alla conferma umana del
    salvataggio glossario in GUI."""
    existing = load_used(tmdb_id)
    merged = sorted(existing | {(int(s), int(e)) for s, e in keys})
    _glossary_dir().mkdir(parents=True, exist_ok=True)
    path = used_episodes_path(tmdb_id)
    payload = {
        "version": 1,
        "episodes": [[s, e] for s, e in merged],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding='utf-8')
    tmp_path.replace(path)
    return path
