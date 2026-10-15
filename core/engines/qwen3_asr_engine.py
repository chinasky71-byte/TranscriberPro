"""
Qwen3-ASR Engine - Trascrizione con Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B
File: core/engines/qwen3_asr_engine.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Qwen3-ASR-1.7B in bfloat16 su CUDA via pacchetto qwen-asr (transformers backend,
   attention di default — NO flash_attention_2 su Windows)
✅ ForcedAligner integrato: transcribe(..., return_time_stamps=True) restituisce
   testo + parole con timestamp in un'unica chiamata (aligner max 180s/passata,
   i chunk della pipeline sono 10-25s → ampiamente nei limiti)
✅ Auto-detect lingua (LID nativo) quando language=None: probe sul primo chunk;
   se la lingua rilevata è FUORI dalle 11 lingue dell'aligner solleva
   LanguageNotAlignable → il router ri-trascrive con faster-whisper
✅ Timestamp: word items dell'aligner + offset start del chunk
   (come faster-whisper: segment.start + start_time)
✅ Segmentazione sottotitoli con gli stessi parametri dello splitting whisper
   (max 80 caratteri, max 6s) + break su punteggiatura forte e pause
"""
import gc
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import torch

from core.engines.base_engine import TranscriptionEngine, LanguageNotAlignable
from utils.logger import setup_logger
from utils.config import get_config
from utils.eta import EtaEstimator

logger = setup_logger()

# ── Mappe lingua: ISO 639-1 ↔ nomi inglesi richiesti dal pacchetto qwen-asr ──
# ASR: 30 lingue supportate (SUPPORTED_LANGUAGES di qwen_asr).
ISO_TO_QWEN_NAME = {
    'zh': 'Chinese', 'en': 'English', 'yue': 'Cantonese', 'ar': 'Arabic',
    'de': 'German', 'fr': 'French', 'es': 'Spanish', 'pt': 'Portuguese',
    'id': 'Indonesian', 'it': 'Italian', 'ko': 'Korean', 'ru': 'Russian',
    'th': 'Thai', 'vi': 'Vietnamese', 'ja': 'Japanese', 'tr': 'Turkish',
    'hi': 'Hindi', 'ms': 'Malay', 'nl': 'Dutch', 'sv': 'Swedish',
    'da': 'Danish', 'fi': 'Finnish', 'pl': 'Polish', 'cs': 'Czech',
    'fil': 'Filipino', 'tl': 'Filipino', 'fa': 'Persian', 'el': 'Greek',
    'ro': 'Romanian', 'hu': 'Hungarian', 'mk': 'Macedonian',
}
QWEN_NAME_TO_ISO = {
    'Chinese': 'zh', 'English': 'en', 'Cantonese': 'yue', 'Arabic': 'ar',
    'German': 'de', 'French': 'fr', 'Spanish': 'es', 'Portuguese': 'pt',
    'Indonesian': 'id', 'Italian': 'it', 'Korean': 'ko', 'Russian': 'ru',
    'Thai': 'th', 'Vietnamese': 'vi', 'Japanese': 'ja', 'Turkish': 'tr',
    'Hindi': 'hi', 'Malay': 'ms', 'Dutch': 'nl', 'Swedish': 'sv',
    'Danish': 'da', 'Finnish': 'fi', 'Polish': 'pl', 'Czech': 'cs',
    'Filipino': 'fil', 'Persian': 'fa', 'Greek': 'el', 'Romanian': 'ro',
    'Hungarian': 'hu', 'Macedonian': 'mk',
}
# ForcedAligner: 11 lingue (subset delle 30 ASR). Le lingue ASR fuori da questo
# set NON possono produrre timestamp affidabili → routing su faster-whisper.
ALIGNER_LANGS_639_1 = {'zh', 'en', 'yue', 'fr', 'de', 'it', 'ja', 'ko', 'pt', 'ru', 'es'}

# Punteggiatura forte per la chiusura dei sottotitoli
_STRONG_PUNCT = ('.', '!', '?', '…', '。', '！', '？')
# Pausa tra parole oltre la quale si chiude comunque il sottotitolo
_GAP_BREAK_S = 0.8
# Punteggiatura da riagganciare alle parole allineate (l'aligner restituisce
# parole NUDE: senza questo recupero gli SRT perderebbero la punteggiatura)
_TRAILING_PUNCT = '.,!?;:…"»”\')]}％%。｡！？，、；：'
_LEADING_PUNCT = '¿¡«“"\'([{'


class Qwen3AsrEngine(TranscriptionEngine):
    """
    Engine Qwen3-ASR-1.7B + ForcedAligner-0.6B (bfloat16, CUDA).
    Copre le lingue nell'intersezione ASR ∩ ForcedAligner; auto-detect nativo.
    """

    # Valore usato quando 'punctuation_restore_mode' == 'auto' (v. config.py).
    PUNCT_AUTO_MODE = 'missing'

    name = "qwen3"

    def __init__(self, log_callback: Optional[Callable] = None):
        super().__init__(log_callback=log_callback)
        self.config = get_config()
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._punct_restorer = None  # lazy, v. _maybe_restore_punctuation
        # v1.29.0: default prudenti, sovrascritti in transcribe_chunks dalla config reale
        # (qwen3_lang_retry_enabled/_accept_langs) — v. core/qwen3_lang_retry.py.
        self._lang_retry_enabled = True
        self._lang_retry_accept = frozenset({'en'})

        # Mappa batch dal profilo: batch_size_hint del profilo trascrizione,
        # con cap prudente a 8 (chunk da 25s in bf16 su 12GB condivisi con Demucs).
        # num_workers e beam_size del profilo NON hanno un equivalente qwen-asr
        # (generazione greedy interna al pacchetto) → ignorati volutamente.
        try:
            from utils.transcription_profiles import ProfileConfig
            profile = ProfileConfig.from_string(self.config.get_transcription_profile())
            hint = ProfileConfig.get_profile_config(profile).get('batch_size_hint') or 8
        except Exception:
            hint = 8

        # Il cap di 8 è tarato su chunk da 25s: con chunk più lunghi (config
        # asr_chunk_max_duration) le attivazioni dell'encoder audio crescono
        # ~linearmente con la durata → si scala il batch per conservare il
        # prodotto batch×durata (WDDM non fa OOM, sconfina in silenzio: uno
        # sconfinamento su chunk lunghi sarebbe un rallentamento invisibile,
        # non un crash).
        _ref_sec = 25.0
        _chunk_max = float(self.config.get('asr_chunk_max_duration', 25))
        _cap = max(1, int(8 * _ref_sec / max(_chunk_max, _ref_sec)))
        self.batch_size = max(1, min(int(hint), _cap))

        # max_new_tokens: v. piano_fix_pipeline_trascrizione punto B/D5. Il
        # default storico (256) tronca già un chunk denso da 25s (~266 token
        # stimati) — 0 = calcolo automatico dalla durata massima dei chunk.
        self._max_new_tokens = self._compute_max_new_tokens(_chunk_max)

    def _compute_max_new_tokens(self, chunk_max_sec: float) -> int:
        """Determina il cap di generazione per Qwen3-ASR.

        Config esplicita (`qwen3_max_new_tokens` > 0) ha sempre priorità.
        Con 0 (default) si stima dal peggior chunk possibile — non dalla
        durata media — perché un troncamento taglia in silenzio la coda del
        testo del chunk, senza errore a video (v. piano_fix_pipeline_
        trascrizione punto B.2/D.5).

        Formula: tokens ≈ (chunk_sec/60) × WPM_peak × TOK_PER_WORD + OVERHEAD
          - WPM_peak=220: parlato cinematografico concitato in italiano
            (dimensionato sul peggior chunk, non sulla media conversazionale)
          - TOK_PER_WORD=2.5: tokenizer BPE Qwen su italiano, conservativo
          - OVERHEAD=64: prefisso lingua + margine
        Arrotondato a multipli di 128, minimo 256 (comportamento storico),
        massimo 2048.
        """
        configured = int(self.config.get('qwen3_max_new_tokens', 0) or 0)
        if configured > 0:
            return configured

        wpm_peak, tok_per_word, overhead = 220, 2.5, 64
        estimated = (chunk_max_sec / 60.0) * wpm_peak * tok_per_word + overhead
        import math
        rounded = max(256, min(2048, int(math.ceil(estimated / 128.0) * 128)))
        return rounded

    # ------------------------------------------------------------------
    # Capability detection
    # ------------------------------------------------------------------
    @classmethod
    def is_available(cls) -> bool:
        try:
            from qwen_asr import Qwen3ASRModel  # noqa: F401
            return True
        except Exception:
            return False

    @classmethod
    def supports_language(cls, lang_639_1: Optional[str]) -> bool:
        # None = auto-detect: supportato (LID nativo).
        # Lingue esplicite: solo intersezione ASR ∩ ForcedAligner (timestamp
        # affidabili obbligatori per SRT destinati a OpenSubtitles).
        if lang_639_1 is None:
            return True
        return lang_639_1 in ALIGNER_LANGS_639_1 and lang_639_1 in ISO_TO_QWEN_NAME

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load(self):
        """Carica Qwen3-ASR + ForcedAligner in bfloat16 su CUDA."""
        if self.model is not None:
            return
        from qwen_asr import Qwen3ASRModel

        asr_id = self.config.get('qwen3_asr_model_id', 'Qwen/Qwen3-ASR-1.7B')
        aligner_id = self.config.get('qwen3_aligner_model_id', 'Qwen/Qwen3-ForcedAligner-0.6B')

        t0 = time.time()
        free0 = self._free_vram_gb()
        self.log(f"  📦 Caricamento modello {asr_id} + aligner (bfloat16)...")

        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        device_map = "cuda:0" if self.device == "cuda" else "cpu"

        # NB: attention di default (NO flash_attention_2: compilazione
        # problematica su Windows). Il pacchetto usa transformers 4.57.6.
        self.model = Qwen3ASRModel.from_pretrained(
            asr_id,
            forced_aligner=aligner_id,
            forced_aligner_kwargs=dict(dtype=dtype, device_map=device_map),
            dtype=dtype,
            device_map=device_map,
            max_inference_batch_size=self.batch_size,
            max_new_tokens=self._max_new_tokens,
        )

        elapsed = time.time() - t0
        free1 = self._free_vram_gb()
        self.log(f"  ✅ Qwen3-ASR caricato in {elapsed:.1f}s su {self.device.upper()}"
                 + (f" │ VRAM: {free0:.1f} → {free1:.1f} GB liberi" if free0 else ""))
        self.log(f"  ⚙️ batch={self.batch_size} │ max_new_tokens={self._max_new_tokens}")

    def unload(self):
        """Scarica completamente ASR + aligner da VRAM."""
        try:
            if self.model is not None:
                # Rilascia anche l'aligner interno del wrapper qwen-asr
                try:
                    if getattr(self.model, 'forced_aligner', None) is not None:
                        del self.model.forced_aligner
                except Exception:
                    pass
                del self.model
                self.model = None
            if self._punct_restorer is not None:
                self._punct_restorer.unload()
                self._punct_restorer = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            logger.info("✅ Qwen3AsrEngine unload completato")
        except Exception as e:
            logger.error(f"Errore durante unload Qwen3: {e}")

    def _maybe_restore_punctuation(self, words: List[dict], text: str,
                                    language: str, chunk_num: int) -> List[dict]:
        """Applica il ripristino punteggiatura (punto D) se il trigger di
        config lo richiede per questo chunk. 'off' = comportamento storico,
        nessun import né chiamata — costo zero quando disattivato."""
        mode = self.config.get('punctuation_restore_mode', 'auto')
        if mode == 'auto':
            mode = self.PUNCT_AUTO_MODE
        if mode == 'off':
            return words

        from core.punctuation_restorer import PunctuationRestorer
        if language not in PunctuationRestorer.SUPPORTED_LANGS:
            return words  # lingua fuori dal modello: nessun log fuorviante

        min_density = float(self.config.get('punctuation_min_density', 0.0))
        trigger = (mode == 'all') or (
            mode == 'missing' and PunctuationRestorer.needs_restoration(text, min_density))
        if not trigger:
            return words

        if self._punct_restorer is None:
            self._punct_restorer = PunctuationRestorer(
                model_id=self.config.get('punctuation_model_id',
                                          'oliverguhr/fullstop-punctuation-multilang-large'),
                device=self.config.get('punctuation_device', 'cpu'),
                log_callback=self.log,
            )
        # Per chunk: SOLO nel file di log (a schermo disturbava la barra di avanzamento);
        # a fine trascrizione compare il riepilogo "Punteggiatura ripristinata su N/M chunk".
        logger.info(f"  ✍️ Ripristino punteggiatura chunk {chunk_num}...")
        restored = self._punct_restorer.restore_words(words, language)
        self._n_punct_restored = getattr(self, '_n_punct_restored', 0) + 1   # solo a chiamata riuscita
        return restored

    def _maybe_lang_retry(self, chunk_path: str, forced_iso: str, r, text: str, chunk_num: int):
        """v1.29.0 (core/qwen3_lang_retry.py, trovato su X Factor): se il chunk forzato su
        `forced_iso` è sospetto (vuoto, poche parole rispetto alla voce presente, o pieno di
        parole inglesi pur forzato in un'altra lingua) prova un rilevamento lingua e, se la
        lingua rilevata è diversa, supportata dall'aligner e accettata (di default solo
        l'inglese: v. docstring del modulo), ritrascrive il chunk in quella lingua.
        Ritorna (r, text, lingua_del_testo, ritentato) — INVARIATI se non si ritrascrive."""
        from core import qwen3_lang_retry as LR
        try:
            st = LR.voice_stats(chunk_path)
        except Exception as e:
            logger.debug(f"[qwen3-lang-retry] chunk {chunk_num}: misura voce fallita: {e}")
            return r, text, forced_iso, False
        susp, why = LR.is_suspect(text, st['voice_s'], forced_iso)
        if not susp:
            return r, text, forced_iso, False
        try:
            lid = self.model.transcribe(audio=chunk_path, language=None, return_time_stamps=False)
            lid_lang = (lid[0].language if lid else '') or ''
            lid_text = ((lid[0].text if lid else '') or '').strip()
            ok, iso, reason = LR.decide(forced_iso, lid_lang, lid_text, QWEN_NAME_TO_ISO,
                                        ALIGNER_LANGS_639_1, self._lang_retry_accept)
            if not ok:
                logger.debug(f"[qwen3-lang-retry] chunk {chunk_num} sospetto ({why}): {reason}")
                return r, text, forced_iso, False
            det_name = lid_lang.split(',')[0].strip()
            new = self.model.transcribe(audio=chunk_path, language=det_name, return_time_stamps=True)
            new_text = ((new[0].text if new else '') or '').strip()
            if not new_text:
                logger.debug(f"[qwen3-lang-retry] chunk {chunk_num}: ritrascrizione in '{iso}' vuota, "
                            "si tiene l'originale")
                return r, text, forced_iso, False
            # Per chunk: solo nel file di log; il riepilogo "Chunk ritrascritti N/M" e' a fine fase.
            logger.info(f"  🌐 Chunk {chunk_num}: ritrascritto in '{iso}' (forzato '{forced_iso}', {why})")
            return new[0], new_text, iso, True
        except Exception as e:
            logger.warning(f"[qwen3-lang-retry] chunk {chunk_num}: ritrascrizione fallita: {e}")
            return r, text, forced_iso, False

    @staticmethod
    def _free_vram_gb() -> float:
        try:
            if torch.cuda.is_available():
                free_b, _ = torch.cuda.mem_get_info()
                return free_b / 1024**3
        except Exception:
            pass
        return 0.0

    # ------------------------------------------------------------------
    # Trascrizione
    # ------------------------------------------------------------------
    def transcribe_chunks(
        self,
        audio_chunks: List[tuple],
        output_path: str,
        language: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Trascrive i chunk con Qwen3-ASR e timestamp del ForcedAligner.

        Con language=None esegue un probe LID sul primo chunk: se la lingua
        rilevata non è allineabile solleva LanguageNotAlignable (il router
        ripiega su faster-whisper con la lingua rilevata).
        """
        from core.transcriber import save_srt_file

        if self.model is None:
            self.load()

        total_chunks = len(audio_chunks)
        invalid_language_codes = ['und', 'unknown', 'undefined', 'n/a', 'none', '']
        if language is not None and language.lower().strip() in invalid_language_codes:
            language = None

        # ── Probe LID sul primo chunk quando la lingua è ignota ──
        detected_639_1: Optional[str] = None
        if language is None:
            self.log("  🎯 Lingua: AUTO-DETECT (LID nativo Qwen3)")
            first_path = str(audio_chunks[0][0])
            probe = self.model.transcribe(audio=first_path, language=None)
            probe_lang_name = (probe[0].language or '').split(',')[0].strip()
            detected_639_1 = QWEN_NAME_TO_ISO.get(probe_lang_name)
            if detected_639_1 is None:
                # Silenzio o lingua non riconosciuta dall'ASR
                raise LanguageNotAlignable(
                    None, f"LID Qwen3 inconclusivo ('{probe[0].language}')")
            self.log(f"  🔍 Lingua rilevata automaticamente: {detected_639_1} ({probe_lang_name})")
            if detected_639_1 not in ALIGNER_LANGS_639_1:
                # ASR la supporta ma l'aligner no → timestamp inaffidabili
                raise LanguageNotAlignable(
                    detected_639_1,
                    f"Lingua '{detected_639_1}' supportata dall'ASR ma non dal ForcedAligner")
            language = detected_639_1
        else:
            detected_639_1 = language
            self.log(f"  🎯 Lingua: {language}")

        lang_name = ISO_TO_QWEN_NAME.get(language)
        if lang_name is None or language not in ALIGNER_LANGS_639_1:
            raise LanguageNotAlignable(
                language, f"Lingua '{language}' non supportata da Qwen3+aligner")

        self.log(f"  📊 Trascrizione di {total_chunks} chunks audio (batch={self.batch_size})...")

        all_segments = []
        failed_chunks = 0
        truncation_suspects = 0
        n_lang_retried = 0
        self._n_punct_restored = 0
        last_pct = -1
        t0 = time.time()
        eta = EtaEstimator()
        self._lang_retry_enabled = bool(self.config.get('qwen3_lang_retry_enabled', True))
        self._lang_retry_accept = frozenset(self.config.get('qwen3_lang_retry_accept_langs', ['en']))

        # Elaborazione a lotti: il pacchetto batcha internamente fino a
        # max_inference_batch_size, ma iteriamo per chunk per progress/cancel.
        for i, chunk in enumerate(audio_chunks):
            if self._cancelled:
                break
            chunk_path, start_time = str(chunk[0]), float(chunk[1])
            chunk_num = i + 1
            try:
                if not Path(chunk_path).exists():
                    logger.error(f"Chunk {chunk_num} non trovato: {chunk_path}")
                    failed_chunks += 1
                    continue

                results = self.model.transcribe(
                    audio=chunk_path,
                    language=lang_name,
                    return_time_stamps=True,
                )
                r = results[0]
                text = (r.text or '').strip()
                text_lang = language

                if self._lang_retry_enabled:
                    r, text, text_lang, retried = self._maybe_lang_retry(
                        chunk_path, language, r, text, chunk_num)
                    if retried:
                        n_lang_retried += 1

                if not text:
                    continue  # chunk silenzioso (originale o dopo ritrascrizione)

                # Diagnostica (v. piano_fix_pipeline_trascrizione): capire se i
                # tratti senza punteggiatura nell'SRT finale nascono già così
                # dall'ASR o si perdono nel riaggancio con l'aligner.
                if not any(ch in '.,!?;:…' for ch in text):
                    logger.debug(
                        f"[qwen3-diag] chunk {chunk_num}: testo ASR grezzo "
                        f"senza alcuna punteggiatura: {text[:200]!r}")

                # Diagnostica: sospetto troncamento su max_new_tokens. Il
                # pacchetto non espone il conteggio dei token generati →
                # stima dal testo (~2,5 token/parola sul tokenizer Qwen in
                # italiano). Se i chunk "senza punteggiatura" sopra
                # coincidono con questi, il difetto è a monte in B (cap
                # troppo basso), non un problema di punteggiatura vera e
                # propria (v. piano_fix_pipeline_trascrizione punto D.5).
                est_tokens = len(text.split()) * 2.5
                if est_tokens >= 0.9 * self._max_new_tokens:
                    truncation_suspects += 1
                    logger.debug(
                        f"[qwen3-diag] chunk {chunk_num}: sospetto troncamento "
                        f"(~{est_tokens:.0f} token stimati / cap {self._max_new_tokens}) — "
                        f"coda: {text[-80:]!r}")

                # Word items dell'aligner + punteggiatura dal testo ASR
                # completo + offset start del chunk
                words = []
                if r.time_stamps is not None:
                    words = self._attach_punct_words(text, r.time_stamps, start_time, chunk_num)

                # Ripristino punteggiatura (v. piano_fix_pipeline_trascrizione
                # punto D) — SOLO sui chunk diagnosticati, mai su testo già
                # punteggiato dall'ASR (che usa il segnale acustico, non
                # disponibile a un modello testuale). 'off' = comportamento
                # storico, nessuna chiamata.
                if words:
                    words = self._maybe_restore_punctuation(words, text, text_lang, chunk_num)

                if words:
                    all_segments.extend(self._words_to_segments(words))
                else:
                    # Aligner senza output (caso limite): segmento unico sul chunk
                    all_segments.append({
                        'start': start_time,
                        'end': float(chunk[2]) if len(chunk) > 2 else start_time,
                        'text': text,
                    })

                pct = int((chunk_num / total_chunks) * 100)
                eta_txt = eta.update(chunk_num / total_chunks)
                if pct != last_pct:
                    bars = int(pct / 10)
                    bar = '█' * bars + '░' * (10 - bars)
                    from utils.events import emit as _tp_emit
                    _tp_emit('bar', phase='asr', pct=pct)
                    self.log(f"  🎙️ Trascrizione: [{bar}] {pct:3d}% ({chunk_num}/{total_chunks}){eta_txt}")
                    last_pct = pct

            except Exception as e:
                logger.error(f"❌ ERRORE chunk {chunk_num} (Qwen3): {e}", exc_info=True)
                failed_chunks += 1
                continue

        elapsed = time.time() - t0
        mins, secs = divmod(int(elapsed), 60)
        time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
        if failed_chunks > 0:
            self.log(f"  ⚠️ Completato con {failed_chunks} chunks falliti su {total_chunks}")
        from utils.events import emit as _tp_emit
        _tp_emit('bar', phase='asr', pct=100)
        self.log(f"  ✅ Trascrizione: [██████████] 100% ({total_chunks}/{total_chunks}) │ {time_str}")
        self.log(f"  📝 Totale segmenti trascritti: {len(all_segments)}")
        if truncation_suspects:
            self.log(f"  ⚠️ Chunk con sospetto troncamento generazione "
                     f"(cap {self._max_new_tokens} token): {truncation_suspects}/{total_chunks}")
        if n_lang_retried:
            self.log(f"  🌐 Chunk ritrascritti per lingua diversa da quella forzata: "
                     f"{n_lang_retried}/{total_chunks}")
        if self._n_punct_restored:
            self.log(f"  ✍️ Punteggiatura ripristinata su {self._n_punct_restored}/{total_chunks} chunk")

        # Troppi fallimenti = engine inaffidabile su questo file → fallback
        if total_chunks > 0 and failed_chunks > total_chunks * 0.5:
            raise RuntimeError(
                f"Qwen3: {failed_chunks}/{total_chunks} chunk falliti — fallback")

        self._last_segments = all_segments

        if output_path and all_segments:
            save_success = save_srt_file(all_segments, Path(output_path))
            return save_success, detected_639_1

        return len(all_segments) > 0, detected_639_1

    # ------------------------------------------------------------------
    # Punteggiatura: riaggancio dal testo ASR alle parole dell'aligner
    # ------------------------------------------------------------------
    @staticmethod
    def _attach_punct_words(text: str, items, offset: float, chunk_num: Optional[int] = None) -> List[dict]:
        """
        Converte gli item dell'aligner in parole con timestamp riagganciando
        la punteggiatura del testo ASR originale.

        L'aligner restituisce unità NUDE (parola o carattere CJK, senza
        punteggiatura): scorrendo il testo completo con un cursore, ogni
        parola viene estesa con la punteggiatura adiacente (chiusure a destra,
        aperture tipo ¿¡« a sinistra). Se una parola non viene ritrovata nel
        testo (caso limite), si usa la parola nuda.
        """
        words: List[dict] = []
        pos = 0
        not_found = 0
        seen = 0
        for it in items:
            seen += 1
            w = (it.text or '').strip()
            if not w:
                continue
            i = text.find(w, pos)
            if i < 0:
                i = text.find(w)   # robustezza: ritenta dall'inizio
                if i < 0:
                    not_found += 1
            if i >= 0:
                j = i + len(w)
                # Aperture immediatamente adiacenti a sinistra (¿ ¡ « " ...)
                pfx = i
                while pfx - 1 >= pos and text[pfx - 1] in _LEADING_PUNCT:
                    pfx -= 1
                # Chiusure adiacenti a destra (. , ! ? " » ...)
                k = j
                while k < len(text) and text[k] in _TRAILING_PUNCT:
                    k += 1
                token = text[pfx:k]
                pos = k
            else:
                token = w
            words.append({
                'start': float(it.start_time) + offset,
                'end': float(it.end_time) + offset,
                'word': token,
            })

        # Diagnostica (v. piano_fix_pipeline_trascrizione): distingue "l'ASR
        # non punteggia" da "il riaggancio con l'aligner fallisce".
        if not_found:
            logger.debug(
                f"[qwen3-diag] chunk {chunk_num}: {not_found}/{seen} "
                f"parole dell'aligner non trovate nel testo ASR (riaggancio "
                f"punteggiatura fallito, parola nuda usata) — testo: {text[:200]!r}")

        return words

    # ------------------------------------------------------------------
    # Segmentazione: parole con timestamp → sottotitoli
    # ------------------------------------------------------------------
    @staticmethod
    def _words_to_segments(
        words: List[dict],
        max_chars: int = 80,
        max_duration: float = 6.0,
    ) -> List[dict]:
        """
        Raggruppa le parole allineate in segmenti sottotitolo.

        Regole di chiusura (stessi limiti dello splitting whisper):
        - punteggiatura forte a fine parola (. ! ? …)
        - pausa > _GAP_BREAK_S rispetto alla parola successiva
        - superamento di max_chars o max_duration
        """
        segments = []
        cur_words: List[dict] = []
        cur_text = ''

        def _close():
            nonlocal cur_words, cur_text
            if cur_words and cur_text.strip():
                segments.append({
                    'start': cur_words[0]['start'],
                    'end': cur_words[-1]['end'],
                    'text': cur_text.strip(),
                    'words': list(cur_words),
                })
            cur_words = []
            cur_text = ''

        for idx, w in enumerate(words):
            candidate = (cur_text + ' ' + w['word']).strip() if cur_text else w['word']
            duration = w['end'] - (cur_words[0]['start'] if cur_words else w['start'])

            # Chiusura preventiva per limiti dimensionali
            if cur_words and (len(candidate) > max_chars or duration > max_duration):
                _close()
                candidate = w['word']

            cur_words.append(w)
            cur_text = candidate

            # Chiusura per punteggiatura forte o pausa lunga
            next_gap = (words[idx + 1]['start'] - w['end']) if idx + 1 < len(words) else 0.0
            if cur_text.rstrip().endswith(_STRONG_PUNCT) or next_gap > _GAP_BREAK_S:
                _close()

        _close()

        # Anti-frammento: coda con < 4 parole riunita al segmento precedente
        # SOLO se è un vero frammento della stessa frase: pausa breve E frase
        # precedente non conclusa. Una battuta autonoma a fine chunk (es.
        # "Polizia." dopo una pausa) resta un sottotitolo a sé, ancorato ai
        # suoi timestamp — incollarla creava blocchi lunghi anche 20s con
        # due battute distanti nella stessa riga.
        if len(segments) >= 2 and len(segments[-1]['words']) < 4:
            tail = segments[-1]
            prev = segments[-2]
            tail_gap = tail['words'][0]['start'] - prev['words'][-1]['end']
            prev_concluded = prev['text'].rstrip().endswith(_STRONG_PUNCT)
            if tail_gap <= _GAP_BREAK_S and not prev_concluded:
                segments.pop()
                segments[-1] = {
                    'start': prev['start'],
                    'end': tail['end'],
                    'text': (prev['text'] + ' ' + tail['text']).strip(),
                    'words': prev['words'] + tail['words'],
                }

        return segments
