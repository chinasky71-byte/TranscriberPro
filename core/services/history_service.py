# -*- coding: utf-8 -*-
"""HistoryService: la cronologia dei file elaborati (~/.transcriberpro/history.json), senza Qt.

Estratto da gui/history_widget.py: caricamento, salvataggio, statistiche, formattazione delle celle e ricerca. I TESTI sono quelli
di prima, carattere per carattere (data `AAAA-MM-GG HH:MM`, lingua `src→dst`, durata `Hh MMm SSs`, dimensione con il
suo arrotondamento). La GUI Qt disegna la tabella e le tessere; la web UI lo fara' con lo stesso servizio.

Formato del file (invariato): lista JSON di voci {name, date_iso, src_lang, dst_lang, duration_seconds, size_bytes, srt_path,
video_path}, indent=2, ensure_ascii=False. Un file assente o illeggibile vale «cronologia vuota»; un JSON valido ma non
una lista (che prima mandava in errore l'avvio) vale anch'esso «vuota».
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


def default_path() -> Path:
    return Path.home() / '.transcriberpro' / 'history.json'


def format_bytes(n) -> str:
    """'900 B', '2 KB', '5 GB', '1.0 TB' (come la colonna Dimensione)."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.0f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def format_duration(seconds) -> str:
    """'2m 05s' oppure '1h 02m 05s' (come la colonna Durata)."""
    secs = int(seconds or 0)
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def format_date(entry: dict) -> str:
    return entry.get('date_iso', '')[:16].replace('T', ' ')


def format_language(entry: dict) -> str:
    src = entry.get('src_lang', 'auto')
    dst = entry.get('dst_lang', '')
    return f"{src}→{dst}" if dst else src


@dataclass(frozen=True)
class HistoryStats:
    total: int
    total_bytes: int
    total_seconds: int

    @property
    def size_text(self) -> str:
        """Tessera «Spazio totale»: '2.0 GB' (un decimale, fino a TB)."""
        tb = float(self.total_bytes)
        unit = 'B'
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if tb < 1024:
                break
            tb /= 1024
        return f'{tb:.1f} {unit}'

    @property
    def time_text(self) -> str:
        """Tessera «Tempo totale»: '1h 05m'."""
        m, _s = divmod(self.total_seconds, 60)
        h, m = divmod(m, 60)
        return f'{h}h {m:02d}m'


@dataclass(frozen=True)
class HistoryRow:
    """Le celle di testo di una voce (le azioni si decidono con `actions_of`)."""
    name: str
    date: str
    language: str
    duration: str
    size: str

    def as_tuple(self) -> Tuple[str, str, str, str, str]:
        return (self.name, self.date, self.language, self.duration, self.size)


def row_of(entry: dict) -> HistoryRow:
    return HistoryRow(entry.get('name', ''), format_date(entry), format_language(entry),
                      format_duration(entry.get('duration_seconds', 0)), format_bytes(entry.get('size_bytes', 0)))


def actions_of(entry: dict) -> Tuple[str, str]:
    """(percorso del .srt, cartella del video): stringa vuota = azione non disponibile."""
    srt = entry.get('srt_path', '')
    folder = str(Path(entry['video_path']).parent) if entry.get('video_path') else ''
    return srt, folder


def matches(query: str, row: HistoryRow) -> bool:
    """Ricerca della GUI: il testo (senza spazi ai bordi, minuscolo) e' contenuto nel nome o nella lingua mostrata."""
    q = (query or '').strip().lower()
    return not q or q in row.name.lower() or q in row.language.lower()


class HistoryService:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_path()
        self.entries: List[dict] = []

    # ------------------------------------------------------------------------------------------------------ persistenza
    def load(self) -> List[dict]:
        """Rilegge il file. Assente, illeggibile o non-lista -> vuota."""
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding='utf-8'))
                self.entries = loaded if isinstance(loaded, list) else []
            else:
                self.entries = []
        except Exception:
            self.entries = []
        return self.entries

    def save(self) -> bool:
        """Scrive il file (atomico: temporaneo + replace; se non riesce, scrittura diretta). False se non riesce."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self.entries, ensure_ascii=False, indent=2)
            tmp = self.path.with_suffix(self.path.suffix + f'.{os.getpid()}.tmp')
            try:
                tmp.write_text(data, encoding='utf-8')
                tmp.replace(self.path)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                self.path.write_text(data, encoding='utf-8')
            return True
        except Exception:
            return False

    def append(self, entry: dict) -> bool:
        """Aggiunge una voce in coda e salva."""
        self.entries.append(entry)
        return self.save()

    # ------------------------------------------------------------------------------------------------------------ vista
    def total_count(self) -> int:
        return len(self.entries)

    def stats(self) -> HistoryStats:
        return HistoryStats(len(self.entries), sum(e.get('size_bytes', 0) for e in self.entries),
                            int(sum(e.get('duration_seconds', 0) for e in self.entries)))

    def rows(self) -> List[HistoryRow]:
        return [row_of(e) for e in self.entries]

    def search(self, query: str) -> List[int]:
        """Indici delle voci che corrispondono alla ricerca (tutte se vuota)."""
        return [i for i, e in enumerate(self.entries) if matches(query, row_of(e))]
