"""
Forced Aligner
File: core/aligner.py

Riallinea i word timestamps di Faster-Whisper usando modelli wav2vec2,
ottenendo precisione a livello di fonema per sottotitoli di qualità
broadcast/cinema.

Funzionamento:
- Dopo la trascrizione Whisper, carica un modello wav2vec2 per la lingua
  rilevata e riallinea ogni parola al millisecondo esatto.
- Per parole che il modello non riesce ad ancorare (nomi propri, termini
  rari), mantiene i timestamp originali di Whisper come fallback.
- Se la lingua non è supportata, restituisce i segmenti originali intatti.

VRAM: ~1-1.5GB. Progettato per coesistere con Whisper in VRAM (~5GB totali).
"""
from __future__ import annotations
import torch
from typing import List, Dict, Optional, Callable


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

        self.log(f"  📦 Caricamento modello alignment per '{language_code}'...")
        try:
            self._model, self._metadata = whisperx.load_align_model(**kwargs)
        except ValueError:
            # whisperx lancia ValueError per lingue senza modello wav2vec2 nativo.
            # Proviamo il modello generico multilingua come fallback.
            self.log(
                f"  ℹ️ Nessun modello nativo per '{language_code}' "
                f"— fallback modello generico ({GENERIC_ALIGN_MODEL.split('/')[-1]})"
            )
            kwargs['model_name'] = GENERIC_ALIGN_MODEL
            try:
                self._model, self._metadata = whisperx.load_align_model(**kwargs)
            except Exception as e:
                self.log(
                    f"  ⚠️ Forced alignment: lingua '{language_code}' non supportata — skip"
                )
                return False

        self._device = device
        model_id = getattr(self._model, 'name_or_path',
                           kwargs.get('model_name', GENERIC_ALIGN_MODEL))
        self.log(f"  ✅ Aligner caricato ({model_id.split('/')[-1]})")
        return True

    def align(self, segments: List[Dict], audio_path: str) -> List[Dict]:
        """Riallinea word timestamps con forced alignment.

        Per parole che Wav2Vec2 non riesce ad ancorare (nomi propri,
        termini rari), mantiene i timestamp originali di Whisper.

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

        try:
            result = whisperx.align(
                segments,
                self._model,
                self._metadata,
                audio,
                self._device,
                return_char_alignments=False,
            )
            aligned = result.get('segments', segments)
        except Exception as e:
            self.log(f"  ⚠️ Alignment fallito: {e} — timestamp Whisper mantenuti")
            return segments

        # Fallback per parole non ancorate (nomi propri, ecc.)
        aligned = self._restore_missing_timestamps(segments, aligned)

        words_aligned = sum(
            1 for seg in aligned
            for w in seg.get('words', [])
            if w.get('start') is not None
        )
        words_total = sum(len(seg.get('words', [])) for seg in aligned)
        self.log(
            f"  ✅ Alignment completato: "
            f"{words_aligned}/{words_total} parole ancorate"
        )
        return aligned

    def unload(self) -> None:
        del self._model
        self._model = None
        self._metadata = None
        self._device = None
        import gc; gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ── Restore fallback ─────────────────────────────────────────────────────

    def _restore_missing_timestamps(
        self,
        original: List[Dict],
        aligned: List[Dict],
    ) -> List[Dict]:
        """Ripristina timestamp Whisper per parole non ancorate da Wav2Vec2.

        Gestisce anche la mancata corrispondenza del numero di segmenti
        (whisperx non dovrebbe alterare la struttura, ma per sicurezza).
        """
        if len(aligned) != len(original):
            # Non possiamo fare un mapping sicuro: fallback sui segmenti allineati as-is
            self.log(
                f"  ⚠️ Alignment: conteggio segmenti non corrisponde "
                f"({len(aligned)} vs {len(original)}) — nessun fallback parola"
            )
            return aligned

        for orig_seg, aln_seg in zip(original, aligned):
            orig_words = orig_seg.get('words', [])
            aln_words  = aln_seg.get('words', [])

            for wi, aln_word in enumerate(aln_words):
                missing_start = aln_word.get('start') is None
                missing_end   = aln_word.get('end')   is None
                if not (missing_start or missing_end):
                    continue
                if wi < len(orig_words):
                    orig_word = orig_words[wi]
                    if missing_start:
                        aln_word['start'] = orig_word.get('start')
                    if missing_end:
                        aln_word['end'] = orig_word.get('end')

            # Aggiorna start/end del segmento dai timestamps delle parole
            valid_starts = [w['start'] for w in aln_words if w.get('start') is not None]
            valid_ends   = [w['end']   for w in aln_words if w.get('end')   is not None]
            if valid_starts:
                aln_seg['start'] = valid_starts[0]
            if valid_ends:
                aln_seg['end'] = valid_ends[-1]

        return aligned
