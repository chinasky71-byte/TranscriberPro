# -*- coding: utf-8 -*-
"""
SubtitleSynchronizer — Pipeline "Anchor & Match"
File: core/subtitle_synchronizer.py

Allinea un file .srt italiano esterno (fuori sincrono) ai timestamp corretti
estratti dai sottotitoli embedded di un video (o da una trascrizione Whisper).

PIPELINE:
    S1  10%  Ancoraggio      — estrae timing di riferimento dal video
    S2  40%  Ponte Semantico — NLLB traduce anchor EN → IT grezzo
    S3  80%  Abbinamento     — Qwen2.5-14B-Q4_K abbina anchor-IT → external-IT
    S4  95%  Rifinitura      — costruisce SRT finale + VRAM cleanup
    done 100%
"""

import gc
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Verifica disponibilità llama-cpp-python
_LLAMA_CPP_AVAILABLE  = False
_GRAMMAR_AVAILABLE    = False
try:
    from llama_cpp import Llama as _Llama
    _LLAMA_CPP_AVAILABLE = True
    try:
        from llama_cpp import LlamaGrammar as _LlamaGrammar
        _GRAMMAR_AVAILABLE = True
    except ImportError:
        pass
except ImportError:
    pass

# Grammatica GBNF per forzare output JSON strutturato — elimina token illegali
# durante la generazione, riducendo i tempi del 25-35%.
# Chiavi in ordine fisso (conforme al system prompt).
_JSON_GRAMMAR = r'''root      ::= ws "[" ws item (ws "," ws item)* ws "]" ws
item      ::= "{" ws "\"ext_id\"" ws ":" ws string ws "," ws "\"anchor_ids\"" ws ":" ws anc-array ws "," ws "\"new_start_sec\"" ws ":" ws number ws "," ws "\"new_end_sec\"" ws ":" ws number ws "," ws "\"match_type\"" ws ":" ws matchtype ws "," ws "\"confidence\"" ws ":" ws number ws "}"
anc-array ::= "[]" | "[" ws string (ws "," ws string)* ws "]"
matchtype ::= "\"direct\"" | "\"merged\"" | "\"split_first\"" | "\"split_second\"" | "\"no_match\""
string    ::= "\"" ([^"\\] | "\\" ["\\/bfnrt])* "\""
number    ::= "-"? [0-9]+ ("." [0-9]+)?
ws        ::= [ \t\n\r]*
'''


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SyncSubtitle:
    """Sottotitolo con rappresentazione doppia: stringa SRT e secondi float."""
    index: int
    start_time: str   # "HH:MM:SS,mmm"
    end_time: str     # "HH:MM:SS,mmm"
    text: str
    start_seconds: float = field(init=False)
    end_seconds: float   = field(init=False)

    def __post_init__(self):
        self.start_seconds = self._ts_to_sec(self.start_time)
        self.end_seconds   = self._ts_to_sec(self.end_time)

    @staticmethod
    def _ts_to_sec(ts: str) -> float:
        """Converte "HH:MM:SS,mmm" in float secondi."""
        try:
            h, m, rest = ts.split(':')
            s, ms = rest.split(',')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        except Exception:
            return 0.0

    @staticmethod
    def _sec_to_ts(sec: float) -> str:
        """Converte float secondi in "HH:MM:SS,mmm"."""
        sec = max(0.0, sec)
        ms_total = round(sec * 1000)
        h  = ms_total // 3_600_000; ms_total %= 3_600_000
        m  = ms_total //    60_000; ms_total %=    60_000
        s  = ms_total //     1_000; ms_total %=     1_000
        return f"{h:02d}:{m:02d}:{s:02d},{ms_total:03d}"

    def update_times(self, start_sec: float, end_sec: float) -> None:
        """Aggiorna atomicamente secondi e stringhe SRT."""
        self.start_seconds = start_sec
        self.end_seconds   = end_sec
        self.start_time    = self._sec_to_ts(start_sec)
        self.end_time      = self._sec_to_ts(end_sec)


@dataclass
class MatchResult:
    """Risultato dell'abbinamento per un singolo sottotitolo esterno."""
    external_index: int
    anchor_indices: List[int]   # 1 o 2 anchor abbinati
    new_start_sec: float
    new_end_sec: float
    # 'direct' | 'merged' | 'split_first' | 'split_second' | 'positional'
    match_type: str
    confidence: float


# ── Classe interna Qwen ───────────────────────────────────────────────────────

class _LocalQwenMatcher:
    """
    Wrapper llama-cpp-python per Qwen2.5-14B-Instruct-Q4_K.
    Caricato in-process dopo il cleanup NLLB di STEP 2 (VRAM libera).
    """

    def __init__(self, model_path: str, log_callback: Optional[Callable] = None):
        self._model_path = model_path
        self._log_cb     = log_callback
        self._llm        = None
        self._grammar    = None   # LlamaGrammar compilata, None se non disponibile

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self._log_cb:
            self._log_cb(msg)

    def load(self) -> bool:
        if not _LLAMA_CPP_AVAILABLE:
            self._log("  llama-cpp-python non disponibile — abbinamento solo posizionale.")
            return False
        if not Path(self._model_path).exists():
            self._log(f"  Modello Qwen non trovato: {self._model_path}")
            return False
        try:
            self._log("  Caricamento Qwen in VRAM...")
            self._llm = _Llama(
                model_path=self._model_path,
                n_gpu_layers=-1,
                n_ctx=4096,
                n_batch=512,
                verbose=False,
            )
            self._log("  Qwen caricato.")

            # Compila grammar GBNF per output JSON strutturato (opt. velocità)
            if _GRAMMAR_AVAILABLE:
                try:
                    self._grammar = _LlamaGrammar.from_string(_JSON_GRAMMAR, verbose=False)
                    self._log("  Grammar JSON attiva.")
                except Exception as eg:
                    logger.warning(f"Grammar GBNF non compilata: {eg}")
                    self._grammar = None

            return True
        except Exception as e:
            logger.error(f"Errore caricamento Qwen: {e}", exc_info=True)
            self._log(f"  Errore caricamento Qwen: {e}")
            return False

    def match_window(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Chiama Qwen via create_chat_completion.
        Restituisce il testo grezzo della risposta o None su eccezione.
        """
        if self._llm is None:
            return None
        try:
            kwargs = dict(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.1,
                top_p=0.9,
                repeat_penalty=1.05,
                max_tokens=2048,
            )
            if self._grammar is not None:
                kwargs['grammar'] = self._grammar
            # cache_prompt=True: riusa KV cache del system prompt tra finestre.
            # Supportato da llama-cpp-python >= 0.2.77; ignorato o gestito
            # con TypeError su versioni precedenti.
            try:
                response = self._llm.create_chat_completion(**kwargs, cache_prompt=True)
            except TypeError:
                response = self._llm.create_chat_completion(**kwargs)
            return response['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.warning(f"Errore inferenza Qwen: {e}")
            return None

    def unload(self) -> None:
        if self._llm is not None:
            del self._llm
            self._llm = None
        gc.collect()


# ── Classe principale ─────────────────────────────────────────────────────────

class SubtitleSynchronizer:
    """
    Esegue la pipeline "Anchor & Match" per sincronizzare un .srt esterno
    ai timestamp embedded di un video.

    Uso:
        syncer = SubtitleSynchronizer(
            video_path='film.mkv',
            external_srt_path='film.it.srt',
            log_callback=gui_log,
            progress_callback=gui_progress,
        )
        ok = syncer.synchronize()
    """

    _STEP_PCT: Dict[str, int] = {
        'S1': 10, 'S2': 40, 'S3': 80, 'S4': 95, 'done': 100,
    }

    # Prompt di sistema per il matching (in inglese per prestazioni migliori)
    _SYSTEM_PROMPT = (
        "You are a subtitle timestamp synchronization expert.\n"
        "Your task: match EXTERNAL Italian subtitle segments to ANCHOR segments "
        "(rough Italian translation with correct timing), and determine the correct "
        "timestamps for each EXTERNAL segment.\n\n"
        "MATCHING RULES:\n"
        "1. DIRECT (1 external ↔ 1 anchor): semantically equivalent. "
        "Use anchor start/end unchanged.\n"
        "2. MERGED (1 external ↔ 2 anchors): external combines two anchor lines. "
        "new_start = first_anchor.start, new_end = last_anchor.end.\n"
        "3. SPLIT_FIRST / SPLIT_SECOND (2 externals ↔ 1 anchor): external pair "
        "maps to one anchor. Split anchor duration proportionally by character count.\n"
        "4. NO_MATCH: no clear semantic match exists. Use match_type 'no_match'.\n\n"
        "OUTPUT: return ONLY a strictly valid JSON array — no markdown fences, "
        "no prose, no explanation.\n"
        "Schema per elemento:\n"
        '{"ext_id":"E<n>","anchor_ids":["A<n>",...],'
        '"new_start_sec":<float>,"new_end_sec":<float>,'
        '"match_type":"direct|merged|split_first|split_second|no_match",'
        '"confidence":<float 0-1>}\n\n'
        "Include an entry for EVERY ext_id. Output ONLY the JSON array."
    )

    def __init__(
        self,
        video_path: str,
        external_srt_path: str,
        output_path: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ):
        self.video_path        = Path(video_path)
        self.external_srt_path = Path(external_srt_path)

        # Import lazy per evitare import circolari a livello modulo
        from utils.config import get_config
        from utils.file_handler import FileHandler
        self.config       = get_config()
        self.file_handler = FileHandler()

        if output_path:
            self._output_path = Path(output_path)
        else:
            stem = self.external_srt_path.stem
            # Rimuove estensione lingua se presente (es. "film.it" → "film")
            if '.' in stem:
                base, lang = stem.rsplit('.', 1)
                stem = base if len(lang) <= 5 else stem
            self._output_path = (
                self.external_srt_path.parent / f"{stem}.synced.it.srt"
            )

        self._log_callback      = log_callback
        self._progress_callback = progress_callback

        # Cancellazione
        self._cancelled: bool = False
        self._current_proc: Optional[subprocess.Popen] = None

        # Riferimenti ai modelli per cleanup
        self._nllb_translator  = None
        self._transcriber      = None
        self._audio_processor  = None
        self._qwen_matcher: Optional[_LocalQwenMatcher] = None
        self._cleanup_done: bool = False

        # Parametri da config
        self._window_size: int = self.config.get('sync_llm_window_size', 20)
        self._src_language: str = self.config.get('sync_src_language', 'en')

    # ── API pubblica ──────────────────────────────────────────────────────────

    def synchronize(self) -> bool:
        """
        Esegue la pipeline completa S1→S4.
        Restituisce True su successo, False su errore o annullamento.
        """
        try:
            self._log("=" * 68)
            self._log(f"Sincronizzazione: {self.video_path.name}")
            self._log(f"SRT esterno:      {self.external_srt_path.name}")
            self._log(f"Output:           {self._output_path.name}")
            self._log("=" * 68)

            externals = self._parse_srt_file(self.external_srt_path)
            if not externals:
                self._log("ERRORE: SRT esterno vuoto o non leggibile.")
                return False
            self._log(f"  SRT esterno: {len(externals)} sottotitoli caricati.")

            # ── S1: Ancoraggio ────────────────────────────────────────────
            self._log("\n1. Ancoraggio — estrazione timing di riferimento...")
            anchors = self._step1_extract_anchors()
            if anchors is None or self._cancelled:
                if not self._cancelled:
                    self._log("ERRORE S1: impossibile estrarre timing di riferimento.")
                return False
            self._log(f"  Anchor estratti: {len(anchors)} segmenti.")
            self._report_progress(self._STEP_PCT['S1'])

            self._unload_transcriber()

            # ── S2: Ponte Semantico ───────────────────────────────────────
            self._log("\n2. Ponte Semantico — traduzione anchor → IT grezzo...")
            anchors_it = self._step2_translate_anchors(anchors)
            if anchors_it is None or self._cancelled:
                if not self._cancelled:
                    self._log("ERRORE S2: traduzione NLLB fallita.")
                return False
            self._log(f"  Traduzione completata: {len(anchors_it)} anchor in italiano.")
            self._report_progress(self._STEP_PCT['S2'])

            # ── S3: Abbinamento ───────────────────────────────────────────
            self._log("\n3. Abbinamento — semantic matching con Qwen...")
            matches = self._step3_match_subtitles(anchors_it, externals)
            if self._cancelled:
                return False
            direct  = sum(1 for m in matches if m.match_type == 'direct')
            pos     = sum(1 for m in matches if m.match_type == 'positional')
            self._log(f"  Match: {direct} diretti, {pos} posizionali su {len(matches)} totali.")
            self._report_progress(self._STEP_PCT['S3'])

            # ── S4: Rifinitura ────────────────────────────────────────────
            self._log("\n4. Rifinitura — costruzione SRT finale...")
            ok = self._step4_build_output(externals, matches)
            if not ok:
                self._log("ERRORE S4: scrittura output fallita.")
                return False
            self._report_progress(self._STEP_PCT['S4'])

            self._log(f"\nSincronizzazione completata: {self._output_path.name}")
            self._report_progress(self._STEP_PCT['done'])
            return True

        except Exception as e:
            self._log(f"ERRORE CRITICO: {e}")
            logger.error(f"SubtitleSynchronizer error: {e}", exc_info=True)
            return False

        finally:
            self._cleanup()

    def cancel(self) -> None:
        self._cancelled = True
        if self._current_proc:
            try:
                self._current_proc.kill()
            except Exception:
                pass
        if self._transcriber:
            try:
                self._transcriber.cancel()
            except Exception:
                pass
        if self._audio_processor:
            try:
                self._audio_processor.cancel()
            except Exception:
                pass

    # ── STEP 1 ────────────────────────────────────────────────────────────────

    def _step1_extract_anchors(self) -> Optional[List[SyncSubtitle]]:
        """
        Path primario: SubtitleExtractor → embedded SRT.

        Priorità lingua anchor per il synchronizer:
            ENG > SPA > FRA > DEU > POR > RUS > JPN
        I sottotitoli italiani embedded vengono SCARTATI: usarli come anchor
        causerebbe un matching IT→IT ambiguo e renderebbe inutile il bridge NLLB.

        Fallback: AudioTrackSelector → AudioProcessor → Transcriber (Whisper).

    	quindi usare anchor non italiani migliora il matching semantico.

    	Fallback:
        	AudioTrackSelector → AudioProcessor → Transcriber (Whisper).
    	"""
        from core.subtitle_extractor import SubtitleExtractor

        extractor = SubtitleExtractor(str(self.video_path))
        streams   = extractor.detect_subtitles()

        # Lingue accettate come anchor, in ordine di preferenza.
        # L'italiano è ESCLUSO: usarlo come anchor creerebbe un matching
        # IT-embedded → IT-esterno ambiguo e renderebbe inutile il bridge NLLB.
        ANCHOR_PRIORITY = ['eng', 'spa', 'fra', 'deu', 'por', 'rus', 'jpn']
        ITALIAN_PREFIXES = ('ita', 'it')

        # Stream validi: no forced, no bitmap, no italiano
        valid_streams = [
            s for s in streams
            if not s['forced']
            and s['codec'].lower() not in extractor.BITMAP_CODECS
            and not s['language'].lower().startswith(ITALIAN_PREFIXES)
        ]

        discarded_it = [
            s for s in streams
            if not s['forced']
            and s['codec'].lower() not in extractor.BITMAP_CODECS
            and s['language'].lower().startswith(ITALIAN_PREFIXES)
        ]
        if discarded_it:
            self._log(
                f"  Scartati {len(discarded_it)} stream italiani embedded "
                f"(non utilizzabili come anchor)."
            )

        selected = None

        if valid_streams:
            self._log(f"  Trovati {len(valid_streams)} stream non-IT validi.")

        # Seleziona seguendo la priorità lingua
        for lang in ANCHOR_PRIORITY:
            lang_subs = [
                s for s in valid_streams
                if s['language'].lower().startswith(lang[:2])
            ]
            if not lang_subs:
                continue

            # Preferisci regular rispetto a HI
            regular = [s for s in lang_subs if not s['hearing_impaired']]
            chosen  = regular[0] if regular else lang_subs[0]
            tag     = "regular" if regular else "HI"
            self._log(
                f"  Anchor selezionato: {chosen['language'].upper()} {tag} "
                f"(Stream {chosen['index']})"
            )
            selected = chosen
            break

        # Fallback: primo stream non-IT disponibile (lingua non in lista priorità)
        if selected is None and valid_streams:
            selected = valid_streams[0]
            self._log(
                f"  ⚠️ Nessuna lingua prioritaria trovata — "
                f"uso fallback: {selected['language'].upper()} "
                f"(Stream {selected['index']})"
            )

        # Estrazione embedded
        if selected:
            temp_srt = self.file_handler.get_temp_path(
                self.video_path, "anchor_embedded.srt"
            )
            if extractor.extract_subtitle(temp_srt, selected['index']):
                subs = self._parse_srt_file(temp_srt)
                if subs:
                    self._log(
                        f"  {len(subs)} anchor embedded estratti "
                        f"(lingua: {selected.get('language', '?').upper()})."
                    )
                    return subs
            self._log("  Estrazione embedded fallita — provo trascrizione Whisper.")
        else:
            self._log(
                "  Nessun sottotitolo embedded non-italiano trovato — "
                "provo trascrizione Whisper."
            )

        # Whisper fallback
        if not self.config.get('sync_allow_whisper_fallback', True):
            self._log("  Fallback Whisper disabilitato dalla configurazione.")
            return None

        return self._step1_whisper_fallback()

    def _step1_whisper_fallback(self) -> Optional[List[SyncSubtitle]]:
        """Fallback: estrae audio e trascrive con Faster-Whisper."""
        from core.audio_track_selector import AudioTrackSelector
        from core.audio_processor import AudioProcessor
        from core.transcriber import Transcriber

        temp_dir = self.file_handler.get_temp_dir(self.video_path)

        selector = AudioTrackSelector(str(self.video_path))
        stream   = selector.select_best_track()
        if not stream:
            self._log("  Nessuna traccia audio trovata nel video.")
            return None

        audio_path = self.file_handler.get_temp_path(self.video_path, "anchor_audio.wav")
        if not selector.extract_audio_track(audio_path, stream['index']):
            self._log("  Estrazione traccia audio fallita.")
            return None

        self._audio_processor = AudioProcessor()
        self._audio_processor.set_log_callback(self._log_callback)

        chunks = self._audio_processor.process_for_transcription(
            audio_path=audio_path,
            output_dir=temp_dir,
            use_batched_pipeline=False,
        )
        if self._cancelled or not chunks:
            self._log("  Elaborazione audio fallita o annullata.")
            return None

        transcribed_srt = self.file_handler.get_temp_path(
            self.video_path, "anchor_transcribed.srt"
        )
        self._transcriber = Transcriber(log_callback=self._log_callback)
        success, _ = self._transcriber.transcribe_chunks(
            audio_chunks=chunks,
            output_path=str(transcribed_srt),
            whisper_language=self._src_language,
        )
        if not success or not transcribed_srt.exists():
            self._log("  Trascrizione Whisper fallita.")
            return None

        self._log("  Trascrizione Whisper completata.")
        return self._parse_srt_file(transcribed_srt)

    # ── STEP 2 ────────────────────────────────────────────────────────────────

    def _step2_translate_anchors(
        self, anchors: List[SyncSubtitle]
    ) -> Optional[List[SyncSubtitle]]:
        """
        Traduce gli anchor (lingua sorgente → IT grezzo) via NLLB locale.
        Unload immediato di NLLB + _clear_vram() al termine.
        """
        from core.translator import get_translator

        temp_in  = self.file_handler.get_temp_path(self.video_path, "anchor_src.srt")
        temp_out = self.file_handler.get_temp_path(self.video_path, "anchor_it.srt")

        self._write_srt_file(anchors, temp_in)

        self._nllb_translator = get_translator(model_type='nllb')
        try:
            ok = self._nllb_translator.translate_file(
                input_path=str(temp_in),
                output_path=str(temp_out),
                src_lang=self._src_language,
                tgt_lang='it',
            )
        except Exception as e:
            self._log(f"  Errore traduzione NLLB: {e}")
            logger.error(f"NLLB translate error: {e}", exc_info=True)
            ok = False
        finally:
            # Unload NLLB subito per liberare VRAM per Qwen (STEP 3)
            try:
                self._nllb_translator.cleanup()
            except Exception:
                pass
            self._nllb_translator = None
            self._clear_vram()

        if not ok or not temp_out.exists():
            return None

        translated = self._parse_srt_file(temp_out)

        # Reintegra i timestamp originali (translate_file li conserva, ma
        # verifichiamo che il count sia coerente)
        if len(translated) != len(anchors):
            self._log(
                f"  ⚠️ Count anchor cambiato dopo traduzione "
                f"({len(anchors)} → {len(translated)}). Uso count tradotto."
            )
        # Ripristina i timestamp dall'anchor originale corrispondente
        anchor_map = {a.index: a for a in anchors}
        for sub in translated:
            orig = anchor_map.get(sub.index)
            if orig:
                sub.update_times(orig.start_seconds, orig.end_seconds)

        return translated

    # ── STEP 3 ────────────────────────────────────────────────────────────────

    def _step3_match_subtitles(
        self,
        anchors_it: List[SyncSubtitle],
        externals:  List[SyncSubtitle],
    ) -> List[MatchResult]:
        """
        Abbina i segmenti anchor-IT a quelli external-IT usando Qwen locale.
        Processing SEQUENZIALE per finestre overlap (GPU singola).
        Fallback posizionale per entry non risolte o se Qwen non disponibile.
        """
        model_path = self.config.get('gender_correction_model_path', '')
        qwen_ok = False

        if model_path:
            self._qwen_matcher = _LocalQwenMatcher(
                model_path=model_path,
                log_callback=self._log_callback,
            )
            qwen_ok = self._qwen_matcher.load()

        if not qwen_ok:
            self._log("  Qwen non disponibile — abbinamento posizionale totale.")
            return self._positional_fallback(anchors_it, externals, set())

        # Controllo rapporto asimmetrico
        ratio = len(externals) / max(len(anchors_it), 1)
        if ratio > 3.0 or ratio < 0.33:
            self._log(
                f"  ⚠️ Rapporto anchor/external molto asimmetrico ({ratio:.1f}x) "
                f"— abbinamento posizionale totale."
            )
            try:
                self._qwen_matcher.unload()
            except Exception:
                pass
            self._qwen_matcher = None
            self._clear_vram()
            return self._positional_fallback(anchors_it, externals, set())

        results: Dict[int, MatchResult] = {}
        step     = max(1, self._window_size - 2)   # overlap=2 invece di 5 → ~16% meno finestre
        n_anc    = len(anchors_it)
        wins     = list(range(0, max(1, n_anc - 4), step))
        n_wins   = len(wins)

        self._log(f"  Finestre da elaborare: {n_wins} (window={self._window_size}, step={step})")

        for wi, a_start in enumerate(wins):
            if self._cancelled:
                break

            a_end      = min(a_start + self._window_size, n_anc)
            anchor_win = anchors_it[a_start:a_end]
            win_t0     = anchor_win[0].start_seconds
            win_t1     = anchor_win[-1].end_seconds

            ext_win = [
                e for e in externals
                if e.end_seconds >= win_t0 - 60.0
                and e.start_seconds <= win_t1 + 60.0
            ]
            if not ext_win:
                continue

            user_prompt = self._build_window_prompt(anchor_win, ext_win)
            raw_response = self._qwen_matcher.match_window(
                self._SYSTEM_PROMPT, user_prompt
            )

            if raw_response:
                win_results = self._parse_llm_match_response(
                    raw_response, anchor_win, ext_win
                )
            else:
                win_results = []

            for mr in win_results:
                if mr.external_index not in results:
                    results[mr.external_index] = mr

            # Aggiorna progresso interno (S2→S3 range)
            pct = self._STEP_PCT['S2'] + int(
                (wi + 1) / n_wins * (self._STEP_PCT['S3'] - self._STEP_PCT['S2'])
            )
            self._report_progress(pct)

        # Unload Qwen
        try:
            self._qwen_matcher.unload()
        except Exception:
            pass
        self._qwen_matcher = None
        self._clear_vram()

        # Fallback posizionale per external non risolti
        unresolved = [e for e in externals if e.index not in results]
        if unresolved:
            self._log(f"  Fallback posizionale per {len(unresolved)} sottotitoli non abbinati.")
            for mr in self._positional_fallback(anchors_it, unresolved, set(results)):
                results[mr.external_index] = mr

        return [results[k] for k in sorted(results)]

    # ── STEP 4 ────────────────────────────────────────────────────────────────

    def _step4_build_output(
        self,
        externals: List[SyncSubtitle],
        matches:   List[MatchResult],
    ) -> bool:
        """
        Applica i nuovi timestamp, formatta con SubtitleFormatter, scrive output.
        Gestisce la split di anchor per 2 external ↔ 1 anchor.
        """
        from core.subtitle_formatter import SubtitleFormatter

        match_map = {mr.external_index: mr for mr in matches}

        # Gestione speciale split: i match split_first/split_second devono
        # essere applicati in coppia; qui usiamo new_start_sec/new_end_sec
        # già calcolati correttamente da _parse_llm_match_response.
        for ext in externals:
            mr = match_map.get(ext.index)
            if mr:
                ext.update_times(mr.new_start_sec, mr.new_end_sec)

        segments = [
            {'start': s.start_seconds, 'end': s.end_seconds, 'text': s.text}
            for s in sorted(externals, key=lambda x: x.start_seconds)
        ]

        formatter = SubtitleFormatter(log_callback=self._log)
        srt_str   = formatter.format_srt(segments)

        try:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            self._output_path.write_text(srt_str, encoding='utf-8')
            self._log(f"  Scritto: {self._output_path}")
        except Exception as e:
            self._log(f"  Errore scrittura: {e}")
            return False

        # Gender correction opzionale (stesso pattern subprocess pipeline STEP 6.5)
        if self.config.get('gender_correction_enabled', False):
            self._run_gender_correction()

        self._clear_vram()
        return True

    # ── Helper: parsing / writing SRT ─────────────────────────────────────────

    def _parse_srt_file(self, path: Path) -> List[SyncSubtitle]:
        """Legge un file .srt e restituisce List[SyncSubtitle]."""
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        content   = None
        for enc in encodings:
            try:
                content = Path(path).read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if not content:
            return []

        pattern = (
            r'(\d+)\s*\n'
            r'([\d:,]+)\s*-->\s*([\d:,]+)\s*\n'
            r'((?:.*\n?)+?)(?=\n\d+\s*\n|$)'
        )
        subs = []
        for m in re.finditer(pattern, content, re.MULTILINE):
            text = m.group(4).strip()
            if text:
                subs.append(SyncSubtitle(
                    index=int(m.group(1)),
                    start_time=m.group(2).strip(),
                    end_time=m.group(3).strip(),
                    text=text,
                ))
        return subs

    def _write_srt_file(self, subtitles: List[SyncSubtitle], path: Path) -> None:
        """Scrive List[SyncSubtitle] come file .srt valido."""
        lines = []
        for s in subtitles:
            lines.append(str(s.index))
            lines.append(f"{s.start_time} --> {s.end_time}")
            lines.append(s.text)
            lines.append("")
        Path(path).write_text('\n'.join(lines), encoding='utf-8')

    # ── Helper: LLM prompt & parsing ──────────────────────────────────────────

    def _build_window_prompt(
        self,
        anchor_win:   List[SyncSubtitle],
        external_win: List[SyncSubtitle],
    ) -> str:
        anchor_lines = "\n".join(
            f"A{a.index} | {a.start_seconds:.3f} | {a.end_seconds:.3f} | {a.text}"
            for a in anchor_win
        )
        external_lines = "\n".join(
            f"E{e.index} | {e.text}"
            for e in external_win
        )
        return (
            f"ANCHOR SEGMENTS (correct timing, rough Italian translation):\n"
            f"{anchor_lines}\n\n"
            f"EXTERNAL SEGMENTS (correct Italian text, wrong timestamps):\n"
            f"{external_lines}\n\n"
            f"Match each EXTERNAL to its ANCHOR(s) and provide correct timestamps."
        )

    def _parse_llm_match_response(
        self,
        raw: str,
        anchor_win:   List[SyncSubtitle],
        external_win: List[SyncSubtitle],
    ) -> List[MatchResult]:
        """
        Pulisce la risposta e fa json.loads().
        Gestisce backtick Markdown, calcola split proporzionali.
        Fallback posizionale su parse error.
        """
        anchor_map   = {f"A{a.index}": a for a in anchor_win}
        external_map = {f"E{e.index}": e for e in external_win}

        # Pulizia aggressiva dei backtick Markdown
        cleaned = raw.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        cleaned = cleaned.strip()

        # Estrai solo la parte JSON (primo '[' ... ultimo ']')
        start_b = cleaned.find('[')
        end_b   = cleaned.rfind(']')
        if start_b != -1 and end_b != -1 and end_b > start_b:
            cleaned = cleaned[start_b:end_b + 1]

        try:
            items = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"Parse JSON risposta Qwen fallito: {e} — raw: {raw[:200]}")
            return self._positional_fallback(
                list(anchor_win), list(external_win), set()
            )

        results: List[MatchResult] = []
        already_split: Dict[str, Tuple[float, float]] = {}

        for item in items:
            try:
                ext_id      = str(item.get('ext_id', ''))
                anchor_ids  = [str(a) for a in item.get('anchor_ids', [])]
                match_type  = str(item.get('match_type', 'direct'))
                confidence  = float(item.get('confidence', 1.0))
                new_start   = float(item.get('new_start_sec', 0.0))
                new_end     = float(item.get('new_end_sec', 0.0))

                ext = external_map.get(ext_id)
                if ext is None:
                    continue

                # Usa valori LLM se plausibili (> 0 e start < end)
                if new_start >= 0.0 and new_end > new_start:
                    results.append(MatchResult(
                        external_index=ext.index,
                        anchor_indices=[
                            int(aid[1:]) for aid in anchor_ids if aid in anchor_map
                        ],
                        new_start_sec=new_start,
                        new_end_sec=new_end,
                        match_type=match_type,
                        confidence=confidence,
                    ))
                    continue

                # LLM non ha fornito timestamp: calcoliamo noi in base al match_type
                if not anchor_ids:
                    continue
                first_anc = anchor_map.get(anchor_ids[0])
                if first_anc is None:
                    continue

                if match_type in ('direct', 'merged'):
                    last_anc = anchor_map.get(anchor_ids[-1], first_anc)
                    results.append(MatchResult(
                        external_index=ext.index,
                        anchor_indices=[int(a[1:]) for a in anchor_ids if a in anchor_map],
                        new_start_sec=first_anc.start_seconds,
                        new_end_sec=last_anc.end_seconds,
                        match_type=match_type,
                        confidence=confidence,
                    ))

                elif match_type in ('split_first', 'split_second'):
                    anc      = first_anc
                    anc_key  = anchor_ids[0]
                    duration = anc.end_seconds - anc.start_seconds

                    if anc_key in already_split:
                        split_pt = already_split[anc_key][1]
                    else:
                        # Cerca il partner (split_second o split_first)
                        partner_ext = next(
                            (
                                e for e in external_win
                                if e.index != ext.index
                                and f"E{e.index}" in {
                                    str(it.get('ext_id', ''))
                                    for it in items
                                    if anchor_ids
                                    and str(it.get('anchor_ids', [''])[0]) == anc_key
                                    and it.get('ext_id') != ext_id
                                }
                            ),
                            None,
                        )
                        len_self    = len(ext.text)
                        len_partner = len(partner_ext.text) if partner_ext else len_self
                        ratio_self  = len_self / max(len_self + len_partner, 1)

                        if duration <= 0.2:
                            split_pt = anc.start_seconds + duration / 2.0
                        else:
                            raw_split = anc.start_seconds + duration * ratio_self
                            split_pt  = max(
                                anc.start_seconds + 0.1,
                                min(raw_split, anc.end_seconds - 0.1),
                            )
                        already_split[anc_key] = (anc.start_seconds, split_pt, anc.end_seconds)

                    if match_type == 'split_first':
                        s, e = anc.start_seconds, split_pt
                    else:
                        s, e = split_pt, anc.end_seconds

                    results.append(MatchResult(
                        external_index=ext.index,
                        anchor_indices=[int(anc_key[1:])],
                        new_start_sec=s,
                        new_end_sec=e,
                        match_type=match_type,
                        confidence=confidence,
                    ))

            except Exception as parse_err:
                logger.debug(f"Skip item malformato: {parse_err}")
                continue

        # Entry no_match o con ext_id non trovato → fallback posizionale
        resolved     = {mr.external_index for mr in results}
        unresolved_w = [e for e in external_win if e.index not in resolved]
        if unresolved_w:
            results.extend(
                self._positional_fallback(list(anchor_win), unresolved_w, resolved)
            )

        return results

    # ── Helper: fallback posizionale ──────────────────────────────────────────

    def _positional_fallback(
        self,
        anchors:         List[SyncSubtitle],
        externals:       List[SyncSubtitle],
        already_matched: Set[int],
    ) -> List[MatchResult]:
        """Assegna timestamp per ratio di indice quando il matching LLM fallisce."""
        results  = []
        n_anc    = len(anchors)
        n_ext    = len(externals)
        if n_anc == 0 or n_ext == 0:
            return results
        for i, ext in enumerate(externals):
            if ext.index in already_matched:
                continue
            ratio   = i / max(n_ext - 1, 1)
            a_idx   = min(int(ratio * n_anc), n_anc - 1)
            anchor  = anchors[a_idx]
            results.append(MatchResult(
                external_index=ext.index,
                anchor_indices=[anchor.index],
                new_start_sec=anchor.start_seconds,
                new_end_sec=anchor.end_seconds,
                match_type='positional',
                confidence=0.0,
            ))
        return results

    # ── Helper: gender correction ─────────────────────────────────────────────

    def _run_gender_correction(self) -> None:
        """Spawna subprocess gender_corrector_cli (identico a pipeline.py STEP 6.5)."""
        try:
            corrected = self.file_handler.get_temp_path(
                self.video_path, "synced_gender_corrected.srt"
            )
            args_path = self.file_handler.get_temp_path(
                self.video_path, "sync_gender_args.json"
            )
            args_payload = {
                "input_srt":         str(self._output_path),
                "output_srt":        str(corrected),
                "original_srt":      None,
                "character_context": {},
            }
            args_path.write_text(
                json.dumps(args_payload, ensure_ascii=False), encoding='utf-8'
            )

            project_root = Path(__file__).resolve().parent.parent
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8']       = '1'

            self._log("  Avvio subprocess Gender Corrector...")
            proc = subprocess.Popen(
                [sys.executable, "-m", "core.gender_corrector_cli", str(args_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(project_root),
                env=env,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
            self._current_proc = proc

            for line in proc.stdout:
                if self._cancelled:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                    break
                line = line.rstrip()
                if line:
                    self._log(f"  [LLM] {line}")

            return_code = proc.wait()
            self._current_proc = None

            if not self._cancelled and return_code == 0 and corrected.exists():
                import shutil
                shutil.copy2(str(corrected), str(self._output_path))
                self._log("  Correzione genere applicata.")
            elif not self._cancelled:
                self._log(
                    f"  ⚠️ Correzione genere fallita (exit {return_code}). Uso originale."
                )

            try:
                args_path.unlink(missing_ok=True)
            except Exception:
                pass

        except Exception as e:
            self._log(f"  ⚠️ Errore gender correction: {e}")
            logger.error(f"Gender correction sync error: {e}", exc_info=True)

    # ── Helper: VRAM / cleanup ────────────────────────────────────────────────

    def _unload_transcriber(self) -> None:
        """Scarica Whisper + AudioProcessor dopo S1 per liberare VRAM."""
        if self._transcriber is not None:
            try:
                self._transcriber.cleanup()
            except Exception:
                pass
            self._transcriber = None
        if self._audio_processor is not None:
            try:
                self._audio_processor.cleanup_model()
            except Exception:
                pass
            self._audio_processor = None
        gc.collect()

    def _clear_vram(self) -> None:
        """Cleanup VRAM aggressivo — identico a ProcessingPipeline._clear_vram()."""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass
                try:
                    torch._C._cuda_clearCublasWorkspaces()
                except Exception:
                    pass
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                try:
                    torch.cuda.ipc_collect()
                except Exception:
                    pass
        except ImportError:
            pass

    def _cleanup(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True

        if self._qwen_matcher is not None:
            try:
                self._qwen_matcher.unload()
            except Exception:
                pass
            self._qwen_matcher = None

        if self._nllb_translator is not None:
            try:
                self._nllb_translator.cleanup()
            except Exception:
                pass
            self._nllb_translator = None

        self._unload_transcriber()
        self._clear_vram()

        try:
            from utils.resource_monitor import release_ram_to_os
            release_ram_to_os()
        except Exception:
            pass

        try:
            self.file_handler.cleanup(self.video_path)
        except Exception:
            pass

    # ── Helper: log / progress ────────────────────────────────────────────────

    def _log(self, message: str) -> None:
        logger.info(message)
        if self._log_callback:
            try:
                self._log_callback(message)
            except Exception:
                pass

    def _report_progress(self, pct: int) -> None:
        if self._progress_callback:
            try:
                self._progress_callback(pct)
            except Exception:
                pass
