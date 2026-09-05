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
import random
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
            # n_ctx=8192 (non 4096): con finestre dense il prompt da solo può
            # superare i 2000 token e lasciare troppo poco spazio alla
            # risposta — il limite che tronca la risposta JSON a metà è
            # n_ctx (prompt+risposta), non max_tokens da solo. Qwen2.5-14B
            # supporta nativamente fino a 131072 token, il costo VRAM
            # aggiuntivo è trascurabile rispetto ai ~9GB dei pesi.
            self._llm = _Llama(
                model_path=self._model_path,
                n_gpu_layers=-1,
                n_ctx=8192,
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

    def match_window(self, system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> Optional[str]:
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
                max_tokens=max_tokens,
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

    # Default a livello di classe (non solo in __init__): _expected_shift lo
    # legge da _step3_match_subtitles, che può essere chiamato anche su
    # istanze costruite per test senza passare dal vero __init__.
    _shift_model: Optional[Tuple[float, float]] = None

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
            # Rimuove SOLO un suffisso lingua noto (es. "film.it" → "film"),
            # non un segmento qualunque ≤5 caratteri: un file come
            # "Movie.2019.1080p.x264.srt" ha stem "Movie.2019.1080p.x264",
            # e ".x264" (4 char) veniva troncato per errore, perdendo
            # informazione nel nome del file di output.
            _KNOWN_LANG_SUFFIXES = {
                'it', 'ita', 'italian', 'en', 'eng', 'english',
                'es', 'spa', 'fr', 'fre', 'fra', 'de', 'deu', 'ger',
                'pt', 'por', 'ru', 'rus', 'ja', 'jpn',
            }
            if '.' in stem:
                base, lang = stem.rsplit('.', 1)
                if lang.lower() in _KNOWN_LANG_SUFFIXES:
                    stem = base
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
        # max(2, ...): 4 chiavi sync_* non hanno UI (si editano solo a mano
        # in config.json) — un window_size <= 0 farebbe sollevare IndexError
        # su anchor_win[0] dentro _step3_match_subtitles, con un messaggio
        # "ERRORE CRITICO" incomprensibile invece di un fallimento chiaro.
        self._window_size: int = max(2, int(self.config.get('sync_llm_window_size', 20)))
        self._src_language: str = self.config.get('sync_src_language', 'en')
        self._max_offset_sec: float = float(self.config.get('sync_max_offset_sec', 30))
        # Lingua realmente rilevata per l'anchor (stream embedded o Whisper
        # autodetect): sovrascrive _src_language in S2 quando disponibile,
        # vedi _step1_extract_anchors / _step1_whisper_fallback.
        self._anchor_language: Optional[str] = None

        # Modello di shift (a, b): shift_atteso(t) = a*t + b, appreso dai
        # match già accettati — vedi _learn_shift/_expected_shift. None
        # finché non esiste un fit valido: _expected_shift torna 0.0, cioè
        # il gate di plausibilità si comporta esattamente come prima
        # dell'introduzione di questo modello (confronto con la posizione
        # assoluta originale dell'external).
        self._shift_model: Optional[Tuple[float, float]] = None

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
            if self._cancelled:
                return False
            # `anchors` può essere una lista VUOTA (embedded estratti ma
            # senza cue validi, o trascrizione Whisper senza risultati) e
            # non solo None: senza questo controllo il fallback posizionale
            # a valle produce un intero SRT con i timestamp originali
            # (sbagliati) e la pipeline dichiara comunque "completato".
            # Una manciata di anchor non basta nemmeno a coprire una sola
            # finestra in modo significativo: soglia minima 10.
            if not anchors or len(anchors) < 10:
                self._log(f"ERRORE S1: anchor insufficienti ({len(anchors or [])}, minimo 10).")
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
            tipi = {}
            for m in matches:
                tipi[m.match_type] = tipi.get(m.match_type, 0) + 1
            # 'interpolated' e 'positional' sono i due segnali di quanto
            # fidarsi del file: il primo giro di fix aveva un log che
            # contava solo 'direct'/'positional', nascondendo il fatto che
            # 'interpolated' era diventato il fallback principale — un file
            # con molte righe interpolate può comunque essere corretto (lo
            # shift è dedotto dai vicini risolti) ma è un segnale che
            # l'utente deve poter vedere, non solo dedurre dal codice.
            riepilogo = ", ".join(f"{v} {k}" for k, v in sorted(tipi.items(), key=lambda kv: -kv[1]))
            self._log(f"  Match: {riepilogo} (totale {len(matches)}).")
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

    # Lingue accettate come anchor, in ordine di preferenza, con TUTTI gli
    # alias di codice noti (ISO 639-1, 639-2/B, 639-2/T) — un confronto per
    # prefisso ('por'[:2]=='po' combacerebbe con 'pol' polacco; 'deu'[:2]
    # non combacia con 'ger') produce falsi positivi/negativi, quindi qui
    # si usa appartenenza a un set esplicito.
    _ANCHOR_LANG_ALIASES: Dict[str, Set[str]] = {
        'eng': {'eng', 'en'},
        'spa': {'spa', 'es'},
        'fra': {'fra', 'fre', 'fr'},
        'deu': {'deu', 'ger', 'de'},
        'por': {'por', 'pt', 'pob'},
        'rus': {'rus', 'ru'},
        'jpn': {'jpn', 'ja'},
    }
    _ITALIAN_LANG_ALIASES: Set[str] = {'ita', 'it', 'italian'}

    @classmethod
    def _canon_lang(cls, tag: Optional[str]) -> Optional[str]:
        """
        Normalizza un tag lingua GREZZO (da ffprobe o da Whisper) al codice
        che `core.translator.BaseTranslator.LANGUAGE_CODES` sa riconoscere.
        Necessario perché passare il tag grezzo (com'era subito dopo il
        primo giro di fix) è una regressione: tag reali come 'pob'
        (portoghese brasiliano, comune nei rip), 'pt-BR', 'en-US', 'it_IT'
        NON sono chiavi di LANGUAGE_CODES — non vengono tradotti "con la
        lingua sbagliata" come col vecchio default fisso 'en', l'intera
        traduzione NLLB di S2 FALLISCE e la sincronizzazione si interrompe
        del tutto. Qui si normalizza il separatore regionale (- o _) e si
        mappano gli alias noti dei /B code (pob/pt-BR -> por, ecc.).
        """
        if not tag:
            return None
        base = re.split(r'[-_]', tag.lower())[0]
        if base in cls._ITALIAN_LANG_ALIASES:
            return 'ita'
        for canon, aliases in cls._ANCHOR_LANG_ALIASES.items():
            if base in aliases:
                return canon
        return base or None

    def _step1_extract_anchors(self) -> Optional[List[SyncSubtitle]]:
        """
        Path primario: SubtitleExtractor → embedded SRT.

        Priorità lingua anchor per il synchronizer:
            ENG > SPA > FRA > DEU > POR > RUS > JPN
        I sottotitoli italiani embedded vengono SCARTATI: usarli come anchor
        causerebbe un matching IT→IT ambiguo e renderebbe inutile il bridge NLLB.

        Fallback: AudioTrackSelector → AudioProcessor → Transcriber (Whisper).

        Side effect: imposta self._anchor_language alla lingua realmente
        usata per l'anchor (embedded o rilevata da Whisper), così S2 può
        tradurre con la lingua sorgente corretta invece del default fisso
        di configurazione.
        """
        from core.subtitle_extractor import SubtitleExtractor

        extractor = SubtitleExtractor(str(self.video_path))
        streams   = extractor.detect_subtitles()

        ANCHOR_PRIORITY = ['eng', 'spa', 'fra', 'deu', 'por', 'rus', 'jpn']

        def _lang_is(tag: str, aliases: Set[str]) -> bool:
            """Confronto per appartenenza esatta (+ prefisso su varianti
            regionali tipo 'it-IT' O 'it_IT', entrambi i separatori),
            non per prefisso su TUTTA la stringa: evita falsi
            positivi/negativi come 'por'[:2]=='po' (polacco) o 'deu' che
            non combacia con l'alias 'ger'."""
            tag = tag.lower()
            base = re.split(r'[-_]', tag)[0]
            return tag in aliases or base in aliases

        # Stream validi: no forced, no bitmap, no italiano
        valid_streams = [
            s for s in streams
            if not s['forced']
            and s['codec'].lower() not in extractor.BITMAP_CODECS
            and not _lang_is(s['language'], self._ITALIAN_LANG_ALIASES)
        ]

        discarded_it = [
            s for s in streams
            if not s['forced']
            and s['codec'].lower() not in extractor.BITMAP_CODECS
            and _lang_is(s['language'], self._ITALIAN_LANG_ALIASES)
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
                if _lang_is(s['language'], self._ANCHOR_LANG_ALIASES[lang])
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
                    self._anchor_language = self._canon_lang(selected.get('language'))
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
        # whisper_language=None -> autodetect: forzare 'en' fisso (il default
        # di sync_src_language, senza UI per cambiarlo) su un film NON in
        # inglese produce anchor spazzatura senza errore visibile — il ponte
        # NLLB parte già dalla lingua sbagliata. La lingua rilevata alimenta
        # S2 tramite self._anchor_language.
        success, detected_lang = self._transcriber.transcribe_chunks(
            audio_chunks=chunks,
            output_path=str(transcribed_srt),
            whisper_language=None,
        )
        if detected_lang:
            self._anchor_language = self._canon_lang(detected_lang)
            self._log(f"  Lingua rilevata da Whisper: {detected_lang.upper()}")
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

        # Preferisce la lingua REALMENTE rilevata per l'anchor (stream
        # embedded o Whisper autodetect, impostata in S1) al default fisso
        # di configurazione: quest'ultimo esiste solo perché non c'è modo
        # di sapere in anticipo, prima di S1, quale lingua verrà usata.
        src_lang = self._anchor_language or self._src_language

        self._nllb_translator = get_translator(model_type='nllb')

        # Rete di sicurezza: _canon_lang normalizza i tag noti, ma un
        # autodetect Whisper su una lingua rara/un tag non censito può
        # ancora produrre un codice che NLLB non riconosce — senza questo
        # controllo l'intera sincronizzazione si interromperebbe (S2
        # fallisce) invece di procedere con una traduzione sub-ottimale ma
        # funzionante.
        if hasattr(self._nllb_translator, '_nllb_to_iso') and self._nllb_translator._nllb_to_iso(src_lang) is None:
            self._log(f"  ⚠️ Lingua anchor '{src_lang}' non riconosciuta da NLLB — uso il default '{self._src_language}'.")
            src_lang = self._src_language

        self._log(f"  Lingua sorgente per la traduzione: {src_lang.upper()}")
        try:
            ok = self._nllb_translator.translate_file(
                input_path=str(temp_in),
                output_path=str(temp_out),
                src_lang=src_lang,
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

    # Numero massimo di external per singola chiamata Qwen: il system prompt
    # impone "un'entry per OGNI ext_id" e con finestre dense il conteggio di
    # external può eccedere il budget di token della risposta (n_ctx) e
    # troncarla a metà JSON — vedi _LocalQwenMatcher.load() (n_ctx=8192) e
    # _qwen_max_tokens_for(). Oltre questa soglia l'ext_win viene spezzato in
    # più chiamate sulla STESSA finestra di anchor invece di allargare la
    # singola chiamata.
    #
    # 32 e non 25 per ridurre il NUMERO di chiamate, non perché una finestra
    # ci stia dentro: misurato su un episodio reale (794 cue in 41 min, 19
    # cue/min, window=20, slack=max_offset+5) gli external per finestra vanno
    # da 24 a 61, media 44,8 — il 95% delle finestre eccede 32 e viene
    # comunque spezzata in 2 chiamate. Il guadagno reale è 86 chiamate contro
    # 95 a cap 25 (e contro 104 con il vecchio slack 2×). Non alzare oltre
    # senza rimisurare i token: 64*32+128 = 2176 di risposta più il prompt
    # (20 anchor + 32 external) resta dentro n_ctx=8192, un cap doppio no.
    # NOTA: le due metà di uno split che cadono in sotto-batch diversi non si
    # vedono (`_find_split_partner` lavora sugli item di UNA sola chiamata),
    # quindi meno sotto-batch = meno split spezzati.
    _MAX_EXT_PER_CALL = 32

    @staticmethod
    def _qwen_max_tokens_for(n_items: int) -> int:
        """~46 token/item misurati con la grammar JSON attiva; 64 dà margine."""
        return min(4096, 64 * max(n_items, 1) + 128)

    # ── Modello di shift (compensa il drift PAL/NTSC) ─────────────────────────
    #
    # Il gate di plausibilità e lo slack di cattura confrontavano il nuovo
    # timestamp (corretto, preso da un anchor — che è un timestamp VERO per
    # QUESTO video, riga per riga, non un offset globale calcolato una volta:
    # vedi _step1_extract_anchors) con la posizione ORIGINALE della riga
    # esterna. Su un desync costante questo equivale a un modello con
    # pendenza zero e funziona. Su un file con drift PAL/NTSC (25fps↔23.976fps,
    # fattore ~1.0427) il desync CRESCE nel tempo: verificato con un matcher
    # semanticamente perfetto (zero allucinazioni, solo drift) che senza
    # questo modello l'output era esatto per l'11% delle righe (78% oltre 30s
    # di errore, fino a 280s) — il gate scartava come "implausibili" match
    # CORRETTI vicino alla fine del film, e lo slack di cattura non
    # proponeva nemmeno il 65% delle righe alla finestra giusta. Con il
    # modello attivo: 100% esatto, errore massimo 0.0s. Il drift non è un
    # limite del matching per-riga sugli anchor — lo era del gate.

    def _expected_shift(self, t: float) -> float:
        """
        Shift atteso (new_start − ext.start_seconds originale) al tempo `t`,
        secondo self._shift_model. Ritorna 0.0 finché _learn_shift non ha
        ancora prodotto un fit valido: comportamento IDENTICO al gate
        pre-esistente (confronto con la posizione assoluta originale).
        """
        if self._shift_model is None:
            return 0.0
        a, b = self._shift_model
        return a * t + b

    def _learn_shift(
        self,
        results:      Dict[int, MatchResult],
        ext_by_index: Dict[int, SyncSubtitle],
    ) -> None:
        """
        Aggiorna self._shift_model con un fit Theil-Sen (mediana delle
        pendenze a coppie — robusto agli outlier più di una least-squares)
        su (ext.start_seconds, new_start − ext.start_seconds) dei match
        semantici già accettati (NON 'positional'/'interpolated', che sono
        già derivati da un modello o da un fallback per rapporto d'indice,
        non da un abbinamento diretto — userli qui sarebbe circolare).
        Chiamato una volta per finestra, in ordine temporale crescente:
        il modello si affina progressivamente man mano che la
        sincronizzazione avanza nel film.

        Controllo di qualità OBBLIGATORIO prima di accettare il fit: senza,
        con un tasso di allucinazione alto il modello si adatta al rumore e
        PEGGIORA le prestazioni rispetto a non avere alcun modello (misurato:
        84% di errore >30s con un fit non validato su Qwen che allucina al
        100%, contro il 13% del comportamento senza modello). Se il fit non
        supera il controllo, self._shift_model resta quello precedente
        (probabilmente None) — mai un fit scadente.
        """
        pairs = [
            (ext_by_index[idx].start_seconds, mr.new_start_sec - ext_by_index[idx].start_seconds)
            for idx, mr in results.items()
            if mr.match_type in ('direct', 'merged', 'split_first', 'split_second')
            and idx in ext_by_index
        ]
        if len(pairs) < 8:
            return   # troppo pochi punti per un fit affidabile

        # O(n²): campiona se il numero di match accettati diventa grande
        # (su un film intero possono essere centinaia).
        if len(pairs) > 200:
            pairs = random.sample(pairs, 200)

        slopes = []
        for i in range(len(pairs)):
            ti, si = pairs[i]
            for j in range(i + 1, len(pairs)):
                tj, sj = pairs[j]
                if abs(tj - ti) > 1.0:   # evita pendenze da intervalli minuscoli/rumorosi
                    slopes.append((sj - si) / (tj - ti))
        if not slopes:
            return
        slopes.sort()
        a = slopes[len(slopes) // 2]
        a = max(-0.06, min(0.06, a))   # clamp: il drift PAL/NTSC reale è ~0.0427

        intercepts = sorted(s - a * t for t, s in pairs)
        b = intercepts[len(intercepts) // 2]

        residuals = sorted(abs(s - (a * t + b)) for t, s in pairs)
        mad = residuals[len(residuals) // 2]
        inlier_ratio = sum(1 for r in residuals if r <= 2.0) / len(pairs)
        if mad <= 2.0 and inlier_ratio >= 0.6:
            self._shift_model = (a, b)
        # altrimenti: non aggiornare — mantiene l'ultimo modello valido (o None)

    def _step3_match_subtitles(
        self,
        anchors_it: List[SyncSubtitle],
        externals:  List[SyncSubtitle],
    ) -> List[MatchResult]:
        """
        Abbina i segmenti anchor-IT a quelli external-IT usando Qwen locale.
        Processing SEQUENZIALE per finestre overlap (GPU singola).
        Fallback per interpolazione (vicini risolti) per entry non risolte,
        posizionale totale (per rapporto d'indice) solo se Qwen non è
        disponibile o il rapporto anchor/external è troppo asimmetrico per
        fidarsi del semantic matching.
        """
        model_path = (
            self.config.get('sync_qwen_model_path', '')
            or self.config.get('gender_correction_model_path', '')
        )
        qwen_ok = False

        if model_path:
            self._qwen_matcher = _LocalQwenMatcher(
                model_path=model_path,
                log_callback=self._log_callback,
            )
            qwen_ok = self._qwen_matcher.load()

        if not qwen_ok:
            self._log(
                "  ⚠️ Qwen non disponibile — abbinamento POSIZIONALE TOTALE "
                "(per rapporto d'indice, non semantico): l'output può avere "
                "errori di decine di secondi su singole righe. Configura "
                "'sync_qwen_model_path' (o 'gender_correction_model_path') "
                "per un matching affidabile."
            )
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
        ext_by_index = {e.index: e for e in externals}   # per il tie-break del merge sotto
        self._llm_entries   = 0
        self._gate_rejected = 0
        step  = max(1, self._window_size - 2)   # overlap=2 invece di 5 → ~16% meno finestre
        n_anc = len(anchors_it)

        if n_anc <= self._window_size:
            wins = [0]
        else:
            wins = list(range(0, n_anc - self._window_size + 1, step))
            # L'ultima finestra generata da range() può lasciare scoperti
            # gli ultimi 1-2 anchor (n_anc ≡ 4,5 mod step): non è un caso
            # raro (~11% dei file con window=20), e quegli anchor non
            # vengono mai proposti all'LLM. Garantisce sempre una finestra
            # che tocca la fine.
            if wins[-1] + self._window_size < n_anc:
                wins.append(n_anc - self._window_size)
        n_wins = len(wins)

        self._log(f"  Finestre da elaborare: {n_wins} (window={self._window_size}, step={step})")

        for wi, a_start in enumerate(wins):
            if self._cancelled:
                break

            a_end      = min(a_start + self._window_size, n_anc)
            anchor_win = anchors_it[a_start:a_end]
            win_t0     = anchor_win[0].start_seconds
            win_t1     = anchor_win[-1].end_seconds

            # Slack di CATTURA (quali external proporre a questa finestra) e
            # gate di PLAUSIBILITÀ (self._max_offset_sec, applicato dentro
            # _parse_llm_match_response) sono deliberatamente disaccoppiati e
            # diversi: lo slack qui resta largo (2×) per non perdere external
            # con desync vicino al limite — un external appena fuori da uno
            # slack stretto non verrebbe MAI proposto a nessuna finestra e
            # cadrebbe subito nel fallback per interpolazione, anche quando
            # l'LLM lo avrebbe risolto correttamente. È il gate a valle a
            # scartare i match implausibili (allucinazioni su dialogo
            # generico, verificate con inferenza reale), non la riduzione
            # dello slack di cattura: stringere lo slack da solo (come nel
            # primo giro di fix, ±60s→±30s) riduceva l'esposizione alle
            # allucinazioni solo per via statistica, a costo di perdere
            # copertura reale su desync 30-60s.
            #
            # Il valore giusto è però `max_offset + 5`, non `2*max_offset`:
            # è il limite ESATTO oltre il quale il gate non può comunque
            # accettare nulla. Un match è accettabile solo se esiste uno
            # new_start con win_lo <= new_start <= win_hi (bound di finestra,
            # ±5s) E |new_start - ext.start| <= max_offset; combinando le due,
            # servono ext.start <= win_t1 + 5 + max_offset e
            # ext.start >= win_t0 - 5 - max_offset. Tutto ciò che sta oltre
            # viene catturato, speso in token di prompt e poi scartato dal
            # gate: misurato su un episodio reale (794 cue, 41 min, 19
            # cue/min) con 2*max_offset il 28% degli external proposti era
            # matematicamente impossibile da accettare, la media saliva a
            # 60,9 external per finestra (max 86) e servivano 104 chiamate
            # Qwen invece di 86 — cioè ~20% di S3 speso su candidati morti.
            slack = self._max_offset_sec + 5.0
            # La cattura confronta la posizione PREVISTA (originale + shift
            # del modello appreso, vedi _expected_shift), non quella
            # originale grezza: su un file con drift PAL/NTSC il desync
            # cresce nel tempo, quindi la posizione originale di una riga
            # verso la fine del film può essere lontanissima dal vero
            # anchor pur essendo il match corretto — _expected_shift(t)
            # torna 0.0 finché non esiste un modello valido, quindi questo
            # è un'estensione, non una modifica, del comportamento
            # pre-esistente su file a desync costante.
            ext_win_all = [
                e for e in externals
                if e.end_seconds   + self._expected_shift(e.start_seconds) >= win_t0 - slack
                and e.start_seconds + self._expected_shift(e.start_seconds) <= win_t1 + slack
            ]
            if not ext_win_all:
                continue

            # Spezza in sotto-batch per non troncare la risposta JSON (vedi
            # _MAX_EXT_PER_CALL) — più chiamate sulla STESSA finestra di
            # anchor invece di una chiamata monolitica.
            win_results: List[MatchResult] = []
            for bstart in range(0, len(ext_win_all), self._MAX_EXT_PER_CALL):
                if self._cancelled:
                    break
                ext_batch = ext_win_all[bstart:bstart + self._MAX_EXT_PER_CALL]
                user_prompt = self._build_window_prompt(anchor_win, ext_batch)
                max_tokens  = self._qwen_max_tokens_for(len(ext_batch))
                raw_response = self._qwen_matcher.match_window(
                    self._SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens
                )
                if raw_response:
                    win_results.extend(self._parse_llm_match_response(
                        raw_response, anchor_win, ext_batch
                    ))

            # Vince il match migliore fra finestre sovrapposte, non la prima
            # arrivata: un external "preso in prestito" da una finestra che
            # non conteneva il suo vero anchor non produce più un match
            # 'positional' spurio, quindi qui
            # arrivano solo match semantici. `confidence` da sola NON basta
            # come criterio (misurato: Qwen la riporta quasi sempre vicina a
            # 1 anche su match sbagliati, quindi un `>` stretto degenera
            # verso "vince la prima finestra" nella pratica) — a parità
            # effettiva di confidence, a spuntarla è il match il cui nuovo
            # start è più vicino allo start ORIGINALE della riga: un match
            # corretto sposta la riga di poco (l'offset di desync reale),
            # uno sbagliato la sposta di molto (vedi il gate di plausibilità
            # in _parse_llm_match_response, che comunque scarta la maggior
            # parte di questi casi PRIMA di arrivare qui).
            for mr in win_results:
                prev = results.get(mr.external_index)
                if prev is None:
                    results[mr.external_index] = mr
                    continue
                if mr.confidence > prev.confidence + 1e-6:
                    results[mr.external_index] = mr
                elif abs(mr.confidence - prev.confidence) <= 1e-6:
                    ext = ext_by_index.get(mr.external_index)
                    if ext is not None:
                        d_new  = abs(mr.new_start_sec - ext.start_seconds)
                        d_prev = abs(prev.new_start_sec - ext.start_seconds)
                        if d_new < d_prev:
                            results[mr.external_index] = mr

            # Riaffina il modello di shift (drift PAL/NTSC) con i match di
            # QUESTA finestra: le finestre sono processate in ordine
            # temporale crescente, quindi il modello migliora man mano che
            # la sincronizzazione avanza nel film. Va fatto qui, non dopo il
            # loop: la finestra successiva deve già poter usare il modello
            # aggiornato nel proprio slack di cattura e gate di plausibilità.
            self._learn_shift(results, ext_by_index)

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

        # Tasso di scarto del gate: se l'LLM propone abbondantemente ma quasi
        # nulla passa, la causa quasi sempre è che il desync reale del file
        # supera `sync_max_offset_sec` (default 30s, senza UI: si edita solo
        # a mano in config.json). Senza questa riga il sintomo è muto — si
        # vede solo un file interamente 'interpolated' o 'positional' e non
        # se ne capisce il motivo.
        entries  = getattr(self, '_llm_entries', 0)
        rejected = getattr(self, '_gate_rejected', 0)
        if entries and rejected / entries > 0.5:
            self._log(
                f"  ⚠️ Il gate di plausibilità ha scartato {rejected}/{entries} "
                f"proposte dell'LLM ({100 * rejected / entries:.0f}%): il desync "
                f"del file supera probabilmente 'sync_max_offset_sec' "
                f"({self._max_offset_sec:.0f}s) — alzalo in config.json e riprova."
            )
        elif entries:
            self._log(
                f"  Gate di plausibilità: {rejected}/{entries} proposte scartate "
                f"({100 * rejected / entries:.0f}%)."
            )

        # Fallback per interpolazione (dai vicini risolti) per external non
        # risolti da nessuna finestra: MAI _positional_fallback qui, che
        # sparge un sottoinsieme sparso su TUTTO l'arco degli anchor (vedi
        # _interpolate_fallback).
        unresolved = [e for e in externals if e.index not in results]
        if unresolved:
            self._log(f"  Fallback per interpolazione per {len(unresolved)} sottotitoli non abbinati.")
            for mr in self._interpolate_fallback(externals, results, anchors_it):
                results[mr.external_index] = mr

        return [results[k] for k in sorted(results)]

    # ── STEP 4 ────────────────────────────────────────────────────────────────

    def _step4_build_output(
        self,
        externals: List[SyncSubtitle],
        matches:   List[MatchResult],
    ) -> bool:
        """
        Applica i nuovi timestamp e scrive l'output. NON usa SubtitleFormatter:
        quel formatter è pensato per l'output di un aligner (fonde cue vicine,
        ritaglia a capo le righe lunghe, ricalcola durate minime, ripulisce
        tag) — qui il testo è già italiano corretto scritto dall'utente e il
        contratto della feature è "cambia SOLO i tempi". Passarlo da
        SubtitleFormatter fondeva cue con timestamp identici (conseguenza di
        BUG 3) perdendo battute, e alterava testo/formattazione che non
        andava toccato. Gestisce la split di anchor per 2 external ↔ 1
        anchor: new_start_sec/new_end_sec sono già calcolati correttamente da
        _parse_llm_match_response.
        """
        if not matches:
            self._log("  ERRORE: nessun match prodotto — output non scritto.")
            return False

        match_map = {mr.external_index: mr for mr in matches}
        clamped = 0

        for ext in externals:
            mr = match_map.get(ext.index)
            if mr:
                ext.update_times(mr.new_start_sec, mr.new_end_sec)

        ordered = sorted(externals, key=lambda x: x.start_seconds)

        # Passata di sanità: un match sbagliato (LLM o fallback) può produrre
        # un end &lt;= start, o un overlap ampio con la cue successiva — non i
        # micro-overlap da arrotondamento che SubtitleFormatter._fix_overlaps
        # era pensato a coprire. Qui si limita il danno invece di scrivere un
        # SRT malformato; ogni clamp è un segnale che il matching per quella
        # riga è dubbio, quindi va loggato per intero, non silenziato.
        # Le cue con start quasi identici si trattano in BLOCCO, non a
        # coppie. A coppie (com'era) l'intervallo utile della prima veniva
        # tagliato dal confine con la TERZA, che nella pila ha lo stesso
        # start: span_end collassava sullo start stesso e la prima cue
        # tornava a durare 0,1s, cioè invisibile a schermo — esattamente il
        # difetto che il trattamento a coppie doveva risolvere (verificato:
        # 3 cue sullo stesso start davano 0,100s / 2,450s / 2,450s; 5 ne
        # davano tre da 0,100s). Le pile di 3+ non sono un caso di
        # laboratorio: _positional_fallback assegna lo stesso anchor — quindi
        # gli stessi identici timestamp — a tutti gli external che cadono
        # nello stesso rapporto d'indice.
        i = 0
        while i < len(ordered):
            s = ordered[i]
            if s.end_seconds <= s.start_seconds:
                clamped += 1
                s.update_times(s.start_seconds, s.start_seconds + 1.0)

            # Raccoglie la pila: cue consecutive che iniziano entro 0,2s
            # dalla prima.
            j = i + 1
            while j < len(ordered) and ordered[j].start_seconds - s.start_seconds < 0.2:
                j += 1

            if j > i + 1:
                run = ordered[i:j]
                clamped += len(run) - 1
                span_end = max(x.end_seconds for x in run)
                if j < len(ordered):
                    # `ordered[j]` non è ancora stato toccato e per
                    # costruzione inizia almeno 0,2s dopo: il confine è reale.
                    span_end = min(span_end, ordered[j].start_seconds)
                if span_end <= s.start_seconds:
                    span_end = s.start_seconds + 0.1 * len(run)
                width = (span_end - s.start_seconds) / len(run)
                t = s.start_seconds
                for x in run:
                    x.update_times(t, t + width)
                    t += width
                i = j
                continue

            if i + 1 < len(ordered):
                nxt = ordered[i + 1]
                if s.end_seconds > nxt.start_seconds:
                    clamped += 1
                    new_end = max(s.start_seconds + 0.05, nxt.start_seconds - 0.020)
                    s.update_times(s.start_seconds, new_end)
            i += 1

        for n, s in enumerate(ordered, start=1):
            s.index = n

        if clamped:
            self._log(
                f"  ⚠️ {clamped} timestamp corretti per inversione/overlap "
                f"dopo il matching — segnale di match dubbi, verifica il file."
            )

        try:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_srt_file(ordered, self._output_path)
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
                # Indice POSIZIONALE (len(subs)+1), non quello dichiarato nel
                # file: `index` è usato come chiave nei dizionari di matching
                # (results/anchor_map/external_map) in tutta la pipeline —
                # un SRT con numerazione duplicata o che riparte da 1 (capita
                # su file scaricati/concatenati) farebbe collidere due cue
                # distinte sulla stessa chiave, perdendone una in silenzio.
                subs.append(SyncSubtitle(
                    index=len(subs) + 1,
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

    @staticmethod
    def _find_split_partner(items: list, anc_key: str, ext_id: str) -> Optional[str]:
        """
        Trova l'ext_id dell'altra metà di uno split_first/split_second sullo
        stesso anchor. Sostituisce una comprehension annidata che ricalcolava
        un set filtrando l'intero `items` per OGNI entry di split (O(n²)) e
        che testava `if anchor_ids` (la variabile dell'item CORRENTE, sempre
        vera a quel punto — un copia-incolla che non proteggeva nulla) invece
        di controllare gli anchor_ids dell'item `it` in esame.
        """
        for it in items:
            if str(it.get('match_type', '')) not in ('split_first', 'split_second'):
                continue   # un 'direct'/'merged' che referenzia lo stesso
                           # anchor non è il partner dello split: usarlo
                           # calcolerebbe il rapporto di caratteri sul
                           # testo sbagliato (osservato: pescava un match
                           # 'direct' genuino sullo stesso anchor)
            aids = it.get('anchor_ids') or []
            if not aids:
                continue
            if str(aids[0]) == anc_key and str(it.get('ext_id', '')) != ext_id:
                return str(it.get('ext_id', ''))
        return None

    def _parse_llm_match_response(
        self,
        raw: str,
        anchor_win:   List[SyncSubtitle],
        external_win: List[SyncSubtitle],
    ) -> List[MatchResult]:
        """
        Pulisce la risposta e fa json.loads(). Gestisce backtick Markdown,
        calcola split proporzionali.

        Le entry non risolte in QUESTA finestra (no_match, ext_id non
        trovato, JSON non parsabile) restano fuori dal risultato invece di
        ricevere un fallback posizionale ristretto agli anchor della
        finestra — quel fallback ristretto è quello che produceva errori di
        decine di secondi su righe "prese in prestito" da una finestra
        adiacente, che qui non possono essere risolte perché il loro vero
        anchor non è nel prompt. Le entry davvero irrisolte le recupera
        _interpolate_fallback a fine _step3_match_subtitles, con visibilità
        sull'intero file — non esiste (né è mai esistito un chiamante per)
        una modalità che estenda questo fallback all'intera finestra qui
        dentro: se in futuro serve, va reintrodotta con un parametro
        esplicito, non lasciata "disponibile ma inutilizzata" (rischio di
        essere riattivata per errore, come il ramo split che il primo giro
        di fix ha trovato reso permanentemente morto dallo stesso pattern).
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
            return []

        # Bound geometrici della finestra (+5s di margine): un timestamp
        # dell'LLM fuori da questo intervallo, o con durata assurda, è
        # un'allucinazione — capita anche con la grammar GBNF attiva, che
        # forza il formato JSON ma non la plausibilità dei valori. Questo
        # controllo non dipende dall'onestà auto-riportata di `confidence`
        # (osservata sempre vicina a 1 nei test reali, quindi inutile come
        # soglia da sola).
        #
        # GATE DI OFFSET (in aggiunta ai bound di finestra sopra): misurato
        # con inferenza reale che Qwen risolve con sicurezza (spesso
        # confidence=1.0) dialoghi generici — "Sì.", "Va bene.", "Ok." — su
        # anchor semanticamente simili ma lontani decine di secondi, quando
        # la vera collocazione dell'external è in una finestra diversa.
        # Confronta con la posizione PREVISTA (_expected_shift), non con
        # quella originale grezza: su un desync costante _expected_shift
        # torna 0.0 finché non c'è un modello, quindi il comportamento è
        # identico a un confronto assoluto — ma su un file con drift
        # PAL/NTSC (desync che CRESCE nel tempo) un confronto assoluto
        # scarterebbe come "implausibili" match CORRETTI verso la fine del
        # film: verificato (matcher semanticamente perfetto, zero
        # allucinazioni, solo drift) 11% di righe esatte / 78% oltre 30s di
        # errore col confronto assoluto, 100% esatto con _expected_shift.
        # sync_max_offset_sec resta il significato originale — tolleranza
        # massima attesa attorno alla legge di desync del file (costante
        # sola, o costante+drift una volta che il modello si affina) — non
        # un limite sulla posizione assoluta.
        win_lo = anchor_win[0].start_seconds - 5.0
        win_hi = anchor_win[-1].end_seconds + 5.0
        max_offset = self._max_offset_sec

        def _plausible(start: float, end: float, ext: SyncSubtitle) -> bool:
            expected = ext.start_seconds + self._expected_shift(ext.start_seconds)
            return (
                win_lo <= start <= win_hi
                and 0.1 <= (end - start) <= 30.0
                and abs(start - expected) <= max_offset
            )

        # Contatori di osservabilità del gate: quante entry l'LLM ha proposto
        # e quante ne sono state scartate. Un tasso di scarto alto è il
        # segnale — altrimenti invisibile — che `sync_max_offset_sec` è
        # tarato più stretto del desync reale del file: in quel caso il gate
        # rifiuta OGNI match e la pipeline scivola sul fallback posizionale
        # totale senza che nulla lo spieghi. Vedi il riepilogo in
        # _step3_match_subtitles.
        self._llm_entries = getattr(self, '_llm_entries', 0) + len(items)

        results: List[MatchResult] = []
        already_split:    Dict[str, float] = {}       # anc_key -> punto di split
        split_roles_used: Dict[str, Set[str]] = {}     # anc_key -> {'split_first','split_second'} già emessi

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

                # match_type PRIMA della scorciatoia sui timestamp: la
                # grammar GBNF rende new_start_sec/new_end_sec obbligatori,
                # quindi anche un 'no_match' esplicito o uno split arrivano
                # sempre con timestamp validi (spesso IDENTICI per le due
                # metà di uno split) — controllarli per primi li accettava
                # come match diretto, rendendo il ramo split sotto codice
                # morto e onorando 'no_match' solo per caso (quando l'LLM
                # emetteva 0.0/0.0).
                if match_type == 'no_match':
                    continue   # resta irrisolto -> _interpolate_fallback

                if match_type in ('split_first', 'split_second'):
                    if not anchor_ids:
                        continue
                    anc_key = anchor_ids[0]
                    anc     = anchor_map.get(anc_key)
                    if anc is None:
                        continue

                    # 3+ split sullo stesso anchor: already_split memorizza
                    # UN solo punto di taglio binario, un terzo/quarto
                    # richiedente riceverebbe timestamp duplicati con un
                    # altro. Meglio lasciarlo irrisolto (interpolato dopo)
                    # che scrivere due cue identiche.
                    if match_type in split_roles_used.get(anc_key, set()):
                        continue

                    if anc_key in already_split:
                        split_pt    = already_split[anc_key]
                        newly_split = False
                    else:
                        partner_id  = self._find_split_partner(items, anc_key, ext_id)
                        partner_ext = external_map.get(partner_id) if partner_id else None
                        duration    = anc.end_seconds - anc.start_seconds
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
                        newly_split = True

                    if match_type == 'split_first':
                        s, e = anc.start_seconds, split_pt
                    else:
                        s, e = split_pt, anc.end_seconds

                    # GATE DI OFFSET ANCHE SUGLI SPLIT. Il gate `_plausible`
                    # sotto copre solo i rami direct/merged: uno split
                    # allucinato — stesso identico errore, ma dichiarato con
                    # un altro match_type — passava del tutto libero, perché
                    # i suoi timestamp sono ricavati dall'anchor e quindi
                    # sempre dentro i bound della finestra. Misurato in
                    # simulazione avversaria (1200 righe, desync 9,5s,
                    # allucinazioni al 30%): errore massimo 176s e 14% delle
                    # righe oltre 30s, contro i 38,5s di errore massimo
                    # (= max_offset + desync reale, il limite matematico del
                    # gate) quando le stesse allucinazioni escono come
                    # 'direct'. Qui si applica SOLO il vincolo di offset e
                    # non `_plausible` per intero: le due metà di uno split
                    # sono legittimamente più brevi di 0,1s su anchor molto
                    # corti, e i bound di finestra sono già garantiti per
                    # costruzione (s,e vengono dall'anchor stesso).
                    expected = ext.start_seconds + self._expected_shift(ext.start_seconds)
                    if abs(s - expected) > max_offset:
                        self._gate_rejected = getattr(self, '_gate_rejected', 0) + 1
                        continue

                    # Lo stato di split si registra SOLO su un match
                    # accettato: memorizzare il punto di taglio di uno split
                    # poi scartato lo farebbe riusare tale e quale dal
                    # partner legittimo, che invece deve ricalcolarlo sul
                    # proprio testo.
                    if newly_split:
                        already_split[anc_key] = split_pt
                    split_roles_used.setdefault(anc_key, set()).add(match_type)

                    results.append(MatchResult(
                        external_index=ext.index,
                        anchor_indices=[anc.index],
                        new_start_sec=s,
                        new_end_sec=e,
                        match_type=match_type,
                        confidence=confidence,
                    ))
                    continue

                # direct / merged / qualunque altro valore: usa i timestamp
                # dell'LLM SOLO se geometricamente plausibili rispetto alla
                # finestra E all'offset atteso, altrimenti ricalcola dagli
                # anchor indicati.
                if _plausible(new_start, new_end, ext):
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

                if not anchor_ids:
                    self._gate_rejected = getattr(self, '_gate_rejected', 0) + 1
                    continue
                first_anc = anchor_map.get(anchor_ids[0])
                if first_anc is None:
                    self._gate_rejected = getattr(self, '_gate_rejected', 0) + 1
                    continue
                last_anc = anchor_map.get(anchor_ids[-1], first_anc)
                # 'merged' deve coprire anchor ADIACENTI (l'external combina
                # righe consecutive) — un merge fra anchor lontani nella
                # finestra è la stessa allucinazione del gate sopra, solo
                # senza timestamp diretti da controllare. Senza questo
                # controllo un 'merged' con anchor_ids sbagliati produce
                # comunque un intervallo enorme (osservato: 52s), che il
                # gate su new_start/new_end non intercetta perché qui non
                # stiamo usando i timestamp dell'LLM ma quelli ricalcolati.
                if match_type == 'merged' and abs(last_anc.index - first_anc.index) > 2:
                    self._gate_rejected = getattr(self, '_gate_rejected', 0) + 1
                    continue
                if not _plausible(first_anc.start_seconds, last_anc.end_seconds, ext):
                    self._gate_rejected = getattr(self, '_gate_rejected', 0) + 1
                    continue
                results.append(MatchResult(
                    external_index=ext.index,
                    anchor_indices=[int(a[1:]) for a in anchor_ids if a in anchor_map],
                    new_start_sec=first_anc.start_seconds,
                    new_end_sec=last_anc.end_seconds,
                    match_type=match_type,
                    confidence=confidence,
                ))

            except Exception as parse_err:
                logger.debug(f"Skip item malformato: {parse_err}")
                continue

        return results

    # ── Helper: fallback posizionale / interpolazione ────────────────────────

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

    def _interpolate_fallback(
        self,
        all_externals: List[SyncSubtitle],
        results:       Dict[int, MatchResult],
        anchors:       List[SyncSubtitle],
    ) -> List[MatchResult]:
        """
        Fallback per i sottotitoli esterni non risolti da nessuna finestra
        Qwen: interpola lo SHIFT (nuovo_start − vecchio_start) dai vicini
        RISOLTI più prossimi, ordinati per posizione originale — non per
        rapporto d'indice sul sottoinsieme dei non risolti
        (_positional_fallback), che sparge un pugno di righe sparse su TUTTO
        l'arco degli anchor: con un solo external non risolto in tutto il
        file, quel calcolo lo sposta sempre all'inizio (ratio=0/max(0,1)=0),
        qualunque fosse la sua posizione reale. La durata originale della
        riga viene conservata (non quella dell'anchor, che può essere molto
        diversa).
        """
        order = sorted(all_externals, key=lambda e: e.start_seconds)
        shifts: List[Tuple[int, float]] = [
            (i, results[e.index].new_start_sec - e.start_seconds)
            for i, e in enumerate(order)
            if e.index in results
        ]
        if not shifts:
            # Nessun vicino risolto in TUTTO il file: non c'è nulla da
            # interpolare — ultima spiaggia il posizionale totale (per
            # rapporto d'indice, senza alcuna garanzia semantica). Logga
            # esplicitamente: il chiamante annuncia genericamente "fallback
            # per interpolazione", che qui sarebbe fuorviante — è il
            # caso peggiore della pipeline, non un'interpolazione affidabile.
            self._log(
                "  ⚠️ Nessun sottotitolo risolto da Qwen in tutto il file — "
                "fallback POSIZIONALE TOTALE (per rapporto d'indice, senza "
                "garanzia semantica): il file va verificato a mano."
            )
            return self._positional_fallback(anchors, all_externals, set(results))

        out: List[MatchResult] = []
        for i, e in enumerate(order):
            if e.index in results:
                continue
            prev_shift = next(((j, s) for j, s in reversed(shifts) if j <= i), None)
            next_shift = next(((j, s) for j, s in shifts if j >= i), None)
            if prev_shift and next_shift:
                (jp, sp), (jn, sn) = prev_shift, next_shift
                shift = sp if jp == jn else sp + (i - jp) / (jn - jp) * (sn - sp)
            elif prev_shift:
                shift = prev_shift[1]
            elif next_shift:
                shift = next_shift[1]
            else:
                shift = 0.0
            dur = e.end_seconds - e.start_seconds
            new_start = max(0.0, e.start_seconds + shift)
            out.append(MatchResult(
                external_index=e.index,
                anchor_indices=[],
                new_start_sec=new_start,
                new_end_sec=new_start + dur,
                match_type='interpolated',
                confidence=0.3,
            ))
        return out

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
            # "original_srt"/"character_context" sono chiavi del vecchio
            # motore, ignorate da core/gender_corrector_cli.py (v2): la
            # chiave che serve davvero è "video_path", da cui si costruisce
            # la speaker gender map dall'audio. Senza — come prima di questo
            # fix — gender_corrector_v2 non ha nulla da cui correggere,
            # ritorna comunque successo (exit 0) copiando il file INVARIATO,
            # e questo metodo lo registrava come "Correzione genere
            # applicata" quando in realtà non aveva fatto nulla, pagando
            # comunque lo spawn del subprocess + venv NLP per zero risultato.
            # character_context vuoto (qui non c'è metadata TMDB, a
            # differenza della pipeline principale) degrada solo i vocativi
            # di 2a persona, non la correzione di 1a persona dall'audio.
            args_payload = {
                "input_srt":         str(self._output_path),
                "output_srt":        str(corrected),
                "video_path":        str(self.video_path),
                "diarization_json":  None,
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
                # gender_corrector_v2 ritorna successo anche quando non ha
                # potuto correggere nulla (es. video_path assente), copiando
                # il file INVARIATO: un confronto dei byte distingue una
                # correzione vera da un no-op silenzioso, invece di
                # dichiarare sempre "applicata".
                try:
                    unchanged = corrected.read_bytes() == self._output_path.read_bytes()
                except Exception:
                    unchanged = False
                shutil.copy2(str(corrected), str(self._output_path))
                if unchanged:
                    self._log("  Correzione genere: nessuna modifica necessaria.")
                else:
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
