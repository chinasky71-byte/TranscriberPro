"""
Orchestratore: da blocchi SRT a sottotitoli italiani adattati
==============================================================
Mette insieme engine + prompt + validatore + post-processing, e soprattutto
gestisce il fallimento. Un LLM da 8B che traduce a batch sbaglia: la differenza
tra un esperimento e una pipeline di produzione è tutta qui.

Politica di retry a scalare, in quest'ordine:
  1. stesso batch, con l'errore rilevato scritto nel prompt
  2. batch dimezzato (spesso il problema è la lunghezza della risposta)
  3. un blocco per volta (elimina il disallineamento per costruzione)
  4. fallback sul traduttore di riserva (NLLB fine-tuned)

Il quarto gradino è quello che rende il tutto utilizzabile: il ramo LLM
storico, quando fallisce, scrive nell'SRT la frase inglese originale
(`core/translator.py`, ramo `translations.append(texts[i])`), lasciando righe
non tradotte nel file finale.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from utils.logger import setup_logger

from . import postprocess
from .postprocess import DASH_PREFIX
from .prompt_builder import SubtitleUnit, build_mt_messages
from .validator import blocking, validate

logger = setup_logger(__name__)

DEFAULT_BATCH = 12
MIN_BATCH = 1
TOKENS_PER_BLOCK = 70      # stima larga: una battuta italiana sta in molto meno
MIN_NEW_TOKENS = 256
HISTORY_DEPTH = 4

# Issue bloccanti che rendono l'output INSERVIBILE (non solo imperfetto): un
# blocco che le porta ancora dopo il retry singolo va segnalato al chiamante
# invece di restare silenziosamente nei risultati con il testo del primo
# tentativo. Deliberatamente stretto: `too_short`/`too_long` premiano/puniscono
# la condensazione (vedi il commento in testa a validator.py sulla soglia
# 0.35 ritirata perché puniva la condensazione corretta), `over_budget` lo
# sistema il post-processing, `softened_profanity`/`glossary` sono difetti di
# resa, non di traduzione mancata: allargare questo insieme moltiplicherebbe
# il traffico verso i livelli di recupero successivi per comportamenti che
# non sono il bug che stiamo chiudendo.
UNUSABLE_CODES = {"empty", "wrong_language", "copy_through", "degenerate"}


class SubtitleLLMTranslator:
    """Traduce una lista di blocchi con un LLM, con rete di sicurezza."""

    def __init__(
        self,
        engine,
        fallback: Optional[Callable[[Sequence[str]], List[str]]] = None,
        batch_size: int = DEFAULT_BATCH,
        log_callback: Optional[Callable] = None,
        glossary: Optional[Dict[str, str]] = None,
        source_lang: str = "en",
    ):
        """
        `fallback`: funzione che traduce una lista di testi. Riceve i blocchi
        che l'LLM non è riuscito a produrre. Se assente, quei blocchi restano
        vuoti e vengono segnalati.

        `source_lang`: codice lingua che il motore scrive nel prompt come
        lingua di partenza (`source_lang_code` del chat template di
        TranslateGemma). Il default "en" è il comportamento storico: prima di
        questo argomento il codice era fisso a "en" qualunque fosse la lingua
        reale del sottotitolo. Viaggia in `_mt_prompt`, che è il punto unico da
        cui passano il primo giro, il retry singolo e il recupero L2 (che
        richiama `_translate_mt`): cambia solo il codice, mai il testo delle
        istruzioni.

        `glossary`: rete di sicurezza indipendente dal mascheramento a monte
        (core/translator.py._mask_glossary) — qui `unit.text` è già la
        versione mascherata quando il mascheramento riesce, quindi questo
        controllo scatta solo quando un termine è sfuggito al mascheramento
        (regex non combaciante) ED è finito nell'output senza la resa fissa.
        """
        self.engine = engine
        self.fallback = fallback
        self.log_callback = log_callback
        self.glossary = glossary or {}
        self.source_lang = source_lang or "en"

        # Il tetto lo detta il modello, non il chiamante: un 12B quantizzato
        # lascia poco più di 4 GB liberi, e lo stesso batch che un 8B regge
        # senza sforzo lo manda a sconfinare nella RAM di sistema.
        cap = getattr(getattr(engine, "spec", None), "max_batch", batch_size)
        self.batch_size = max(MIN_BATCH, min(batch_size, cap))
        self._batch_cap = cap
        self._batch_mgr = self._make_batch_manager()
        self.stats = {
            "batch": 0, "retry_single": 0,
            "fallback_blocks": 0, "unresolved": 0,
        }
        # Quali controlli scattano, e quante volte: serve a distinguere un
        # modello che sbaglia da un validatore troppo severo.
        self.issue_counts: Dict[str, int] = {}
        # Id dei blocchi il cui output resta INSERVIBILE (UNUSABLE_CODES)
        # anche dopo il retry singolo — o il cui output è vuoto. Popolato da
        # `_translate_mt`, consumato dal chiamante (`core/translator.py`,
        # `LLMSubtitleTranslator.translate_file`) per instradarli ai livelli
        # di recupero successivi (L2/L3) invece di lasciarli silenziosamente
        # nel dict dei risultati con il testo del primo tentativo fallito.
        self.unresolved_ids: set = set()

    def log(self, message: str) -> None:
        logger.info(message)
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass

    def _batch_log(self, message: str) -> None:
        """Canale del gestore batch verso lo schermo — e SOLO verso lo schermo.

        Passargli `self.log` scriveva lo stesso messaggio tre volte nel file
        condiviso: il gestore lo manda già al proprio logger
        (`adaptive_batch_manager._log`), `self.log` lo rimanda al logger di
        questo modulo e il callback della GUI (`LLMSubtitleTranslator.log`,
        core/translator.py:134) una terza. Qui si inoltra soltanto. Stesso
        schema del ramo NLLB (core/translator.py:1315).
        """
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _make_batch_manager(self):
        """Riusa il gestore adattivo già in servizio sul ramo NLLB.

        Su WDDM non arriva nessun OOM da intercettare: quando la memoria
        dedicata finisce, il driver continua ad allocare nella RAM di sistema
        e l'unico sintomo è il crollo della velocità. Il gestore lavora perciò
        sulla percentuale di memoria occupata letta tra un batch e l'altro —
        è lo stesso meccanismo che in v1.9.5 ha eliminato lo sconfinamento su
        NLLB e sul ramo LLM, e non c'è ragione di scriverne un secondo.
        """
        try:
            import torch
            use_gpu = torch.cuda.is_available()
        except Exception:
            use_gpu = False
        if not use_gpu:
            return None
        try:
            from utils.adaptive_batch_manager import AdaptiveBatchSizeManager
        except Exception as exc:
            logger.warning(f"Gestore batch adattivo non disponibile: {exc}")
            return None
        return AdaptiveBatchSizeManager(
            device="cuda", use_gpu=True,
            initial_size=self.batch_size,
            min_size=MIN_BATCH, max_size=self._batch_cap,
            # I pesi da soli occupano già il 60-75% della scheda: con la soglia
            # bassa di serie (0,60) il batch non salirebbe mai, e con l'alta di
            # serie (0,85) scenderebbe troppo tardi per un 12B.
            high_threshold=0.90, low_threshold=0.80,
            warmup_batches=3,
            # Prima era None: il suo avviso "GPU contesa: la tengo ferma" non
            # arrivava mai a schermo, lasciando solo il sintomo generico di
            # _check_throughput senza la diagnosi vera (contesa esterna o
            # memoria nostra) che il gestore calcola già. Gli aggiustamenti
            # "Memoria alta: batch X → Y" restano invece fuori dallo schermo
            # di proposito: il gestore li manda a `logger.info` e non a
            # `_log` perché intercalati alla barra ne impedirebbero la
            # riscrittura in-place (adaptive_batch_manager.py:186-190).
            log_callback=self._batch_log,
        )

    # Oltre questo rapporto rispetto al ritmo migliore del file, la
    # generazione sta andando a una frazione della velocità di cui è capace.
    SLOWDOWN_TRIP = 2.0
    # Prima di poter avvisare servono almeno tanti campioni: il primo batch
    # paga l'autotuning dei kernel e non è un riferimento onesto.
    SLOW_MIN_SAMPLES = 3

    def _check_throughput(self, seconds: float, chars: int) -> None:
        """Dice quando la generazione sta andando piano. Segnala e basta.

        Stesso punto cieco del ramo NLLB, e qui con una storia alle spalle:
        su questo ramo lo sconfinamento in RAM di sistema su WDDM è già stato
        osservato, e la sua unica firma documentata è "il tempo per blocco che
        RISALE" — non un OOM, che il driver Windows non solleva perché serve
        l'allocazione dalla memoria condivisa.

        Il denominatore sono i CARATTERI generati, non i token: il motore
        restituisce testo, non tensori, e per una lingua fissa i due sono
        proporzionali. Quel che conta è il rapporto con il ritmo migliore
        dello stesso file, non il valore assoluto.

        Non agisce sul batch. Misurato sul ramo NLLB (run contese del
        2026-09-05): sotto contesa di un altro processo ridurre il batch
        peggiora il tempo del 62%. Qui serve saperlo, non reagire.
        """
        try:
            if chars <= 0 or seconds <= 0 or getattr(self, "_quiet_bar", False):
                return
            ms_per_char = seconds * 1000.0 / chars
            self._slow_samples = getattr(self, "_slow_samples", 0) + 1
            base = getattr(self, "_ms_char_base", None)
            if base is None or ms_per_char < base:
                self._ms_char_base = ms_per_char
                return
            if (base > 0 and self._slow_samples >= self.SLOW_MIN_SAMPLES
                    and ms_per_char > base * self.SLOWDOWN_TRIP
                    and not getattr(self, "_slow_warned", False)):
                self._slow_warned = True
                # `_slow_warned` si azzera a ogni cambio di batch (_reset_throughput_base): senza
                # questo contatore l'avviso poteva comparire piu' volte nello stesso file. A
                # schermo ne esce UNA per file; le altre restano nel file di log e il numero
                # totale compare nella riga "Completato in ...".
                self._slow_events = getattr(self, "_slow_events", 0) + 1
                msg = (f"  ⚠️ Generazione rallentata {ms_per_char / base:.1f}× "
                       f"rispetto al ritmo migliore di questo file. Di solito "
                       f"significa che un altro processo sta usando la GPU.")
                if self._slow_events == 1:
                    self.log(msg)
                else:
                    logger.info(f"{msg} (segnalazione n. {self._slow_events}, non mostrata a schermo)")
        except Exception as exc:
            logger.debug(f"_check_throughput: {exc}")

    def _record_ok(self) -> None:
        if self._batch_mgr is not None:
            self._batch_mgr.record_success()

    def _record_failure(self, exc: Exception) -> None:
        """Un OOM vero è raro su WDDM ma non impossibile (batch enormi, o un
        secondo processo che si prende la scheda): quando arriva, il batch va
        dimezzato subito invece di aspettare la lettura di memoria del giro
        successivo."""
        if self._batch_mgr is None:
            return
        text = f"{type(exc).__name__} {exc}".lower()
        if "out of memory" in text or "cuda error" in text:
            self._batch_mgr.record_oom()

    def _reset_throughput_base(self) -> None:
        """Butta via il ritmo di riferimento e i campioni raccolti finora.

        Da chiamare quando quello che verrà misurato non è più confrontabile
        con quello che è stato misurato.
        """
        self._ms_char_base = None
        self._slow_samples = 0
        self._slow_warned = False

    def _next_batch_size(self) -> int:
        if self._batch_mgr is None:
            return self.batch_size
        size = self._batch_mgr.get_batch_size()
        if size != self.batch_size:
            logger.info(f"  Batch LLM {self.batch_size} → {size}")
            self.batch_size = size
            # Il ritmo per CARATTERE non è confrontabile tra batch di
            # dimensioni diverse: un passo di decodifica costa quasi lo stesso
            # con 12 o con 16 conversazioni in parallelo, quindi il batch più
            # piccolo esce sempre più lento per carattere. Con Aya il gestore
            # parte da 12 (DEFAULT_BATCH_SIZE), il warm-up lo porta al tetto
            # di 16 e lo steady-state lo riporta a 12 perché insostenibile in
            # VRAM: comportamento sano, ma il confronto 12-contro-16 faceva
            # scattare "generazione rallentata" quasi a ogni file.
            #
            # Agganciare il reset alla sola transizione warm-up→steady-state
            # NON bastava: la chiamata che chiude il warm-up esegue ancora il
            # ramo di warm-up e restituisce la dimensione decisa lì (16) — il
            # taglio dello steady-state arriva al batch DOPO. La base veniva
            # quindi rifissata esattamente sul batch gonfiato che si voleva
            # escludere. Invalidare a ogni cambio di dimensione copre quel
            # caso e, in più, tutte le risalite/discese dello steady-state.
            self._reset_throughput_base()
        return size

    # ------------------------------------------------------------------
    def _bar(self, fatti: int, totale: int, t0: float,
             chiuso: bool = False) -> None:
        """La stessa barra del ramo NLLB, aggiornata sul posto.

        La GUI riscrive in-place le righe che contengono `Traduzione: [`
        (`main_window.UPDATABLE_PATTERNS`): senza quella sequenza esatta ogni
        aggiornamento finirebbe su una riga nuova, ed è il motivo per cui il
        ramo LLM riempiva il registro di righe invece di aggiornarne una.

        Rispetto a NLLB c'è in più la stima del tempo rimanente, che qui serve
        davvero: un 12B fa circa tre secondi a battuta, quindi un film intero
        sono ore e non minuti.
        """
        # Modalità silenziosa: `_translate_mt` viene richiamato una seconda
        # volta dal livello di recupero L2 (core/translator.py, fase B) su
        # una manciata di blocchi. Senza questa guardia la barra ripartirebbe
        # da 0% DOPO che quella della traduzione principale è già arrivata a
        # 100%: la GUI riscrive in-place le righe `Traduzione: [`, quindi a
        # schermo sembrerebbe che la traduzione ricominci da capo.
        if getattr(self, "_quiet_bar", False):
            return
        import time as _t
        trascorso = _t.time() - t0
        if chiuso:
            m, sec = divmod(int(trascorso), 60)
            durata = f"{m}m {sec:02d}s" if m else f"{sec}s"
            self.log(f"  ✅ Traduzione: [██████████] 100% "
                     f"({totale}/{totale}) │ {durata}")
            return
        pct = int(fatti * 100 / totale) if totale else 0
        pieni = pct // 10
        barra = "█" * pieni + "░" * (10 - pieni)
        coda = ""
        if fatti:
            manca = trascorso / fatti * (totale - fatti)
            m = int(manca // 60)
            coda = f" │ ~{m}m" if m else f" │ ~{int(manca)}s"
        self.log(f"  🌐 Traduzione: [{barra}] {pct:3d}% ({fatti}/{totale}) "
                 f"│ batch:{self.batch_size}{coda}")

    def _record(self, issues) -> None:
        for issue in issues:
            key = issue.code if issue.blocking else f"~{issue.code}"
            self.issue_counts[key] = self.issue_counts.get(key, 0) + 1

    # ------------------------------------------------------------------
    def _expand_dialogue(
        self, units: Sequence[SubtitleUnit]
    ) -> Tuple[List[SubtitleUnit], Dict[int, List[Tuple[int, bool]]]]:
        """Spezza i blocchi a due parlanti in un'unità di traduzione per riga.

        Il modello non garantisce di riprodurre il newline e il trattino: a
        volte fonde le due battute in una riga sola, e il risultato assegna
        allo stesso parlante parole di entrambi. Tradurre riga per riga elimina
        il problema per costruzione — il numero di righe dopo la traduzione è
        identico all'originale.

        È la stessa soluzione che il ramo NLLB adotta in
        `NLLBTranslator._build_translation_units`, dove il difetto era già
        stato osservato empiricamente.
        """
        expanded: List[SubtitleUnit] = []
        rebuild: Dict[int, List[Tuple[int, bool]]] = {}
        next_id = max((u.id for u in units), default=0) + 1

        for unit in units:
            lines = [l for l in unit.text.split("\n") if l.strip()]
            has_dash = any(DASH_PREFIX.match(l) for l in lines)
            if len(lines) < 2 or not has_dash:
                expanded.append(unit)
                continue

            parts: List[Tuple[int, bool]] = []
            for line in lines:
                dashed = bool(DASH_PREFIX.match(line))
                clean = DASH_PREFIX.sub("", line).strip()
                expanded.append(SubtitleUnit(
                    id=next_id,
                    text=clean,
                    duration=unit.duration / len(lines),
                    is_dialogue=False,
                    speaker=unit.speaker,
                ))
                parts.append((next_id, dashed))
                next_id += 1
            rebuild[unit.id] = parts

        return expanded, rebuild

    @staticmethod
    def _expand_drafts(
        raw_drafts: Dict[int, str],
        rebuild: Dict[int, List[Tuple[int, bool]]],
    ) -> Dict[int, str]:
        """Allinea le bozze alle unità dopo l'espansione dei dialoghi.

        Se la bozza ha lo stesso numero di righe dell'originale l'allineamento
        è ovvio. Se non lo ha — il traduttore di base ha fuso o spezzato le
        battute — la bozza intera va alla prima riga: meglio un contesto
        ridondante che un'assegnazione sbagliata, che attribuirebbe a un
        parlante le parole dell'altro.
        """
        drafts = dict(raw_drafts)
        for orig_id, parts in rebuild.items():
            whole = drafts.pop(orig_id, "")
            lines = [DASH_PREFIX.sub("", l).strip()
                     for l in whole.split("\n") if l.strip()]
            if len(lines) == len(parts):
                for (part_id, _), line in zip(parts, lines):
                    drafts[part_id] = line
            else:
                for i, (part_id, _) in enumerate(parts):
                    drafts[part_id] = whole if i == 0 else ""
        return drafts

    @staticmethod
    def _rebuild_dialogue(
        results: Dict[int, str],
        rebuild: Dict[int, List[Tuple[int, bool]]],
    ) -> Dict[int, str]:
        """Ricompone i blocchi spezzati, rimettendo i trattini dov'erano."""
        for orig_id, parts in rebuild.items():
            lines = []
            for part_id, dashed in parts:
                text = results.pop(part_id, "").strip()
                # Il modello può aggiungere un trattino proprio: si normalizza
                # sulla struttura dell'originale, che è l'unica affidabile.
                text = DASH_PREFIX.sub("", text).strip()
                if not text:
                    continue
                lines.append(f"- {text}" if dashed else text)
            results[orig_id] = "\n".join(lines)
        return results

    # ------------------------------------------------------------------
    def translate(self, units: Sequence[SubtitleUnit]) -> Dict[int, str]:
        """Traduce tutti i blocchi e restituisce {id: testo italiano}."""
        if not units:
            return {}

        sources = {u.id: u.text for u in units}
        order = [u.id for u in units]

        work, rebuild = self._expand_dialogue(units)
        results = self._translate_mt(work)
        results = self._rebuild_dialogue(results, rebuild)
        return postprocess.process(results, order=order, sources=sources)

    # ------------------------------------------------------------------
    def _mt_prompt(self, unit: SubtitleUnit):
        """Delega al motore, che conosce il formato dei propri pesi.

        Il budget di caratteri viaggia insieme al testo: il percorso "adapt" lo
        passava da sempre dentro il prompt, questo no, ed era il motivo per cui
        i modelli MT scrivevano battute che non stavano sullo schermo.

        Anche la lingua di partenza viaggia qui (`self.source_lang`): era
        sempre il default "en" del motore, anche per un file francese.
        """
        builder = getattr(self.engine, "mt_messages", None)
        if builder is None:
            return build_mt_messages(unit)
        # `getattr` e non `self.source_lang`: le istanze costruite con
        # `__new__` (test, sonde) non passano da `__init__`.
        src = getattr(self, "source_lang", "en")
        try:
            return builder(unit.text, src_lang=src, budget=unit.budget)
        except TypeError:
            # Motore con la firma vecchia: meglio un prompt senza budget (e
            # senza lingua) che una traduzione mancata. Si scala di un
            # gradino alla volta: prima si toglie la lingua tenendo il budget
            # (firma intermedia), poi anche il budget.
            if src != "en" and not getattr(self, "_warned_src_drop", False):
                self._warned_src_drop = True
                self.log(f"  ⚠️ Il motore non accetta src_lang: lingua "
                         f"'{src}' ignorata, prompt con 'en'")
            try:
                return builder(unit.text, budget=unit.budget)
            except TypeError:
                return builder(unit.text)

    def _translate_mt(self, units: Sequence[SubtitleUnit]) -> Dict[int, str]:
        """Percorso per i modelli MT specializzati.

        Una battuta per conversazione, ma più conversazioni nella stessa
        chiamata a `generate()`: il batching avviene sulla GPU invece che nel
        prompt. Non serve parsing — l'output È la traduzione — quindi cadono
        per costruzione il disallineamento degli id e i retry che ne seguono.
        """
        results: Dict[int, str] = {}
        total = len(units)
        t0 = time.time()
        self._bar(0, total, t0)
        # Le battute sono corte: il tetto serve solo contro le degenerazioni.
        max_new = 160

        i = 0
        while i < total:
            batch = list(units[i:i + self._next_batch_size()])
            self.stats["batch"] += 1
            # Il prompt nativo lo costruisce il motore: TranslateGemma vuole
            # un content strutturato coi codici lingua, gli altri una frase.
            conversations = [self._mt_prompt(u) for u in batch]
            _t_gen = time.time()
            _generated = True
            try:
                outputs = self.engine.generate(conversations,
                                               max_new_tokens=max_new)
                self._record_ok()
            except Exception as exc:
                # Un prompt invalido (es. codice lingua assente dal chat
                # template) e' deterministico: ripeterlo su ogni batch e poi su
                # L2/L3 svuoterebbe in silenzio tutto il file. Si ferma subito.
                try:
                    import jinja2
                    if isinstance(exc, jinja2.TemplateError):
                        raise
                except ImportError:
                    pass
                logger.warning(f"Generazione MT fallita su {len(batch)} "
                               f"blocchi: {exc}")
                self._record_failure(exc)
                outputs = [""] * len(batch)
                _generated = False
            # Fuori dal try: una misura non deve poter essere scambiata per un
            # fallimento di generazione. Solo batch PIENI: l'ultimo batch del
            # file è quasi sempre troncato (`units[i:i + size]`), e un batch
            # corto paga il costo fisso del passo di decodifica su meno
            # caratteri — con 3 unità invece di 12 il ms/carattere sale di
            # parecchie volte e fa scattare l'avviso di rallentamento proprio
            # in fondo a ogni file, senza nessuna contesa in corso.
            if _generated and len(batch) == self.batch_size:
                self._check_throughput(time.time() - _t_gen,
                                       sum(len(t or "") for t in outputs))

            for unit, text in zip(batch, outputs):
                results[unit.id] = text.strip()

            issues = validate(
                batch, {u.id: results[u.id] for u in batch},
                glossary=self.glossary,
                )
            self._record(issues)

            # Riprova una volta sola i blocchi difettosi, singolarmente.
            issues_by_id: Dict[int, List] = {}
            for issue in issues:
                if issue.id is not None:
                    issues_by_id.setdefault(issue.id, []).append(issue)
            bad = {x.id for x in blocking(issues) if x.id is not None}
            for unit in [u for u in batch if u.id in bad]:
                self.stats["retry_single"] += 1

                def _mark_if_unusable(codes) -> None:
                    if {c.code for c in codes} & UNUSABLE_CODES:
                        self.unresolved_ids.add(unit.id)

                try:
                    retry = self.engine.generate(
                        [self._mt_prompt(unit)], max_new_tokens=max_new)[0]
                except Exception:
                    # Il PRIMO tentativo resta in `results` (riga 342): se era
                    # inservibile, va comunque segnalato — senza questo un
                    # copy-through che il retry non ha nemmeno potuto tentare
                    # sopravviverebbe silenzioso nell'output finale.
                    _mark_if_unusable(issues_by_id.get(unit.id, []))
                    continue
                if retry.strip():
                    single = {unit.id: retry.strip()}
                    still = validate([unit], single, glossary=self.glossary)
                    if not blocking(still):
                        results[unit.id] = retry.strip()
                    else:
                        # Il retry non ha risolto il problema: NON si tiene il
                        # suo output (potrebbe essere peggio del primo), ma si
                        # marca il blocco come da recuperare a un livello
                        # superiore invece di lasciare in `results` il testo
                        # del primo tentativo senza che nessuno lo sappia.
                        _mark_if_unusable(still)
                else:
                    _mark_if_unusable(issues_by_id.get(unit.id, []))

            prev, i = i, i + len(batch)
            if i * 100 // total != prev * 100 // total or i >= total:
                self._bar(i, total, t0)

        # Blocchi usciti vuoti dal motore primario: marcati come da recuperare
        # a un livello superiore, esattamente come i copy-through/wrong_language
        # sopra. PRIMA chiamava `self._apply_fallback(...)`, un metodo mai
        # definito da nessuna parte del progetto: qualunque blocco vuoto
        # faceva sollevare AttributeError, risalito fino a `translate_file`
        # (core/translator.py) e trasformato in `return False` — cioè faceva
        # fallire la traduzione dell'INTERO file per un singolo blocco vuoto.
        failed = [u for u in units if not results.get(u.id, "").strip()]
        for u in failed:
            self.unresolved_ids.add(u.id)
        if failed and self.fallback:
            try:
                fallback_texts = self.fallback([u.text for u in failed])
                for u, text in zip(failed, fallback_texts):
                    if text and text.strip():
                        results[u.id] = text.strip()
                        self.unresolved_ids.discard(u.id)
                        self.stats["fallback_blocks"] += 1
            except Exception as exc:
                logger.warning(f"Fallback callback fallito: {exc}")
        self.stats["unresolved"] = len(self.unresolved_ids)

        self._bar(total, total, t0, chiuso=True)
        if getattr(self, "_quiet_bar", False):
            self.log(f"  Recupero senza mascheramento: {total} blocchi in "
                     f"{(time.time() - t0) / 60:.1f} min")
        else:
            _slow_n = getattr(self, "_slow_events", 0)
            self.log(f"  Completato in {(time.time() - t0) / 60:.1f} min | "
                     f"batch {self.stats['batch']} | retry "
                     f"{self.stats['retry_single']} | fallback "
                     f"{self.stats['fallback_blocks']}"
                     + (f" | rallentamenti {_slow_n}" if _slow_n > 1 else ""))
        return results
