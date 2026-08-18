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
from .prompt_builder import (DocumentContext, SubtitleUnit, build_mt_messages,
                             build_messages, build_refine_messages)
from .validator import blocking, parse_response, summarize, validate

logger = setup_logger(__name__)

DEFAULT_BATCH = 12
MIN_BATCH = 1
TOKENS_PER_BLOCK = 70      # stima larga: una battuta italiana sta in molto meno
MIN_NEW_TOKENS = 256
HISTORY_DEPTH = 4


class SubtitleLLMTranslator:
    """Traduce una lista di blocchi con un LLM, con rete di sicurezza."""

    def __init__(
        self,
        engine,
        context: Optional[DocumentContext] = None,
        fallback: Optional[Callable[[Sequence[str]], List[str]]] = None,
        batch_size: int = DEFAULT_BATCH,
        log_callback: Optional[Callable] = None,
        mode: str = "translate",
    ):
        """
        `fallback`: funzione che traduce una lista di testi. Riceve i blocchi
        che l'LLM non è riuscito a produrre. Se assente, quei blocchi restano
        vuoti e vengono segnalati.

        `mode`: "translate" (l'LLM traduce da zero) oppure "refine" (l'LLM
        riscrive una bozza prodotta dal fallback). La seconda parte da una
        traduzione già fedele e ne corregge solo la resa.
        """
        self.engine = engine
        self.context = context
        self.fallback = fallback
        self.log_callback = log_callback
        self.mode = mode

        # Il tetto lo detta il modello, non il chiamante: un 12B quantizzato
        # lascia poco più di 4 GB liberi, e lo stesso batch che un 8B regge
        # senza sforzo lo manda a sconfinare nella RAM di sistema.
        cap = getattr(getattr(engine, "spec", None), "max_batch", batch_size)
        self.batch_size = max(MIN_BATCH, min(batch_size, cap))
        self._batch_cap = cap
        self._batch_mgr = self._make_batch_manager()
        self.stats = {
            "batch": 0, "retry_prompt": 0, "retry_split": 0,
            "retry_single": 0, "fallback_blocks": 0, "unresolved": 0,
        }
        # Quali controlli scattano, e quante volte: serve a distinguere un
        # modello che sbaglia da un validatore troppo severo.
        self.issue_counts: Dict[str, int] = {}

    def log(self, message: str) -> None:
        logger.info(message)
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
            log_callback=None,
        )

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

    def _next_batch_size(self) -> int:
        if self._batch_mgr is None:
            return self.batch_size
        size = self._batch_mgr.get_batch_size()
        if size != self.batch_size:
            logger.info(f"  Batch LLM {self.batch_size} → {size}")
            self.batch_size = size
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

        # La bozza va chiesta sui blocchi INTERI: il traduttore di base lavora
        # sul testo originale, non sulle righe che stiamo per separare.
        raw_drafts: Dict[int, str] = {}
        if self.mode == "refine":
            if self.fallback is None:
                raise ValueError("mode='refine' richiede un traduttore di base")
            self.log("  Bozza con il traduttore di base...")
            base = self.fallback([u.text for u in units])
            raw_drafts = {u.id: t for u, t in zip(units, base)}

        work, rebuild = self._expand_dialogue(units)
        drafts = self._expand_drafts(raw_drafts, rebuild) if raw_drafts else {}

        style = getattr(getattr(self.engine, "spec", None), "prompt_style",
                        "adapt")
        if style == "mt":
            results = self._translate_mt(work)
            results = self._rebuild_dialogue(results, rebuild)
            return postprocess.process(results, order=order, sources=sources)

        results: Dict[int, str] = {}
        history: List[Tuple[str, str]] = []
        total = len(work)
        t0 = time.time()
        self._bar(0, total, t0)

        i = 0
        while i < total:
            batch = list(work[i:i + self._next_batch_size()])
            done = self._translate_batch(batch, history, drafts)
            results.update(done)

            for u in batch:
                if u.id in done and done[u.id]:
                    history.append((u.text, done[u.id]))
            history = history[-HISTORY_DEPTH:]

            prev = i
            i += len(batch)
            # Un aggiornamento per punto percentuale, come sul ramo NLLB: la
            # riga viene riscritta sul posto, quindi costa niente ed evita che
            # una run lunga sembri bloccata fra un decimo e l'altro.
            if i * 100 // total != prev * 100 // total or i >= total:
                self._bar(i, total, t0)

        elapsed = time.time() - t0
        self._bar(total, total, t0, chiuso=True)
        self.log(
            f"  Completato in {elapsed / 60:.1f} min | batch {self.stats['batch']} "
            f"| retry {self.stats['retry_prompt']}+{self.stats['retry_split']}"
            f"+{self.stats['retry_single']} | fallback "
            f"{self.stats['fallback_blocks']} blocchi"
        )
        if self.stats["unresolved"]:
            self.log(f"  ATTENZIONE: {self.stats['unresolved']} blocchi non "
                     f"risolti")

        results = self._rebuild_dialogue(results, rebuild)
        return postprocess.process(results, order=order, sources=sources)

    # ------------------------------------------------------------------
    def _mt_prompt(self, unit: SubtitleUnit):
        """Delega al motore, che conosce il formato dei propri pesi.

        Il budget di caratteri viaggia insieme al testo: il percorso "adapt" lo
        passava da sempre dentro il prompt, questo no, ed era il motivo per cui
        i modelli MT scrivevano battute che non stavano sullo schermo.
        """
        builder = getattr(self.engine, "mt_messages", None)
        if builder is None:
            return build_mt_messages(unit)
        try:
            return builder(unit.text, budget=unit.budget)
        except TypeError:
            # Motore con la firma vecchia: meglio un prompt senza budget che
            # una traduzione mancata.
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
            try:
                outputs = self.engine.generate(conversations,
                                               max_new_tokens=max_new)
                self._record_ok()
            except Exception as exc:
                logger.warning(f"Generazione MT fallita su {len(batch)} "
                               f"blocchi: {exc}")
                self._record_failure(exc)
                outputs = [""] * len(batch)

            for unit, text in zip(batch, outputs):
                results[unit.id] = text.strip()

            issues = validate(
                batch, {u.id: results[u.id] for u in batch},
                glossary=self.context.glossary if self.context else None)
            self._record(issues)

            # Riprova una volta sola i blocchi difettosi, singolarmente.
            bad = {x.id for x in blocking(issues) if x.id is not None}
            for unit in [u for u in batch if u.id in bad]:
                self.stats["retry_single"] += 1
                try:
                    retry = self.engine.generate(
                        [self._mt_prompt(unit)], max_new_tokens=max_new)[0]
                except Exception:
                    continue
                if retry.strip():
                    single = {unit.id: retry.strip()}
                    if not blocking(validate([unit], single)):
                        results[unit.id] = retry.strip()

            prev, i = i, i + len(batch)
            if i * 100 // total != prev * 100 // total or i >= total:
                self._bar(i, total, t0)

        failed = [u for u in units if not results.get(u.id, "").strip()]
        if failed:
            results.update(self._apply_fallback(failed, {}))

        self._bar(total, total, t0, chiuso=True)
        self.log(f"  Completato in {(time.time() - t0) / 60:.1f} min | "
                 f"batch {self.stats['batch']} | retry "
                 f"{self.stats['retry_single']} | fallback "
                 f"{self.stats['fallback_blocks']}")
        return results

    def _generate(self, units: Sequence[SubtitleUnit],
                  history: Sequence[Tuple[str, str]],
                  drafts: Dict[int, str],
                  retry_note: Optional[str] = None) -> Dict[int, str]:
        """Una chiamata al modello; restituisce ciò che è riuscito a parsare."""
        if self.mode == "refine":
            messages = build_refine_messages(units, drafts, self.context)
        else:
            messages = build_messages(units, self.context, history, retry_note)

        max_new = max(MIN_NEW_TOKENS, len(units) * TOKENS_PER_BLOCK)
        try:
            raw = self.engine.generate([messages], max_new_tokens=max_new)[0]
            self._record_ok()
        except Exception as exc:
            self._record_failure(exc)
            raise

        parsed, parse_issues = parse_response(raw, [u.id for u in units])
        for issue in parse_issues:
            logger.debug(str(issue))
        return parsed

    def _bad_ids(self, units, results):
        """Quali blocchi vanno rifatti, e con quale spiegazione.

        Distingue i guasti di BATCH (la risposta non si parsa, mancano gli id)
        dai guasti di BLOCCO (una singola resa è vuota, degenerata, o attenua
        il turpiloquio). È la distinzione che rende il retry economico: rifare
        dodici blocchi perché uno solo è sbagliato costava, alla misura, un
        fattore tre sul tempo totale.
        """
        issues = validate(
            units, results,
            glossary=self.context.glossary if self.context else None)
        self._record(issues)
        hard = blocking(issues)
        if not hard:
            return set(), "", issues

        ids = {i.id for i in hard if i.id is not None}
        # Un blocco assente dalla risposta è comunque da rifare.
        ids.update(u.id for u in units
                   if not results.get(u.id, "").strip())
        # Guasto senza id (JSON illeggibile): tocca tutto il batch.
        if not ids:
            ids = {u.id for u in units}

        note = summarize([i for i in hard if i.id is None or i.id in ids])
        return ids, note, issues

    def _translate_batch(self, units: Sequence[SubtitleUnit],
                         history: Sequence[Tuple[str, str]],
                         drafts: Dict[int, str]) -> Dict[int, str]:
        """Un batch, con retry mirati e poi la rete di sicurezza."""
        self.stats["batch"] += 1

        results = self._safe_generate(units, history, drafts)
        bad, note, _ = self._bad_ids(units, results)
        if not bad:
            return results

        # Gradino 1 — si rigenerano SOLO i blocchi difettosi, spiegando
        # l'errore. Se a fallire è l'intero batch e i blocchi sono molti, la
        # causa più probabile è una risposta troppo lunga: si dimezza.
        for _ in range(2):
            todo = [u for u in units if u.id in bad]
            if len(todo) == len(units) and len(units) > 3:
                self.stats["retry_split"] += 1
                mid = len(units) // 2
                return {**self._translate_batch(units[:mid], history, drafts),
                        **self._translate_batch(units[mid:], history, drafts)}

            self.stats["retry_prompt"] += 1
            logger.info(f"Retry mirato su {len(todo)} blocchi: {note}")
            redo = self._safe_generate(todo, history, drafts, retry_note=note)
            for key, value in redo.items():
                if value.strip():
                    results[key] = value

            bad, note, _ = self._bad_ids(units, results)
            if not bad:
                return results

        # Gradino 2 — un blocco per volta: elimina il disallineamento per
        # costruzione, perché non c'è più niente da allineare.
        for unit in [u for u in units if u.id in bad]:
            self.stats["retry_single"] += 1
            single = self._safe_generate([unit], history, drafts,
                                         retry_note=note)
            text = single.get(unit.id, "")
            if text.strip() and not blocking(validate([unit], single)):
                results[unit.id] = text

        # Gradino 3 — fallback sul traduttore di base per ciò che resta.
        bad, _, _ = self._bad_ids(units, results)
        failed = [u for u in units if u.id in bad]
        if failed:
            results.update(self._apply_fallback(failed, drafts))
        return results

    def _safe_generate(self, units, history, drafts, retry_note=None):
        """Un'eccezione del modello non deve far cadere l'intero file."""
        try:
            return self._generate(units, history, drafts, retry_note)
        except Exception as exc:
            logger.warning(f"Generazione fallita su {len(units)} blocchi: {exc}")
            return {}

    def _apply_fallback(self, units: Sequence[SubtitleUnit],
                        drafts: Dict[int, str]) -> Dict[int, str]:
        # In modalità refine la bozza c'è già: usarla è il fallback naturale.
        ready = {u.id: drafts[u.id] for u in units
                 if drafts.get(u.id, "").strip()}
        missing = [u for u in units if u.id not in ready]

        if missing and self.fallback is not None:
            self.log(f"  Fallback sul traduttore di base per "
                     f"{len(missing)} blocchi")
            try:
                texts = self.fallback([u.text for u in missing])
                for unit, text in zip(missing, texts):
                    ready[unit.id] = text
            except Exception as exc:
                logger.error(f"Anche il fallback è fallito: {exc}")

        self.stats["fallback_blocks"] += len(ready)
        for unit in units:
            if not ready.get(unit.id, "").strip():
                self.stats["unresolved"] += 1
                ready[unit.id] = ""
        return ready
