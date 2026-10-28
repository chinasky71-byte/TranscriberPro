# -*- coding: utf-8 -*-
"""
SubtitleSynchronizer — Pipeline "Anchor & Match"
File: core/subtitle_synchronizer.py

Allinea un file .srt italiano esterno (fuori sincrono) ai timestamp corretti
estratti dai sottotitoli embedded di un video (o dai tempi del parlato).

PIPELINE (unico percorso, ADR-009):
    S1  10%  Ancoraggio      — estrae timing di riferimento dal video
    S2  40%  Allineamento    — scala/offset globali + offset a tratti sul parlato,
                               senza LLM (core/timing_aligner.py). Copertura troppo bassa = coppia fallita.
    S4  95%  Rifinitura      — costruisce SRT finale + VRAM cleanup
    done 100%

Il vecchio percorso 'llm' (NLLB traduceva gli anchor, Qwen2.5-14B li abbinava al
testo esterno) e' stato rimosso insieme a NLLB: era un secondo motore, non un
ripiego, e questo sincronizzatore confronta TEMPI, non testi.
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
from utils.translations import all_texts, tr

logger = logging.getLogger(__name__)

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
    # legge da _step23_timing_align, che può essere chiamato anche su istanze
    # costruite per test senza passare dal vero __init__.
    _shift_model: Optional[Tuple[float, float]] = None

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
            # Definizione UNICA del percorso di output (core/sync_pairing.py): la tabella della coda
            # multi-file e il file realmente scritto coincidono per costruzione.
            from core.sync_pairing import default_output_path
            self._output_path = default_output_path(self.external_srt_path)

        self._log_callback      = log_callback
        self._progress_callback = progress_callback

        # Cancellazione
        self._cancelled: bool = False
        self._current_proc: Optional[subprocess.Popen] = None

        # Riferimenti ai modelli per cleanup
        self._transcriber      = None
        self._audio_processor  = None
        self._cleanup_done: bool = False

        # Parametri da config
        self._src_language: str = self.config.get('sync_src_language', 'en')
        self._max_offset_sec: float = float(self.config.get('sync_max_offset_sec', 30))
        self._switch_cost: float = float(self.config.get('sync_timing_switch_cost', 5.0))
        # Indice di sovrapposizione al netto del caso (TimingAlignResult.lift). Misurato su coppie giuste/sbagliate:
        #   riferimento = sottotitoli incorporati: giuste >= 0.87, sbagliate <= 0.42 -> rifiuto < 0.60, avviso < 0.80
        #   riferimento = VAD dell'audio:         giuste >= 0.38, sbagliate <= 0.23 -> rifiuto < 0.30, avviso < 0.50
        self._anchor_kind: str = 'sub'      # 'sub' | 'vad' (impostato da S1)
        self.last_error: Optional[str] = None
        # Lingua della traccia embedded da cui vengono gli anchor (None se il
        # riferimento sono i tempi del parlato): informativa per il log.
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
            self._log(tr('sy_synchronization').format(name=self.video_path.name))
            self._log(tr('sy_external_srt').format(name=self.external_srt_path.name))
            self._log(tr('sy_output').format(name=self._output_path.name))
            self._log("=" * 68)

            externals = self._parse_srt_file(self.external_srt_path)
            if not externals:
                self._log(tr('sy_error_external_srt_empty_or'))
                return False
            self._log(tr('sy_external_srt_subtitles_loaded').format(n=len(externals)))

            # ── S1: Ancoraggio ────────────────────────────────────────────
            self._log(tr('sy_1_anchoring_extracting_reference_timing'))
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
                self._log(tr('sy_error_s1_insufficient_anchors_minimum').format(n=len(anchors or [])))
                return False
            self._log(tr('sy_anchors_extracted_segments').format(n=len(anchors)))
            self._report_progress(self._STEP_PCT['S1'])

            self._unload_transcriber()

            # ── S2+S3: allineamento solo temporale. ADR-009: non esiste piu'
            # un secondo motore che possa tradurre gli anchor per un confronto
            # semantico, quindi il percorso 'llm' (NLLB + Qwen) e' stato rimosso
            # insieme a NLLB. Il confronto e' sui TEMPI, non sul testo.
            self._log(tr('sy_2_alignment_global_scale_offset'))
            matches = self._step23_timing_align(anchors, externals)
            if self._cancelled:
                return False
            if matches is None:
                # Copertura bassa = SRT che non corrisponde al video (episodio o
                # lingua sbagliati): nessun motore puo' rimediare e scrivere un
                # output sarebbe peggio.
                return False
            self._report_progress(self._STEP_PCT['S2'])
            self._log(tr('sy_3_check_speech_coverage_verified'))
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
            self._log(tr('sy_match_total').format(summary=riepilogo, n=len(matches)))
            self._report_progress(self._STEP_PCT['S3'])

            # ── S4: Rifinitura ────────────────────────────────────────────
            self._log(tr('sy_4_finishing_building_the_final'))
            ok = self._step4_build_output(externals, matches)
            if not ok:
                self._log(tr('sy_error_s4_writing_the_output'))
                return False
            self._report_progress(self._STEP_PCT['S4'])

            self._log(tr('sy_synchronization_completed').format(name=self._output_path.name))
            self._report_progress(self._STEP_PCT['done'])
            return True

        except Exception as e:
            self._log(tr('sy_critical_error').format(e=e))
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
        Normalizza un tag lingua GREZZO (da ffprobe) al codice ISO 639-2.
        Il ponte semantico su NLLB e' stato rimosso (ADR-009), quindi il valore
        non alimenta piu' un traduttore: resta informativo nel log, dove un tag
        regionale ('pt-BR', 'pob') e' comunque piu' utile normalizzato.
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
                tr('sy_discarded_embedded_italian_streams_not').format(n=len(discarded_it))
            )

        selected = None

        if valid_streams:
            self._log(tr('sy_found_valid_non_it_streams').format(n=len(valid_streams)))

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
                tr('sy_anchor_selected_stream').format(lang=chosen['language'].upper(), tag=tag, index=chosen['index'])
            )
            selected = chosen
            break

        # Fallback: primo stream non-IT disponibile (lingua non in lista priorità)
        if selected is None and valid_streams:
            selected = valid_streams[0]
            self._log(
                tr('sy_no_priority_language_found_using').format(lang=selected['language'].upper(), index=selected['index'])
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
                        tr('sy_embedded_anchors_extracted_language').format(n=len(subs), lang=selected.get('language', '?').upper())
                    )
                    return subs
            self._log(tr('sy_embedded_extraction_failed_audio'))
        else:
            self._log(tr('sy_no_non_italian_embedded_audio'))

        # Whisper fallback
        if not self.config.get('sync_allow_whisper_fallback', True):
            self._log(tr('sy_fallback_on_the_audio_speech'))
            return None

        return self._step1_vad_fallback()

    def _step1_vad_fallback(self) -> Optional[List[SyncSubtitle]]:
        """
        Fallback del motore 'timing' quando il video non ha sottotitoli non-italiani: il riferimento e' il
        PARLATO dell'audio, non il suo testo. Estrae la traccia, isola le voci (Demucs) e ne ricava gli intervalli
        con il nostro Silero VAD (core/vad.py, onnxruntime, CPU). Niente trascrizione: i segmenti da ~20 s di un
        ASR producevano maschere troppo grossolane (misurato: 61% entro 0,5 s su un film con musica invadente).
        La lingua dell'audio e' irrilevante per i soli tempi.
        """
        from core.audio_track_selector import AudioTrackSelector
        from core.audio_processor import AudioProcessor

        selector = AudioTrackSelector(str(self.video_path))
        stream = selector.select_best_track()
        if not stream:
            self._log(tr('sy_no_audio_track_found_in'))
            return None
        audio_path = self.file_handler.get_temp_path(self.video_path, "anchor_audio.wav")
        if not selector.extract_audio_track(audio_path, stream['index']):
            self._log(tr('sy_audio_track_extraction_failed'))
            return None
        self._audio_processor = AudioProcessor()
        self._audio_processor.set_log_callback(self._log_callback)
        self._log(tr('sy_vocal_separation_demucs_to_isolate'))
        vocals = self._audio_processor.separate_vocals(audio_path)
        if self._cancelled:
            return None
        if not vocals or not Path(vocals).exists():
            self._log(tr('sy_vocal_separation_failed_using_the'))
            vocals = audio_path
        try:
            # VAD proprio (core/vad.py, Silero su onnxruntime): nessuna dipendenza da
            # faster-whisper, che non c'e' piu'. Gli intervalli sono in campioni.
            from core import vad as vad_module
            wave = vad_module.decode_audio(Path(vocals), sampling_rate=16000)
            stamps = vad_module.speech_timestamps(wave, sampling_rate=16000,
                                                  threshold=0.5, min_speech_ms=250,
                                                  min_silence_ms=300, pad_ms=100)
        except Exception as e:
            self._log(tr('sy_vad_failed').format(e=e))
            return None
        self._anchor_kind = 'vad'
        subs = [
            SyncSubtitle(index=i + 1, start_time=SyncSubtitle._sec_to_ts(st['start'] / 16000.0),
                         end_time=SyncSubtitle._sec_to_ts(st['end'] / 16000.0), text='(voce)')
            for i, st in enumerate(stamps)
        ]
        self._log(tr('sy_vad_speech_intervals').format(n=len(subs)))
        return subs

    # ── STEP 2+3 (motore 'timing') ───────────────────────────────────────────

    def _step23_timing_align(
        self, anchors: List[SyncSubtitle], externals: List[SyncSubtitle]
    ) -> Optional[List[MatchResult]]:
        """
        Allineamento solo temporale (core/timing_aligner.py): scala+offset globali e offset a tratti, cercando la
        sovrapposizione fra il parlato dell'SRT esterno e quello dell'anchor. Nessun LLM, nessuna GPU: secondi
        invece di un'ora. Ritorna None (coppia FALLITA, nessun output) se la copertura del parlato e' sotto soglia:
        SRT di un altro episodio/lingua o anchor inutilizzabile.
        """
        from core import timing_aligner as TA

        ordered = sorted(externals, key=lambda x: x.start_seconds)
        res = TA.align(
            [(e.start_seconds, e.end_seconds) for e in ordered],
            [(a.start_seconds, a.end_seconds) for a in anchors],
            switch_cost=self._switch_cost,
            log=self._log,
        )
        if res is None:
            self._log(tr('sy_time_alignment_impossible_insufficient_data'))
            return None

        for note in res.notes:
            if any(k in note for k in all_texts('logm_kw_window')):
                self._log(tr('sy_msg').format(note=note))
        min_lift, warn_lift = (0.30, 0.50) if self._anchor_kind == 'vad' else (0.60, 0.80)
        if res.lift < min_lift:
            self._log(
                tr('sy_error_the_srt_does_not').format(mean_coverage=res.mean_coverage, density=res.density, lift=res.lift, min_lift=min_lift)
            )
            return None
        if res.lift < warn_lift:
            self._log(
                tr('sy_doubtful_result_overlap_index_coverage').format(lift=res.lift, warn_lift=warn_lift, mean_coverage=res.mean_coverage)
            )

        matches = [
            MatchResult(
                external_index=e.index,
                anchor_indices=[],
                new_start_sec=ns,
                new_end_sec=ne,
                match_type='timing',
                confidence=cov,
            )
            for e, (ns, ne), cov in zip(ordered, res.new_intervals, res.coverage)
        ]

        if res.n_pieces > 1:
            self._log(tr('sy_found_segments_with_a_different').format(n_pieces=res.n_pieces))
        dubious = [(e, c) for e, c in zip(ordered, res.coverage) if c < 0.2]
        if dubious:
            def _fmt(t: float) -> str:
                return f"{int(t // 60)}:{int(t % 60):02d}"
            pos = ", ".join(_fmt(m.new_start_sec) for m in
                            [mm for mm, c in zip(matches, res.coverage) if c < 0.2][:6])
            self._log(
                tr('sy_lines_out_of_without_reference').format(n=len(dubious), total=len(ordered), pos=pos, ellipsis=' …' if len(dubious) > 6 else '')
            )
        return matches

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
            self._log(tr('sy_error_no_match_produced_output'))
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
                tr('sy_timestamps_corrected_for_inversion_overlap').format(clamped=clamped)
            )

        try:
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_srt_file(ordered, self._output_path)
            self._log(tr('sy_written').format(output_path=self._output_path))
        except Exception as e:
            self._log(tr('sy_write_error').format(e=e))
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
                tr('sy_no_subtitle_resolved_by_qwen')
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

            self._log(tr('sy_starting_gender_corrector_subprocess'))
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
                    self._log(tr('sy_gender_correction_no_change_needed'))
                else:
                    self._log(tr('sy_gender_correction_applied'))
            elif not self._cancelled:
                self._log(
                    tr('sy_gender_correction_failed_exit_using').format(return_code=return_code)
                )

            try:
                args_path.unlink(missing_ok=True)
            except Exception:
                pass

        except Exception as e:
            self._log(tr('sy_gender_correction_error').format(e=e))
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
        if message.lstrip().startswith(all_texts('logm_error_prefix')):
            self.last_error = message.strip()          # motivo del fallimento, riportato dalla coda (result.json)
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
