# -*- coding: utf-8 -*-
"""Metadati del file (TMDB) senza Qt: titolo mostrato sotto la locandina e ricerca della locandina.

Estratto da gui/services/metadata_service.py e da gui/workers.py::PosterLoaderWorker SENZA cambiare semantica (la GUI Qt li
usa; la web UI usera' gli stessi). Il client TMDB (`utils/tmdb_client.TMDBClient`) e' un parametro: nessuna rete in questo modulo.

Titolo mostrato («Nome show SxxExx» per le serie, solo il titolo per i film):
  - calcolato una volta per file e messo in cache; quello PROVVISORIO (anime con il solo numero assoluto, stagione non ancora
    risolta da TMDB) non si mette in cache e si rivaluta al massimo ogni 5 s (parse_filename scrive righe di debug);
  - season < 100: 'The.Corporation.720x480' non e' una stagione 720.
"""
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

PROVISIONAL_RECHECK_S = 5.0


class TitleResolver:
    def __init__(self, tmdb_client):
        # letto a ogni chiamata (mai copiato): chi lo sostituisce a runtime viene rispettato
        self.tmdb_client = tmdb_client
        self.cache: Dict[str, str] = {}
        # chiave -> (etichetta provvisoria, istante)
        self.provisional: Dict[str, Tuple[str, float]] = {}

    def clear(self) -> None:
        self.cache.clear()
        self.provisional.clear()

    def title_for(self, path: str, filename: str) -> str:
        key = path or filename
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        prov = self.provisional.get(key)
        now = time.monotonic()
        if prov is not None and (now - prov[1]) < PROVISIONAL_RECHECK_S:
            return prov[0]
        label = Path(filename or path).stem
        final = True
        try:
            parsed = self.tmdb_client.parse_filename(filename or Path(path).name)
            title = (parsed.get('title') or '').strip()
            if title:
                season, episode = parsed.get('season'), parsed.get('episode')
                absolute = parsed.get('absolute')
                # season < 100: 'The.Corporation.720x480' non e' una stagione 720
                if parsed.get('type') == 'tv' and season is not None and episode is not None and int(season) < 100:
                    label = f"{title} S{int(season):02d}E{int(episode):02d}"
                elif parsed.get('type') == 'tv' and absolute is not None:
                    resolved = self.tmdb_client.resolved_episode(title, absolute, parsed.get('year'))
                    if resolved:
                        label = f"{title} S{int(resolved[0]):02d}E{int(resolved[1]):02d}"
                    else:
                        label = f"{title} E{int(absolute):02d}"
                        final = False
                else:
                    label = title
            elif parsed.get('type') == 'movie':
                # titolo vuoto (es. '1917.2019.1080p'): stessa pulizia usata per la ricerca, non il nome grezzo
                label = (self.tmdb_client._clean_title(self.tmdb_client._pre_clean_title(label)) or label)
        except Exception:
            pass
        if final:
            self.cache[key] = label
            self.provisional.pop(key, None)
        else:
            self.provisional[key] = (label, now)
        return label


@dataclass(frozen=True)
class PosterResult:
    status: str                      # 'found' | 'none' | 'cancelled'
    path: Optional[Path] = None      # file locale della locandina (solo 'found')
    title: str = ''


def find_poster(video_path: str, tmdb_client, is_cancelled: Callable[[], bool] = lambda: False) -> PosterResult:
    """Cerca le informazioni del file su TMDB e scarica la locandina (1-2 s + 1-3 s di rete). Gli errori di rete risalgono:
    chi chiama li tratta come «nessuna locandina». `is_cancelled` si interroga dopo ogni passo lento."""
    if is_cancelled():
        return PosterResult('cancelled')
    # nome COMPLETO (con estensione): parse_filename fa gia' .stem, un secondo .stem toglierebbe il suffisso finale
    # ('.E26' in 'Titolo.E26') e il nome verrebbe cercato come film
    media_info = tmdb_client.get_media_info(Path(video_path).name)
    if is_cancelled():
        return PosterResult('cancelled')
    if media_info and 'poster_path' in media_info and media_info['poster_path']:
        local = tmdb_client.download_poster(media_info['poster_path'], media_info['title'])
        if is_cancelled():
            return PosterResult('cancelled')
        if local and local.exists():
            return PosterResult('found', local, media_info['title'])
    return PosterResult('none')
