# -*- coding: utf-8 -*-
"""
Anteprima dei passi del file in lavorazione ("Pipeline in corso" con Log Sintetico).

Classe pura, senza Qt: `StepTracker` costruisce il PIANO dei passi di un file all'avvio (dalle opzioni job e dalla
configurazione) e lo corregge man mano che la pipeline dichiara cosa sta facendo con gli eventi strutturati
(utils/events.py). Produce `PipelineSnapshot` immutabili (sicuri tra thread) che la vista disegna.

Regole:
  - `FileProgress` (gui/file_progress.py) resta la sola fonte della percentuale TOTALE del file: qui non si tocca.
  - Il tracker lavora SOLO sugli eventi (la worker li abilita sempre con TP_EVENTS=1): nessun parsing del testo.
  - Un passo escluso e' "disattivato" (interruttore spento nelle opzioni) oppure "non necessario" (lo decide il
    file: sottotitoli embedded, lingua gia' finale, IMDb mancante...). Il contatore n/m conta fatti / non esclusi
    e `m` puo' calare durante l'elaborazione.
  - Percentuale ed ETA solo dove esiste una misura reale (eventi `bar`: Demucs, trascrizione, traduzione, genere,
    lettura OCR). Salvataggio e upload hanno una barra STIMATA (animazione: `est_tau`), gli altri passi sono
    indeterminati.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from utils.eta import EtaEstimator

# Stati di un passo
PENDING, ACTIVE, DONE = 'pending', 'active', 'done'
DISABLED, NOT_NEEDED = 'disabled', 'not_needed'
FAILED, STOPPED = 'failed', 'stopped'
EXCLUDED = (DISABLED, NOT_NEEDED)

# Passi del percorso audio/testo e del percorso OCR (ordine di esecuzione)
AUDIO_STEPS = ('extract', 'demucs', 'asr', 'diarize', 'translate', 'gender', 'save', 'upload', 'mux')
OCR_STEPS = ('ocr_extract', 'ocr_read', 'ocr_translate', 'save', 'upload', 'mux')

# Chiave di traduzione (utils/translations.py) dell'etichetta di ogni passo
LABEL_KEYS = {
    'extract': 'step_extract', 'demucs': 'step_demucs', 'asr': 'step_asr', 'diarize': 'step_diarize', 'translate': 'step_translate',
    'gender': 'step_gender', 'save': 'step_save', 'upload': 'step_upload', 'mux': 'step_mux',
    'ocr_extract': 'step_ocr_extract', 'ocr_read': 'step_ocr_read', 'ocr_translate': 'step_translate',
}

# Barra stimata (secondi di costante di tempo): passi brevi di cui non esiste una misura reale
EST_TAU = {'save': 1.5, 'upload': 8.0}

# Passi che dopo il 100% del motore hanno ancora lavoro (trascrizione: allineamento, diarizzazione, punteggiatura;
# traduzione: recupero dei blocchi da rifare): la card li tiene a 99% finche' non inizia il passo successivo.
HOLD_AT_99 = ('asr', 'diarize', 'translate', 'ocr_translate')

# Evento `bar` (gruppo) -> passo che lo riceve (nel percorso OCR la traduzione e' `ocr_translate`)
_BAR_TO_STEP = {'demucs': 'demucs', 'asr': 'asr', 'diarize': 'diarize', 'translate': 'translate', 'gender': 'gender', 'ocr': 'ocr_read'}

_LANG3_TO_2 = {'ita': 'it', 'eng': 'en', 'fra': 'fr', 'fre': 'fr', 'deu': 'de', 'ger': 'de', 'spa': 'es',
               'por': 'pt', 'rus': 'ru', 'jpn': 'ja', 'zho': 'zh', 'chi': 'zh', 'kor': 'ko', 'ara': 'ar',
               'nld': 'nl', 'dut': 'nl', 'pol': 'pl', 'tur': 'tr'}


def _fmt_eta(rem) -> str:
    """'~40s' / '~12m' (stringa vuota se non stimabile): stesso formato delle barre dei motori."""
    if rem is None:
        return ''
    return f"~{max(1, int(rem))}s" if rem < 60 else f"~{int(rem / 60 + 0.5)}m"


def _lang2(code: str) -> str:
    c = (code or '').strip().lower()
    return _LANG3_TO_2.get(c, c if len(c) == 2 else '')


@dataclass(frozen=True)
class PlanOptions:
    """Cio' che decide il piano senza guardare il file (letto dalla configurazione all'avvio del file)."""
    target_language: str = 'ita'
    gender: bool = False             # correzione di genere avanzata
    diarize: bool = True             # riconoscimento dei parlanti (acceso E token Hugging Face presente)
    upload: bool = False             # upload OpenSubtitles acceso E credenziali configurate
    mux: bool = False                # "Muxa nel video"

    @classmethod
    def from_config(cls, config, target_language: str = 'ita', overrides=None) -> 'PlanOptions':
        ov = overrides or {}

        def _get(key, default=False):
            if key in ov:
                return bool(ov[key])            # eccezione per file (utils/job_overrides.py)
            try:
                return bool(config.get(key, default))
            except Exception:
                return default
        upload = _get('opensubtitles_upload_enabled', True)
        if upload:
            try:
                upload = bool(config.is_opensubtitles_configured())
            except Exception:
                upload = False
        diarize = _get('enable_diarization', False) or _get('dialogue_style_enabled', True)
        if diarize:
            try:
                diarize = bool(config.is_huggingface_token_set())
            except Exception:
                diarize = False
        return cls(target_language=target_language, gender=_get('gender_correction_enabled', False),
                   upload=upload, mux=_get('mux_subtitle_into_video', False), diarize=diarize)


@dataclass(frozen=True)
class StepState:
    key: str
    label_key: str
    status: str
    order: Optional[int] = None        # numero d'ordine tra i passi non esclusi (1-based), None se escluso
    pct: Optional[int] = None          # percentuale reale (0..100) se misurata
    eta: str = ''                      # '~2m' / '~40s', vuota se non stimabile
    est_tau: Optional[float] = None    # barra stimata: costante di tempo in secondi (vedi `est_pct`)
    started_at: Optional[float] = None  # time.time() dell'ingresso nel passo (per la barra stimata)


def est_pct(step: StepState, now: Optional[float] = None) -> int:
    """Percentuale STIMATA (mai oltre 95) di un passo breve senza misura reale: 95 * (1 - e^(-t/tau))."""
    import math
    if step.est_tau is None or step.started_at is None:
        return 0
    t = max(0.0, (now if now is not None else time.time()) - step.started_at)
    return min(95, int(95 * (1.0 - math.exp(-t / step.est_tau))))


@dataclass(frozen=True)
class PipelineSnapshot:
    file_path: str
    file_name: str
    steps: Tuple[StepState, ...]
    done: int                          # passi fatti
    total: int                         # passi non esclusi (puo' calare durante l'elaborazione)
    finished: bool = False

    @property
    def active(self) -> Optional[StepState]:
        return next((s for s in self.steps if s.status == ACTIVE), None)


class StepTracker:
    def __init__(self, file_path: str, options: Optional[PlanOptions] = None,
                 clock: Callable[[], float] = time.time):
        self.file_path = str(file_path)
        self.file_name = self.file_path.replace('\\', '/').rsplit('/', 1)[-1]
        self.opt = options or PlanOptions()
        self._clock = clock
        self._target = _lang2(self.opt.target_language)
        self._route = 'audio'
        self._status: Dict[str, str] = {}
        self._pct: Dict[str, int] = {}
        self._eta: Dict[str, str] = {}
        self._started: Dict[str, float] = {}
        self._est: Dict[str, EtaEstimator] = {}
        self._finished = False
        self._plan_audio()

    # ------------------------------------------------------------------ piano
    def _plan_audio(self) -> None:
        self._route = 'audio'
        keep = {k: self._status[k] for k in ('save', 'upload', 'mux') if k in self._status}
        self._status = {k: PENDING for k in AUDIO_STEPS}
        self._pct.clear(); self._eta.clear(); self._est.clear()
        self._started = {k: v for k, v in self._started.items() if k in keep}
        self._apply_static()
        for k, v in keep.items():
            if self._status.get(k) != DISABLED:
                self._status[k] = v

    def _plan_ocr(self, translate: bool) -> None:
        self._route = 'ocr'
        keep = {k: self._status[k] for k in ('save', 'upload', 'mux') if k in self._status}
        steps = tuple(k for k in OCR_STEPS if translate or k != 'ocr_translate')
        self._status = {k: PENDING for k in steps}
        self._pct.clear(); self._eta.clear(); self._est.clear()
        self._apply_static()
        for k, v in keep.items():
            if k in self._status and self._status[k] != DISABLED:
                self._status[k] = v

    def _apply_static(self) -> None:
        """Passi esclusi dalle opzioni job (interruttori): 'disattivato'. Il mux compare solo se acceso."""
        if 'gender' in self._status and not self.opt.gender:
            self._status['gender'] = DISABLED
        if 'diarize' in self._status and not self.opt.diarize:
            self._status['diarize'] = DISABLED
        if 'upload' in self._status and not self.opt.upload:
            self._status['upload'] = DISABLED
        if not self.opt.mux:
            self._status.pop('mux', None)

    # ------------------------------------------------------------------ eventi
    def feed_event(self, kind: str, fields: Optional[dict] = None) -> bool:
        """Elabora un evento. Ritorna True se lo stato VISIBILE (stato, %, ETA, ordine, totale) e' cambiato."""
        before = self._signature()
        try:
            self._event(kind, fields or {})
        except Exception:
            return False
        return self._signature() != before

    def _signature(self):
        return (tuple(self._status.items()), tuple(self._pct.items()), tuple(self._eta.items()))

    def _event(self, kind: str, f: dict) -> None:
        if kind == 'phase':
            name = str(f.get('name') or '')
            if name in ('extract', 'demucs', 'asr', 'diarize', 'translate', 'gender'):
                if self._route == 'ocr':
                    self._plan_audio()               # un marcatore del percorso audio: l'OCR non e' andato a buon fine
                self._enter(name)
            elif name == 'clean':
                self._enter_after('asr')
                self._enter_after('diarize')
                self._not_needed('diarize')           # la pulizia segue la diarizzazione: se non e' mai partita, non serve
            elif name in ('ocr_extract', 'ocr_read', 'ocr_translate'):
                if self._route != 'ocr':
                    self._plan_ocr(translate=name == 'ocr_translate')
                elif name not in self._status:       # traduzione OCR non prevista ma avvenuta
                    self._insert_ocr_translate()
                if self._status.get(name) == ACTIVE:  # nuova passata sullo stesso passo: avanzamento da zero
                    self._pct.pop(name, None); self._eta.pop(name, None); self._est.pop(name, None)
                self._enter(name)
            elif name == 'final':
                self._enter_before('save')
        elif kind == 'route':
            if f.get('path') == 'ocr':
                self._plan_ocr(translate=bool(f.get('translate')))
                self._enter('ocr_extract')
        elif kind == 'ocr_leave':
            if self._route == 'ocr':
                self._plan_audio()
        elif kind == 'audio_lang':
            if self._same_as_target(str(f.get('lang') or '')):
                self._not_needed('translate', 'gender')
        elif kind == 'embedded':
            if self._route == 'ocr':
                self._plan_audio()
            self._not_needed('extract', 'demucs', 'asr', 'diarize')
            if self._same_as_target(str(f.get('lang') or '')):
                self._not_needed('translate', 'gender')
        elif kind == 'skip':
            self._not_needed(*[p for p in (f.get('phases') or []) if isinstance(p, str)])
        elif kind == 'bar':
            self._bar(str(f.get('phase') or ''), f.get('pct'), f.get('eta_s'))
        elif kind == 'step':
            self._step(str(f.get('name') or ''), str(f.get('state') or ''), str(f.get('reason') or ''),
                       bool(f.get('ok', True)))

    # ------------------------------------------------------------------ transizioni
    def _order(self) -> List[str]:
        return list(self._status.keys())

    def _enter(self, key: str) -> None:
        """Il passo `key` diventa attivo; quelli che lo precedono risultano fatti (se attivi) o non necessari."""
        if key not in self._status:
            return
        if self._status[key] == DISABLED:
            return                                   # interruttore spento: un evento tardivo non lo riaccende
        self._resolve_before(key)
        if self._status[key] in (PENDING, NOT_NEEDED):
            # NOT_NEEDED: la lingua rilevata puo' smentire il tag dell'audio (la traduzione parte comunque)
            self._status[key] = ACTIVE
            self._started[key] = self._clock()

    def _resolve_before(self, key: str) -> None:
        order = self._order()
        for p in order[:order.index(key)]:
            st = self._status[p]
            if st == ACTIVE:
                self._status[p] = DONE
            elif st == PENDING:
                self._status[p] = NOT_NEEDED

    def _enter_after(self, key: str) -> None:
        if self._status.get(key) == ACTIVE:
            self._status[key] = DONE

    def _enter_before(self, key: str) -> None:
        """Marcatore di fase finale: tutti i passi prima di `key` sono risolti."""
        if key in self._status:
            self._resolve_before(key)

    def _not_needed(self, *keys: str) -> None:
        for k in keys:
            if k in self._status and self._status[k] in (PENDING, ACTIVE):
                self._status[k] = NOT_NEEDED
                self._pct.pop(k, None); self._eta.pop(k, None)

    def _insert_ocr_translate(self) -> None:
        keys = [k for k in OCR_STEPS if k in self._status or k == 'ocr_translate']
        self._status = {k: self._status.get(k, PENDING) for k in keys}

    def _bar(self, group: str, pct, eta_s=None) -> None:
        key = _BAR_TO_STEP.get(group)
        if key is None or pct is None:
            return
        if key == 'translate' and self._route == 'ocr':
            key = 'ocr_translate'
        if key not in self._status or self._status[key] == DISABLED:
            return
        if key in ('ocr_read', 'diarize') and self._status[key] != ACTIVE:
            return                                   # fase OCR precedente (es. estrazione VOBSUB); o diarizzazione della correzione di genere
                                                     # (il figlio eredita gli eventi) con il passo della pipeline escluso o gia' concluso
        if self._status[key] in (PENDING, NOT_NEEDED):
            self._enter(key)                         # barra senza fase annunciata: il passo e' di fatto in corso
        p = min(max(int(pct), 0), 100)
        if key in HOLD_AT_99 and p >= 100:
            p = 99
        if p > self._pct.get(key, -1):
            self._pct[key] = p
            est = self._est.get(key)
            if est is None:
                est = self._est[key] = EtaEstimator(clock=self._clock)
            est.update(p / 100.0)
            if eta_s is None:                           # nessuna ETA dal motore: stima dal ritmo delle percentuali
                rem = est.remaining_seconds()
                self._eta[key] = _fmt_eta(rem)
        if eta_s is not None and p < 99:                # ETA del motore (la stessa del suo log): ha la precedenza
            self._eta[key] = _fmt_eta(float(eta_s))
        if int(pct) >= 100:                             # il motore ha finito: nessuna ETA (non lasciare l'ultima, ormai vecchia)
            self._eta[key] = ''

    def _step(self, name: str, state: str, reason: str, ok: bool = True) -> None:
        if name not in ('save', 'upload', 'mux'):
            return
        if name not in self._status:
            return
        if state == 'start':
            if self._status[name] in EXCLUDED:
                return
            self._enter(name)
        elif state == 'done':
            if self._status[name] in (PENDING, ACTIVE, NOT_NEEDED):
                self._resolve_before(name)
                self._status[name] = DONE if ok else FAILED
        elif state == 'skip':
            if self._status[name] in (PENDING, ACTIVE):
                self._status[name] = DISABLED if reason == 'disabled' else NOT_NEEDED

    def _same_as_target(self, code: str) -> bool:
        c = _lang2(code)
        return bool(c) and bool(self._target) and c == self._target

    # ------------------------------------------------------------------ esito
    def mark_completed(self) -> None:
        """File riuscito: ogni passo ancora attivo e' fatto, quelli mai iniziati non servivano."""
        for k, st in list(self._status.items()):
            if st == ACTIVE:
                self._status[k] = DONE
            elif st == PENDING:
                self._status[k] = NOT_NEEDED
        self._finished = True

    def _interrupt(self, status: str) -> None:
        """Il passo attivo diventa `status`; se il file si ferma tra due passi (nessuno attivo) il segno va al
        primo passo ancora in attesa: l'errore non resta invisibile."""
        active = [k for k, st in self._status.items() if st == ACTIVE]
        if active:
            for k in active:
                self._status[k] = status
        else:
            nxt = next((k for k, st in self._status.items() if st == PENDING), None)
            if nxt is not None:
                self._status[nxt] = status
        self._finished = True

    def mark_failed(self) -> None:
        self._interrupt(FAILED)

    def mark_stopped(self) -> None:
        self._interrupt(STOPPED)

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> PipelineSnapshot:
        steps: List[StepState] = []
        order = 0
        for key, st in self._status.items():
            if st in EXCLUDED:
                o = None
            else:
                order += 1
                o = order
            steps.append(StepState(
                key=key, label_key=LABEL_KEYS[key], status=st, order=o,
                pct=self._pct.get(key),
                eta=self._eta.get(key, ''),
                est_tau=EST_TAU.get(key) if st == ACTIVE and key not in self._pct else None,
                started_at=self._started.get(key) if st == ACTIVE else None))
        total = sum(1 for s in steps if s.status not in EXCLUDED)
        done = sum(1 for s in steps if s.status == DONE)
        return PipelineSnapshot(self.file_path, self.file_name, tuple(steps), done, total, self._finished)
