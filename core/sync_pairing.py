# -*- coding: utf-8 -*-
"""
Abbinamento video <-> SRT esterno per la coda multi-file del Subtitle Sync.
File: core/sync_pairing.py

Modulo PURO (solo libreria standard, nessun torch/PyQt): lo usano la GUI (tabella delle coppie proposte),
il worker di coda e i test. Contiene anche `default_output_path`, l'UNICA definizione del percorso di
output del sync (SubtitleSynchronizer.__init__ la richiama: tabella e file scritto coincidono per costruzione).

Perche' tanta cura sugli episodi: "Show.S01E01" e "Show.S01E02" hanno una somiglianza testuale altissima,
ma abbinare l'SRT dell'episodio sbagliato produce un file sincronizzato sul video sbagliato senza alcun
errore visibile. Se entrambi i nomi portano un codice episodio (SxxEyy oppure NxMM) e i codici DIFFERISCONO,
il punteggio e' 0.
"""
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

VIDEO_EXT = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v')

# Suffissi di lingua che il nome dell'output ignora (es. "film.it.srt" -> "film.synced.it.srt")
_KNOWN_LANG_SUFFIXES = {
    'it', 'ita', 'italian', 'en', 'eng', 'english',
    'es', 'spa', 'fr', 'fre', 'fra', 'de', 'deu', 'ger',
    'pt', 'por', 'ru', 'rus', 'ja', 'jpn',
}
# Rumore tipico dei nomi di release, ininfluente sull'identita' del titolo
_NOISE = {
    '480p', '576p', '720p', '1080p', '2160p', '4k', 'uhd', 'hdr', 'sdr', 'x264', 'x265', 'h264', 'h265', 'hevc',
    'avc', 'web', 'webrip', 'webdl', 'web-dl', 'bluray', 'bdrip', 'brrip', 'dvdrip', 'hdtv', 'remux', 'proper',
    'repack', 'extended', 'unrated', 'internal', 'multi', 'dual', 'ac3', 'aac', 'dts', 'ddp', 'dd', 'atmos',
    'ita', 'eng', 'sub', 'subs', 'synced', 'forced', 'sdh', 'yify', 'rarbg', 'ntb', 'amzn', 'nf', 'dsnp', 'hmax',
}
_EP_RE = [re.compile(r'[sS](\d{1,2})[\s._-]?[eE](\d{1,3})'), re.compile(r'(?<!\d)(\d{1,2})x(\d{2,3})(?!\d)')]
DEFAULT_THRESHOLD = 0.60


def default_output_path(external_srt_path) -> Path:
    """Percorso dell'SRT sincronizzato: <cartella dell'SRT esterno>/<stem senza suffisso lingua>.synced.it.srt.
    Deriva dall'SRT esterno (non dal video): due SRT omonimi in cartelle diverse scrivono in posti diversi,
    ma due SRT con lo stesso nome nella STESSA cartella (o l'unione di piu' coppie sullo stesso SRT) collidono."""
    srt = Path(external_srt_path)
    stem = srt.stem
    if '.' in stem:
        base, lang = stem.rsplit('.', 1)
        if lang.lower() in _KNOWN_LANG_SUFFIXES:
            stem = base
    return srt.parent / f"{stem}.synced.it.srt"


def episode_key(name: str) -> Optional[str]:
    """'S01E02' / '1x02' -> '1x2'. None se il nome non porta un codice episodio."""
    for rx in _EP_RE:
        m = rx.search(name)
        if m:
            return f"{int(m.group(1))}x{int(m.group(2))}"
    return None


def normalize_stem(name: str) -> str:
    """Nome file -> stringa confrontabile: minuscolo, senza estensione, senza suffisso lingua finale, senza
    rumore di release, punteggiatura -> spazio. Il codice episodio resta (e' informazione)."""
    stem = Path(name).stem
    if '.' in stem:
        base, lang = stem.rsplit('.', 1)
        if lang.lower() in _KNOWN_LANG_SUFFIXES:
            stem = base
    s = stem.lower()
    s = re.sub(r"[\[\]\(\)\{\}_.\-]+", ' ', s)
    toks = [t for t in re.split(r'\s+', s) if t and t not in _NOISE]
    return ' '.join(toks)


def similarity(video_name: str, srt_name: str) -> float:
    """Punteggio 0..1. Episodi diversi (entrambi con codice) -> 0. Codice uguale -> bonus."""
    kv, ks = episode_key(video_name), episode_key(srt_name)
    if kv and ks and kv != ks:
        return 0.0
    a, b = normalize_stem(video_name), normalize_stem(srt_name)
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    if kv and ks and kv == ks:
        r = min(1.0, r + 0.15)
    elif bool(kv) != bool(ks):
        r *= 0.85     # uno solo dei due ha il codice episodio: meno affidabile
    return r


@dataclass
class Pair:
    video: Path
    srt: Optional[Path] = None
    score: float = 0.0
    output: Optional[Path] = None
    duplicate: bool = False           # stesso output di un'altra coppia
    note: str = ''
    include: bool = True

    def refresh_output(self) -> None:
        self.output = default_output_path(self.srt) if self.srt else None


def list_files(folder, exts: Sequence[str], recursive: bool = False) -> List[Path]:
    root = Path(folder)
    it = root.rglob('*') if recursive else root.glob('*')
    exts = tuple(e.lower() for e in exts)
    return sorted((p for p in it if p.is_file() and p.suffix.lower() in exts), key=lambda p: str(p).lower())


def pair_files(videos: Sequence[Path], srts: Sequence[Path], threshold: float = DEFAULT_THRESHOLD):
    """Abbinamento GLOBALE e deterministico (non greedy per video): tutte le coppie candidate con punteggio >=
    soglia si ordinano per punteggio decrescente (poi per nome) e si assegnano se ne' il video ne' l'SRT sono
    gia' presi. Restituisce (coppie ordinate per video, SRT non abbinati). Un video senza SRT compare con
    srt=None. Un SRT gia' sincronizzato (.synced.) non si propone mai come sorgente."""
    srts = [Path(s) for s in srts if '.synced.' not in Path(s).name.lower()]
    cands = []
    for v in videos:
        for s in srts:
            sc = similarity(Path(v).name, Path(s).name)
            if sc >= threshold:
                cands.append((sc, str(v).lower(), str(s).lower(), Path(v), Path(s)))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_v, used_s, chosen = set(), set(), {}
    for sc, _kv, _ks, v, s in cands:
        if v in used_v or s in used_s:
            continue
        used_v.add(v)
        used_s.add(s)
        chosen[v] = (s, sc)
    pairs: List[Pair] = []
    for v in sorted((Path(x) for x in videos), key=lambda p: str(p).lower()):
        if v in chosen:
            s, sc = chosen[v]
            p = Pair(video=v, srt=s, score=sc)
            p.refresh_output()
            if sc < 0.75:
                p.note = 'abbinamento incerto: controllare'
        else:
            p = Pair(video=v, note='nessun SRT abbinato', include=False)
        pairs.append(p)
    leftovers = sorted((s for s in srts if s not in used_s), key=lambda p: str(p).lower())
    mark_duplicates(pairs)
    return pairs, leftovers


def mark_duplicates(pairs: Sequence[Pair]) -> int:
    """Segna `duplicate` sulle coppie che scriverebbero sullo stesso file di output. Ritorna quante sono."""
    seen: Dict[str, int] = {}
    for p in pairs:
        if p.output is not None and p.include:
            seen[str(p.output).lower()] = seen.get(str(p.output).lower(), 0) + 1
    n = 0
    for p in pairs:
        p.duplicate = bool(p.output is not None and p.include and seen.get(str(p.output).lower(), 0) > 1)
        n += p.duplicate
    return n


def runnable(pairs: Sequence[Pair]) -> List[Pair]:
    """Coppie da eseguire: incluse, con SRT, senza output duplicato."""
    return [p for p in pairs if p.include and p.srt is not None and not p.duplicate]
