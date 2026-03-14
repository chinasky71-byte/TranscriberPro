# -*- coding: utf-8 -*-
"""
Library Scanner - Verifica Sottotitoli
Controlla la presenza di sottotitoli italiani:
  1. File esterni (.srt, .sub, .ass, .ssa, .vtt) nella stessa cartella
     - Pattern Bazarr: VideoName.it.srt, VideoName.it.cc.srt, VideoName.ita.hi.srt, etc.
     - Pattern generici: tag italiani nel nome file
  2. Sottotitoli embedded nel file video (via ffprobe)
"""
import logging
import re
import subprocess
import json
from pathlib import Path
from typing import Tuple

from library_scanner.config import Config

logger = logging.getLogger(__name__)

# Codici lingua italiana riconosciuti
_ITALIAN_CODES = {"ita", "it", "italian", "italiano"}

# Qualificatori validi dopo il codice lingua (Bazarr, Sonarr, Radarr)
_SUB_QUALIFIERS = {"cc", "hi", "sdh", "forced", "full", "regular", "closedcaptions"}

# Pattern regex per matching flessibile del suffisso lingua
# Cattura: separatore + codice_lingua + (opzionale: separatore + qualificatore)*
# Esempi matchati: .it  .ita  .it.cc  .ita.hi  .it.cc.forced  _ita  -it.sdh
_LANG_SUFFIX_RE = re.compile(
    r'^[.\-_]'                         # separatore iniziale (. - _)
    r'(?P<lang>' + '|'.join(_ITALIAN_CODES) + r')'  # codice lingua
    r'(?:[.\-_](?:' + '|'.join(_SUB_QUALIFIERS) + r'))*'  # zero o più qualificatori
    r'$',                              # fine dello stem (l'estensione è già rimossa)
    re.IGNORECASE
)


def check_external_subtitles(video_path: Path) -> bool:
    """
    Verifica se esiste un file di sottotitoli italiano esterno
    nella stessa cartella del video.

    Strategia di rilevamento (in ordine di priorità):

    1. SAME-NAME MATCH (pattern Bazarr/Sonarr/Radarr):
       Il file sottotitolo ha lo STESSO nome base del video + suffisso lingua.
       Questo è il metodo più affidabile e previene falsi positivi.
       Esempi:
         Video:  The.Movie.2024.1080p.BluRay.mkv
         Match:  The.Movie.2024.1080p.BluRay.it.srt          ✓
         Match:  The.Movie.2024.1080p.BluRay.ita.srt         ✓
         Match:  The.Movie.2024.1080p.BluRay.it.cc.srt       ✓
         Match:  The.Movie.2024.1080p.BluRay.ita.hi.srt      ✓
         Match:  The.Movie.2024.1080p.BluRay.it.sdh.srt      ✓
         Match:  The.Movie.2024.1080p.BluRay.italian.srt     ✓
         Match:  The.Movie.2024.1080p.BluRay_ita.srt         ✓
         Match:  The.Movie.2024.1080p.BluRay-it.forced.srt   ✓

    2. TAG MATCH (fallback per naming non standard):
       Il nome del file sottotitolo contiene un tag italiano riconoscibile.
       Meno preciso ma cattura casi particolari.
       Esempi:
         sottotitoli_italiano.srt
         film.italian.sub

    Returns:
        True se trovato almeno un sottotitolo italiano esterno
    """
    video_dir = video_path.parent
    video_stem = video_path.stem  # nome senza estensione video
    video_stem_lower = video_stem.lower()

    try:
        for item in video_dir.iterdir():
            if not item.is_file():
                continue

            # Verifica estensione sottotitolo
            if item.suffix.lower() not in Config.SUBTITLE_EXTENSIONS:
                continue

            item_stem_lower = item.stem.lower()

            # ===== STRATEGIA 1: Same-name match (Bazarr pattern) =====
            # Il nome del sub inizia con lo stesso stem del video
            if item_stem_lower.startswith(video_stem_lower):
                remainder = item_stem_lower[len(video_stem_lower):]

                # Caso 1a: nome identico (es. Movie.srt per Movie.mkv)
                # Non possiamo assumere che sia italiano senza tag, skip

                # Caso 1b: ha un suffisso lingua dopo lo stem
                if remainder and _LANG_SUFFIX_RE.match(remainder):
                    logger.debug(
                        f"  Sottotitolo italiano esterno (same-name): {item.name}"
                    )
                    return True

            # ===== STRATEGIA 2: Regex match nel nome del file sottotitolo =====
            # Copre pattern con spazi, parentesi quadre e varianti non-Bazarr
            if Config.ITALIAN_FILENAME_RE.search(item.name):
                logger.debug(
                    f"  Sottotitolo italiano esterno (regex match): {item.name}"
                )
                return True

    except PermissionError:
        logger.warning(f"  Permesso negato leggendo directory: {video_dir}")
    except OSError as e:
        logger.warning(f"  Errore leggendo directory {video_dir}: {e}")

    return False


def check_embedded_subtitles(video_path: Path) -> Tuple[bool, str]:
    """
    Verifica se il file video contiene sottotitoli italiani embedded.
    Usa ffprobe per analizzare gli stream.

    Returns:
        Tuple[bool, str]: (ha_sottotitoli_italiani, eventuale_errore)
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "s",  # Solo stream subtitle
            str(video_path)
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            err = result.stderr.strip()[:200] if result.stderr else "ffprobe error"
            return False, err

        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        if not streams:
            return False, ""

        for stream in streams:
            tags = stream.get("tags", {})

            # Controlla il campo language
            lang = tags.get("language", "").lower().strip()
            if lang in Config.ITALIAN_LANG_CODES:
                logger.debug(f"  Sottotitolo italiano embedded trovato (language={lang})")
                return True, ""

            # Controlla anche il campo title come fallback
            title = tags.get("title", "").lower().strip()
            for code in Config.ITALIAN_LANG_CODES:
                if code in title:
                    logger.debug(f"  Sottotitolo italiano embedded trovato (title={title})")
                    return True, ""

        # Fallback: stream presenti ma nessuno con tag di lingua riconoscibile.
        # Se il nome del video contiene indicatori italiani, è probabile che
        # i sottotitoli embedded siano italiani ma privi di metadati.
        if streams and Config.ITALIAN_FILENAME_RE.search(video_path.name):
            logger.debug(
                f"  Sottotitolo embedded senza tag, nome video suggerisce ITA: "
                f"{video_path.name}"
            )
            return True, ""

        return False, ""

    except subprocess.TimeoutExpired:
        return False, "ffprobe timeout (30s)"
    except json.JSONDecodeError as e:
        return False, f"ffprobe output non valido: {e}"
    except FileNotFoundError:
        return False, "ffprobe non trovato nel sistema"
    except Exception as e:
        return False, f"Errore ffprobe: {e}"


def check_all_subtitles(video_path: Path) -> dict:
    """
    Verifica completa sottotitoli per un file video.

    Returns:
        dict con chiavi: has_external, has_embedded, has_any, error
    """
    has_external = check_external_subtitles(video_path)
    has_embedded, error = check_embedded_subtitles(video_path)

    return {
        "has_external": has_external,
        "has_embedded": has_embedded,
        "has_any": has_external or has_embedded,
        "error": error
    }
