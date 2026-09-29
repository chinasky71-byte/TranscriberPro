"""
Ritrascrizione dei chunk "sospetti" di Qwen3-ASR con rilevamento lingua (v1.29.0).
File: core/qwen3_lang_retry.py

Problema (trovato su X Factor, mt_eval/xfactor_canto/, 28-29/09/2026): Qwen3AsrEngine.transcribe_chunks forza la
lingua della traccia audio su OGNI chunk, anche l'aligner lavora in quella lingua, e un chunk con testo vuoto
viene scartato in silenzio. Le parti cantate/parlate in una lingua diversa (quasi sempre inglese: canzoni,
citazioni) spariscono o escono come testo storpiato nella lingua forzata ("Quanto è bella, Bruno!" al posto di
"No more tears, my heart is dry.").

Verificato su 9 clip reali (mt_eval/xfactor_canto/review/CONFRONTO.md): la ritrascrizione mirata recupera il
canto inglese vero, non introduce rumore fuori dai chunk toccati (0 casi), e lascia invariato il parlato/canto
nella lingua giusta (clip di controllo italiana bit-per-bit identica).

Logica (pura, senza torch/modello — solo qwen3_asr_engine.py la usa):
  1. is_suspect(text, voice_s, forced_iso): il chunk forzato è sospetto se il testo è vuoto, se ha pochissime
     parole rispetto alla voce presente (canto/parlato non trascritto), o se è pieno di parole inglesi comuni
     pur essendo forzato in un'altra lingua (l'ASR a volte scrive l'inglese così com'è, ma l'aligner nella
     lingua sbagliata lo allinea male).
  2. Se sospetto: una chiamata di solo rilevamento lingua (LID, senza timestamp).
  3. decide(...): la ritrascrizione si tiene SOLO se la lingua rilevata è diversa da quella forzata, supportata
     dal ForcedAligner, e nell'insieme delle lingue accettate (di default solo l'inglese: è l'unica validata,
     v. sotto). Il testo ritrascritto deve anche non essere vuoto.

Perché solo l'inglese per default: il LID di Qwen3 su applausi/rumore/musica senza voce a volte rileva lingue
come cinese/giapponese/coreano/spagnolo con testo ALLUCINATO (non silenzio → non scartato dal passo 2). Una prova
con `decide()` senza questo filtro (mt_eval/xfactor_canto/, braccio Whisper "multilingual" senza filtro) ha
sovrascritto parlato italiano VERO con testo polacco insensato. L'inglese è l'unica lingua "estranea" validata
su materiale reale (canzoni), quindi resta l'unica accettata finché non si misura altro; configurabile con
`qwen3_lang_retry_accept_langs`.

Soglie: STIME (non tarate su un banco dedicato, solo osservate su X Factor). `qwen3_lang_retry_enabled=False`
disattiva tutto (nessuna chiamata in più, comportamento identico a prima).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Frame RMS da 50 ms: abbastanza corto da seguire sillabe e pause brevi.
FRAME_S = 0.05
# Soglia "voce" in dBFS sul file del chunk (la traccia vocals di Demucs). Broadcast/film
# tipicamente normalizzati; parlato e canto nel vocals stanno di solito fra -30 e -12 dBFS,
# silenzio/residui musicali sotto -45. Margine sul parlato sommesso.
VOICE_DB = -40.0
# Parole per secondo di VOCE sotto cui il chunk è sospetto (parlato tipico ~2,5-3,5/s,
# canto ben trascritto ~1-2/s; sotto 0,6 la voce non è quasi per niente diventata testo).
MAX_WPS = 0.6
# Secondi di voce minimi perché la regola parole/s valga (sotto, la stima è troppo rumorosa:
# "Grazie!" + applausi è normale).
MIN_VOICE_S = 4.0
# Testo forzato ma pieno di parole inglesi comuni: quante ne servono almeno, e che quota
# minima delle parole del chunk devono essere (indipendente dalla lingua forzata).
EN_HITS_MIN = 3
EN_HITS_RATIO = 0.34
# Lingue che la ritrascrizione può introdurre. V. motivazione sopra: solo l'inglese è
# validato su materiale reale; configurabile via 'qwen3_lang_retry_accept_langs'.
DEFAULT_ACCEPT_LANGS = frozenset({'en'})

EN_WORDS = frozenset("""
    the and you your you're yours i'm i've i'll i'd it's that's don't can't won't
    is are was were be been am my mine we our us they them their he she his her him
    to of on at for with from by up out down off over into this that these those
    what when where why who how all just know now never ever always love baby oh yeah
    feel heart like got get want need let gonna wanna way day night time life world
    tonight say said tell see look keep make take give go going coming back
    there here then than some one more still only can could would should will
    dream hold fire alone again tell think but not do does did have has had
""".split())

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def words_of(text: str) -> List[str]:
    t = (text or '').lower().replace('’', "'")
    return [w.strip("'") for w in _WORD_RE.findall(t) if w.strip("'")]


def voice_stats(path, db_threshold: float = VOICE_DB, frame_s: float = FRAME_S) -> Dict[str, float]:
    """Secondi di voce (frame RMS > soglia dBFS) e durata del file. I chunk sono WAV float32
    (torchaudio): serve soundfile, il modulo `wave` della stdlib non li legge."""
    import numpy as np
    import soundfile as sf
    x, sr = sf.read(str(path), dtype='float32', always_2d=True)
    x = x.mean(axis=1)
    dur = len(x) / float(sr) if sr else 0.0
    n = max(1, int(round(sr * frame_s)))
    nf = len(x) // n
    if nf == 0:
        return {'voice_s': 0.0, 'dur_s': round(dur, 3)}
    fr = x[:nf * n].reshape(nf, n).astype(np.float64)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    db = 20.0 * np.log10(np.maximum(rms, 1e-6))
    return {'voice_s': round(float((db > db_threshold).sum()) * n / sr, 3), 'dur_s': round(dur, 3)}


def is_suspect(text: str, voice_s: float, forced_iso: Optional[str]) -> Tuple[bool, str]:
    """Il chunk (forzato su forced_iso) va ritrascritto con rilevamento lingua? -> (sospetto, motivo)."""
    t = (text or '').strip()
    if not t:
        # Il chunking parte da intervalli non silenziosi: un chunk vuoto è quasi sempre voce
        # non trascritta (il motore la scarta senza dirlo, v. transcribe_chunks).
        return True, 'testo vuoto'
    n = len(words_of(t))
    if voice_s >= MIN_VOICE_S and n / voice_s < MAX_WPS:
        return True, f'{n} parole su {voice_s:.1f}s di voce ({n / voice_s:.2f}/s < {MAX_WPS})'
    if forced_iso != 'en':
        en = sum(w in EN_WORDS for w in words_of(t))
        if en >= EN_HITS_MIN and en >= EN_HITS_RATIO * max(1, n):
            return True, f'testo forzato pieno di parole inglesi ({en}/{n})'
    return False, ''


def decide(forced_iso: Optional[str], lid_language_name: Optional[str], lid_text: str,
           name_to_iso: Dict[str, str], aligner_langs, accept_langs=DEFAULT_ACCEPT_LANGS
           ) -> Tuple[bool, Optional[str], str]:
    """Tenere la ritrascrizione con rilevamento lingua? -> (accetta, iso_rilevata, motivo)."""
    first = (lid_language_name or '').split(',')[0].strip()
    iso = name_to_iso.get(first) if first else None
    if not (lid_text or '').strip():
        return False, iso, 'LID senza testo (silenzio/rumore)'
    if iso is None:
        return False, None, f"LID inconclusivo ({lid_language_name!r})"
    if iso == forced_iso:
        return False, iso, "LID = lingua forzata: si tiene l'originale"
    if iso not in aligner_langs:
        return False, iso, f"lingua '{iso}' non supportata dal ForcedAligner"
    if accept_langs is not None and iso not in accept_langs:
        return False, iso, f"lingua '{iso}' non fra quelle accettate ({sorted(accept_langs)})"
    return True, iso, f"lingua rilevata '{iso}' != forzata '{forced_iso}': si tiene la ritrascrizione"
