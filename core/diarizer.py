"""
Speaker Diarizer
File: core/diarizer.py

Integra pyannote.audio per identificare i parlanti in un file audio
e assegnare il campo 'speaker' a ogni segmento Whisper.

Word-level alignment: se il segmento ha word timestamps (BatchedInferencePipeline),
il segmento viene diviso ai confini esatti di cambio parlante, rilevando cambi
anche all'interno di un singolo segmento Whisper.
"""
from __future__ import annotations
import bisect
import torch
from typing import List, Tuple, Dict, Optional, Callable, NamedTuple
from utils.translations import tr
from utils.eta import EtaEstimator
from utils.events import emit as _tp_emit
from core.diar_progress import DiarProgress


class _DiarBar:
    """Barra della diarizzazione: riga di log (si aggiorna sul posto nella card) ed evento `bar` con ETA, come la correzione di genere.

    `set(frazione)` accetta 0..1 monotona; emette solo quando la percentuale intera cambia. Va creata all'inizio del lavoro."""

    def __init__(self, log: Callable[[str], None]):
        self._log = log
        self._eta = EtaEstimator()
        self._last = -1

    def set(self, fraction: float) -> None:
        pct = int(max(0.0, min(float(fraction), 1.0)) * 100)
        if pct <= self._last:
            return
        self._last = pct
        eta_s = None
        if pct < 100:
            self._eta.update(pct / 100.0)
            eta_s = self._eta.eta_seconds()
        _tp_emit('bar', phase='diarize', pct=pct, eta_s=eta_s)
        if pct >= 100:
            self._log(tr('dr_progress_done'))
        else:
            bar = '\u2588' * (pct // 10) + '\u2591' * (10 - pct // 10)
            eta_str = "-" if eta_s is None else (f"~{eta_s}s" if eta_s < 60 else f"~{int(eta_s / 60 + 0.5)}m")
            self._log(tr('dr_progress_eta').format(bar=bar, progress=pct, eta_str=eta_str))


class SpeakerVote(NamedTuple):
    """Esito del voto pesato sull'overlap per una singola parola
    (v. piano_fix_pipeline_trascrizione punto C.1)."""
    speaker: str
    overlap: float
    runner_up: Optional[str]
    runner_up_overlap: float
    margin: float  # (overlap - runner_up_overlap) / durata_parola_allargata, in [0,1]


class Diarizer:
    # Comportamento storico: l'unico modello su cui 'diarization_clustering_
    # threshold' è stato tarato (v. piano_fix_pipeline_trascrizione punto A).
    DEFAULT_MODEL = "pyannote/speaker-diarization-3.1"

    def __init__(self, hf_token: str, log_callback: Optional[Callable] = None,
                 clustering_threshold: Optional[float] = None,
                 min_cluster_size: Optional[int] = None,
                 model_id: Optional[str] = None):
        """
        Args:
            clustering_threshold, min_cluster_size: override espliciti dei
                parametri di clustering pyannote (v. piano_fix_pipeline_
                trascrizione punto A). None = leggi da config
                ('diarization_clustering_threshold'/'diarization_min_cluster_
                size', entrambi 0 = default del modello pyannote/speaker-
                diarization-3.1: threshold 0.7046, min_cluster_size 12).
                Servono come parametro esplicito per uno script di A/B che
                vuole forzare un valore senza scrivere nella config globale.
            model_id: override esplicito della pipeline pyannote da caricare
                (stesso motivo dei due sopra: script di A/B). None = leggi
                da config ('diarization_model', default DEFAULT_MODEL).
        """
        self.hf_token = hf_token
        self.log = log_callback or print
        self._pipeline = None
        self._clustering_threshold = clustering_threshold
        self._min_cluster_size = min_cluster_size
        self._model_id = model_id
        self._effective_model = ''
        self._effective_threshold = 0.0
        self._effective_min_cluster_size = 0
        self._effective_min_speakers = 0
        self._effective_max_speakers = 0

    def _apply_clustering_overrides(self) -> None:
        """Applica soglia/min_cluster_size custom alla sub-pipeline di clustering.

        pyannote instantiate() accetta un dict PARZIALE — i parametri non
        citati restano quelli del config.yaml del modello. Soglia PIU' ALTA
        = MENO cluster (fcluster con criterion='distance').

        'pyannote/speaker-diarization-community-1' usa VBxClustering invece
        di AgglomerativeClustering: HA anch'esso un 'threshold' (stesso
        fcluster/criterion='distance', v. sorgente pyannote installato —
        NON è un bersaglio inventato), ma 'min_cluster_size' NON ESISTE.
        instantiate() applica le chiavi del dict UNA A UNA e solleva
        sulla PRIMA sconosciuta: senza l'introspezione sotto, un dict con
        {'threshold':..., 'min_cluster_size':...} lascerebbe la soglia
        GIA' APPLICATA (silenziosamente, non annullata dall'except) prima
        di sollevare su min_cluster_size — il log direbbe "default pyannote"
        mentre una soglia non-default resta viva nella pipeline (bug-check
        Opus, scoperto proprio pensando a community-1: in produzione
        min_cluster_size=0 non lo fa scattare, ma nel banco di taratura
        diar_eval/ che usa mcs>0 avrebbe contaminato in silenzio ogni run).
        """
        from utils.config import get_config
        cfg = get_config()
        thr = self._clustering_threshold
        if thr is None:
            thr = float(cfg.get('diarization_clustering_threshold', 0.0))
        mcs = self._min_cluster_size
        if mcs is None:
            mcs = int(cfg.get('diarization_min_cluster_size', 0))

        self._effective_threshold = float(thr) if thr and thr > 0 else 0.0
        self._effective_min_cluster_size = int(mcs) if mcs and mcs > 0 else 0

        overrides = {}
        if self._effective_threshold > 0:
            overrides['threshold'] = self._effective_threshold
        if self._effective_min_cluster_size > 0:
            overrides['min_cluster_size'] = self._effective_min_cluster_size
        if not overrides:
            return

        # Introspezione PRIMA di inviare: quali chiavi 'clustering' esiste
        # DAVVERO in questa pipeline. Funziona identica su 3.1 e community-1,
        # nessun branch sul nome del modello.
        try:
            supported = set(self._pipeline.parameters(instantiated=True).get('clustering', {}))
        except Exception as e:
            supported = None
            self.log(tr('di_clustering_parameter_introspection_failed_sending').format(e=e))

        if supported is not None:
            dropped = {k: v for k, v in overrides.items() if k not in supported}
            overrides = {k: v for k, v in overrides.items() if k in supported}
            for k, v in dropped.items():
                self.log(tr('di_clustering_parameter_does_not_exist').format(k=k, v=v, model=self._effective_model or '?', available=sorted(supported)))
            if 'threshold' in dropped:
                self._effective_threshold = 0.0
            if 'min_cluster_size' in dropped:
                self._effective_min_cluster_size = 0
            if not overrides:
                return

        # Guardia esplicita: 0.85 è una decisione di prodotto tarata
        # sull'AgglomerativeClustering di 3.1 (v. piano_fix_pipeline_
        # trascrizione punto A — scelta NONOSTANTE McNemar p=1.00). Su VBx
        # la stessa chiave 'threshold' inizializza solo l'AHC preliminare
        # (default del modello 0.6, intervallo previsto dagli autori
        # Uniform(0.5, 0.8) — 0.85 è fuori) e poi VBx ri-stima e pota i
        # cluster: il numero NON porta lo stesso significato, va ritarato.
        if 'threshold' in overrides and self._effective_model != self.DEFAULT_MODEL:
            self.log(tr('di_threshold_was_tuned_on_agglomerative').format(threshold=overrides['threshold'], DEFAULT_MODEL=self.DEFAULT_MODEL, effective_model=self._effective_model))

        # Applicazione UNA CHIAVE ALLA VOLTA (bug-check Opus #2).
        # pyannote.pipeline.Pipeline.instantiate() itera il dict e fa
        # setattr chiave per chiave, sollevando sulla PRIMA sconosciuta:
        # con una sola chiamata le chiavi già viste restano applicate ma
        # l'except azzera TUTTI i campi _effective_*, che quindi mentono
        # (log "default pyannote" con una soglia non-default viva nella
        # pipeline). L'introspezione sopra evita il caso noto, ma non
        # quello in cui l'introspezione stessa fallisce. Una chiamata per
        # chiave rende noto l'esito di ciascuna e rimuove la classe di
        # bug, non una sua istanza: né SpeakerDiarization né
        # BaseClustering sovrascrivono initialize() (no-op, verificato sul
        # sorgente installato) e i due parametri sono plain setattr,
        # quindi N chiamate lasciano esattamente lo stato di una sola.
        applied = {}
        for k, v in overrides.items():
            try:
                self._pipeline.instantiate({'clustering': {k: v}})
                applied[k] = v
            except Exception as e:
                # Ampio deliberatamente (bug-check Opus): un'eccezione
                # diversa da una futura versione di pyannote non deve far
                # fallire load() — l'alternativa sarebbe un intero film
                # senza speaker labels solo per un parametro di A/B non
                # applicato.
                if k == 'threshold':
                    self._effective_threshold = 0.0
                elif k == 'min_cluster_size':
                    self._effective_min_cluster_size = 0
                self.log(tr('di_clustering_override_ignored_pyannote_default').format(k=k, v=v, e=e))
        if applied:
            self.log(tr('di_pyannote_clustering_overridden').format(applied=applied))

    def load(self) -> None:
        import warnings
        # Sopprimi warning noti e non azionabili
        warnings.filterwarnings("ignore", module=r"pyannote\.audio\.core\.io")               # torchcodec
        warnings.filterwarnings("ignore", module=r"torchaudio\._backend\.utils")             # torchaudio 2.9 deprecation
        warnings.filterwarnings("ignore", module=r"pyannote\.audio\.utils\.reproducibility") # TF32
        warnings.filterwarnings("ignore", module=r"pyannote\.audio\.models\.blocks\.pooling") # std() on short audio
        warnings.filterwarnings("ignore", message=r".*speechbrain\.pretrained.*")            # speechbrain 1.0 module redirect

        # Salva stato TF32 prima che pyannote lo disabiliti
        self._tf32_matmul = torch.backends.cuda.matmul.allow_tf32
        self._tf32_cudnn  = torch.backends.cudnn.allow_tf32

        from pyannote.audio import Pipeline
        from utils.config import get_config
        model_id = (self._model_id
                    or (get_config().get('diarization_model') or '').strip()
                    or self.DEFAULT_MODEL)
        self._effective_model = model_id
        self.log(tr('di_loading_pyannote_model').format(model=model_id.split('/')[-1]))
        self._pipeline = Pipeline.from_pretrained(
            model_id,
            token=self.hf_token
        )
        if torch.cuda.is_available():
            self._pipeline = self._pipeline.to(torch.device("cuda"))
            self.log(tr('di_diarizer_loaded_on_cuda'))
        else:
            self.log(tr('di_diarizer_loaded_on_cpu'))

        # instantiate() è economico (initialize() non è overridata: no-op) —
        # sicuro da chiamare subito dopo from_pretrained.
        self._apply_clustering_overrides()

    def diarize(self, audio_path: str, num_speakers: int = 0, *,
                min_speakers: int = 0, max_speakers: int = 0,
                audio_source_label: str = ''
                ) -> List[Tuple[float, float, str]]:
        """Restituisce lista di (start, end, speaker_id).

        Pre-carica l'audio con torchaudio per evitare dipendenza da torchcodec.

        min_speakers/max_speakers (v. piano_fix_pipeline_trascrizione punto
        A): se 0 e num_speakers == 0, letti da config
        ('diarization_min_speakers'/'diarization_max_speakers'). Ignorati
        se num_speakers > 0 (pyannote rifiuta la combinazione).
        """
        import torchaudio
        waveform, sample_rate = torchaudio.load(audio_path)
        audio_input = {'waveform': waveform, 'sample_rate': sample_rate}

        kwargs = {}
        if num_speakers > 0:
            kwargs['num_speakers'] = num_speakers
        else:
            if min_speakers <= 0 or max_speakers <= 0:
                from utils.config import get_config
                cfg = get_config()
                if min_speakers <= 0:
                    min_speakers = int(cfg.get('diarization_min_speakers', 0))
                if max_speakers <= 0:
                    max_speakers = int(cfg.get('diarization_max_speakers', 0))
            if min_speakers > 0:
                kwargs['min_speakers'] = min_speakers
            if max_speakers > 0:
                kwargs['max_speakers'] = max_speakers

        # Valori REALMENTE usati (risolti dalla config se il chiamante ha
        # passato 0): un banco di taratura deve poter registrare cosa è
        # girato davvero, non solo cosa è stato richiesto (bug-check Opus,
        # v. piano_fix_pipeline_trascrizione punto A, diar_eval/).
        self._effective_min_speakers = min_speakers
        self._effective_max_speakers = max_speakers

        # Avanzamento ed ETA: hook di pyannote (segmentazione, impronte vocali, ...) -> barra con ETA nella card del log sintetico.
        # Se la versione di pyannote non accetta `hook` si ricade sulla chiamata di sempre (senza barra).
        bar = _DiarBar(self.log)
        progress = DiarProgress(bar.set)
        try:
            output = self._pipeline(audio_input, hook=progress, **kwargs)
        except TypeError as exc:
            if 'hook' not in str(exc):
                raise
            output = self._pipeline(audio_input, **kwargs)
        progress.finish()
        # pyannote 4.x: DiarizeOutput con .speaker_diarization; 3.x: Annotation diretta
        annotation = getattr(output, 'speaker_diarization', output)
        result = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            result.append((turn.start, turn.end, speaker))
        if not audio_source_label:
            from utils.config import get_config
            audio_source_label = get_config().get('diarization_audio_source', 'vocals')
        self._log_diarization_metrics(result, num_speakers, min_speakers, max_speakers, audio_source_label)
        return result

    def _log_diarization_metrics(
        self, result: List[Tuple[float, float, str]],
        num_speakers: int, min_speakers: int, max_speakers: int,
        audio_source_label: str = ''
    ) -> None:
        """Riga di log strutturata per un A/B misurabile (v. piano_fix_
        pipeline_trascrizione punto A.4) — grep-abile con '[diar-ab]'.

        speech/turn_med/top5/tail_lt2pct sono gli indicatori di sovra-
        clustering: 'speakers' grezzo non basta (un tetto max_speakers può
        essere soddisfatto tenendo i cluster sbagliati).
        """
        if not result:
            self.log(tr('di_diar_ab_no_turn_detected'))
            return

        from collections import defaultdict
        by_speaker: dict = defaultdict(float)
        turn_durations = []
        for start, end, speaker in result:
            dur = end - start
            by_speaker[speaker] += dur
            turn_durations.append(dur)

        speech_total = sum(by_speaker.values())
        turn_durations.sort()
        n = len(turn_durations)
        turn_med = turn_durations[n // 2] if n % 2 else (
            turn_durations[n // 2 - 1] + turn_durations[n // 2]) / 2

        ranked = sorted(by_speaker.values(), reverse=True)
        top5_pct = [round(100 * d / speech_total, 1) for d in ranked[:5]] if speech_total > 0 else []
        tail_lt2pct = sum(1 for d in by_speaker.values()
                           if speech_total > 0 and d / speech_total < 0.02)

        # thr/mcs=0 significa "default del modello pyannote" (0.7046/12),
        # non "soglia zero" — 'default' evita di leggerlo al contrario in
        # un confronto A/B (bug-check Opus).
        thr_label = f"{self._effective_threshold:.4f}" if self._effective_threshold > 0 else "default"
        mcs_label = str(self._effective_min_cluster_size) if self._effective_min_cluster_size > 0 else "default"
        self.log(
            f"  🎭 [diar-ab] model={self._effective_model.split('/')[-1] or '?'} "
            f"source={audio_source_label or 'vocals'} "
            f"thr={thr_label} mcs={mcs_label} "
            f"nspk={num_speakers}/min={min_speakers}/max={max_speakers} | "
            f"speakers={len(by_speaker)} turns={len(result)}")
        self.log(
            f"      speech={speech_total:.1f}s turn_med={turn_med:.1f}s "
            f"top5={top5_pct}% tail_lt2pct={tail_lt2pct}")

    # ── Assegnazione speaker ──────────────────────────────────────────────────

    def assign_speakers(
        self,
        segments: List[Dict],
        diarization: List[Tuple[float, float, str]],
        *,
        word_vote: Optional[bool] = None,
        tolerance_ms: Optional[int] = None,
        v2_params: Optional[Dict] = None,
    ) -> List[Dict]:
        """Assegna il campo 'speaker' a ogni segmento Whisper.

        Se il segmento ha word timestamps (BatchedInferencePipeline), usa
        l'allineamento word-level: divide il segmento ai confini di cambio
        parlante, creando sotto-segmenti separati per ogni speaker.

        Altrimenti fallback a overlap massimo sull'intero segmento.

        'diarization_word_vote_enabled' (v. piano_fix_pipeline_trascrizione
        punto C, default False): sostituisce il lookup a midpoint con un
        voto pesato sull'overlap + una politica esplicita sulle run corte
        (invece della fusione automatica nella run precedente). False =
        comportamento storico byte per byte.

        word_vote/tolerance_ms/v2_params: override espliciti per la
        taratura (v. diar_eval/) — None (default) legge dalla config
        globale, esattamente come prima. Non chiamare mai in produzione
        con questi argomenti diversi da None: servono solo a chi vuole
        confrontare v1/v2 senza toccare la config (il banco di taratura
        NON deve mai scrivere config, v. piano_fix_pipeline_trascrizione).
        """
        from utils.config import get_config
        cfg = get_config()
        _word_vote_overridden = word_vote is not None
        if word_vote is None:
            word_vote = bool(cfg.get('diarization_word_vote_enabled', False))
        if tolerance_ms is None:
            tolerance_ms = int(cfg.get('diarization_word_tolerance_ms', 100))

        turns_sorted: Optional[List[Tuple[float, float, str]]] = None
        starts: Optional[List[float]] = None
        if word_vote:
            # Costruiti UNA sola volta per l'intero film: senza indice il
            # voto sarebbe O(parole × turni) senza early-return, troppo
            # lento su un film intero (v. piano_fix_pipeline_trascrizione
            # punto C.1).
            turns_sorted = sorted(diarization, key=lambda t: t[0])
            starts = [t[0] for t in turns_sorted]

        # Osservabilità (bug-check Opus): v1 e v2 calcolano
        # 'speaker_confidence' con definizioni diverse, ma il consumatore
        # (SubtitleFormatter, gate del trattino) logga un numero identico
        # in entrambi i casi — senza questa riga non è possibile capire da
        # un log quale algoritmo ha prodotto un dato SRT. "override" segna
        # una chiamata di taratura (diar_eval), "da config" un run reale.
        provenance = "override" if _word_vote_overridden else tr('di_provenance_from_config')
        self.log(tr('di_speaker_assignment_word_vote').format(
                 v='ON (tol=' + str(tolerance_ms) + 'ms, ' + provenance + ')' if word_vote
                 else tr('di_word_vote_off').format(provenance=provenance)))

        v2_kwargs = dict(v2_params or {})
        result = []
        for seg in segments:
            words = seg.get('words', [])
            if not words:
                self._assign_segment_speaker(seg, diarization)
                result.append(seg)
            elif word_vote:
                sub_segs = self._split_at_speaker_changes_v2(
                    seg, words, turns_sorted, starts,
                    tolerance_ms=tolerance_ms, **v2_kwargs)
                result.extend(sub_segs)
            else:
                sub_segs = self._split_at_speaker_changes(seg, words, diarization)
                result.extend(sub_segs)
        self.log(tr('di_segments_after_word_level_alignment').format(n=len(result)))
        return result

    def _assign_segment_speaker(
        self, seg: Dict, diarization: List[Tuple[float, float, str]]
    ) -> None:
        """Assegna speaker per overlap massimo (in-place). Fallback senza words.

        Calcola anche 'speaker_confidence' = frazione della durata del
        segmento coperta dal parlante vincente. Un segmento che ingloba
        per errore parole di due parlanti diversi (crosstalk) avrà
        confidenza bassa — usata a valle da SubtitleFormatter per decidere
        se fidarsi dell'etichetta ai fini del trattino stile dialogo.
        """
        seg_start, seg_end = seg['start'], seg['end']
        seg_duration = seg_end - seg_start
        overlap_by_speaker: Dict[str, float] = {}
        for d_start, d_end, speaker in diarization:
            overlap = min(seg_end, d_end) - max(seg_start, d_start)
            if overlap > 0:
                overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0) + overlap
        if overlap_by_speaker:
            winner = max(overlap_by_speaker, key=overlap_by_speaker.get)
            seg['speaker'] = winner
            seg['speaker_confidence'] = (
                overlap_by_speaker[winner] / seg_duration if seg_duration > 0 else 0.0
            )

    def _get_speaker_at(
        self, timestamp: float, diarization: List[Tuple[float, float, str]]
    ) -> Optional[str]:
        """Trova il parlante attivo a un dato timestamp. None = silenzio/pausa."""
        for d_start, d_end, speaker in diarization:
            if d_start <= timestamp <= d_end:
                return speaker
        return None

    def _split_at_speaker_changes(
        self,
        seg: Dict,
        words: List[Dict],
        diarization: List[Tuple[float, float, str]],
        min_words_per_turn: int = 3,
    ) -> List[Dict]:
        """Divide un segmento in sotto-segmenti ai confini di cambio parlante.

        Algoritmo run-based con soglia minima:
        1. Assegna speaker a ogni parola (midpoint)
        2. Riempi silenzi (None) con speaker precedente/successivo
        3. Identifica run consecutive di stesso speaker
        4. Fonde run troppo corte (< min_words_per_turn) nella run precedente
           → previene falsi split su singole parole tipo "Va", "Sì", "No"
        5. Crea sotto-segmenti solo per le run rimanenti
        """
        if not words:
            return [seg]

        # Passo 1: speaker per ogni parola
        word_speakers: List[Optional[str]] = []
        for word in words:
            w_mid = (word['start'] + word['end']) / 2
            word_speakers.append(self._get_speaker_at(w_mid, diarization))

        # Copia pre-fill: usata per la confidenza (passo 6) — distingue le
        # parole con un turno pyannote osservato direttamente da quelle che
        # erediteranno lo speaker di un vicino solo per riempire un silenzio.
        word_speakers_observed = list(word_speakers)

        # Passo 2a: fill in avanti (silenzi ereditano speaker precedente)
        current: Optional[str] = None
        for i, sp in enumerate(word_speakers):
            if sp is not None:
                current = sp
            elif current is not None:
                word_speakers[i] = current

        # Passo 2b: fill indietro per silenzi iniziali
        last: Optional[str] = None
        for i in range(len(word_speakers) - 1, -1, -1):
            if word_speakers[i] is not None:
                last = word_speakers[i]
            elif last is not None:
                word_speakers[i] = last

        # Passo 3: identifica run (sequenze di parole stesso speaker)
        runs: List[Tuple[int, int, Optional[str]]] = []  # (start_idx, end_idx, speaker)
        run_start = 0
        run_spk = word_speakers[0]
        for i in range(1, len(word_speakers)):
            if word_speakers[i] != run_spk:
                runs.append((run_start, i - 1, run_spk))
                run_start = i
                run_spk = word_speakers[i]
        runs.append((run_start, len(word_speakers) - 1, run_spk))

        # Passo 4: fonde run troppo corte nella precedente
        merged_runs: List[Tuple[int, int, Optional[str]]] = []
        for start_i, end_i, spk in runs:
            length = end_i - start_i + 1
            if length < min_words_per_turn and merged_runs:
                prev_s, _, prev_spk = merged_runs[-1]
                merged_runs[-1] = (prev_s, end_i, prev_spk)
            else:
                merged_runs.append((start_i, end_i, spk))

        def _run_confidence(start_i: int, end_i: int, spk: Optional[str]) -> float:
            """Frazione di parole del run il cui speaker è stato osservato
            direttamente da pyannote (non ereditato per riempimento silenzi
            né dalla fusione di run corte nel passo 4)."""
            length = end_i - start_i + 1
            if length <= 0 or not spk:
                return 0.0
            observed = sum(
                1 for i in range(start_i, end_i + 1)
                if word_speakers_observed[i] == spk
            )
            return observed / length

        # Solo un run → assegna speaker al segmento intero senza splitting
        if len(merged_runs) <= 1:
            result = dict(seg)
            spk = merged_runs[0][2] if merged_runs else None
            if spk:
                result['speaker'] = spk
                start_i, end_i, _ = merged_runs[0]
                result['speaker_confidence'] = _run_confidence(start_i, end_i, spk)
            return [result]

        # Passo 5: costruisce sotto-segmenti per ogni run
        #
        # Join robusto multi-engine: whisper incorpora lo spazio ad inizio
        # parola (" trasferita"), Qwen3/Canary restituiscono parole nude
        # ("trasferita", spazio implicito nel join di _words_to_segments).
        # strip() per-parola + join con spazio esplicito normalizza
        # entrambe le convenzioni — un '' .join() ingenuo (come prima)
        # produceva testo con parole incollate su segmenti Qwen3/Canary.
        #
        # Passo 6: 'speaker_confidence' per run (v. _run_confidence) — usata
        # da SubtitleFormatter per decidere se fidarsi dell'attribuzione ai
        # fini del trattino stile dialogo. Run corte fuse nel passo 4
        # (interiezioni come "Sì.", "No.") ereditano lo speaker della run
        # precedente MA la loro confidenza riflette la copertura reale sulle
        # parole della run fusa, non quella della run originaria.
        sub_segs = []
        for start_i, end_i, spk in merged_runs:
            run_words = words[start_i:end_i + 1]
            text = ' '.join(w['word'].strip() for w in run_words if w['word'].strip())
            sub_segs.append({
                'start':              run_words[0]['start'],
                'end':                run_words[-1]['end'],
                'text':               text,
                'speaker':            spk,
                'speaker_confidence': _run_confidence(start_i, end_i, spk),
            })

        return sub_segs

    # ── Voto pesato sull'overlap (v. piano_fix_pipeline_trascrizione punto C) ──

    def _speaker_overlaps(
        self, w_start: float, w_end: float,
        turns_sorted: List[Tuple[float, float, str]], starts: List[float],
        tolerance: float,
    ) -> Dict[str, float]:
        """Overlap totale (secondi) fra [w_start-tol, w_end+tol] e ogni
        turno pyannote che lo tocca, anche parzialmente.

        Indicizzato con bisect su 'starts' (turns_sorted ordinati per
        start): scandisce all'indietro dal punto di inserimento fermandosi
        dopo 32 turni consecutivi che finiscono prima della finestra — i
        turni pyannote possono sovrapporsi (crosstalk) ma non sono
        annidati in profondità, quindi un early-stop locale è sicuro senza
        dover visitare l'intera lista.
        """
        lo, hi = w_start - tolerance, w_end + tolerance
        idx = bisect.bisect_right(starts, hi)
        overlaps: Dict[str, float] = {}
        i = idx - 1
        misses = 0
        while i >= 0 and misses <= 32:
            t_start, t_end, speaker = turns_sorted[i]
            if t_end < lo:
                misses += 1
            else:
                misses = 0
                ov = min(hi, t_end) - max(lo, t_start)
                if ov > 0:
                    overlaps[speaker] = overlaps.get(speaker, 0.0) + ov
            i -= 1
        return overlaps

    @staticmethod
    def _vote_from_overlaps(overlaps: Dict[str, float], width: float) -> Optional['SpeakerVote']:
        if not overlaps:
            return None
        ranked = sorted(overlaps.items(), key=lambda kv: kv[1], reverse=True)
        winner, win_ov = ranked[0]
        runner_up, ru_ov = ranked[1] if len(ranked) > 1 else (None, 0.0)
        margin = (win_ov - ru_ov) / max(width, 1e-6)
        return SpeakerVote(winner, win_ov, runner_up, ru_ov, margin)

    def _speaker_vote(
        self, w_start: float, w_end: float,
        turns_sorted: List[Tuple[float, float, str]], starts: List[float],
        tolerance: float = 0.10,
    ) -> Optional['SpeakerVote']:
        """Assegna lo speaker per voto pesato sull'overlap.

        Somma la durata di sovrapposizione fra la parola (allargata di
        `tolerance` su entrambi i lati) e ogni turno diarizzato che la
        tocca; vince lo speaker con overlap totale maggiore. I turni
        pyannote possono sovrapporsi in crosstalk: il lookup istantaneo sul
        midpoint (_get_speaker_at) restituiva il PRIMO turno in lista,
        scelta arbitraria in quei casi.

        None se nessun turno tocca la parola (silenzio/pausa), come
        _get_speaker_at.
        """
        overlaps = self._speaker_overlaps(w_start, w_end, turns_sorted, starts, tolerance)
        width = (w_end - w_start) + 2 * tolerance
        return self._vote_from_overlaps(overlaps, width)

    @staticmethod
    def _margin_vs_speaker(overlaps: Dict[str, float], speaker: Optional[str], width: float) -> float:
        """Margine della parola rispetto a UNO speaker specifico (non
        necessariamente il vincitore del voto originale) — serve a
        ricalcolare la confidenza quando la parola finisce in una run
        ospite diversa da quella per cui aveva votato (v. C.3)."""
        if not overlaps or not speaker:
            return 0.0
        host_ov = overlaps.get(speaker, 0.0)
        best_other = max((v for k, v in overlaps.items() if k != speaker), default=0.0)
        return max(0.0, (host_ov - best_other) / max(width, 1e-6))

    def _mean_margin_vs(
        self, word_overlaps: List[Dict[str, float]], words: List[Dict],
        s_i: int, e_i: int, speaker: Optional[str], tolerance: float,
    ) -> float:
        """confidence(run) = media di margin(w) rispetto a `speaker` sulle
        parole [s_i, e_i] — margin=0 per le parole senza voto (silenzio
        riempito), come da definizione C.3."""
        n = e_i - s_i + 1
        if n <= 0:
            return 0.0
        total = 0.0
        for i in range(s_i, e_i + 1):
            width = (words[i]['end'] - words[i]['start']) + 2 * tolerance
            total += self._margin_vs_speaker(word_overlaps[i], speaker, width)
        return total / n

    def _nearest_boundary_distance(
        self, time_point: float, speaker: Optional[str],
        turns_sorted: List[Tuple[float, float, str]], starts: List[float],
        window: int = 64,
    ) -> float:
        """Distanza minima fra time_point e il confine (start o end) del
        turno pyannote più vicino appartenente a `speaker`, cercando in una
        finestra di indici attorno al punto di inserimento (i turni sono
        ordinati per start: un turno vicino nel tempo è vicino anche in
        indice, salvo sovrapposizioni estreme che qui non servono coprire).
        inf se nessun turno di quello speaker cade nella finestra."""
        if not speaker:
            return float('inf')
        idx = bisect.bisect_left(starts, time_point)
        lo = max(0, idx - window)
        hi = min(len(turns_sorted), idx + window)
        best = float('inf')
        for t_start, t_end, spk in turns_sorted[lo:hi]:
            if spk != speaker:
                continue
            best = min(best, abs(time_point - t_start), abs(time_point - t_end))
        return best

    @staticmethod
    def _overlap_sum_for(word_overlaps: List[Dict[str, float]], s_i: int, e_i: int,
                          speaker: Optional[str]) -> float:
        if not speaker:
            return 0.0
        return sum(ov.get(speaker, 0.0) for ov in word_overlaps[s_i:e_i + 1])

    def _resolve_short_runs(
        self,
        runs: List[List],  # [start_i, end_i, speaker] mutabili
        words: List[Dict],
        word_overlaps: List[Dict[str, float]],
        turns_sorted: List[Tuple[float, float, str]],
        starts: List[float],
        tolerance: float,
        min_words_per_turn: int,
        short_run_margin_keep: float,
        short_run_gap_keep: float,
        short_run_boundary_far: float,
    ) -> List[List]:
        """Decide, per ogni run più corta di min_words_per_turn, se è
        un'interiezione autentica da tenere come turno a sé o un artefatto
        di diarization da fondere — e in quel caso in quale run vicina
        (precedente O successiva, non sempre la precedente come nella v1).

        Criterio (v. piano_fix_pipeline_trascrizione punto C.2):
          TIENI se mean_margin ≥ short_run_margin_keep E (gap_before ≥
          short_run_gap_keep O la run precedente termina con punteggiatura
          forte). Altrimenti FONDI nel vicino con il confine di turno
          pyannote più vicino (se ≤ short_run_boundary_far); se nessun
          confine è vicino, nel vicino il cui speaker accumula più overlap
          sull'intervallo della run corta; a parità, nella precedente
          (comportamento storico sui casi indecidibili).

        Iterativo fino a stabilità: i run per segmento sono pochissimi
        (segmenti già cappati a ~6s/80 char a monte), quindi un fixed-point
        con guardia è più semplice e sicuro di calcolare tutte le fusioni
        in un unico passaggio sulla struttura originale.
        """
        runs = [list(r) for r in runs]
        # Ogni passata risolve AL MASSIMO una fusione (break dopo la prima
        # trovata) — il numero massimo di fusioni possibili è len(runs)-1,
        # non un numero fisso di passate: un tetto fisso a 20 (bug-check
        # Opus) su un'alternanza fitta A/B con oltre 20 run da 1 parola
        # lasciava run corte non risolte in silenzio.
        guard = 0
        guard_max = len(runs) + 5
        changed = True
        while changed and guard < guard_max and len(runs) > 1:
            changed = False
            guard += 1
            for j, (s_i, e_i, spk) in enumerate(runs):
                length = e_i - s_i + 1
                if length >= min_words_per_turn:
                    continue

                mean_margin = self._mean_margin_vs(word_overlaps, words, s_i, e_i, spk, tolerance)
                gap_before = (words[s_i]['start'] - words[s_i - 1]['end']) if s_i > 0 else float('inf')
                prev_text = words[s_i - 1]['word'].strip() if s_i > 0 else ''
                prev_concluded = bool(prev_text) and prev_text[-1] in '.!?…'

                if mean_margin >= short_run_margin_keep and (
                        gap_before >= short_run_gap_keep or prev_concluded):
                    continue  # TIENI: run corta ma autentica, non si fonde

                has_prev = j > 0
                has_next = j < len(runs) - 1
                d_prev = (self._nearest_boundary_distance(words[s_i]['start'], runs[j - 1][2],
                                                            turns_sorted, starts)
                          if has_prev else float('inf'))
                d_next = (self._nearest_boundary_distance(words[e_i]['end'], runs[j + 1][2],
                                                            turns_sorted, starts)
                          if has_next else float('inf'))

                target = None
                if has_prev and d_prev <= short_run_boundary_far and d_prev <= d_next:
                    target = 'prev'
                elif has_next and d_next <= short_run_boundary_far:
                    target = 'next'
                elif has_prev or has_next:
                    # Nessun confine di turno vicino: nessuna run vicina ha
                    # evidenza posizionale — decide chi "sente" davvero
                    # queste parole (overlap accumulato), non la posizione.
                    ov_prev = self._overlap_sum_for(word_overlaps, s_i, e_i, runs[j - 1][2]) if has_prev else -1.0
                    ov_next = self._overlap_sum_for(word_overlaps, s_i, e_i, runs[j + 1][2]) if has_next else -1.0
                    target = 'prev' if (has_prev and ov_prev >= ov_next) else 'next'

                if target == 'prev':
                    runs[j - 1][1] = e_i
                    del runs[j]
                    changed = True
                    break
                elif target == 'next':
                    runs[j + 1][0] = s_i
                    del runs[j]
                    changed = True
                    break

        if changed and guard >= guard_max:
            still_short = sum(1 for s_i, e_i, _ in runs if e_i - s_i + 1 < min_words_per_turn)
            if still_short:
                self.log(tr('di_resolve_short_runs_guard_exhausted').format(still_short=still_short))

        # Coalescenza: fondere una run corta nella successiva può lasciare
        # due run adiacenti dello stesso speaker separate (v. C.2 passo 3).
        coalesced: List[List] = []
        for r in runs:
            if coalesced and coalesced[-1][2] == r[2]:
                coalesced[-1][1] = r[1]
            else:
                coalesced.append(list(r))
        return coalesced

    def _split_at_speaker_changes_v2(
        self,
        seg: Dict,
        words: List[Dict],
        turns_sorted: List[Tuple[float, float, str]],
        starts: List[float],
        min_words_per_turn: int = 3,
        tolerance_ms: Optional[int] = None,
        short_run_margin_keep: float = 0.60,
        short_run_gap_keep: float = 0.25,
        short_run_boundary_far: float = 0.50,
    ) -> List[Dict]:
        """Come _split_at_speaker_changes, ma con voto pesato sull'overlap
        (invece del lookup a midpoint) e una politica esplicita sulle run
        corte (invece della fusione automatica nella run precedente).
        Attiva solo con 'diarization_word_vote_enabled' (v. assign_speakers).

        Le soglie di default sono parametri della funzione, non costanti di
        modulo: la funzione resta chiamabile con valori diversi da un test
        (v. piano_fix_pipeline_trascrizione punto C.2 per il ragionamento
        dietro ciascun default).
        """
        if not words:
            return [seg]

        if tolerance_ms is None:
            from utils.config import get_config
            tolerance_ms = int(get_config().get('diarization_word_tolerance_ms', 100))
        tolerance = tolerance_ms / 1000.0

        # Passo 1: voto pesato per parola. word_overlaps è la cache grezza
        # (per-speaker) usata sia per il voto iniziale sia, più avanti, per
        # ricalcolare la confidenza rispetto allo speaker OSPITE di una run
        # in cui la parola finisce dopo una fusione (C.3).
        word_overlaps: List[Dict[str, float]] = []
        word_speakers_observed: List[Optional[str]] = []
        for w in words:
            overlaps = self._speaker_overlaps(w['start'], w['end'], turns_sorted, starts, tolerance)
            word_overlaps.append(overlaps)
            width = (w['end'] - w['start']) + 2 * tolerance
            vote = self._vote_from_overlaps(overlaps, width)
            word_speakers_observed.append(vote.speaker if vote else None)

        # Passo 2a/2b: riempimento silenzi, identico alla v1.
        word_speakers = list(word_speakers_observed)
        current: Optional[str] = None
        for i, sp in enumerate(word_speakers):
            if sp is not None:
                current = sp
            elif current is not None:
                word_speakers[i] = current
        last: Optional[str] = None
        for i in range(len(word_speakers) - 1, -1, -1):
            if word_speakers[i] is not None:
                last = word_speakers[i]
            elif last is not None:
                word_speakers[i] = last

        # Passo 3: run consecutive.
        runs: List[List] = []
        run_start = 0
        run_spk = word_speakers[0]
        for i in range(1, len(word_speakers)):
            if word_speakers[i] != run_spk:
                runs.append([run_start, i - 1, run_spk])
                run_start = i
                run_spk = word_speakers[i]
        runs.append([run_start, len(word_speakers) - 1, run_spk])

        if len(runs) > 1:
            runs = self._resolve_short_runs(
                runs, words, word_overlaps, turns_sorted, starts, tolerance,
                min_words_per_turn, short_run_margin_keep,
                short_run_gap_keep, short_run_boundary_far)

        if len(runs) <= 1:
            result = dict(seg)
            spk = runs[0][2] if runs else None
            if spk:
                result['speaker'] = spk
                s_i, e_i, _ = runs[0]
                result['speaker_confidence'] = self._mean_margin_vs(
                    word_overlaps, words, s_i, e_i, spk, tolerance)
            return [result]

        sub_segs = []
        for s_i, e_i, spk in runs:
            run_words = words[s_i:e_i + 1]
            text = ' '.join(w['word'].strip() for w in run_words if w['word'].strip())
            sub_segs.append({
                'start':              run_words[0]['start'],
                'end':                run_words[-1]['end'],
                'text':               text,
                'speaker':            spk,
                'speaker_confidence': self._mean_margin_vs(
                    word_overlaps, words, s_i, e_i, spk, tolerance),
            })
        return sub_segs

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def unload(self) -> None:
        del self._pipeline
        self._pipeline = None
        # Ripristina stato TF32 precedente
        torch.backends.cuda.matmul.allow_tf32 = getattr(self, '_tf32_matmul', True)
        torch.backends.cudnn.allow_tf32        = getattr(self, '_tf32_cudnn',  True)
        import gc; gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
