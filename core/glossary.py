# -*- coding: utf-8 -*-
"""
Glossario a resa fissa per serie/film — Fase 2 di Gender V2.5.
File: core/glossary.py

Un glossario fissa la resa italiana di un termine ricorrente (nomi propri
di macchine/luoghi/oggetti della serie: "Knight Runner", "Silhouette
Knight", ...) così NLLB e i motori LLM non lo traducono in modo diverso
blocco per blocco. Costruito a mano la prima volta per una serie, poi
riusato per ogni episodio via lookup sul TMDB id.

Dove vive: ~/.transcriberpro/glossary/tmdb_<id>.json — stessa area dati
utente di config/cache poster. Formato:
    {"Knight Runner": "Runner dei Cavalieri", "Silhouette Knight": "Silhouette Knight"}

Nessun glossario per un dato id = comportamento storico invariato
(get_translator/translate_file ricevono glossary={} e nessuna riga di
codice esistente cambia strada).
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Union

logger = logging.getLogger(__name__)


def _glossary_dir() -> Path:
    return Path.home() / '.transcriberpro' / 'glossary'


def glossary_path(tmdb_id: Union[int, str]) -> Path:
    return _glossary_dir() / f"tmdb_{tmdb_id}.json"


def load_glossary(tmdb_id: Optional[Union[int, str]]) -> Dict[str, str]:
    """Carica il glossario per un TMDB id. {} se assente o non leggibile —
    mai un'eccezione: un glossario mancante non deve mai far fallire una
    traduzione."""
    if not tmdb_id:
        return {}
    path = glossary_path(tmdb_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            logger.warning(f"Glossario {path} non è un oggetto JSON, ignorato")
            return {}
        return {str(k): str(v) for k, v in data.items() if k and v}
    except Exception as e:
        logger.warning(f"Glossario {path} illeggibile, ignorato: {e}")
        return {}


def save_glossary(tmdb_id: Union[int, str], terms: Dict[str, str]) -> Path:
    """Scrive/sovrascrive il glossario per un TMDB id. Uso: costruzione
    manuale la prima volta per una serie (non chiamato dalla pipeline)."""
    _glossary_dir().mkdir(parents=True, exist_ok=True)
    path = glossary_path(tmdb_id)
    path.write_text(json.dumps(terms, ensure_ascii=False, indent=2),
                     encoding='utf-8')
    return path


def _rotate_backups(path: Path, keep: int = 3) -> None:
    """tmdb_<id>.json.bak, .bak2, .bak3 — il piu' vecchio (.bak3) viene
    scartato. Best-effort: un backup fallito non deve mai bloccare il
    salvataggio del glossario nuovo."""
    try:
        for i in range(keep, 1, -1):
            src = path.with_suffix(f"{path.suffix}.bak{i - 1}" if i > 2
                                    else f"{path.suffix}.bak")
            dst = path.with_suffix(f"{path.suffix}.bak{i}")
            if src.exists():
                dst.write_bytes(src.read_bytes())
        if path.exists():
            first_backup = path.with_suffix(f"{path.suffix}.bak")
            first_backup.write_bytes(path.read_bytes())
    except Exception as e:
        logger.warning(f"Backup glossario {path} fallito (si procede comunque): {e}")


def merge_glossary(tmdb_id: Union[int, str], new_terms: Dict[str, str]) -> Path:
    """Fonde `new_terms` nel glossario esistente per il TMDB id — MAI una
    sovrascrittura secca: un glossario gia' validato a mano non deve poter
    essere cancellato da una run automatica successiva. Ogni chiave in
    `new_terms` sovrascrive la propria voce (i conflitti li risolve
    l'utente in GUI prima di chiamare questa funzione), le altre voci
    esistenti restano intatte. Backup ruotato (fino a 3 copie) prima di
    scrivere. Scrittura atomica (file temporaneo + replace)."""
    path = glossary_path(tmdb_id)
    existing = load_glossary(tmdb_id)
    _rotate_backups(path)
    merged = {**existing, **{k: v for k, v in new_terms.items() if k and v}}
    _glossary_dir().mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                         encoding='utf-8')
    tmp_path.replace(path)
    return path
