"""
Forced Aligner
File: core/aligner.py

Riallinea i word timestamps di Faster-Whisper usando modelli wav2vec2,
ottenendo precisione a livello di fonema per sottotitoli di qualità
broadcast/cinema.

Funzionamento:
- Dopo la trascrizione Whisper, carica un modello wav2vec2 per la lingua
  rilevata e riallinea ogni parola.
- STRUTTURA: i segmenti restano quelli di Whisper. whisperx.align divide da
  solo ogni segmento in frasi (nltk punkt): adottare quell'output moltiplica i
  segmenti (es. 678 -> 1696) e crea blocchi-lampo. Si allinea quindi UN segmento
  Whisper per volta e si copiano soltanto i tempi sulle parole Whisper.
- GUARDIA: un tempo allineato viene accettato solo se resta entro
  ALIGN_MAX_SHIFT_S dal tempo Whisper e la parola non diventa più lunga di
  max(ALIGN_MAX_WORD_S, 2 x durata Whisper); altrimenti si tiene il tempo
  Whisper. Se numero/testo delle parole non coincidono, l'intero segmento
  resta com'è (A/B 24/09/2026: 5 segmenti su 169).
- Se la lingua non è supportata, restituisce i segmenti originali intatti.

VRAM: ~1-1.5GB. Progettato per coesistere con Whisper in VRAM (~5GB totali).
"""
from __future__ import annotations
import re
import torch
from typing import List, Dict, Optional, Callable
from utils.translations import tr


# Override modello: lingue per cui vogliamo un modello specifico
# invece di quello che whisperx selezionerebbe di default.
#
# Per qualità broadcast/cinema usiamo modelli XLSR-53 large (~1.2GB).
# whisperx default per italiano = VOXPOPULI_ASR_BASE_10K_IT (torchaudio, ~100MB, base).
MODEL_OVERRIDES: Dict[str, str] = {
    'it': 'jonatasgrosman/wav2vec2-large-xlsr-53-italian',
    'en': 'jonatasgrosman/wav2vec2-large-xlsr-53-english',
    'fr': 'jonatasgrosman/wav2vec2-large-xlsr-53-french',
    'es': 'jonatasgrosman/wav2vec2-large-xlsr-53-spanish',
}

# Modello generico multilingua: usato come fallback per lingue senza
# modello specifico e senza supporto nativo in whisperx.
GENERIC_ALIGN_MODEL = 'facebook/wav2vec2-large-xlsr-53'

# Guardia sui tempi allineati (v. docstring del modulo).
ALIGN_MAX_SHIFT_S = 1.5
ALIGN_MAX_WORD_S = 1.5

_NORM_RE = re.compile(r"[^\w']+", re.UNICODE)


def _norm(word: str) -> str:
    return _NORM_RE.sub('', (word or '').lower())


class ForcedAligner:
    """Riallinea word timestamps con forced alignment via wav2vec2."""

    def __init__(self, log_callback: Optional[Callable] = None):
        self.log = log_callback or print
        self._model = None
        self._metadata = None
        self._device: Optional[str] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self, language_code: str, device: str) -> bool:
        """Carica modello wav2vec2 per la lingua specificata.

        Returns:
            True se caricato con successo.
            False se la lingua non è supportata (skip silenzioso).

        Raises:
            Exception per errori imprevisti (rete, disco, ecc.).
        """
        import whisperx

        kwargs: Dict = {'language_code': language_code, 'device': device}
        if language_code in MODEL_OVERRIDES:
            kwargs['model_name'] = MODEL_OVERRIDES[language_code]

        self.log(tr('al_loading_alignment_model_for').format(language_code=language_code))
        try:
            self._model, self._metadata = whisperx.load_align_model(**kwargs)
        except ValueError:
            # whisperx lancia ValueError per lingue senza modello wav2vec2 nativo.
            # Proviamo il modello generico multilingua come fallback.
            self.log(
                tr('al_no_native_model_for_falling').format(language_code=language_code, model=GENERIC_ALIGN_MODEL.split('/')[-1])
            )
            kwargs['model_name'] = GENERIC_ALIGN_MODEL
            try:
                self._model, self._metadata = whisperx.load_align_model(**kwargs)
            except Exception as e:
                self.log(
                    tr('al_forced_alignment_language_not_supported').format(language_code=language_code)
                )
                return False

        self._device = device
        model_id = getattr(self._model, 'name_or_path',
                           kwargs.get('model_name', GENERIC_ALIGN_MODEL))
        self.log(tr('al_aligner_loaded').format(model=model_id.split('/')[-1]))
        return True

    def align(self, segments: List[Dict], audio_path: str) -> List[Dict]:
        """Riallinea word timestamps con forced alignment.

        I segmenti in uscita sono gli STESSI di Whisper (stesso numero, stesso
        testo): cambiano solo start/end delle parole (e quindi del segmento),
        e solo quando la guardia li accetta.

        Args:
            segments:   Lista di segmenti con campo 'words' (output Whisper).
            audio_path: Path del file audio da allineare.

        Returns:
            Segmenti con word timestamps riallineati.
            In caso di errore restituisce i segmenti originali.
        """
        if self._model is None:
            return segments

        import whisperx

        audio = whisperx.load_audio(audio_path)

        result: List[Dict] = []
        n_seg_fallback = 0
        n_words = 0
        n_words_moved = 0
        for seg in segments:
            words = seg.get('words') or []
            if not words:
                result.append(seg)
                continue
            try:
                r = whisperx.align(
                    [{'start': seg['start'], 'end': seg['end'], 'text': seg['text']}],
                    self._model,
                    self._metadata,
                    audio,
                    self._device,
                    return_char_alignments=False,
                )
                aligned_words = [w for s in r.get('segments', []) for w in s.get('words', [])]
            except Exception:
                aligned_words = None

            new_seg, moved = self.remap_segment(seg, aligned_words)
            if moved is None:
                n_seg_fallback += 1
            else:
                n_words += len(words)
                n_words_moved += moved
            result.append(new_seg)

        self.log(
            tr('al_alignment_completed_words_realigned_segments').format(n_words_moved=n_words_moved, n_words=n_words, n_seg=len(result) - n_seg_fallback, n=len(result), n_seg_fallback=n_seg_fallback)
        )
        return result

    def unload(self) -> None:
        del self._model
        self._model = None
        self._metadata = None
        self._device = None
        import gc; gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ── Remap sui segmenti Whisper ───────────────────────────────────────────

    @staticmethod
    def _expand_to_whisper_words(orig_words: List[Dict], aligned_words: List[Dict]) -> List[Dict]:
        """Whisper spezza in piu' "parole" i token col trattino ("Uh" + "-huh.",
        "1" + "-2" + "-3"): le continuazioni NON hanno lo spazio iniziale,
        mentre whisperx divide solo sugli spazi. Raggruppa le parole Whisper
        per spazio iniziale; se i gruppi corrispondono 1:1 alle parole
        allineate, espande: gruppo di 1 parola -> parola allineata; gruppo di
        piu' parole -> voci senza tempi (restano quelli Whisper).
        Altrimenti restituisce aligned_words invariato."""
        if not orig_words or not (orig_words[0].get('word') or '')[:1].isspace():
            return aligned_words
        groups: List[List[Dict]] = []
        for o in orig_words:
            w = o.get('word') or ''
            if not groups or w[:1].isspace():
                groups.append([o])
            else:
                groups[-1].append(o)
        if len(groups) != len(aligned_words):
            return aligned_words
        out: List[Dict] = []
        for g, a in zip(groups, aligned_words):
            if _norm(''.join(o.get('word') or '' for o in g)) != _norm(a.get('word')):
                return aligned_words
            if len(g) == 1:
                out.append(a)
            else:
                out.extend({'word': o.get('word')} for o in g)
        return out

    @staticmethod
    def remap_segment(seg: Dict, aligned_words: Optional[List[Dict]]):
        """Copia sui dizionari parola di Whisper i tempi allineati accettati.

        Returns:
            (segmento, n_parole_spostate). n_parole_spostate è None se il
            segmento è rimasto interamente con i tempi Whisper (allineamento
            fallito o parole non corrispondenti).
        """
        orig_words = seg.get('words') or []
        if aligned_words is not None and len(aligned_words) != len(orig_words):
            aligned_words = ForcedAligner._expand_to_whisper_words(orig_words, aligned_words)
        if (aligned_words is None or len(aligned_words) != len(orig_words)
                or any(_norm(a.get('word')) != _norm(o.get('word'))
                       for a, o in zip(aligned_words, orig_words))):
            return seg, None

        new_words: List[Dict] = []
        moved_flags: List[bool] = []
        prev_end: Optional[float] = None
        for a, o in zip(aligned_words, orig_words):
            nw = dict(o)
            moved_here = False
            s, e = a.get('start'), a.get('end')
            ws, we = o.get('start'), o.get('end')
            if s is not None and e is not None and ws is not None and we is not None:
                if prev_end is not None and s < prev_end:
                    s = prev_end
                if (e >= s
                        and abs(s - ws) <= ALIGN_MAX_SHIFT_S
                        and abs(e - we) <= ALIGN_MAX_SHIFT_S
                        and (e - s) <= max(ALIGN_MAX_WORD_S, 2.0 * (we - ws))):
                    nw['start'], nw['end'] = float(s), float(e)
                    moved_here = True
            prev_end = nw['end'] if nw.get('end') is not None else prev_end
            new_words.append(nw)
            moved_flags.append(moved_here)

        # Una parola rifiutata dalla guardia tiene il tempo Whisper e puo'
        # sovrapporsi a una vicina spostata: si ripristinano i tempi Whisper
        # delle parole spostate coinvolte, finche' non restano nuove
        # sovrapposizioni (ogni giro azzera almeno un flag: termina sempre).
        changed = True
        while changed:
            changed = False
            for i in range(1, len(new_words)):
                p, c = new_words[i - 1], new_words[i]
                if ((moved_flags[i - 1] or moved_flags[i])
                        and p.get('end') is not None and c.get('start') is not None
                        and c['start'] < p['end']):
                    for j in (i - 1, i):
                        if moved_flags[j]:
                            new_words[j] = dict(orig_words[j])
                            moved_flags[j] = False
                    changed = True
        moved = sum(moved_flags)

        new_seg = dict(seg)
        new_seg['words'] = new_words
        starts = [w['start'] for w in new_words if w.get('start') is not None]
        ends = [w['end'] for w in new_words if w.get('end') is not None]
        if starts:
            new_seg['start'] = starts[0]
        if ends:
            new_seg['end'] = ends[-1]
        return new_seg, moved
