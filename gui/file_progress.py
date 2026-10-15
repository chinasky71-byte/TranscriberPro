# -*- coding: utf-8 -*-
"""
Avanzamento del SINGOLO file in lavorazione (barra nell'elenco della coda e barra sotto la locandina).

Classe pura, senza Qt: `FileProgress.feed(riga)` riceve le righe stampate dal subprocess della pipeline
(`core.pipeline_cli`) e ritorna la nuova percentuale intera (0..99) quando aumenta, altrimenti None.

Perche': prima la percentuale si muoveva solo sui marcatori di passo ("4. Trascrizione...") con una
tabella fissa, quindi la fase piu' lunga (trascrizione 60->68%, traduzione 88->93%) lasciava la barra
ferma per ore e poi saltava a 100%. Ora:
  - ogni fase pesa in proporzione alla sua durata MISURATA sui log reali (Demucs 1 : trascrizione
    2,5-6 : traduzione 30);
  - dentro una fase la barra segue la barra interna che la fase stampa gia' ("Trascrizione: [..] 40%");
  - le fasi che non avverranno (traduzione se la lingua e' gia' quella finale, audio se ci sono sottotitoli
    embedded) escono dal calcolo appena la riga che lo dice compare.

Regole che evitano regressioni (v. memoria sottotitoli/avanzamento):
  - mai 100: il 100% lo mette `on_file_completed` della GUI; il valore e' sempre <= 99 e monotono;
  - solo pattern ASCII (le stringhe della pipeline sono in parte mojibake nel sorgente);
  - "Warm-up: [" e le barre di un'altra fase sono ignorate;
  - una riga di decisione con lo stesso numero di passo ("6. Lingua originale == ...") non apre la fase;
  - nessun marcatore e' obbligatorio (8. solo con upload attivo; il ramo OCR salta 5/6/7).
"""
import re
from typing import Dict, Optional, Set

# Fasi nell'ordine canonico di esecuzione.
_ORDER = ['setup', 'ocr_extract', 'ocr_read', 'ocr_translate', 'extract', 'demucs', 'asr', 'clean',
          'translate', 'gender', 'final']

_BASE_WEIGHTS: Dict[str, float] = {
    'setup': 0.3, 'extract': 0.3, 'demucs': 1.0, 'asr': 4.0, 'clean': 0.1,
    'translate': 30.0, 'gender': 1.5, 'final': 1.0,
    'ocr_extract': 0.5, 'ocr_read': 3.0, 'ocr_translate': 12.0,
}
# Peso della trascrizione per motore (rapporto misurato con Demucs = 1: Qwen3 ~6, Canary ~2,5).
_ASR_BY_ENGINE = (('qwen3', 6.0), ('canary', 2.5))

# Chiave della barra interna accettata da ogni fase.
_INNER_KEYS = {
    'demucs': ('Demucs: [',),
    'asr': ('Trascrizione: [',),
    'translate': ('Traduzione: [', 'Progresso:'),
    'ocr_translate': ('Traduzione: [', 'Progresso:'),
    'gender': ('Correzione genere: [',),
}

_LANG3_TO_2 = {'ita': 'it', 'eng': 'en', 'fra': 'fr', 'fre': 'fr', 'deu': 'de', 'ger': 'de', 'spa': 'es',
               'por': 'pt', 'rus': 'ru', 'jpn': 'ja', 'zho': 'zh', 'chi': 'zh', 'kor': 'ko', 'ara': 'ar',
               'nld': 'nl', 'dut': 'nl', 'pol': 'pl', 'tur': 'tr'}

# Barre interne: gruppo dell'evento `bar` -> fasi in cui vale; fase -> gruppo (per cedere il passo al testo).
_BAR_PHASES = {'demucs': ('demucs',), 'asr': ('asr',), 'translate': ('translate', 'ocr_translate'),
               'gender': ('gender',)}
_PHASE_BAR = {p: g for g, ps in _BAR_PHASES.items() for p in ps}

_STEP_RE = re.compile(r'^\s*(\d+(?:\.\d+)?[a-z]?)\.\s+(\S.*)$')
_PCT_RE = re.compile(r'(\d+)\s*%')
_AUDIO_LANG_RE = re.compile(r'Audio estratto\. Lingua:\s*([A-Za-z]+)')
_EMBEDDED_RE = re.compile(r'Sottotitoli embedded trovati \(([A-Za-z]+)\)')


def _lang2(code: str) -> str:
    c = (code or '').strip().lower()
    return _LANG3_TO_2.get(c, c if len(c) == 2 else '')


class FileProgress:
    CAP = 99

    def __init__(self, target_language: str = 'ita'):
        self.target = _lang2(target_language)
        self.possible: Set[str] = {'setup', 'extract', 'demucs', 'asr', 'clean', 'translate', 'gender', 'final'}
        self.weights: Dict[str, float] = dict(_BASE_WEIGHTS)
        self.fraction: Dict[str, float] = {}
        self.phase: Optional[str] = None
        self.value = 0
        # gruppi di barre per cui sono arrivati eventi `bar`: per quelli il testo non conta piu'
        self._evt_bars: Set[str] = set()

    # ------------------------------------------------------------------
    def feed(self, line: str) -> Optional[int]:
        """Elabora una riga. Ritorna la nuova percentuale (int, <= 99) solo se e' aumentata."""
        try:
            self._consume(line or '')
        except Exception:
            return None
        return self._bump()

    def feed_event(self, kind: str, fields: Optional[dict] = None) -> Optional[int]:
        """Elabora un evento strutturato (utils/events.py). Stessa regola di `feed`: ritorna la nuova
        percentuale solo se e' aumentata. Gli eventi e il testo convivono sullo stesso stato (le decisioni
        sono idempotenti); per le barre interne, dopo il primo evento `bar` di un gruppo il testo di quel
        gruppo non conta piu'."""
        try:
            self._event(kind, fields or {})
        except Exception:
            return None
        return self._bump()

    def _bump(self) -> Optional[int]:
        v = self._compute()
        if v > self.value:
            self.value = v
            return v
        return None

    def _event(self, kind: str, f: dict) -> None:
        if kind == 'phase':
            name = f.get('name')
            if name not in _ORDER:
                return
            if name in ('setup', 'extract', 'demucs', 'asr', 'clean', 'translate', 'gender'):
                self._leave_ocr()       # come i marcatori 1..6.5 del testo
            if name == 'asr':
                engine = str(f.get('engine') or '').lower()
                for key, w in _ASR_BY_ENGINE:
                    if key in engine:
                        self.weights['asr'] = w
                        break
            self._enter(name)
            if f.get('fraction') is not None:
                self.fraction[name] = max(self.fraction.get(name, 0.0), min(1.0, float(f['fraction'])))
        elif kind == 'route':
            if f.get('path') == 'ocr':
                self.possible = {'setup', 'ocr_extract', 'ocr_read', 'final'}
                if f.get('translate'):
                    self.possible.add('ocr_translate')
                self._enter('ocr_extract')
        elif kind == 'audio_lang':
            if self._same_as_target(str(f.get('lang') or '')):
                self._drop('translate', 'gender')
        elif kind == 'embedded':
            self._leave_ocr()
            self._drop('extract', 'demucs', 'asr')
            if self._same_as_target(str(f.get('lang') or '')):
                self._drop('translate', 'gender')
        elif kind == 'skip':
            self._drop(*[p for p in (f.get('phases') or []) if p in _ORDER])
        elif kind == 'ocr_leave':
            self._leave_ocr()
        elif kind == 'bar':
            group = str(f.get('phase') or '')
            if group not in _BAR_PHASES:
                return
            self._evt_bars.add(group)
            if self.phase in _BAR_PHASES[group] and f.get('pct') is not None:
                fr = min(max(int(f['pct']), 0), 100) / 100.0
                if fr > self.fraction.get(self.phase, 0.0):
                    self.fraction[self.phase] = fr

    # ------------------------------------------------------------------
    def _compute(self) -> int:
        total = sum(self.weights[p] for p in self.possible)
        if total <= 0:
            return self.value
        done = sum(self.weights[p] * self.fraction.get(p, 0.0) for p in self.possible)
        return min(self.CAP, max(0, int(done / total * self.CAP + 0.5)))

    def _enter(self, phase: str) -> None:
        """Apre una fase: le fasi precedenti (ordine canonico) risultano completate."""
        if phase not in self.possible:
            self.possible.add(phase)
        idx = _ORDER.index(phase)
        for p in _ORDER[:idx]:
            if p in self.possible:
                self.fraction[p] = 1.0
        self.phase = phase
        self.fraction.setdefault(phase, 0.0)

    def _leave_ocr(self) -> None:
        """OCR fallito o non usato: si torna al percorso testo/audio (fasi OCR fuori dal calcolo)."""
        if not any(p in self.possible for p in ('ocr_extract', 'ocr_read', 'ocr_translate')):
            return
        for p in ('ocr_extract', 'ocr_read', 'ocr_translate'):
            self.possible.discard(p)
            self.fraction.pop(p, None)
        self.possible |= {'setup', 'extract', 'demucs', 'asr', 'clean', 'translate', 'gender', 'final'}
        self.phase = 'setup'

    def _drop(self, *phases: str) -> None:
        for p in phases:
            self.possible.discard(p)

    def _same_as_target(self, code: str) -> bool:
        c = _lang2(code)
        return bool(c) and bool(self.target) and c == self.target

    def _consume(self, line: str) -> None:
        # righe di decisione (ovunque nella riga: le stringhe della pipeline possono avere un prefisso mojibake)
        if 'Warm-up: [' in line:
            return                      # anche durante la trascrizione: mai conta come avanzamento
        if '[Gender]' in line and self.phase != 'gender':
            return                      # righe del correttore di genere: valgono solo nella sua fase
        m = _AUDIO_LANG_RE.search(line)
        if m:
            if self._same_as_target(m.group(1)):
                self._drop('translate', 'gender')
            return
        m = _EMBEDDED_RE.search(line)
        if m:
            self._leave_ocr()
            self._drop('extract', 'demucs', 'asr')
            if self._same_as_target(m.group(1)):
                self._drop('translate', 'gender')
            return

        m = _STEP_RE.match(line)
        if m:
            self._step(m.group(1), m.group(2))
            return

        # ramo OCR (nessuna percentuale nelle righe di stato)
        if 'ocr_extract' in self.possible:
            if re.search(r'OCR\W+Analisi bitmap', line):
                self._enter('ocr_read')
                return
            if re.search(r'OCR\W+Traduzione', line):
                self._enter('ocr_translate')     # anche se non prevista: bitmap dichiarato italiano ma straniero
                return
            if 'OCR bitmap non riuscito' in line or 'Errore OCR bitmap' in line:
                self._leave_ocr()               # la pipeline ripiega su testo/audio
                return
            if 'SRT italiano scritto' in line or 'OCR bitmap completato' in line:
                self._enter('final')
                return

        # barra interna della fase corrente
        if (self.phase in _INNER_KEYS and _PHASE_BAR.get(self.phase) not in self._evt_bars
                and any(k in line for k in _INNER_KEYS[self.phase])):
            p = _PCT_RE.search(line)
            if p:
                f = min(int(p.group(1)), 100) / 100.0
                if f > self.fraction.get(self.phase, 0.0):
                    self.fraction[self.phase] = f

    def _step(self, num: str, text: str) -> None:
        low = text.lower()
        if num in ('1', '2', '2.5', '3', '4', '5', '6', '6.5'):
            self._leave_ocr()       # marcatori del percorso audio/testo: l'OCR (se c'era) non e' andato a buon fine
        if num == '1':
            self._enter('setup')
        elif num == '1b':
            # ramo OCR: nessuna trascrizione audio; la traduzione c'e' solo se il testo la dichiara
            self.possible = {'setup', 'ocr_extract', 'ocr_read', 'final'}
            if 'traduzione' in low:
                self.possible.add('ocr_translate')
            self._enter('ocr_extract')
        elif num == '2':
            self._enter('extract')
        elif num == '2.5':
            self._enter('extract')
        elif num == '3':
            self._enter('demucs')
        elif num == '4':
            for key, w in _ASR_BY_ENGINE:
                if key in low:
                    self.weights['asr'] = w
                    break
            self._enter('asr')
        elif num == '5':
            self._enter('clean')
        elif num == '6':
            if 'salto traduzione' in low or 'lingua originale' in low:
                self._drop('translate', 'gender')
            else:
                self._enter('translate')
        elif num == '6.5':
            if 'saltata' in low:
                self._drop('gender')
            else:
                self._enter('gender')
        elif num in ('7', '8', '9'):
            # salvataggio / upload / remux: avanzano la fase finale a piccoli passi (il 100% lo mette la GUI)
            self._enter('final')
            step = {'7': 0.4, '8': 0.7, '9': 0.9}[num]
            self.fraction['final'] = max(self.fraction.get('final', 0.0), step)
        # altri marcatori (anche sconosciuti): nessun effetto
