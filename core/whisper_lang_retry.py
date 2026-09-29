"""
Ritrascrizione dei segmenti/vuoti "sospetti" di Faster-Whisper con rilevamento lingua (v1.30.0).
File: core/whisper_lang_retry.py

Stesso principio di core/qwen3_lang_retry.py (v1.29.0, Qwen3-ASR), applicato al motore Faster-Whisper: quando
Whisper trascrive con la lingua FORZATA (traccia audio dichiarata in una lingua), le parti in un'altra lingua
(quasi sempre canzoni/citazioni in inglese) spariscono o escono storpiate. Un segmento sospetto viene
ritrascritto con rilevamento lingua e tenuto solo se la lingua rilevata è diversa, non vuota e nell'insieme
accettato (di default solo l'inglese: l'unica lingua validata su materiale reale, v. sotto).

Sviluppato e misurato su 9 clip reali di X Factor (mt_eval/xfactor_canto/, 28-29/09/2026), dove la stessa
correzione è nata per Qwen3-ASR. Due differenze necessarie, trovate proprio lì, che lo rendono NON un porting
1:1 di qwen3_lang_retry:

1. **Vuoti fra i segmenti**: il VAD di Faster-Whisper spesso non rileva ALCUNA voce sul canto (specie se
   sovrapposto a musica): interi tratti (misurati fino a 78 s) restano ASSENTI dai segmenti, non "vuoti con
   testo vuoto" come i chunk di Qwen3 (che copre sempre tutto l'audio a chunk fissi). Un filtro che guarda solo
   i segmenti esistenti non li vede mai. Si esaminano quindi anche i vuoti fra un segmento e il successivo (e
   prima del primo/dopo l'ultimo): se contengono voce, sono trattati come un segmento sospetto "vuoto".
2. **Vuoti lunghi**: un vuoto ritrascritto in un'UNICA chiamata (clip "Bang Bang", rap veloce su base ritmata:
   vuoto di 114 s) ha recuperato solo 2 righe su un'intera strofa — lo stesso VAD, riapplicato in blocco sul
   vuoto, ha comunque scartato la maggior parte del rap. I vuoti più lunghi di MAX_GAP_CHUNK_S vengono quindi
   divisi in sotto-finestre prima della ritrascrizione (più chiamate, più occasioni per il VAD di agganciarsi),
   con parametri VAD più permissivi di quelli della trascrizione forzata: dentro un vuoto già isolato sappiamo
   che c'è voce (misurata con voice_stats prima di ritrascrivere), quindi conviene rischiare qualche falso
   positivo di silenzio pur di non perdere il canto.

Verificato: sulla clip con l'allucinazione trovata inizialmente (testo italiano vero sovrascritto con testo
polacco insensato da un approccio SENZA filtro) questo modulo lascia il segmento italiano invariato (non è
sospetto) e recupera invece i vuoti dove il canto mancava del tutto.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional, Tuple

from core.qwen3_lang_retry import DEFAULT_ACCEPT_LANGS, is_suspect, voice_stats  # noqa: F401 (re-esportati)

MIN_GAP_S = 1.5          # sotto, un vuoto fra due segmenti e' una pausa normale, non esaminato
MIN_GAP_VOICE_S = 1.0    # voce minima nel vuoto perche' valga la pena tentare un rilevamento
PAD_S = 0.15             # margine (s) attorno a un SEGMENTO nella fetta ritagliata (parole sul bordo)
MAX_GAP_CHUNK_S = 30.0   # vuoti piu' lunghi vengono divisi in sotto-finestre per la ritrascrizione (v. punto 2)
# Parametri VAD per le ritrascrizioni: piu' permissivi di quelli della trascrizione forzata (500ms/0.5), perche'
# qui sappiamo gia' (voice_stats) che c'e' voce nella fetta: preferiamo qualche falso positivo di silenzio a
# perdere ancora il canto.
RETRY_VAD_PARAMS = dict(min_silence_duration_ms=250, threshold=0.35)


def decide_whisper(forced_iso: Optional[str], detected_iso: Optional[str], detected_text: str,
                   accept_langs=DEFAULT_ACCEPT_LANGS) -> Tuple[bool, Optional[str], str]:
    """Come core.qwen3_lang_retry.decide, adattata a Faster-Whisper: la lingua rilevata è già un codice
    ISO 639-1 (niente mappa nomi), e non c'è un ForcedAligner separato da controllare (Whisper allinea
    qualunque lingua trascriva). Ritorna (accetta, iso_rilevata, motivo)."""
    if not (detected_text or '').strip():
        return False, detected_iso, 'rilevamento senza testo (silenzio/rumore)'
    if not detected_iso:
        return False, None, 'rilevamento lingua inconclusivo'
    if detected_iso == forced_iso:
        return False, detected_iso, "rilevata = lingua forzata: si tiene l'originale"
    if accept_langs is not None and detected_iso not in accept_langs:
        return False, detected_iso, f"lingua '{detected_iso}' non fra quelle accettate ({sorted(accept_langs)})"
    return True, detected_iso, f"lingua rilevata '{detected_iso}' != forzata '{forced_iso}': si tiene la ritrascrizione"


def _timeline(segs, total_dur: float, min_gap_s: float = MIN_GAP_S, max_gap_chunk_s: float = MAX_GAP_CHUNK_S):
    """Unità da esaminare in ordine: ('seg', segmento) e ('gap', inizio, fine) per i vuoti fra i segmenti (e
    prima del primo/dopo l'ultimo) più lunghi di min_gap_s; i vuoti più lunghi di max_gap_chunk_s sono divisi
    in sotto-finestre consecutive (punto 2 del modulo)."""
    def split_gap(g0, g1):
        n = g1 - g0
        if n <= max_gap_chunk_s:
            yield ('gap', g0, g1)
            return
        k = int(n // max_gap_chunk_s) + (1 if n % max_gap_chunk_s else 0)
        step = n / k
        for i in range(k):
            yield ('gap', g0 + i * step, g0 + (i + 1) * step if i < k - 1 else g1)

    out = []
    prev_end = 0.0
    for seg in segs:
        if seg.start - prev_end > min_gap_s:
            out.extend(split_gap(prev_end, seg.start))
        out.append(('seg', seg))
        prev_end = max(prev_end, seg.end)
    if total_dur - prev_end > min_gap_s:
        out.extend(split_gap(prev_end, total_dur))
    return out


def apply(transcribe_fn: Callable, segs: list, x, sr: int, forced_iso: str, accept_langs,
         beam_size: int, log: Optional[Callable] = None, records: Optional[List[dict]] = None) -> list:
    """Esamina segmenti e vuoti (v. docstring del modulo) e ritorna la lista di segmenti risultante (originali +
    sostituzioni/aggiunte), ordinata per tempo. `transcribe_fn` è `model.transcribe` (o equivalente): chiamato
    SOLO con language=None (rilevamento) sulle fette ritagliate — mai in ricorsione sulla chiamata forzata, che
    è già stata fatta da chi chiama questa funzione. `x`/`sr`: stesso audio (array mono) della chiamata forzata.
    """
    total_dur = len(x) / float(sr) if sr else 0.0
    out = []
    n_suspect = n_retried = 0
    for kind, *rest in _timeline(segs, total_dur):
        if kind == 'seg':
            seg = rest[0]
            text = (seg.text or '').strip()
            off = max(0.0, seg.start - PAD_S)
            i0, i1 = int(off * sr), min(len(x), int((seg.end + PAD_S) * sr))
        else:
            g0, g1 = rest
            text = ''
            off, i0, i1 = g0, int(g0 * sr), min(len(x), int(g1 * sr))
        if i1 <= i0:
            if kind == 'seg':
                out.append(seg)
            continue
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
                tmp = Path(tf.name)
            import soundfile as sf
            sf.write(str(tmp), x[i0:i1], sr)
            st = voice_stats(tmp)
            if kind == 'gap' and st['voice_s'] < MIN_GAP_VOICE_S:
                continue        # vuoto senza voce sufficiente: non e' materiale perso, si salta
            susp, why = is_suspect(text, st['voice_s'], forced_iso)
            if not susp:
                if kind == 'seg':
                    out.append(seg)
                continue
            n_suspect += 1
            new_segs, new_info = transcribe_fn(str(tmp), language=None, word_timestamps=True, vad_filter=True,
                                               vad_parameters=RETRY_VAD_PARAMS, beam_size=beam_size, batch_size=1)
            new_segs = list(new_segs)
            new_text = ' '.join((s.text or '').strip() for s in new_segs).strip()
            detected = getattr(new_info, 'language', None)
            ok, iso, reason = decide_whisper(forced_iso, detected, new_text, accept_langs)
            if not ok:
                if kind == 'seg':
                    out.append(seg)
                if records is not None:
                    records.append({'kind': kind, 'start': round(off, 2), 'suspect_reason': why,
                                    'detected': iso, 'decision_reason': reason})
                continue
            n_retried += 1
            if log:
                log(f"  🌐 [{kind}] {off:.1f}s: ritrascritto in '{iso}' (forzato '{forced_iso}', {why})")
            if records is not None:
                records.append({'kind': kind, 'start': round(off, 2), 'suspect_reason': why,
                                'detected': iso, 'decision': 'ritrascritto', 'text_after': new_text})
            for ns in new_segs:
                words = [SimpleNamespace(start=w.start + off, end=w.end + off, word=w.word)
                        for w in (ns.words or [])]
                out.append(SimpleNamespace(start=ns.start + off, end=ns.end + off, text=ns.text, words=words))
        except Exception as e:
            if log:
                log(f"  ⚠️ [whisper-lang-retry] {kind} {off:.1f}s: {type(e).__name__}: {e}")
            if kind == 'seg':
                out.append(seg)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    out.sort(key=lambda s: s.start)
    if log and n_suspect:
        log(f"  🌐 Segmenti/vuoti sospetti: {n_suspect}, ritrascritti: {n_retried}")
    return out
