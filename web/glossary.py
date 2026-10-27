"""Glossary review over reports produced by `glossary_engine`.

The web interface does **not** build reports: building one needs the show
folder, an English reference track and the Qwen extractor (a long GPU job).
`glossary_engine.build_glossary_candidates.build_full_report(report_out=...)`
writes the JSON; this module reads it and stores the human decisions next to it
as `<report>.decisions.json`.

Report shape (frozen by the engine, only the fields used here are read):

```
{"show": str, "gate": {...}, "blocks": int, "episodes_used": [...],
 "candidates": [{"term": str, "occurrences": int, "status": "auto|review|reject",
                 "reason": str, "align_verdict": str, "qwen_verdict": str}, ...]}
```

Decisions: `{term: {"decision": "approved|rejected|pending",
"translation": str, "note": str, "updated_at": float}}`.

Reports and decisions contain show and character names: they live in
`TP_DATA_DIR/glossary/`, never in the repository.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from web.ocr_review import atomic_write_json, read_json

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")
DECISIONS_SUFFIX = ".decisions.json"
DECISIONS = ("pending", "approved", "rejected")
MAX_TRANSLATION_CHARS = 200
MAX_NOTE_CHARS = 500


class GlossaryError(ValueError):
    """Bad request: unknown report, invalid name or decision."""


class GlossaryNotFound(GlossaryError):
    """The report does not exist."""


class GlossaryStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ── paths ────────────────────────────────────────────────────────────
    def _path(self, name: str) -> Path:
        if not NAME_RE.match(name or "") or "/" in name or "\\" in name:
            raise GlossaryNotFound("unknown glossary report")
        path = self.root / f"{name}.json"
        if not path.is_file():
            raise GlossaryNotFound("unknown glossary report")
        return path

    def _decisions_path(self, name: str) -> Path:
        return self.root / f"{name}{DECISIONS_SUFFIX}"

    # ── reads ────────────────────────────────────────────────────────────
    def list(self) -> List[Dict[str, Any]]:
        reports = []
        for path in sorted(self.root.glob("*.json")):
            if path.name.endswith(DECISIONS_SUFFIX):
                continue
            report = read_json(path, {}) or {}
            decisions = self.decisions(path.stem)
            candidates = report.get("candidates") or []
            reports.append({
                "name": path.stem,
                "show": report.get("show") or path.stem,
                "candidates": len(candidates),
                "to_review": sum(1 for item in candidates
                                 if (item.get("status") or "") == "review"),
                "decided": sum(1 for value in decisions.values()
                               if value.get("decision") in ("approved", "rejected")),
                "updated_at": path.stat().st_mtime,
            })
        reports.sort(key=lambda item: item["updated_at"], reverse=True)
        return reports

    def report(self, name: str) -> Dict[str, Any]:
        return read_json(self._path(name), {}) or {}

    def decisions(self, name: str) -> Dict[str, Any]:
        if not NAME_RE.match(name or "") or "/" in name or "\\" in name:
            raise GlossaryNotFound("unknown glossary report")
        return read_json(self._decisions_path(name), {}) or {}

    def view(self, name: str) -> Dict[str, Any]:
        """Report with the current decision attached to every candidate."""
        report = self.report(name)
        decisions = self.decisions(name)
        rows = []
        for index, candidate in enumerate(report.get("candidates") or []):
            term = candidate.get("term") or ""
            decision = decisions.get(term) or {}
            rows.append({
                "index": index,
                "term": term,
                "occurrences": candidate.get("occurrences"),
                "status": candidate.get("status") or "",
                "reason": candidate.get("reason") or "",
                "align_verdict": candidate.get("align_verdict") or "",
                "qwen_verdict": candidate.get("qwen_verdict") or "",
                "decision": decision.get("decision") or "pending",
                "translation": decision.get("translation") or "",
                "note": decision.get("note") or "",
            })
        return {
            "name": name,
            "show": report.get("show") or name,
            "gate": report.get("gate") or {},
            "blocks": report.get("blocks"),
            "episodes": len(report.get("episodes_used") or []),
            "rows": rows,
        }

    # ── writes ───────────────────────────────────────────────────────────
    def decide(self, name: str, term: str, decision: str, translation: str = "",
               note: str = "") -> Dict[str, Any]:
        self._path(name)  # validates the report exists
        if decision not in DECISIONS:
            raise GlossaryError(f"decision must be one of {', '.join(DECISIONS)}")
        translation = (translation or "").strip()
        note = (note or "").strip()
        if len(translation) > MAX_TRANSLATION_CHARS:
            raise GlossaryError(f"translation is longer than {MAX_TRANSLATION_CHARS} characters")
        if len(note) > MAX_NOTE_CHARS:
            raise GlossaryError(f"note is longer than {MAX_NOTE_CHARS} characters")
        terms = {item.get("term") for item in self.view(name)["rows"]}
        if term not in terms:
            raise GlossaryNotFound("unknown term")
        decisions = self.decisions(name)
        decisions[term] = {
            "decision": decision,
            "translation": translation,
            "note": note,
            "updated_at": time.time(),
        }
        atomic_write_json(self._decisions_path(name), decisions)
        return decisions[term]

    def set_many(self, name: str, terms: List[str], decision: str) -> Dict[str, Any]:
        for term in terms:
            self.decide(name, term, decision)
        return self.decisions(name)


def env_root(config: Any) -> Path:
    base = getattr(config, "CONFIG_DIR", None) or ""
    return Path(base).expanduser() / "glossary" if base else Path.home() / ".transcriberpro" / "glossary"


# --------------------------------------------------------------- glossari "a resa fissa"
# La pagina /glossary serve anche a creare il glossario che il pipeline usa per il
# contesto ASR e per la traduzione (core/glossary.py): due strade, il cast TMDB
# oppure un elenco incollato a mano ("Nome as Personaggio", come nelle schede
# delle serie). Il file finisce in TP_DATA_DIR/glossary/, mai nel repository.

CAST_LINE_RE = re.compile(r"^(?P<actor>.+?)\s+as\s+(?P<character>[^\[\]]+)", re.IGNORECASE)
MAX_CAST_CHARS = 20000


def parse_cast_text(text: str) -> Dict[str, str]:
    """Elenco incollato -> `{personaggio: personaggio}`.

    Gestisce il formato delle schede cast:

        Ella Beatty as Lizzie Borden[1]
        Vicky Krieps as                       <- il nome è sulla riga dopo
        Bridget "Maggie" Sullivan, the maid   <- descrizione dopo la virgola
        Charlie Hunnam as Andrew Borden, Emma's and Lizzie's father[3]

    Regole: si tolgono le note `[n]` e le parentesi, si unisce una riga che
    finisce con "as" alla successiva, si taglia alla prima virgola (il resto è
    descrizione), si scartano i ruoli generici e le righe troppo lunghe. Un alias
    fra virgolette ("Maggie") diventa anche una voce a sé: è così che lo chiamano
    nei dialoghi.
    """
    terms: Dict[str, str] = {}
    skip = {"himself", "herself", "narrator", "unknown", "self", "voice",
            "guest", "recurring", "main", "cast", "characters"}

    def add(name: str) -> None:
        cleaned = re.sub(r"\s*\([^)]*\)", "", name).strip(" -\t\"'")
        cleaned = re.sub(r"^(as|e|and)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        if len(cleaned) < 3 or cleaned.lower() in skip or len(cleaned.split()) > 6:
            return
        terms.setdefault(cleaned, cleaned)
        alias = re.match(r"^[^\"]*\"([^\"]+)\"", cleaned)
        if alias and len(alias.group(1)) >= 3:
            terms.setdefault(alias.group(1), alias.group(1))

    lines = [re.sub(r"\[[^\]]*\]", "", raw).strip() for raw in (text or "").splitlines()]
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line or line.lower().rstrip(":") in skip:
            continue
        if re.search(r"\bas\s*$", line, re.IGNORECASE) and index < len(lines):
            character = lines[index]
            index += 1
            add(character.split(",")[0])
            continue
        match = CAST_LINE_RE.match(line)
        target = match.group("character") if match else line
        add(target.split(",")[0])
    return terms


def list_fixed_glossaries() -> List[Dict[str, Any]]:
    """Glossari `tmdb_<id>.json` / `manual_<slug>.json` presenti nella data dir."""
    from core.glossary import _glossary_dir
    from web.ocr_review import read_json as _read
    root = _glossary_dir()
    found: List[Dict[str, Any]] = []
    try:
        entries = sorted(root.glob("*.json"))
    except OSError:
        return []
    for path in entries:
        if path.name.endswith(DECISIONS_SUFFIX):
            continue
        data = _read(path) or {}
        if not isinstance(data, dict):
            continue
        kind = "tmdb" if path.name.startswith("tmdb_") else "manual"
        found.append({"name": path.stem, "kind": kind, "terms": len(data),
                      "path": str(path)})
    return found


def write_fixed_glossary(key: str, terms: Dict[str, str]) -> Path:
    """Scrive il glossario a resa fissa per `key` (id TMDB o nome serie)."""
    from core.glossary import save_glossary
    if not terms:
        raise GlossaryError("the cast list is empty: nothing to save")
    if len(terms) > 500:
        raise GlossaryError("too many terms (limit 500)")
    return save_glossary(key, terms)


def build_from_tmdb(tmdb_id: str, media_type: str = "tv", season: Optional[int] = None,
                    episode: Optional[int] = None) -> Dict[str, str]:
    """Glossario dal cast TMDB (richiede la chiave API nei settings)."""
    from core.glossary import ensure_glossary
    from utils.tmdb_client import TMDBClient
    if not str(tmdb_id).strip().isdigit():
        raise GlossaryError("TMDB id must be a number")
    client = TMDBClient()
    if not getattr(client, "api_key", ""):
        raise GlossaryError("no TMDB API key configured: add it in Settings, or paste the cast by hand")
    terms = ensure_glossary(int(str(tmdb_id).strip()), client, media_type,
                            season=season, episode=episode, overwrite=True)
    if not terms:
        raise GlossaryError("TMDB returned no cast for that id")
    return terms
