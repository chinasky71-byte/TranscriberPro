"""
Translator - MULTI-MODEL ARCHITECTURE (NLLB + LLM locale + Claude API)
File: core/translator.py

VERSIONE: v6.0 - INTEGRAZIONE CLAUDE API

NUOVO v6.0:
✅ ClaudeTranslator - traduzione cloud-based con API Anthropic
✅ Zero requisiti GPU per Claude (cloud processing)
✅ Batch processing intelligente (4 sottotitoli/chiamata)
✅ Gestione rate limits con retry exponential backoff
✅ Uso contesto TMDB (sinossi) per traduzioni contestuali
✅ Supporto 50+ lingue con qualità superiore
✅ Factory get_translator aggiornata per selezione dinamica
✅ Config aggiornato con claude_api_key e validazione

VERSIONE: v5.4 - FIX ALLUCINAZIONI E RIPETIZIONI DEL RAMO LLM
(Riscrittura completa della generazione LLM con parametri anti-ripetizione
e controlli di qualità per eliminare allucinazioni e ripetizioni infinite)

CORREZIONI v5.4:
✅ FIX CRITICO: Parametri anti-ripetizione
   - repetition_penalty=1.2 per penalizzare ripetizioni
   - no_repeat_ngram_size=3 per impedire ripetizioni di trigrammi
   - TEMPERATURE ridotto a 0.3 per output più deterministico
   - MAX_NEW_TOKENS ridotto a 150 (più appropriato per sottotitoli)
✅ FIX CRITICO: Controlli di qualità output
   - Rilevamento ripetizioni eccessive (pattern ripetuto >3 volte)
   - Controllo lunghezza anomala (>3x originale)
   - Fallback su testo originale per output problematici
✅ MIGLIORAMENTO: Prompt semplificato e più diretto
✅ MIGLIORAMENTO: early_stopping=True per fermare alla generazione EOS
✅ MIGLIORAMENTO: Batch size ridotto a 8 per maggiore stabilità

CORREZIONI v5.3:
✅ FIX CRITICO: Corretta estrazione traduzione in _run_translation()
   - Estrae solo i token generati dal modello (outputs[:, input_length:])
   - Elimina il metodo fragile output.replace(prompt, '')

FUNZIONALITÀ v5.2:
✅ Impedita l'invio di stringhe vuote/solo contenuti mascherati
✅ Controllo esplicito allucinazione ("# non lo so #") con fallback
✅ Logica di copia dell'originale gestita robustamente
✅ Caricamento token HuggingFace per i modelli gated
"""
import logging
import torch
import re
import time
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Dict, Any
from abc import ABC, abstractmethod
# NOTE: È necessario installare bitsandbytes e accelerate per la quantizzazione
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM, BitsAndBytesConfig, AutoConfig
from threading import Lock
from huggingface_hub import snapshot_download
# Install with: pip install bitsandbytes accelerate anthropic

# Anthropic API per Claude Translator
try:
    from anthropic import Anthropic, APIError, RateLimitError, APIConnectionError
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from openai import OpenAI as OpenAIClient, RateLimitError as OpenAIRateLimitError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# setup_logger (non logging.getLogger nudo): senza handler esplicito questo
# logger non scrive nel file di sessione condiviso — misurato dopo che una
# traduzione con blocchi rimasti in inglese non aveva LASCIATO TRACCIA nel
# file di log pur avendo chiamato logger.warning() più volte (core.translator
# non compariva mai fra i logger attivi nel file). setup_logger attacca
# l'handler-file condiviso al NOME passato, logging.getLogger no.
from utils.logger import setup_logger
from utils.translations import tr
logger = setup_logger(__name__)

# --- MODIFICA v5.2: Importa get_config per caricare il token ---
try:
    from utils.config import get_config
except ImportError:
    # Fallback nel caso in cui il file venga eseguito da solo
    logger.warning("Impossibile importare 'utils.config'. Il caricamento di modelli gated fallirà.")
    get_config = None
# --- FINE MODIFICA ---


# ============================================================================
# BASE TRANSLATOR ABSTRACT CLASS
# ============================================================================

SRT_SUBTITLE = Tuple[int, str, str, str]  # (index, start_time, end_time, text)


class BaseTranslator(ABC):
    """
    Classe base astratta per tutti i traduttori
    
    Definisce l'interfaccia comune che tutti i traduttori devono implementare.
    """
    
    # Mappa codici lingua ISO 639-2/1 → codici specifici del modello
    LANGUAGE_CODES: Dict[str, str] = {}
    
    def __init__(self, log_callback: Optional[Callable] = None, context: Optional[str] = None,
                 glossary: Optional[Dict[str, str]] = None):
        """
        Inizializza il traduttore

        Args:
            log_callback: Callback opzionale per logging verso GUI
            context: Contesto opzionale (es. sinossi film/episodio) per migliorare la traduzione
            glossary: Resa italiana fissa per termini ricorrenti della serie
                (es. {"Knight Runner": "Runner dei Cavalieri"}) — vedi core/glossary.py
        """
        self.log_callback = log_callback
        self.use_gpu = torch.cuda.is_available()
        self.device = 'cuda' if self.use_gpu else 'cpu'
        self.context = context
        self.glossary = glossary or {}

        # Prepara contesto troncato se fornito
        self._prepared_context = None
        if context and context.strip():
            # Limita a ~120 token (circa 500 caratteri) per non saturare MAX_LENGTH
            truncated = context[:500].strip()
            if len(context) > 500:
                truncated += "..."
            self._prepared_context = f"[CONTEXT: {truncated}]\n"
    
    def log(self, message: str):
        """Helper per logging sia su logger che su callback GUI"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def set_log_callback(self, callback: Optional[Callable]):
        """
        Imposta callback per logging verso GUI
        
        Args:
            callback: Funzione callback che riceve stringhe di log
        """
        self.log_callback = callback
        logger.debug(f"{self.__class__.__name__}: Log callback impostato")

    # ------------------------------------------------------------------
    # Criterio di successo della traduzione
    #
    # `translate_file` storicamente ritornava True appena riusciva a
    # scrivere il file, anche se OGNI batch era stato saltato per un errore
    # e i blocchi erano stati rimessi in lingua originale (falso positivo
    # osservato su AMD: HIP error su tutti i batch, 41/46 righe in inglese,
    # exit 0 e .it.srt salvato come se fosse tradotto).
    #
    # Qui il successo richiede che i blocchi rimasti nella lingua sorgente
    # non superino `translation_max_untranslated_pct` (default 80%).
    # ------------------------------------------------------------------
    DEFAULT_MAX_UNTRANSLATED_PCT = 80.0

    # Errori GPU/sistemici: non sono "una riga sbagliata", il batch
    # successivo fallira' allo stesso modo. Meglio fermarsi subito e
    # lasciare alla pipeline il ripiego sul file in lingua originale.
    _FATAL_GPU_ERROR_MARKERS = (
        'hip error', 'cuda error', 'invalid device function',
        'device-side assert', 'no kernel image', 'hipblas', 'miopen',
        'cublas', 'gpu memoria insufficiente',
    )

    @classmethod
    def _is_fatal_gpu_error(cls, exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(marker in msg for marker in cls._FATAL_GPU_ERROR_MARKERS)

    def _max_untranslated_pct(self) -> float:
        """Soglia configurata, sempre in [0, 100]."""
        try:
            from utils.config import get_config
            value = float(get_config().get(
                'translation_max_untranslated_pct',
                self.DEFAULT_MAX_UNTRANSLATED_PCT))
        except Exception:
            value = self.DEFAULT_MAX_UNTRANSLATED_PCT
        return min(100.0, max(0.0, value))

    def _translation_exceeds_error_budget(self, untranslated: int,
                                          total: int) -> bool:
        """True se troppi blocchi sono rimasti nella lingua sorgente.

        Args:
            untranslated: blocchi ancora identici al sorgente (audit L4).
            total: blocchi totali del file SRT.
        """
        total = max(1, int(total))
        pct = 100.0 * int(untranslated) / total
        limit = self._max_untranslated_pct()
        if pct > limit:
            self.log(tr('tl_translation_failed_untranslated_over_threshold').format(
                n=int(untranslated), total=total, pct=pct, limit=limit))
            return True
        return False
    
    @abstractmethod
    def translate_file(self, input_path: Path, output_path: Path, 
                      src_lang: str, tgt_lang: str, context: Optional[str] = None) -> bool:
        """
        Traduce file SRT da lingua sorgente a lingua target
        
        Args:
            input_path: Path del file SRT da tradurre
            output_path: Path del file SRT tradotto
            src_lang: Codice lingua sorgente (ISO 639-2, es: 'eng')
            tgt_lang: Codice lingua target (ISO 639-2, es: 'ita')
            context: Contesto opzionale per migliorare traduzione
            
        Returns:
            True se successo, False altrimenti
        """
        pass
    
    @abstractmethod
    def cleanup(self):
        """
        Pulizia risorse e memoria GPU
        """
        pass
    
    def _parse_srt(self, srt_path: Path) -> List[SRT_SUBTITLE]:
        """
        Parsing file SRT migliorato per gestione multilinea
        
        Args:
            srt_path: Path del file SRT
            
        Returns:
            Lista di tuple (index, start_time, end_time, text)
        """
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            subtitles = []
            # Pattern SRT: numero, timestamp, testo (multilinea)
            pattern = r'(\d+)\s*\n([\d:,]+)\s*-->\s*([\d:,]+)\s*\n((?:.*\n?)+?)(?=\n\d+\s*\n|$)'
            
            for match in re.finditer(pattern, content, re.MULTILINE):
                index = int(match.group(1))
                start_time = match.group(2).strip()
                end_time = match.group(3).strip()
                text = match.group(4).strip()
                
                if text:
                    subtitles.append((index, start_time, end_time, text))
            
            return subtitles
            
        except Exception as e:
            logger.error(f"Errore parsing SRT: {e}")
            return []
    
    def _extract_dash_flags(
        self, subtitles: List[SRT_SUBTITLE]
    ) -> Tuple[List[SRT_SUBTITLE], Dict[int, List[bool]]]:
        """Rimuove i prefissi '- ' dai testi e restituisce i flags per il restore.

        Il '- ' è formattazione (marcatore cambio parlante da diarizzazione),
        non contenuto da tradurre. I modelli MT (specialmente NLLB) possono
        non preservarlo → va estratto prima e ripristinato dopo la traduzione.
        """
        dash_flags: Dict[int, List[bool]] = {}
        clean: List[SRT_SUBTITLE] = []
        for idx, start, end, text in subtitles:
            lines = text.split('\n')
            flags = []
            clean_lines = []
            for line in lines:
                if line.startswith('- '):
                    flags.append(True)
                    clean_lines.append(line[2:])
                else:
                    flags.append(False)
                    clean_lines.append(line)
            dash_flags[idx] = flags
            clean.append((idx, start, end, '\n'.join(clean_lines)))
        return clean, dash_flags

    def _generate_srt(self, subtitles: List[SRT_SUBTITLE],
                      dash_flags: Dict[int, List[bool]] = None) -> str:
        """
        Genera contenuto SRT da lista sottotitoli

        Args:
            subtitles: Lista di tuple (index, start_time, end_time, text)
            dash_flags: Flags opzionali per ripristinare prefissi '- ' (diarizzazione)

        Returns:
            Stringa contenuto SRT formattato
        """
        restored_texts: List[str] = []
        for index, start, end, text in subtitles:
            if dash_flags and index in dash_flags:
                lines = text.split('\n')
                flags = dash_flags[index]
                restored = []
                for i, line in enumerate(lines):
                    has_dash = flags[i] if i < len(flags) else False
                    restored.append(f"- {line}" if has_dash and line.strip() else line)
                text = '\n'.join(restored)
            restored_texts.append(text)

        restored_texts = self._polish(restored_texts)

        srt_content = []
        for (index, start, end, _), text in zip(subtitles, restored_texts):
            srt_content.append(f"{index}")
            srt_content.append(f"{start} --> {end}")
            srt_content.append(text)
            srt_content.append("")

        return "\n".join(srt_content)

    # Le convenzioni tipografiche del sottotitolo italiano si applicano
    # all'uscita di QUALUNQUE motore: disattivabile per classe se un motore
    # dovesse produrre un formato che non va toccato.
    POSTPROCESS_OUTPUT = True

    def _polish(self, texts: List[str]) -> List[str]:
        """Rifinitura tipografica dell'SRT tradotto.

        Colma un buco reale della pipeline: `SubtitleFormatter` viene invocato
        allo STEP 4.5, cioè PRIMA della traduzione, e dopo non ricontrolla
        nessuno. L'italiano è mediamente il 15-20% più lungo dell'inglese e su
        300 blocchi misurati il 59% delle righe usciva oltre i 42 caratteri:
        applicando queste regole scende sotto il 10%.

        Sono tutte deterministiche — ellissi, punteggiatura doppia, marcatori
        di continuazione tra blocchi, divisione delle righe a piramide — e non
        dipendono dalla lingua di partenza né dal motore.
        """
        if not self.POSTPROCESS_OUTPUT or not texts:
            return texts
        try:
            from core.llm_subtitle_translator import postprocess
            polished = postprocess.process(
                {i: t for i, t in enumerate(texts)},
                order=list(range(len(texts))),
            )
            return [polished.get(i, t) for i, t in enumerate(texts)]
        except Exception as exc:
            logger.warning(f"Rifinitura tipografica saltata: {exc}")
            return texts

    def _mask_text(self, text: str, model_prefix: str) -> Tuple[str, Dict[str, str], bool]:
        """
        Maschera il testo per la traduzione, preservando blocchi specifici.

        Logica:
        - I blocchi tra ♪...♪ sono *sempre* mascherati e preservati (copia esatta).
        - I blocchi tra [...] non vengono mascherati, ma sono gestiti dalla traduzione
          del modello (verranno tradotti all'interno delle quadre).

        Args:
            text: Testo del sottotitolo originale.
            model_prefix: Prefisso unico per il placeholder (e.g., 'NLLB' o 'LLM').

        Returns:
            Tuple: (Testo da tradurre, Mappa dei placeholder {placeholder: contenuto originale}, Solo contenuti mascherati)
        """
        placeholders = {}
        
        # 1. Maschera il testo tra ♪...♪ per impedirne la traduzione e garantirne la copia esatta.
        def masking_replacer(match):
            index = len(placeholders)
            # Chiave del dizionario SENZA padding: se il placeholder finisce
            # per essere l'unico contenuto della riga, il `.strip()` finale
            # di questo metodo toglie gli spazi ai bordi del testo — una
            # chiave con gli spazi inclusi non farebbe più match in
            # _unmask_text (replace() cerca una sottostringa, quindi una
            # chiave "nuda" funziona sia in mezzo al testo sia da sola).
            #
            # Forma "<MUSIC0>" (una sola coppia di parentesi angolari, corpo
            # alfanumerico) e non "<[PREFIX_MUSIC_PRESERVE_0]>": misurato su
            # NLLB reale (core/translator.py, glossario "Ark"/"The Ark" su
            # The Ark) che il secondo formato — parentesi quadre e
            # underscore multipli — viene quasi sempre alterato dal
            # tokenizer/decoder durante la generazione (troncato o perso),
            # mentre il primo sopravvive intatto nella grande maggioranza
            # dei casi reali. _unmask_text_checked resta comunque la rete di
            # sicurezza per i casi residui.
            token = f"<MUSIC{index}>"
            placeholders[token] = match.group(0)
            return f" {token} "

        # Regex (non-greedy, DOTALL) che cattura tutto tra le due note musicali
        masked_text = re.sub(r'♪.*?♪', masking_replacer, text, flags=re.DOTALL)

        # Stessa protezione per la convenzione statunitense, che al posto della
        # nota musicale usa l'asterisco: '* Every day it's a-getting closer *'.
        # Le liriche seguono il trattamento di ♪ — si preservano tali e quali,
        # non si traducono.
        #
        # Gli spazi nel pattern non sono decorativi: l'asterisco serve ANCHE a
        # censurare il turpiloquio nella fonte ('ca***', 'fanc***'), e un
        # pattern piu' largo spezzerebbe quelle parole a meta'. Richiedere uno
        # spazio subito dopo l'asterisco di apertura e subito prima di quello
        # di chiusura separa i due usi: una lirica ha le spaziature, una parola
        # censurata no.
        masked_text = re.sub(r'\*\s.*?\s\*', masking_replacer, masked_text,
                             flags=re.DOTALL)
        
        # 2. Verifica se il testo rimanente, una volta ripulito dagli spazi, è vuoto.
        text_without_placeholders = masked_text
        for placeholder in placeholders:
            text_without_placeholders = text_without_placeholders.replace(placeholder, ' ')

        # Anche i placeholder del glossario (_mask_glossary, applicato PRIMA
        # di questo metodo) vanno tolti dal controllo, anche se non sono nel
        # dizionario locale `placeholders`: senza questo, una riga fatta
        # SOLO di un termine di glossario ("Knight Runner") verrebbe letta
        # come "ha lettere" (il placeholder stesso ne contiene, es.
        # "GLOSS0") e mandata al modello invece di passare intatta.
        text_without_placeholders = re.sub(r'<(?:MUSIC|GLOSS)\d+>', ' ',
                                           text_without_placeholders)

        text_without_placeholders_cleaned = re.sub(r'^-', '', text_without_placeholders).strip()

        # Un blocco senza NESSUNA lettera non ha niente da tradurre: e' un
        # marcatore, non una battuta. Va lasciato passare intatto.
        #
        # Non basta controllare che sia vuoto. Le tracce statunitensi usano
        # spesso l'asterisco al posto della nota musicale: '**' significa
        # "musica senza parole". Mandato a un LLM, quel blocco non viene
        # copiato ma ALLUCINATO — su Brilliant Minds S02E01 tutti e 48 i
        # marcatori '**' sono diventati frasi inventate, 26 volte la stessa
        # ("It's not you, it's me."), perche' a input identico il modello
        # produce sempre la stessa invenzione.
        #
        # La regola guarda l'assenza di lettere invece di elencare i simboli:
        # copre '**', '♪♪', '###', '-- --' e qualunque altra convenzione senza
        # doverle prevedere una per una.
        has_letters = re.search(r'[^\W\d_]', text_without_placeholders_cleaned,
                                flags=re.UNICODE) is not None

        only_masked = (text_without_placeholders_cleaned == "" or not has_letters)

        # 3. Pulizia finale del testo che va al modello
        final_text = masked_text.strip()
        
        return final_text, placeholders, only_masked

    def _unmask_text_checked(self, translated_text: str,
                             placeholders_map: Dict[str, str]) -> Tuple[str, bool]:
        """
        Come `_unmask_text`, ma verifica che OGNI placeholder fosse
        davvero presente prima di sostituirlo — ritorna (testo, ok).

        Va usato quando `translated_text` è uscito da una generazione VERA
        del modello (non dal ramo skip, che non tocca mai il testo). Misurato
        su NLLB reale (glossario "Ark"/"The Ark" su The Ark): un
        encoder-decoder di traduzione non ha nessuna garanzia di riprodurre
        verbatim un token sintetico che non riconosce — a volte lo tronca
        ("<[NLLB_GLOSS_0]>" → "<NLLB_GLOSS_0]>", `_unmask_text` non trova più
        la chiave e il placeholder rotto resta visibile in output), a volte
        lo fa sparire senza lasciare traccia (perdita di contenuto silenziosa,
        ancora peggio). `ok=False` in entrambi i casi: il chiamante deve
        scartare `translated_text` e ripiegare su qualcosa di sicuro, mai
        mostrare il risultato di questo metodo quando `ok` è falso.
        """
        result = translated_text
        ok = True
        for placeholder, original_content in placeholders_map.items():
            if placeholder not in result:
                ok = False
                continue
            result = result.replace(placeholder, original_content)
        return result, ok

    def _unmask_text(self, translated_text: str, placeholders_map: Dict[str, str]) -> str:
        """
        Re-inserisce il contenuto originale non tradotto dai placeholder.
        """
        post_processed_result = translated_text

        for placeholder, original_content in placeholders_map.items():
            post_processed_result = post_processed_result.replace(placeholder, original_content)

        return post_processed_result.strip()

    _PLACEHOLDER_RE = re.compile(r'<([A-Za-z]+)(\d+)>')

    def _unmask_tolerant(self, translated_text: str,
                         placeholders_map: Dict[str, str]) -> Tuple[str, bool, int]:
        """Come `_unmask_text_checked`, ma prima prova a RIPARARE i placeholder
        che il modello ha storpiato, invece di arrendersi al primo mismatch
        esatto.

        Misurato su NLLB e su TranslateGemma reali (glossario "Ark"/"The Ark"
        su The Ark): un placeholder sintetico come `<GLOSS0>` può uscire con
        spazi aggiunti (`< GLOSS0 >`), maiuscole cambiate (`<gloss0>`), o una
        delle due parentesi perse (`<GLOSS0`, `GLOSS0>`, `GLOSS0`). Prima di
        dichiarare fallimento si cercano queste varianti, in ordine dal più
        vicino al placeholder originale al più permissivo.

        Ritorna (testo, ok, numero_di_placeholder_riparati). `ok=False` solo
        se ALMENO un placeholder non è recuperabile in nessuna forma — stesso
        contratto di `_unmask_text_checked`: il chiamante non deve mai
        mostrare `testo` quando `ok` è falso.
        """
        result = translated_text
        ok = True
        repaired = 0

        # Prima MUSIC, poi indice decrescente.
        #
        # Indice decrescente: senza questo <GLOSS1> farebbe match dentro
        # <GLOSS10> (o dentro la sua forma riparata "GLOSS10") lasciando lo
        # zero finale orfano nel testo.
        #
        # MUSIC prima di GLOSS perché i due mascheramenti sono ANNIDATI:
        # `_mask_glossary` gira per primo, quindi quando `_mask_text` cattura
        # un blocco ♪...♪ si porta dentro i placeholder di glossario che ci
        # stanno in mezzo. Un <GLOSS1> dentro il contenuto di <MUSIC0> non
        # esiste ancora nel testo tradotto: con il solo indice decrescente
        # veniva cercato PRIMA che <MUSIC0> lo facesse riaffiorare, non
        # trovato, e dichiarato irrecuperabile (ok=False) — un blocco tradotto
        # perfettamente finiva in L2, che ritraduce SENZA mascheramento e
        # quindi perde la garanzia del glossario. Scatta con un solo verso
        # cantato che nomina un termine, es. "Garnet!\n♪ Sail on, Ark ♪".
        # L'annidamento è a senso unico (la resa italiana di un termine non
        # può contenere un <MUSIC*>), quindi basta l'ordine, non serve un
        # secondo giro di risoluzione.
        def _idx(item):
            key, _ = item
            m = self._PLACEHOLDER_RE.match(key)
            if not m:
                return (1, 0)
            return (0 if m.group(1).upper() == 'MUSIC' else 1,
                    -int(m.group(2)))

        for placeholder, original_content in sorted(
                placeholders_map.items(), key=_idx):
            if placeholder in result:
                result = result.replace(placeholder, original_content)
                continue

            m = self._PLACEHOLDER_RE.match(placeholder)
            if not m:
                ok = False
                continue
            prefix, num = m.group(1), m.group(2)
            candidates = [
                rf'<\s*{prefix}\s*{num}\s*>',   # spazi interni
                rf'<{prefix}{num}(?!\d)',       # parentesi di chiusura persa
                rf'{prefix}{num}>',             # parentesi di apertura persa
                rf'\b{prefix}\s*{num}\b',       # entrambe perse
            ]
            fixed = False
            for pattern in candidates:
                rx = re.compile(pattern, re.IGNORECASE)
                new_result, n = rx.subn(original_content, result, count=1)
                if n:
                    result = new_result
                    repaired += 1
                    fixed = True
                    break
            if not fixed:
                ok = False

        return result, ok, repaired

    # Solo lettere/cifre, minuscolo: azzera differenze di spaziatura,
    # punteggiatura e virgolette che il ri-avvolgimento tipografico introduce
    # senza cambiare il contenuto (es. `on "Ark 15"` -> `on" Ark 15"`).
    _AUDIT_NORM_RE = re.compile(r'[^0-9a-zàèéìòóù]')

    def _audit_norm(self, s: str) -> str:
        return self._AUDIT_NORM_RE.sub('', (s or '').lower())

    _AUDIT_WORD_RE = re.compile(r'[A-Za-zÀ-ÿ]+')

    def _is_untranslated(self, output_text: str, source_text: str) -> bool:
        """Rete di sicurezza indipendente da QUALUNQUE meccanismo di
        mascheramento/recupero: confronta il risultato con il sorgente
        inglese per identità normalizzata, non per come si è arrivati lì.

        Non è `_looks_english` del validatore LLM (richiede ≥4 parole e ≥2
        marcatori inglesi — su "It was an Ark." vede un solo marcatore e non
        scatta).

        Doppia soglia, non una sola: la prima versione usava solo la
        lunghezza normalizzata (≥12 caratteri) e falliva su frasi vere ma
        fatte di parole corte — "It was an Ark." normalizza a 10 caratteri,
        "Oh, God." a 5 — restando SOTTO la soglia e quindi invisibili
        all'audit proprio sui casi reali che l'ha motivato (scoperto dal
        test di regressione su The Ark S03E06, non a priori). Il conteggio
        parole (≥2) è il segnale che protegge dai falsi positivi su
        interiezioni/nomi corti ("Ok.", "Eva!", "219.", che restano
        legittimamente identici in italiano), mentre la lunghezza minima
        (≥5) protegge dai casi degeneri (due token cortissimi). Le due
        soglie insieme, non l'una o l'altra: verificato che coprono tutti i
        24 blocchi noti rimasti inglesi in quell'episodio, zero falsi
        positivi sul resto del file.
        """
        norm_src = self._audit_norm(source_text)
        if len(norm_src) < 5:
            return False
        if len(self._AUDIT_WORD_RE.findall(source_text or "")) < 2:
            return False
        return self._audit_norm(output_text) == norm_src

    def _audit_untranslated(self, output_blocks: Dict[int, str],
                            source_blocks: Dict[int, str],
                            skip_ids=()) -> List[int]:
        """Applica `_is_untranslated` a un file intero. `skip_ids` sono i
        blocchi passthrough (marcatori musicali, righe di solo glossario):
        identici al sorgente per progetto, non un fallimento."""
        skip = set(skip_ids)
        flagged = [idx for idx, out in output_blocks.items()
                  if idx not in skip
                  and self._is_untranslated(out, source_blocks.get(idx, ""))]
        return sorted(flagged)

    def _log_audit(self, output_blocks: Dict[int, str],
                   source_blocks: Dict[int, str], skip_ids=(),
                   counters: Optional[Dict[str, int]] = None) -> List[int]:
        """Chiude ogni `translate_file`: se qualche blocco è rimasto
        indistinguibile dall'inglese, qualunque sia la causa (nota o futura,
        prevista o no), lo dice a schermo. Non è un ripiego, è un allarme —
        con L0-L3 attivi deve restare a zero."""
        flagged = self._audit_untranslated(output_blocks, source_blocks, skip_ids)
        if counters:
            parts = " | ".join(f"{k}: {v}" for k, v in counters.items())
            self.log(tr('tl_translation_completed_residual_source_language').format(parts=parts, n=len(flagged)))
        if flagged:
            preview = ', '.join(str(i) for i in flagged[:15])
            more = f" (+{len(flagged) - 15} altri)" if len(flagged) > 15 else ""
            self.log(tr('tl_warning_blocks_are_still_in').format(n=len(flagged), preview=preview, more=more))
        return flagged

    def _apply_glossary_posthoc(self, italian: str, source_en: str) -> str:
        """Applica il glossario A POSTERIORI su una traduzione già prodotta
        SENZA mascheramento (nessun placeholder sintetico da riprodurre: la
        classe di bug che ha originato questo metodo, quindi, non può
        ripresentarsi qui).

        Best-effort per costruzione: sostituisce un termine solo se è
        sopravvissuto letteralmente nell'inglese sorgente E la resa non è
        già presente nell'italiano prodotto. Se il modello ha già tradotto il
        termine a modo suo, la garanzia del glossario decade su quel singolo
        termine — mai sull'intera frase, che è la scelta giusta: si degrada
        la resa di un nome proprio, non si sostituisce una frase buona con
        l'originale inglese.
        """
        if not self.glossary or not italian:
            return italian
        result = italian
        for term in sorted(self.glossary, key=len, reverse=True):
            rendering = self.glossary[term]
            if term.lower() not in source_en.lower():
                continue
            pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
            # La condizione è "il termine INGLESE è ancora lì", non "la resa
            # non c'è". Fermarsi alla presenza della resa lasciava inglese in
            # mezzo all'italiano ogni volta che il modello aveva reso una
            # occorrenza e non l'altra ("Era un'Arca. Quale Ark?"): la resa
            # c'era, il termine inglese pure, e il metodo non faceva nulla.
            if not pattern.search(result):
                continue

            def _repl(m, _rendering=rendering, _text=result):
                # Maiuscola a inizio riga o dopo punteggiatura forte: la resa
                # segue la capitalizzazione del punto in cui viene inserita,
                # non quella (spesso fissa) della voce di glossario.
                if (m.start() == 0
                        or _text[:m.start()].rstrip()[-1:] in ('.', '!', '?', '')):
                    return _rendering[:1].upper() + _rendering[1:]
                return _rendering
            # TUTTE le occorrenze, non solo la prima: con `count=1` una riga
            # che nomina due volte lo stesso termine ne teneva una in inglese.
            result = pattern.sub(_repl, result)

        # Normalizzazione delle MAIUSCOLE su una resa già presente.
        #
        # È l'unica correzione di glossario a rischio grammaticale ZERO:
        # cambia le maiuscole di una parola già corretta, non tocca articoli
        # né accordi. Si applica solo a un'occorrenza TUTTA MAIUSCOLA di una
        # resa che maiuscola non è ("DRAGONE" dove il glossario dice
        # "Dragone"): così non può mai abbassare la maiuscola legittima di
        # inizio frase, che tutta maiuscola non è mai.
        #
        # Misurato sul banco del serbatoio (39 righe, 61 occorrenze di
        # glossario): è il modo di alzare la conformità di NLLB senza
        # ricorrere al mascheramento, che invece impone la resa ma rompe
        # l'accordo grammaticale attorno al termine.
        for term, rendering in self.glossary.items():
            if rendering.isupper() or term.lower() not in source_en.lower():
                continue
            rx = re.compile(r'\b' + re.escape(rendering) + r'\b', re.IGNORECASE)
            result = rx.sub(
                lambda m, _r=rendering: _r if m.group(0).isupper() else m.group(0),
                result)
        return result

    def _mask_glossary(self, text: str, model_prefix: str,
                       glossary: Dict[str, str]) -> Tuple[str, Dict[str, str]]:
        """
        Sostituisce nel testo SORGENTE (inglese) i termini del glossario con
        placeholder che il modello non tradurrà — esattamente il meccanismo
        di `_mask_text` per i marcatori musicali, ma la mappa restituita
        contiene la RESA ITALIANA FISSA, non il testo originale: `_unmask_text`
        (invariato) la reinserisce al posto del placeholder dopo la
        traduzione, garantendo la resa per costruzione invece di sperare che
        il modello la azzecchi.

        Va chiamato PRIMA di `_mask_text` sullo stesso testo, e le due mappe
        di placeholder vanno unite (chiavi diverse per prefisso, mai in
        collisione: `_MUSIC_PRESERVE_` vs `_GLOSS_`).

        Match case-insensitive, parola intera (`\\b`); termini più lunghi
        prima, così un termine che ne contiene un altro ("Silhouette Knight"
        vs "Knight") non viene spezzato a metà.
        """
        placeholders: Dict[str, str] = {}
        if not glossary:
            return text, placeholders

        masked_text = text
        # Padding `" {token} "` SOLO su NLLB. Il pattern di ricerca è ancorato
        # a `\b` su entrambi i lati, quindi il carattere adiacente al termine
        # nel sorgente NON è mai un carattere di parola: il padding non separa
        # niente che non fosse già separato, RADDOPPIA uno spazio che c'era
        # già ("you,  <GLOSS0>") o ne INVENTA uno dove l'autore non l'aveva
        # ("Mornin' Garnet" → "Mornin' <GLOSS0>" va bene, ma "Garnet's" →
        # "<GLOSS0> 's" no, e '"Ark 16"' → '" <GLOSS0> 16"' nemmeno).
        # MISURATO su TranslateGemma-12B (The Ark S03E08, "I trusted you,
        # Garnet."): con lo spazio spurio prima del punto il modello scarta
        # silenziosamente il placeholder dalla generazione ("Mi fidavo di
        # te.", senza resa), mentre con la frase pulita ("I trusted you,
        # <GLOSS0>.") lo riproduce intatto. Il placeholder scartato fa fallire
        # `_unmask_tolerant`, il blocco finisce nel recupero L2 (ritraduzione
        # SENZA mascheramento) dove `_apply_glossary_posthoc` non protegge le
        # identità che coincidono con una parola inglese comune — cioè
        # riapre esattamente il bug "Garnet"→"Granato" che il mascheramento
        # delle identità (sotto) esiste per chiudere.
        #
        # Si toglie il padding alla RADICE invece di ripulirlo a valle con
        # regex: qualunque ripulitura deve indovinare se una virgoletta o un
        # apostrofo adiacente apre, chiude o è una contrazione dialettale
        # ("Mornin' Garnet" e "Garnet's ship" chiedono il contrario l'uno
        # dell'altro), mentre non aggiungere lo spazio conserva per
        # costruzione la spaziatura dell'autore, ellissi "…" e virgolette
        # tipografiche comprese, senza elencarle.
        #
        # Su NLLB il padding resta: la spaziatura a token isolato è la stessa
        # condizione in cui è stata misurata la sopravvivenza del placeholder
        # su quel tokenizer word-level (attaccare punteggiatura al token può
        # alterarne la segmentazione in subword). Lì non è stato misurato
        # nulla di nuovo, quindi non si cambia nulla.
        pad = (model_prefix == "NLLB")
        for term in sorted(glossary, key=len, reverse=True):
            rendering = glossary[term]

            # Termini a resa IDENTITÀ (es. "FTL"->"FTL", "Garnet"->"Garnet"):
            # il placeholder non compra nulla — il modello dovrebbe comunque
            # lasciare il termine invariato — ma paga per intero il rischio di
            # essere storpiato dal modello e mai riconosciuto in unmask.
            # Misurato su The Ark S03E06 CON NLLB: 8 dei 24 blocchi rimasti in
            # inglese contenevano SOLO un termine identità mascherato — NLLB è
            # un decoder word-level che non sa produrre una frase fluente
            # intorno a un token opaco (stesso sintomo del serbatoio via NLLB,
            # vedi `_reservoir_via_nllb`). Per NLLB si lascia quindi il testo
            # sorgente intatto (il modello traduce intorno); la sopravvivenza
            # del termine è verificata a valle da
            # `_apply_glossary_posthoc`/`_audit_untranslated`, non qui.
            #
            # Il motore LLM (chat-template, es. TranslateGemma) non è lo
            # stesso caso: i termini NON identità del glossario sono già
            # mascherati su questo stesso path e sopravvivono intatti (non è
            # mai stata misurata una regressione lì). Senza questa eccezione,
            # un'identità che coincide con una parola inglese comune (es.
            # "Garnet", anche il nome di una pietra) non viene mai mascherata
            # e può essere tradotta come nome comune ("Garnet" → "Granato",
            # The Ark S03E08) — errore che il controllo a valle non può
            # correggere perché cerca il termine INGLESE ancora presente
            # nell'italiano, non una resa sbagliata plausibile. Si mascherano
            # quindi le identità per tutti i motori tranne NLLB.
            if model_prefix == "NLLB" and term.strip().lower() == rendering.strip().lower():
                continue

            # NIENTE tolleranza automatica al plurale: provata su Knight's &
            # Magic (aggiungeva "'?s?" al pattern, mascherando anche "Knight
            # Runners") ma ritirata dopo il pilota su "The Ark" — lì il
            # plurale italiano di "Ark" è "Arche", non "Arca"+s: la
            # tolleranza automatica avrebbe imposto la resa singolare anche
            # alle occorrenze plurali già corrette da NLLB per conto suo,
            # introducendo una regressione. Quando plurale e singolare
            # condividono davvero la stessa resa italiana (tipico dei nomi
            # tecnici composti, es. "Knight Runners" → ancora "Runner dei
            # Cavalieri"), il curatore aggiunge una seconda voce esplicita
            # nel glossario invece di farla assumere al codice.
            pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)

            def _replacer(match, _rendering=rendering):
                index = len(placeholders)
                # Chiave senza padding, stesso motivo di _mask_text: se il
                # placeholder resta l'unico contenuto della riga, lo strip()
                # a valle in _mask_text toglierebbe gli spazi ai bordi.
                # Forma "<GLOSS0>", non "<[PREFIX_GLOSS_0]>" — stessa misura
                # empirica su NLLB reale di masking_replacer in _mask_text:
                # il formato con parentesi quadre/underscore multipli
                # sopravvive raramente intatto alla generazione.
                token = f"<GLOSS{index}>"
                placeholders[token] = _rendering
                return f" {token} " if pad else token

            masked_text = pattern.sub(_replacer, masked_text)

        return masked_text, placeholders

    # ------------------------------------------------------------------
    # L3 — Serbatoio: ripiego finale condiviso da tutti i motori primari.
    # ------------------------------------------------------------------
    # Tetto di durata del subprocess del serbatoio. Generoso: comprende il
    # caricamento di un GGUF da ~9 GB più la generazione di qualche decina di
    # righe corte. Serve solo a garantire che un blocco duri un tempo finito.
    RESERVOIR_TIMEOUT_S = 1800

    # Motore di ripiego preferito da questa classe quando la config dice
    # 'auto'. Non può mai essere lo stesso del motore primario: il serbatoio
    # esiste per dare una SECONDA opinione, e richiamare il modello che ha già
    # fallito due volte (L1 e L2) non è un ripiego, è una ripetizione.
    RESERVOIR_DEFAULT = 'qwen'

    def _reservoir_engine_choice(self) -> str:
        try:
            from utils.config import get_config as _get_cfg
            choice = (_get_cfg().get_reservoir_engine() or 'auto').lower()
        except Exception:
            choice = 'auto'
        if choice not in ('qwen', 'nllb_ft'):
            choice = self.RESERVOIR_DEFAULT
        return choice

    def _reservoir_via_nllb(self, lines_payload: List[Dict[str, str]],
                            ) -> Dict[str, str]:
        """Serbatoio su NLLB fine-tuned, IN PROCESSO.

        Nessun subprocess, a differenza di Qwen: NLLB è transformers, lo
        stesso stack del motore primario, e `cleanup()` ha già liberato la
        VRAM prima di arrivare qui. Il subprocess serviva solo a llama-cpp,
        che alloca fuori dall'allocatore PyTorch.

        NIENTE mascheramento del glossario. Misurato sul banco del serbatoio:
        mascherare impone la resa (conformità 100%) ma il modello non può
        declinare articolo, genere ed elisione attorno a un token opaco, e
        produce «È il Federazione Orientale», «un risonanza magnetica», «e
        anche tenente Brice». La resa del glossario si applica dopo, con
        `_apply_glossary_posthoc`, che non tocca la struttura della frase.
        """
        base = NLLBFineTunedTranslator(self.log_callback)
        try:
            texts = [re.sub(r'\s*\n\s*', ' ', d["text"]).strip()
                     for d in lines_payload]
            out = base._run_translation(texts, 'eng_Latn', 'ita_Latn',
                                        add_context=False)
            return {d["id"]: (t or "").strip()
                    for d, t in zip(lines_payload, out)}
        except Exception as exc:
            logger.error(f"Serbatoio NLLB fallito: {exc}", exc_info=True)
            self.log(tr('tl_reservoir_nllb_failed').format(exc=exc))
            return {}
        finally:
            try:
                base.cleanup()
            except Exception:
                pass

    def _reservoir_translate(self, pending: Dict[int, str]) -> Dict[int, str]:
        """Ultimo livello di ripiego, in un unico swap a fine file.

        `pending`: {id: testo_inglese_originale NON mascherato} — tutto ciò
        che è sopravvissuto a L1 (unmask tollerante) e L2 (ritraduzione senza
        masking sul motore primario). Su The Ark S03E06 questo era il 3% dei
        blocchi (24/795): a questa scala uno swap di modello one-shot costa
        1-2 minuti sull'intera run, non i 30-50 minuti che costerebbe farlo
        blocco per blocco.

        Gira in `core/fallback_translate_cli.py`, subprocess isolato — stesso
        contratto di `core/gender_corrector_cli.py`: Qwen (llama-cpp-python)
        alloca la VRAM fuori dall'allocatore PyTorch di transformers, e su
        12 GB i due non convivono in modo affidabile in-process.

        Deduplica per testo sorgente normalizzato: nell'episodio di prova, per
        via di un loop temporale narrativo, i 24 blocchi erano solo 13-14
        frasi distinte ripetute — deduplicare dimezza il lavoro e garantisce
        che le ripetizioni escano tradotte in modo identico fra loro (la resa
        corretta per un loop).

        Ritorna {id: testo_italiano} solo per gli id risolti E validati; chi
        chiama decide cosa fare dei mancanti (L4 — inglese, ma rumoroso).
        """
        if not pending:
            return {}

        engine_choice = self._reservoir_engine_choice()
        model_path = ''
        n_gpu_layers = -1
        if engine_choice == 'qwen':
            try:
                from utils.config import get_config as _get_cfg
                model_path, n_gpu_layers = _get_cfg().get_fallback_translator_model(
                    getattr(self, 'llm_model_preference', None))
            except Exception as exc:
                self.log(tr('tl_reservoir_not_available_config').format(exc=exc))
                return {}
            if not model_path or not Path(model_path).exists():
                self.log(tr('tl_reservoir_not_available_no_fallback'))
                return {}

        # Deduplica: gruppo = stesso testo normalizzato. Rappresentante = id
        # più basso del gruppo, è l'unico che viaggia nel prompt.
        groups: Dict[str, List[int]] = {}
        rep_text: Dict[str, str] = {}
        for idx in sorted(pending):
            text = pending[idx]
            key = self._audit_norm(text) or f"__empty_{idx}"
            groups.setdefault(key, []).append(idx)
            rep_text.setdefault(key, text)

        lines_payload = [{"id": key, "text": rep_text[key]} for key in groups]

        # Solo i termini di glossario pertinenti alle righe da recuperare,
        # non l'intero glossario dello show: un prompt corto e mirato è più
        # affidabile di un elenco lungo per lo più irrilevante.
        relevant_glossary = {}
        if self.glossary:
            joined = " ".join(rep_text.values()).lower()
            relevant_glossary = {t: r for t, r in self.glossary.items()
                                 if t.lower() in joined}

        # --- ramo NLLB fine-tuned: in processo, nessun subprocess ---------
        if engine_choice == 'nllb_ft':
            self.log(tr('tl_distinct_sentences_blocks_to_the').format(n=len(lines_payload), n_2=len(pending)))
            try:
                self.cleanup()
            except Exception as exc:
                logger.debug(f"cleanup pre-serbatoio: {exc}")
            per_group = self._reservoir_via_nllb(lines_payload)
            return self._reservoir_fanout(groups, per_group, pending)

        # --- ramo Qwen: subprocess isolato (llama-cpp fuori da PyTorch) ---
        import json, subprocess, sys, tempfile, threading
        tmp_dir = Path(tempfile.mkdtemp(prefix="tp_reservoir_"))
        args_path = tmp_dir / "args.json"
        output_path = tmp_dir / "output.json"
        try:
            args_path.write_text(json.dumps({
                "lines": lines_payload,
                "glossary": relevant_glossary,
                "output_json": str(output_path),
                "model_path": model_path,
                "n_gpu_layers": n_gpu_layers,
            }, ensure_ascii=False), encoding='utf-8')

            project_root = Path(__file__).resolve().parent.parent
            env = __import__('os').environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'

            self.log(tr('tl_distinct_sentences_blocks_to_the_2').format(n=len(lines_payload), n_2=len(pending)))
            try:
                self.cleanup()
            except Exception as exc:
                logger.debug(f"cleanup pre-serbatoio: {exc}")

            # CREATE_NO_WINDOW: quando la traduzione gira dentro pipeline_cli
            # il monkeypatch di `_suppress_subprocess_windows` lo mette
            # già, ma questo metodo può essere invocato anche da un percorso
            # in-process (test, run manuali): senza il flag lampeggerebbe una
            # console. stdin su DEVNULL perché sotto pythonw.exe l'handle
            # ereditato non è valido e alcune librerie ci inciampano.
            popen_kwargs = dict(
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=str(project_root), env=env, text=True,
                encoding='utf-8', errors='replace', bufsize=1,
            )
            if sys.platform == 'win32':
                popen_kwargs['creationflags'] = getattr(
                    subprocess, 'CREATE_NO_WINDOW', 0)
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "core.fallback_translate_cli",
                     str(args_path)], **popen_kwargs)
            except Exception as exc:
                self.log(tr('tl_reservoir_start_failed').format(exc=exc))
                return {}

            def _drain_stderr(stream):
                try:
                    for eline in stream:
                        eline = eline.rstrip()
                        if eline:
                            logger.info(f"[reservoir-stderr] {eline}")
                except Exception:
                    pass

            threading.Thread(target=_drain_stderr, args=(proc.stderr,),
                             daemon=True).start()
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.log(f"   [Serbatoio] {line}")
            # Timeout obbligatorio: senza, un caricamento GGUF che non
            # ritorna (modello corrotto, GPU occupata da un altro processo)
            # bloccherebbe la pipeline per sempre e senza diagnosi. Stesso
            # tetto del selettore di genere (core/gender_corrector_v2.py).
            try:
                return_code = proc.wait(timeout=self.RESERVOIR_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self.log(tr('tl_reservoir_exceeded_s_terminating_it').format(RESERVOIR_TIMEOUT_S=self.RESERVOIR_TIMEOUT_S))
                try:
                    proc.kill()
                    proc.wait(timeout=30)
                except Exception:
                    pass
                return {}

            if return_code != 0 or not output_path.exists():
                self.log(tr('tl_reservoir_failed_exit').format(return_code=return_code))
                return {}

            raw = json.loads(output_path.read_text(encoding='utf-8'))
            per_group: Dict[str, str] = raw.get("translations", {})

        except Exception as exc:
            logger.error(f"Serbatoio: errore inatteso: {exc}", exc_info=True)
            return {}
        finally:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

        return self._reservoir_fanout(groups, per_group, pending)

    def _reservoir_fanout(self, groups: Dict[str, List[int]],
                          per_group: Dict[str, str],
                          pending: Dict[int, str]) -> Dict[int, str]:
        """Riporta la traduzione del rappresentante su tutti gli id del suo
        gruppo, applica il glossario a posteriori e VALIDA: un risultato
        indistinguibile dall'inglese non viene accettato, così chi chiama lo
        vede come non risolto e passa a L4 (inglese, ma segnalato) invece di
        scambiarlo per una traduzione riuscita."""
        resolved: Dict[int, str] = {}
        for key, ids in groups.items():
            it = (per_group.get(key) or "").strip()
            if not it:
                continue
            for idx in ids:
                src = pending[idx]
                it_for_id = self._apply_glossary_posthoc(it, src)
                if self._is_untranslated(it_for_id, src):
                    continue
                resolved[idx] = it_for_id
        return resolved


# ============================================================================
# NLLB TRANSLATOR (MODIFIED FOR 8-BIT QUANTIZATION)
# ============================================================================

# Variabili globali singleton NLLB
_nllb_model = None
_nllb_tokenizer = None
_nllb_lock = Lock()

# Variabili globali singleton NLLB Fine-Tuned
_nllb_ft_model = None
_nllb_ft_tokenizer = None
_nllb_ft_lock = Lock()
_use_gpu = torch.cuda.is_available()
_device = 'cuda' if _use_gpu else 'cpu'
# NLLB su ROCm: NON usare device_map="auto". Su macchine con iGPU AMD + dGPU (es.
# Ryzen con Radeon Graphics + RX 9060 XT) accelerate distribuisce i layer su
# ENTRAMBI i device; l'iGPU (gfx1036) non ha i kernel compilati per alcune
# operazioni e la generazione muore con "HIP error: invalid device
# function" (verificato il 24/10/2026 su ROCm 7.0). NLLB-3.3B fp16 occupa
# ~6.6 GB: entra su una sola GPU. Fissiamo quindi il device 0.
# Solo su ROCm: su CUDA 'auto' serve al ramo 8-bit con offload fp32 su CPU
# (VRAM limitata), che con {'': 0} non funzionerebbe piu'.
_NLLB_DEVICE_MAP = ({'': 0} if _use_gpu and getattr(torch.version, 'hip', None)
                    else 'auto')


def _load_nllb_model(model_name: str = "facebook/nllb-200-3.3B"):
    """Carica il modello e il tokenizer NLLB una sola volta (thread-safe) con quantizzazione 8-bit su GPU."""
    global _nllb_model, _nllb_tokenizer
    
    if _nllb_model is None:
        with _nllb_lock:
            if _nllb_model is not None:
                return

            try:
                logger.info(f"-> Caricamento modello NLLB-200: {model_name}...")
                import gc
                gc.collect()
                if _use_gpu:
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                    free_vram_gb = torch.cuda.mem_get_info()[0] / 1024 ** 3
                    logger.info(f"  VRAM libera pre-caricamento NLLB: {free_vram_gb:.1f} GB")

                _nllb_tokenizer = AutoTokenizer.from_pretrained(model_name)

                if _use_gpu:
                    if free_vram_gb >= 7.0:
                        logger.info(f"  VRAM sufficiente ({free_vram_gb:.1f} GB) — caricamento fp16 (no bitsandbytes)")
                        _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(
                            model_name,
                            dtype=torch.float16,
                            device_map=_NLLB_DEVICE_MAP,
                            low_cpu_mem_usage=True
                        )
                    else:
                        logger.info(f"  VRAM limitata ({free_vram_gb:.1f} GB) — caricamento 8-bit")
                        quantization_config = BitsAndBytesConfig(
                            load_in_8bit=True,
                            llm_int8_threshold=6.0,
                            llm_int8_enable_fp32_cpu_offload=True,
                        )
                        _nllb_cfg = AutoConfig.from_pretrained(model_name)
                        _nllb_quant = {} if getattr(_nllb_cfg, 'quantization_config', None) else {'quantization_config': quantization_config}
                        _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(
                            model_name,
                            **_nllb_quant,
                            device_map=_NLLB_DEVICE_MAP,
                            low_cpu_mem_usage=True
                        )
                else:
                    _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
                    _nllb_model.to(_device)

                _nllb_model.eval()

                logger.info(f"-> Modello NLLB caricato su {_device}")
            except Exception as e:
                logger.critical(f"❌ Errore caricamento NLLB-200: {e}")
                _nllb_model = None
                _nllb_tokenizer = None
                raise


def _get_nllb_translator_resources():
    """Ritorna modello, tokenizer e device globali NLLB"""
    if _nllb_model is None or _nllb_tokenizer is None:
        _load_nllb_model()
    return _nllb_model, _nllb_tokenizer, _device


def _unload_nllb_singleton():
    """Scarica il modello NLLB base dalla VRAM (thread-safe).

    Sequenza di release deterministica:
    1. remove_hook_from_module: rimuove gli hook di accelerate (device_map="auto")
       che trattengono self-reference sui moduli del modello.
    2. model.to('cpu'): forza il release dei tensor GPU spostando i pesi in RAM.
    3. del + gc.collect() + empty_cache(): rompe le ref residue e rilascia
       la cache del caching allocator PyTorch al driver CUDA.
    """
    global _nllb_model, _nllb_tokenizer
    with _nllb_lock:
        if _nllb_model is not None:
            try:
                from accelerate.hooks import remove_hook_from_module
                remove_hook_from_module(_nllb_model, recurse=True)
            except Exception as e:
                logger.debug(f"remove_hook_from_module NLLB base: {e}")
            try:
                _nllb_model.to('cpu')
            except Exception as e:
                logger.debug(f"NLLB base to('cpu') fallito: {e}")
            del _nllb_model
            _nllb_model = None
        if _nllb_tokenizer is not None:
            del _nllb_tokenizer
            _nllb_tokenizer = None
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        try:
            torch._C._cuda_clearCublasWorkspaces()
        except Exception:
            pass
        torch.cuda.empty_cache()
    logger.info("-> NLLB base scaricato dalla VRAM")


def _load_nllb_ft_model():
    """Carica il modello NLLB fine-tuned dalla path configurata in config (thread-safe)."""
    global _nllb_ft_model, _nllb_ft_tokenizer

    if _nllb_ft_model is None:
        with _nllb_ft_lock:
            if _nllb_ft_model is not None:
                return

            # Legge path da config
            model_path = None
            try:
                from utils.config import get_config as _get_cfg
                model_path = _get_cfg().get_nllb_finetuned_model_path()
            except Exception:
                pass

            if not model_path:
                raise ValueError(
                    tr('tl_fine_tuned_nllb_model_path')
                )

            try:
                logger.info(f"-> Caricamento NLLB fine-tuned da: {model_path}")
                import gc
                gc.collect()
                if _use_gpu:
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                    free_vram_gb = torch.cuda.mem_get_info()[0] / 1024 ** 3
                    logger.info(f"  VRAM libera pre-caricamento NLLB-FT: {free_vram_gb:.1f} GB")

                _nllb_ft_tokenizer = AutoTokenizer.from_pretrained(model_path)

                if _use_gpu:
                    # fp16: NLLB-3.3B usa ~6.6 GB VRAM, stabile senza bitsandbytes.
                    # 8-bit: ~3.5 GB VRAM ma bitsandbytes può crashare silenziosamente su Windows
                    # con VRAM parzialmente occupata (stesso bug di ctranslate2 ≥4.7).
                    if free_vram_gb >= 7.0:
                        logger.info(f"  VRAM sufficiente ({free_vram_gb:.1f} GB) — caricamento fp16 (no bitsandbytes)")
                        _nllb_ft_model = AutoModelForSeq2SeqLM.from_pretrained(
                            model_path,
                            dtype=torch.float16,
                            device_map=_NLLB_DEVICE_MAP,
                            low_cpu_mem_usage=True
                        )
                    else:
                        logger.info(f"  VRAM limitata ({free_vram_gb:.1f} GB) — caricamento 8-bit")
                        _nllb_ft_cfg = AutoConfig.from_pretrained(model_path)
                        quantization_config = BitsAndBytesConfig(
                            load_in_8bit=True,
                            llm_int8_threshold=6.0,
                            llm_int8_enable_fp32_cpu_offload=True,
                        )
                        _nllb_ft_quant = {} if getattr(_nllb_ft_cfg, 'quantization_config', None) else {'quantization_config': quantization_config}
                        _nllb_ft_model = AutoModelForSeq2SeqLM.from_pretrained(
                            model_path,
                            **_nllb_ft_quant,
                            device_map=_NLLB_DEVICE_MAP,
                            low_cpu_mem_usage=True
                        )
                else:
                    _nllb_ft_model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
                    _nllb_ft_model.to(_device)

                _nllb_ft_model.eval()
                logger.info(f"-> NLLB fine-tuned caricato su {_device}")
            except Exception as e:
                logger.critical(f"Errore caricamento NLLB fine-tuned: {e}")
                _nllb_ft_model = None
                _nllb_ft_tokenizer = None
                raise


def _get_nllb_ft_resources():
    """Ritorna modello, tokenizer e device del NLLB fine-tuned."""
    if _nllb_ft_model is None or _nllb_ft_tokenizer is None:
        _load_nllb_ft_model()
    return _nllb_ft_model, _nllb_ft_tokenizer, _device


def _unload_nllb_ft_singleton():
    """Scarica il modello NLLB fine-tuned dalla VRAM (thread-safe).

    Stessa sequenza di _unload_nllb_singleton: remove_hook_from_module,
    to('cpu'), del, gc, empty_cache. Questo e' critico per NLLB-FT perche'
    altrimenti i ~6 GB di pesi restano stuck in VRAM anche dopo 'cleanup',
    bloccando lo STEP 6.5 (Gender Correction LLM).
    """
    global _nllb_ft_model, _nllb_ft_tokenizer
    with _nllb_ft_lock:
        if _nllb_ft_model is not None:
            try:
                from accelerate.hooks import remove_hook_from_module
                remove_hook_from_module(_nllb_ft_model, recurse=True)
            except Exception as e:
                logger.debug(f"remove_hook_from_module NLLB-FT: {e}")
            try:
                _nllb_ft_model.to('cpu')
            except Exception as e:
                logger.debug(f"NLLB-FT to('cpu') fallito: {e}")
            del _nllb_ft_model
            _nllb_ft_model = None
        if _nllb_ft_tokenizer is not None:
            del _nllb_ft_tokenizer
            _nllb_ft_tokenizer = None
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        try:
            torch._C._cuda_clearCublasWorkspaces()
        except Exception:
            pass
        torch.cuda.empty_cache()
    logger.info("-> NLLB fine-tuned scaricato dalla VRAM")


class NLLBTranslator(BaseTranslator):
    """
    Traduttore NLLB-200 con BATCH SIZE ADATTIVO
    """

    # Serbatoio (L3) per il ramo NLLB: Qwen, non NLLB.
    #
    # Qui il motore primario È NLLB: richiamarlo come ripiego ripeterebbe il
    # tentativo che ha già fallito in L1 e in L2. Qwen è l'unica seconda
    # opinione sempre disponibile (GGUF già presente per la correzione di
    # genere), e sul banco del serbatoio produce sì un italiano meno curato,
    # ma su righe che altrimenti resterebbero in inglese.
    RESERVOIR_DEFAULT = 'qwen'


    # Mappa COMPLETA codici lingua ISO 639-2/1 → codici NLLB
    LANGUAGE_CODES = {
        'eng': 'eng_Latn', 'en': 'eng_Latn', 'english': 'eng_Latn',
        'ita': 'ita_Latn', 'it': 'ita_Latn', 'italian': 'ita_Latn',
        'fra': 'fra_Latn', 'fr': 'fra_Latn', 'fre': 'fra_Latn', 'french': 'fra_Latn',
        'deu': 'deu_Latn', 'de': 'deu_Latn', 'ger': 'deu_Latn', 'german': 'deu_Latn',
        'spa': 'spa_Latn', 'es': 'spa_Latn', 'spanish': 'spa_Latn',
        'por': 'por_Latn', 'pt': 'por_Latn', 'portuguese': 'por_Latn',
        'rus': 'rus_Cyrl', 'ru': 'rus_Cyrl', 'russian': 'rus_Cyrl',
        'jpn': 'jpn_Jpan', 'ja': 'jpn_Jpan', 'japanese': 'jpn_Jpan',
        'chi': 'zho_Hans', 'zh': 'zho_Hans', 'zho': 'zho_Hans', 'chinese': 'zho_Hans',
        'ara': 'ara_Arab', 'ar': 'ara_Arab', 'arabic': 'ara_Arab',
        'kor': 'kor_Hang', 'ko': 'kor_Hang', 'korean': 'kor_Hang',
        'hin': 'hin_Deva', 'hi': 'hin_Deva', 'hindi': 'hin_Deva',
        'pol': 'pol_Latn', 'pl': 'pol_Latn', 'polish': 'pol_Latn',
        'tur': 'tur_Latn', 'tr': 'tur_Latn', 'turkish': 'tur_Latn',
        'nld': 'nld_Latn', 'nl': 'nld_Latn', 'dut': 'nld_Latn', 'dutch': 'nld_Latn',
        'swe': 'swe_Latn', 'sv': 'swe_Latn', 'swedish': 'swe_Latn',
        'dan': 'dan_Latn', 'da': 'dan_Latn', 'danish': 'dan_Latn',
        'nor': 'nob_Latn', 'no': 'nob_Latn', 'norwegian': 'nob_Latn',
        'fin': 'fin_Latn', 'fi': 'fin_Latn', 'finnish': 'fin_Latn',
        'ces': 'ces_Latn', 'cs': 'ces_Latn', 'cze': 'ces_Latn', 'czech': 'ces_Latn',
        'hun': 'hun_Latn', 'hu': 'hun_Latn', 'hungarian': 'hun_Latn',
        'ron': 'ron_Latn', 'ro': 'ron_Latn', 'rum': 'ron_Latn', 'romanian': 'ron_Latn',
        'ukr': 'ukr_Cyrl', 'uk': 'ukr_Cyrl', 'ukrainian': 'ukr_Cyrl',
        'ell': 'ell_Grek', 'el': 'ell_Grek', 'gre': 'ell_Grek', 'greek': 'ell_Grek',
        'heb': 'heb_Hebr', 'he': 'heb_Hebr', 'hebrew': 'heb_Hebr',
        'vie': 'vie_Latn', 'vi': 'vie_Latn', 'vietnamese': 'vie_Latn',
        'tha': 'tha_Thai', 'th': 'tha_Thai', 'thai': 'tha_Thai',
        'srp': 'srp_Cyrl', 'sr': 'srp_Cyrl', 'serbian': 'srp_Cyrl',
        'hrv': 'hrv_Latn', 'hr': 'hrv_Latn', 'croatian': 'hrv_Latn',
        'bos': 'bos_Latn', 'bs': 'bos_Latn', 'bosnian': 'bos_Latn',
        'slk': 'slk_Latn', 'sk': 'slk_Latn', 'slovak': 'slk_Latn',
        'slv': 'slv_Latn', 'sl': 'slv_Latn', 'slovenian': 'slv_Latn',
        'bul': 'bul_Cyrl', 'bg': 'bul_Cyrl', 'bulgarian': 'bul_Cyrl',
        'cat': 'cat_Latn', 'ca': 'cat_Latn', 'catalan': 'cat_Latn',
        'lit': 'lit_Latn', 'lt': 'lit_Latn', 'lithuanian': 'lit_Latn',
        'lav': 'lvs_Latn', 'lv': 'lvs_Latn', 'latvian': 'lvs_Latn',
        'est': 'est_Latn', 'et': 'est_Latn', 'estonian': 'est_Latn',
        # Lingue comuni nei film
        'pes': 'pes_Arab', 'fa': 'pes_Arab', 'per': 'pes_Arab', 'fas': 'pes_Arab', 'persian': 'pes_Arab', 'farsi': 'pes_Arab',
        'ind': 'ind_Latn', 'id': 'ind_Latn', 'indonesian': 'ind_Latn',
        'zsm': 'zsm_Latn', 'ms': 'zsm_Latn', 'may': 'zsm_Latn', 'msa': 'zsm_Latn', 'malay': 'zsm_Latn',
        'als': 'als_Latn', 'sq': 'als_Latn', 'sqi': 'als_Latn', 'alb': 'als_Latn', 'albanian': 'als_Latn',
        'mkd': 'mkd_Cyrl', 'mk': 'mkd_Cyrl', 'macedonian': 'mkd_Cyrl',
        'kat': 'kat_Geor', 'ka': 'kat_Geor', 'geo': 'kat_Geor', 'georgian': 'kat_Geor',
        'hye': 'hye_Armn', 'hy': 'hye_Armn', 'arm': 'hye_Armn', 'armenian': 'hye_Armn',
        'ben': 'ben_Beng', 'bn': 'ben_Beng', 'bengali': 'ben_Beng',
        'urd': 'urd_Arab', 'ur': 'urd_Arab', 'urdu': 'urd_Arab',
        'tam': 'tam_Taml', 'ta': 'tam_Taml', 'tamil': 'tam_Taml',
        'tel': 'tel_Telu', 'te': 'tel_Telu', 'telugu': 'tel_Telu',
        'mal': 'mal_Mlym', 'ml': 'mal_Mlym', 'malayalam': 'mal_Mlym',
        'tgl': 'tgl_Latn', 'tl': 'tgl_Latn', 'tagalog': 'tgl_Latn',
        'swh': 'swh_Latn', 'sw': 'swh_Latn', 'swa': 'swh_Latn', 'swahili': 'swh_Latn',
        # Lingue meno comuni ma supportate da NLLB
        'aze': 'azj_Latn', 'az': 'azj_Latn', 'azerbaijani': 'azj_Latn',
        'bel': 'bel_Cyrl', 'be': 'bel_Cyrl', 'belarusian': 'bel_Cyrl',
        'kaz': 'kaz_Cyrl', 'kk': 'kaz_Cyrl', 'kazakh': 'kaz_Cyrl',
        'khk': 'khk_Cyrl', 'mn': 'khk_Cyrl', 'mon': 'khk_Cyrl', 'mongolian': 'khk_Cyrl',
        'npi': 'npi_Deva', 'ne': 'npi_Deva', 'nep': 'npi_Deva', 'nepali': 'npi_Deva',
        'sin': 'sin_Sinh', 'si': 'sin_Sinh', 'sinhala': 'sin_Sinh',
        'mya': 'mya_Mymr', 'my': 'mya_Mymr', 'bur': 'mya_Mymr', 'burmese': 'mya_Mymr',
        'khm': 'khm_Khmr', 'km': 'khm_Khmr', 'khmer': 'khm_Khmr',
        'amh': 'amh_Ethi', 'am': 'amh_Ethi', 'amharic': 'amh_Ethi',
        'uzn': 'uzn_Latn', 'uz': 'uzn_Latn', 'uzb': 'uzn_Latn', 'uzbek': 'uzn_Latn',
        'tgk': 'tgk_Cyrl', 'tg': 'tgk_Cyrl', 'tajik': 'tgk_Cyrl',
        'eus': 'eus_Latn', 'eu': 'eus_Latn', 'baq': 'eus_Latn', 'basque': 'eus_Latn',
        'glg': 'glg_Latn', 'gl': 'glg_Latn', 'galician': 'glg_Latn',
        'cym': 'cym_Latn', 'cy': 'cym_Latn', 'wel': 'cym_Latn', 'welsh': 'cym_Latn',
        'isl': 'isl_Latn', 'is': 'isl_Latn', 'icelandic': 'isl_Latn',
        'mlt': 'mlt_Latn', 'mt': 'mlt_Latn', 'maltese': 'mlt_Latn',
        'afr': 'afr_Latn', 'af': 'afr_Latn', 'afrikaans': 'afr_Latn',
        'mar': 'mar_Deva', 'mr': 'mar_Deva', 'marathi': 'mar_Deva',
        'pan': 'pan_Guru', 'pa': 'pan_Guru', 'punjabi': 'pan_Guru',
        'guj': 'guj_Gujr', 'gu': 'guj_Gujr', 'gujarati': 'guj_Gujr',
        'kan': 'kan_Knda', 'kn': 'kan_Knda', 'kannada': 'kan_Knda',
        'lao': 'lao_Laoo', 'lo': 'lao_Laoo', 'laotian': 'lao_Laoo',
        'som': 'som_Latn', 'so': 'som_Latn', 'somali': 'som_Latn',
        'yor': 'yor_Latn', 'yo': 'yor_Latn', 'yoruba': 'yor_Latn',
        'zul': 'zul_Latn', 'zu': 'zul_Latn', 'zulu': 'zul_Latn',
        'und': 'eng_Latn',
    }

    # Parametri ottimizzati per qualità / performance
    NO_REPEAT_NGRAM_SIZE = 3
    MAX_LENGTH_SENTENCE = 256

    # Batch Size Adattivo (RTX 3060 12GB VRAM)
    BATCH_SIZE_ADAPTIVE = 12
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 24

    def __init__(self, log_callback: Optional[Callable] = None, context: Optional[str] = None,
                 glossary: Optional[Dict[str, str]] = None):
        """Inizializza il traduttore NLLB usando l'istanza singleton"""
        super().__init__(log_callback, context, glossary)
        self.model, self.tokenizer, self.device = _get_nllb_translator_resources()

        from utils.adaptive_batch_manager import AdaptiveBatchSizeManager
        cfg = get_config().get_adaptive_batch_config() if get_config else {}

        # Messaggi del batch manager: solo warm-up in GUI, il resto solo nel file di log.
        # Il progresso batch viene già mostrato nella barra "Traduzione: [...]".
        def _batch_log(msg: str):
            logger.debug(msg)
            if 'Warm-up' in msg:
                self.log(msg)

        # Cap a MAX_BATCH_SIZE (tarato per NLLB): la chiave config
        # 'adaptive_batch_max_size' è condivisa con la trascrizione ASR
        # (dove 62 ha senso) — qui, lasciata passare senza tetto, ha spinto
        # il batch a 36+ con beam=7 su un modello già da ~6.6GB in VRAM,
        # causando spillover in RAM condivisa WDDM (stesso bug corretto in
        # v1.9.2 nel vecchio engine Whisper, qui mancava il cap analogo).
        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=self.use_gpu,
            initial_size=cfg.get('initial_size'),
            min_size=cfg.get('min_size', self.MIN_BATCH_SIZE),
            max_size=min(cfg.get('max_size', self.MAX_BATCH_SIZE), self.MAX_BATCH_SIZE),
            warmup_batches=cfg.get('warmup_batches', 5),
            high_threshold=cfg.get('high_threshold', 0.85),
            low_threshold=cfg.get('low_threshold', 0.60),
            log_callback=_batch_log,
        )
        # Alias per compatibilità con il loop translate_file
        self.current_batch_size = self.batch_manager.current_batch_size

    def _nllb_to_iso(self, lang_code: str) -> Optional[str]:
        """Converte codice ISO 639-2/1 in codice NLLB"""
        result = self.LANGUAGE_CODES.get(lang_code.lower(), None)
        if result is None:
            logger.warning(f"Codice lingua '{lang_code}' non trovato in LANGUAGE_CODES")
        return result

    def _build_translation_units(
        self, batch: List[SRT_SUBTITLE], dash_flags: Dict[int, List[bool]]
    ) -> Tuple[List[Tuple[int, Optional[int]]], List[str], List[Dict[str, str]], List[bool], List[str]]:
        """Prepara le unità di traduzione per un batch.

        I blocchi dialogo multi-parlante (dash_flags con più righe, almeno
        una con trattino) vengono espansi in un'unità di traduzione PER RIGA
        invece che un'unica stringa con '\\n' embedded: NLLB non garantisce
        la preservazione del newline nella traduzione di testo multi-riga
        (verificato empiricamente: a volte fonde le battute di due parlanti
        in una riga sola, a volte inserisce trattini propri spuri) — questo
        rompeva il ripristino '- ' basato su posizione in _generate_srt,
        producendo blocchi come "- Vorrei che tu fossi qui. Anch'io." invece
        di due righe separate. Tradurre riga per riga elimina il problema per
        costruzione: il conteggio righe post-traduzione è sempre identico
        all'originale.

        Returns:
            unit_specs: un elemento per unità di traduzione, parallelo agli
                altri elenchi restituiti: (indice nel batch, indice riga o
                None se l'unità rappresenta l'intero blocco non-dialogo).
            texts_to_translate, current_batch_placeholders,
            skip_translation_flags: come nel batch classico, ma a livello di
                unità anziché di sottotitolo.
            unit_original_texts: testo originale (fallback) per unità —
                l'intero blocco per le unità non-dialogo, la singola riga per
                le unità dialogo.
        """
        unit_specs: List[Tuple[int, Optional[int]]] = []
        texts_to_translate: List[str] = []
        current_batch_placeholders: List[Dict[str, str]] = []
        skip_translation_flags: List[bool] = []
        unit_original_texts: List[str] = []

        for j, (index, start, end, text) in enumerate(batch):
            flags = dash_flags.get(index) if dash_flags else None
            is_dialogue_block = bool(flags) and len(flags) > 1 and any(flags)

            if is_dialogue_block:
                for line_idx, line in enumerate(text.split('\n')):
                    gloss_text, gloss_placeholders = self._mask_glossary(
                        line, "NLLB", self.glossary)
                    final_text, placeholders, only_masked = self._mask_text(
                        gloss_text, "NLLB")
                    placeholders.update(gloss_placeholders)
                    unit_specs.append((j, line_idx))
                    texts_to_translate.append(final_text)
                    current_batch_placeholders.append(placeholders)
                    skip_translation_flags.append(only_masked)
                    unit_original_texts.append(line)
            else:
                gloss_text, gloss_placeholders = self._mask_glossary(
                    text, "NLLB", self.glossary)
                final_text, placeholders, only_masked = self._mask_text(
                    gloss_text, "NLLB")
                placeholders.update(gloss_placeholders)
                unit_specs.append((j, None))
                texts_to_translate.append(final_text)
                current_batch_placeholders.append(placeholders)
                skip_translation_flags.append(only_masked)
                unit_original_texts.append(text)

        return (unit_specs, texts_to_translate, current_batch_placeholders,
                skip_translation_flags, unit_original_texts)

    # Oltre questo rapporto rispetto al ritmo migliore del file, il batch sta
    # andando a una frazione della velocità di cui è capace.
    SLOWDOWN_TRIP = 2.0
    # Campioni minimi prima di poter avvisare: il primo batch paga
    # l'autotuning dei kernel e non è un riferimento onesto.
    SLOW_MIN_SAMPLES = 3

    def _check_throughput(self, seconds: float, tokens: int) -> None:
        """Backstop temporale: dice quando la traduzione sta andando piano.

        Su WDDM lo sconfinamento in RAM di sistema NON solleva un OOM — in
        tutto lo storico dei log non c'è un solo evento OOM reale, quindi il
        ramo `except RuntimeError` di `_run_translation` non è mai stato
        raggiunto in produzione. L'unica firma è il tempo che risale.

        SEGNALA E BASTA, di proposito. Misurato sulle due run contese del
        2026-09-05: ridurre il batch sotto contesa ha peggiorato il tempo per
        frase del 62% (0,271 s a batch 24 contro 0,438 s a batch 16). Chi
        rallenta la GPU è un altro processo, e il batch non è la leva giusta.
        Quello che mancava non era una reazione: era saperlo.

        `ms/token` invece di `ms/frase` perché il secondo dipende da quanto
        sono lunghe le battute del batch, il primo quasi no.
        """
        # Tutto dentro try: questo metodo viene chiamato dal `try` di
        # `_run_translation`, dove un'eccezione qualsiasi verrebbe scambiata
        # per un fallimento del batch (o, se non è un RuntimeError, farebbe
        # saltare l'intero batch da un percorso di sola diagnostica). Una
        # misura non deve mai poter rompere il lavoro che misura.
        try:
            if tokens <= 0 or seconds <= 0:
                return
            ms_per_token = seconds * 1000.0 / tokens
            self._slow_samples = getattr(self, '_slow_samples', 0) + 1
            base = getattr(self, '_ms_token_base', None)
            if base is None or ms_per_token < base:
                self._ms_token_base = ms_per_token   # migliore osservato nel file
                return
            # Il primo batch paga l'autotuning dei kernel e l'allocazione dei
            # workspace cuBLAS: non è un riferimento onesto finché non ci sono
            # abbastanza campioni per farlo scendere al ritmo vero.
            if (base > 0 and self._slow_samples >= self.SLOW_MIN_SAMPLES
                    and ms_per_token > base * self.SLOWDOWN_TRIP
                    and not getattr(self, '_slow_warned', False)):
                self._slow_warned = True
                self.log(
                    tr('tl_translation_slowed_down_compared_to').format(ratio=ms_per_token / base, ms_per_token=ms_per_token, base=base)
                )
        except Exception as exc:
            logger.debug(f"_check_throughput: {exc}")

    def _run_translation(self, texts: List[str], src_lang: str, tgt_lang: str, add_context: bool = True) -> List[str]:
        """
        Esegue traduzione batch con gestione OOM dinamica
        """
        # Il contesto NON entra mai qui, e `add_context` resta solo per non
        # cambiare la firma a chi la chiama.
        #
        # MISURATO (mt_eval/validate_pipeline_path.py, 120 blocchi di
        # Deadpool 2): anteponendo "[CONTEXT: <trama>]\n" a ogni battuta, NLLB
        # traduceva la trama e restituiva quella. I 24 sottotitoli del primo
        # batch uscivano tutti identici — "Il mercenario Wade Wilson forma una
        # squadra per proteggere..." al posto di "Fanculo Wolverine" — e i
        # tempi restavano giusti, quindi il file sembrava sano.
        #
        # Non è un difetto di regolazione, è una categoria sbagliata: NLLB è un
        # encoder-decoder che traduce UN segmento, non ha un prompt di sistema
        # in cui infilare informazioni di sfondo. Tutto ciò che gli si mette
        # davanti è testo da tradurre.
        #
        # Il contesto resta passato perché lo usano i motori cloud, Claude e
        # OpenAI, nella sezione CONTEXT del loro prompt. Il ramo LLM locale
        # non lo riceve più: lo consumava solo il percorso "adapt", rimosso il
        # 2026-08-18.
        #
        # Il codice era in `master` da tempo ma non si era mai visto: la
        # pipeline chiamava `get_translator()` senza contesto, quindi
        # `_prepared_context` restava None. È bastato cominciare a passarlo
        # perché il difetto diventasse reale su ogni film.
        del add_context

        # CRITICO: il tokenizer NLLB usa self.tokenizer.src_lang per decidere
        # il token di lingua sorgente da anteporre al testo in input. Se non
        # impostato qui, resta bloccato sul default caricato da from_pretrained
        # (eng_Latn) per QUALSIASI lingua sorgente — l'input viene taggato come
        # inglese anche quando è tedesco/francese/ecc., producendo output
        # allucinati o testo non tradotto (verificato empiricamente: 5/10 frasi
        # tedesche non tradotte senza questa riga, 0/10 con). Va impostato ad
        # ogni chiamata (non solo al load) perché lo stesso translator può
        # essere riusato con lingue sorgente diverse tra un file e l'altro.
        self.tokenizer.src_lang = src_lang

        try:
            inputs = self.tokenizer(
                texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self.MAX_LENGTH_SENTENCE
            ).to(self.device)

            forced_bos_token_id = self.tokenizer.convert_tokens_to_ids(tgt_lang)

            _t_gen = time.perf_counter()
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos_token_id,
                    num_beams=get_config().get_nllb_num_beams(),
                    no_repeat_ngram_size=self.NO_REPEAT_NGRAM_SIZE,
                    max_length=self.MAX_LENGTH_SENTENCE
                )
            self._check_throughput(time.perf_counter() - _t_gen, outputs.numel())

            translations = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)
            return translations
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                self.batch_manager.record_oom()
                self.current_batch_size = self.batch_manager.current_batch_size

                if self.batch_manager.current_batch_size > self.MIN_BATCH_SIZE or self.current_batch_size > self.MIN_BATCH_SIZE:
                    raise Exception("Out of Memory - Batch Size Ridotto")
                else:
                    self.log(tr('tl_oops_critical_oom_with_batch'))
                    raise Exception("Out of Memory - GPU Memoria Insufficiente")
            else:
                raise


    def translate_file(self, input_path: Path, output_path: Path,
                      src_lang: str, tgt_lang: str, context: Optional[str] = None,
                      glossary: Optional[Dict[str, str]] = None) -> bool:
        """
        Traduce file SRT da lingua sorgente a lingua target
        """
        # Converti stringhe a Path se necessario (per compatibilità con pipeline)
        if isinstance(input_path, str):
            input_path = Path(input_path)
        if isinstance(output_path, str):
            output_path = Path(output_path)

        if glossary is not None:
            self.glossary = glossary

        if context is not None:
            self.context = context
            if context and context.strip():
                truncated = context[:500].strip()
                if len(context) > 500:
                    truncated += "..."
                self._prepared_context = f"[CONTEXT: {truncated}]\n"
            else:
                self._prepared_context = None
        
        try:
            model_label = 'FT' if isinstance(self, NLLBFineTunedTranslator) else 'base'
            load_mode = 'fp16' if (self.use_gpu and torch.cuda.mem_get_info()[0] / 1024**3 >= 7.0) else '8-bit'
            num_beams = get_config().get_nllb_num_beams()
            self.log(tr('tl_nllb_translation_beams').format(model_label=model_label, load_mode=load_mode, src_lang=src_lang, tgt_lang=tgt_lang, num_beams=num_beams))

            if self._prepared_context:
                # Non "attivo": ricevuto e ignorato di proposito. Vedi la nota
                # in `_run_translation`.
                self.log(tr('tl_work_context_received_nllb_does'))

            src_nllb = self._nllb_to_iso(src_lang)
            tgt_nllb = self._nllb_to_iso(tgt_lang)

            if not src_nllb or not tgt_nllb:
                self.log(tr('tl_unsupported_language_code_or').format(src_lang=src_lang, tgt_lang=tgt_lang))
                return False

            parsed_subtitles, dash_flags = self._extract_dash_flags(
                self._parse_srt(input_path)
            )
            total = len(parsed_subtitles)
            translated_subtitles = []
            originals_by_index = {idx: text for idx, _, _, text in parsed_subtitles}

            # Coda di recupero (L2/L3), popolata durante il loop principale e
            # svuotata DOPO — dentro il `while` disturberebbe l'
            # AdaptiveBatchSizeManager e frammenterebbe le chiamate a NLLB.
            # Solo unità NON-dialogo (line_idx is None): rattoppare una
            # singola riga di un blocco a più parlanti richiederebbe
            # ricomporre il join su '\n' per posizione, il punto più fragile
            # di questo piano — si preferisce una copertura parziale
            # dichiarata (le righe di dialogo restano coperte da L1 + audit)
            # a un bug di ricomposizione, che varrebbe più danni di quelli
            # che ripara.
            recovery_queue: Dict[int, str] = {}
            n_repaired = 0

            if total == 0:
                self.log(tr('tl_srt_file_empty_or_parsing'))
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write("")
                return True

            self.log(tr('tl_found_subtitles_to_translate').format(total=total))

            self.batch_manager.reset()
            self.current_batch_size = self.batch_manager.current_batch_size
            self._ms_token_base = None      # ritmo di riferimento per file
            self._slow_warned = False
            self._slow_samples = 0
            is_first_batch = True

            import time as _time
            t0 = _time.time()
            # Nessuna barra iniziale a 0%: il warm-up del gestore batch emette
            # la propria riga "Warm-up: [...]" e la barra della traduzione
            # compare solo a warm-up concluso (vedi sotto, `not is_warming_up`).

            i = 0
            last_progress = -1
            max_retries_per_batch = 3
            _eta_tr = None      # stimatore ETA: parte alla prima barra (dopo il warm-up)

            while i < total:
                self.current_batch_size = self.batch_manager.current_batch_size
                batch_index = (i // self.current_batch_size) + 1
                total_batches = (total + self.current_batch_size - 1) // self.current_batch_size

                batch = parsed_subtitles[i:i + self.batch_manager.get_batch_size()]
                (unit_specs, texts_to_translate, current_batch_placeholders,
                 skip_translation_flags, unit_original_texts) = self._build_translation_units(
                    batch, dash_flags)

                progress = int((i / total) * 100)
                if progress != last_progress and not self.batch_manager.is_warming_up:
                    bars = int(progress / 10)
                    bar = '█' * bars + '░' * (10 - bars)
                    bs = self.batch_manager.current_batch_size
                    from utils.events import emit as _tp_emit
                    if _eta_tr is None:
                        from utils.eta import EtaEstimator
                        _eta_tr = EtaEstimator()
                    _eta_txt = _eta_tr.update(i / total)
                    _tp_emit('bar', phase='translate', pct=progress, eta_s=_eta_tr.eta_seconds())
                    self.log(tr('tl_translation_batch').format(bar=bar, progress=progress, i=i, total=total, bs=bs, eta_txt=_eta_txt))
                    last_progress = progress

                retries = 0
                batch_success = False
                # I rami di errore che riemettono il batch originale fanno
                # `break`, ma il controllo dopo il `while` guardava solo
                # `retries >= max_retries_per_batch`: se l'errore capitava
                # all'ULTIMO tentativo, il batch veniva riemesso una seconda
                # volta e `i` avanzava due volte — blocchi inglesi duplicati
                # nell'SRT e un batch intero saltato senza traduzione.
                batch_emitted = False

                while retries < max_retries_per_batch and not batch_success:
                    try:
                        texts_for_nllb = [
                            t for t, skip in zip(texts_to_translate, skip_translation_flags)
                            if not skip and t.strip()
                        ]
                        
                        results = []
                        if texts_for_nllb:
                            results = self._run_translation(texts_for_nllb, src_nllb, tgt_nllb, 
                                                           add_context=is_first_batch)
                        
                        translated_index = 0
                        # partial_results[j][line_idx_or_None] = testo tradotto dell'unità.
                        # Le unità dialogo (line_idx intero) vengono riunite con '\n' DOPO
                        # questo loop, mantenendo per costruzione lo stesso numero di righe
                        # dell'originale (vedi _build_translation_units).
                        partial_results: Dict[int, Dict[Optional[int], str]] = {}
                        for u, (batch_j, line_idx) in enumerate(unit_specs):
                            index = batch[batch_j][0]
                            final_text_to_translate = texts_to_translate[u]
                            placeholders_map = current_batch_placeholders[u]
                            unit_original = unit_original_texts[u]

                            if skip_translation_flags[u] or not final_text_to_translate.strip():
                                # Non solo marcatori musicali: una riga fatta
                                # SOLO di un termine di glossario (es. "Knight
                                # Runner") arriva qui con skip=True perché non
                                # c'e' nulla da tradurre — ma la resa fissa va
                                # comunque applicata, non va copiato l'originale
                                # inglese. _unmask_text su una riga senza
                                # placeholder di glossario è un no-op identico
                                # a `unit_original`.
                                unit_result = self._unmask_text(
                                    final_text_to_translate, placeholders_map) \
                                    if final_text_to_translate.strip() else unit_original

                            else:
                                # line_idx is None = intero blocco non-dialogo:
                                # unico caso in cui un fallimento può andare
                                # in coda di recupero (vedi nota sopra il
                                # `while`). Le unità di dialogo (line_idx
                                # intero) restano sul ripiego immediato.
                                can_queue = (line_idx is None)
                                if translated_index < len(results):
                                    translated_text = results[translated_index]

                                    if translated_text.strip().lower() == "# non lo so #":
                                        if can_queue:
                                            recovery_queue[index] = unit_original
                                        else:
                                            self.log(tr('tl_warning_hallucination_detected_for_line').format(index=index))
                                        unit_result = unit_original
                                    else:
                                        unit_result, unmask_ok, rip = self._unmask_tolerant(
                                            translated_text, placeholders_map)
                                        n_repaired += rip
                                        if not unmask_ok or self._is_untranslated(
                                                unit_result, unit_original):
                                            # NLLB non ha riprodotto un placeholder
                                            # intatto (o ha restituito l'inglese
                                            # con il placeholder preservato): mai
                                            # mostrare testo rotto o non tradotto.
                                            if can_queue:
                                                recovery_queue[index] = unit_original
                                            else:
                                                self.log(tr('tl_warning_masking_placeholder_not_reproduced').format(index=index))
                                            unit_result = unit_original

                                    translated_index += 1

                                else:
                                    if can_queue:
                                        recovery_queue[index] = unit_original
                                    else:
                                        self.log(tr('tl_warning_no_nllb_output_for').format(index=index))
                                    unit_result = unit_original

                            partial_results.setdefault(batch_j, {})[line_idx] = unit_result

                        post_processed_results = []
                        for j in range(len(batch)):
                            parts = partial_results.get(j, {})
                            if None in parts:
                                post_processed_results.append(parts[None])
                            else:
                                n_lines = max(parts.keys()) + 1 if parts else 0
                                post_processed_results.append(
                                    '\n'.join(parts.get(li, '') for li in range(n_lines)))

                        for j, (index, start, end, _) in enumerate(batch):
                            translated_subtitles.append((index, start, end, post_processed_results[j]))
                        
                        batch_success = True
                        self.batch_manager.record_success()
                        is_first_batch = False
                        i += len(batch)

                    except Exception as e:
                        if self._is_fatal_gpu_error(e):
                            # Errore sistemico: i batch successivi fallirebbero
                            # allo stesso modo. Si esce e il chiamante usera' il
                            # file in lingua originale (niente falso positivo).
                            self.log(tr('tl_fatal_gpu_error_aborting').format(
                                error=str(e)[:200]))
                            raise
                        retries += 1

                        if 'Out of Memory - Batch Size Ridotto' in str(e):
                            self.log(tr('tl_retry_with_reduced_batch_size').format(retries=retries, max_retries_per_batch=max_retries_per_batch))
                            self.current_batch_size = self.batch_manager.current_batch_size
                            batch = parsed_subtitles[i:i + self.current_batch_size]
                            (unit_specs, texts_to_translate, current_batch_placeholders,
                             skip_translation_flags, unit_original_texts) = self._build_translation_units(
                                batch, dash_flags)

                        elif 'Out of Memory - GPU Memoria Insufficiente' in str(e):
                            self.log(tr('tl_critical_error_insufficient_gpu_memory'))
                            for item in batch:
                                translated_subtitles.append(item)
                            is_first_batch = False
                            i += len(batch)
                            batch_emitted = True
                            break

                        else:
                            self.log(tr('tl_unknown_error_in_the_batch').format(error=str(e)[:100]))
                            for item in batch:
                                translated_subtitles.append(item)
                            is_first_batch = False
                            i += len(batch)
                            batch_emitted = True
                            break

                if not batch_success and not batch_emitted:
                    self.log(tr('tl_batch_failed_after_attempts_keeping').format(max_retries_per_batch=max_retries_per_batch))
                    for item in batch:
                        translated_subtitles.append(item)
                    is_first_batch = False
                    i += len(batch)

            elapsed = _time.time() - t0
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            from utils.events import emit as _tp_emit
            _tp_emit('bar', phase='translate', pct=100)
            self.log(tr('tl_translation_100').format(total=total, time_str=time_str))

            self.batch_manager.log_summary()

            # ------------------------------------------------------------
            # L2 — motore primario ANCORA CARICO: ritraduce senza masking i
            # blocchi in coda. Una sola chiamata per tutti insieme.
            # ------------------------------------------------------------
            pos_by_index = {item[0]: pos for pos, item in enumerate(translated_subtitles)}
            n_l2 = n_l3 = 0
            confirmed_identical: Dict[int, str] = {}
            if recovery_queue:
                self.log(tr('tl_blocks_to_recover_retrying_without').format(n=len(recovery_queue)))
                try:
                    idx_list = list(recovery_queue.keys())
                    raw_results = self._run_translation(
                        [recovery_queue[i] for i in idx_list],
                        src_nllb, tgt_nllb, add_context=False)
                except Exception as exc:
                    logger.warning(f"L2 NLLB (retry senza masking) fallito: {exc}")
                    raw_results = []
                for i, raw in zip(idx_list, raw_results):
                    text = self._apply_glossary_posthoc(
                        (raw or "").strip(), recovery_queue[i])
                    if not text:
                        continue
                    if self._is_untranslated(text, recovery_queue[i]):
                        # Due generazioni indipendenti (con e senza
                        # placeholder) concordano sul testo del sorgente:
                        # quasi sempre una riga che in italiano resta davvero
                        # identica. Non vale uno swap di modello — l'audit
                        # finale la segnala comunque.
                        confirmed_identical[i] = recovery_queue[i]
                        del recovery_queue[i]
                        continue
                    pos = pos_by_index.get(i)
                    if pos is not None:
                        old = translated_subtitles[pos]
                        translated_subtitles[pos] = (old[0], old[1], old[2], text)
                    del recovery_queue[i]
                    n_l2 += 1

                if confirmed_identical:
                    self.log(tr('tl_blocks_confirmed_identical_to_the').format(n=len(confirmed_identical)))

            # ------------------------------------------------------------
            # L3 — serbatoio, un solo swap di modello per ciò che resta.
            # ------------------------------------------------------------
            if recovery_queue:
                total_for_alarm = max(1, total)
                if len(recovery_queue) > total_for_alarm * 0.10:
                    self.log(tr('tl_warning_blocks_to_the_reservoir').format(n=len(recovery_queue), total_for_alarm=total_for_alarm))
                for i, text in self._reservoir_translate(dict(recovery_queue)).items():
                    pos = pos_by_index.get(i)
                    if pos is not None:
                        old = translated_subtitles[pos]
                        translated_subtitles[pos] = (old[0], old[1], old[2], text)
                    del recovery_queue[i]
                    n_l3 += 1

            # L4 — ciò che resta in `recovery_queue` è già rimasto invariato
            # (inglese) in `translated_subtitles`: si segnala ad alta voce.
            for i in recovery_queue:
                self.log(tr('tl_warning_block_not_translated_stays').format(i=i, text=recovery_queue[i][:60]))

            flagged = self._log_audit(
                {idx: text for idx, _, _, text in translated_subtitles},
                originals_by_index,
                counters={tr('tl_counter_repaired_l1'): n_repaired, tr('tl_counter_recovered_l2'): n_l2,
                         tr('tl_counter_reservoir_l3'): n_l3,
                         tr('tl_counter_confirmed_identical'): len(confirmed_identical)})

            # Criterio di successo: non basta aver completato il ciclo. Se troppi
            # blocchi sono rimasti in lingua originale, la traduzione e'
            # fallita: NON si scrive il file e la pipeline conserva il sorgente.
            if self._translation_exceeds_error_budget(len(flagged), total):
                return False

            srt_content = self._generate_srt(translated_subtitles, dash_flags)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            return True
            
        except Exception as e:
            error_msg = tr('tl_file_translation_error').format(name=output_path.name, e=e)
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            return False
    
    def cleanup(self):
        """Scarica modello NLLB base dalla VRAM.

        Azzera prima le reference dell'istanza (self.model/tokenizer/device)
        perche' sono copie dirette del singleton: finche' l'istanza le tiene,
        _unload_nllb_singleton() non puo' far scendere il ref count a zero
        e la VRAM resta stuck.
        """
        try:
            self.model = None
            self.tokenizer = None
            self.device = None
            _unload_nllb_singleton()
            self.log(tr('tl_nllb_model_unloaded_from_vram'))
        except Exception as e:
            logger.error(f"Errore durante cleanup NLLB: {e}")
            logger.error(f" ❌ Errore durante cleanup GPU: {e}")


# ============================================================================
# TRADUTTORE LLM LOCALE
# ============================================================================

class LLMSubtitleTranslator(BaseTranslator):
    """Traduttore LLM locale per sottotitoli — adapter sul package
    `core.llm_subtitle_translator`.

    Si chiamava `AyaTranslator` finché Aya era l'unico occupante dello slot.
    Il nome era già impreciso da quando il package è diventato model-agnostic,
    ed è diventato sbagliato del tutto quando Aya è stata rimossa
    (2026-08-18): quale modello ci sia dietro è una chiave di configurazione,
    `llm_translator_model`, oggi TranslateGemma-12B.

    Storicamente questa classe conteneva il proprio prompt e la propria
    generazione. Quel percorso aveva quattro difetti che rendevano la misura
    del modello priva di senso: prompt in raw-completion senza il chat template
    su cui il modello è addestrato, `padding_side` di default che corrompeva ogni
    batch maggiore di uno, `output.split('\\n')[0]` che scartava la seconda
    battuta di ogni dialogo, e un fallback che scriveva la frase inglese
    originale nell'SRT finale.

    Ora la logica sta nel package, che è model-agnostic. La facade pubblica —
    `translate_file(input, output, src_lang, tgt_lang, context)` — non cambia,
    quindi `core/pipeline.py` continua a funzionare senza sapere nulla di
    tutto questo.
    """

    # Mappa codici lingua ISO 639-2/1 → nomi usati nel prompt
    LANGUAGE_CODES = {
        'eng': 'en', 'en': 'en', 'english': 'en',
        'ita': 'it', 'it': 'it', 'italian': 'it',
        'fra': 'fr', 'fr': 'fr', 'fre': 'fr', 'french': 'fr',
        'deu': 'de', 'de': 'de', 'ger': 'de', 'german': 'de',
        'spa': 'es', 'es': 'es', 'spanish': 'es',
        'por': 'pt', 'pt': 'pt', 'portuguese': 'pt',
        'rus': 'ru', 'ru': 'ru', 'russian': 'ru',
        'jpn': 'ja', 'ja': 'ja', 'japanese': 'ja',
        'chi': 'zh', 'zh': 'zh', 'zho': 'zh', 'chinese': 'zh',
        'ara': 'ar', 'ar': 'ar', 'arabic': 'ar',
        'kor': 'ko', 'ko': 'ko', 'korean': 'ko',
        'hin': 'hi', 'hi': 'hi', 'hindi': 'hi',
        'pol': 'pl', 'pl': 'pl', 'polish': 'pl',
        'tur': 'tr', 'tr': 'tr', 'turkish': 'tr',
        'nld': 'nl', 'nl': 'nl', 'dut': 'nl', 'dutch': 'nl',
        'swe': 'sv', 'sv': 'sv', 'swedish': 'sv',
        'dan': 'da', 'da': 'da', 'danish': 'da',
        'nor': 'no', 'no': 'no', 'norwegian': 'no',
        'fin': 'fi', 'fi': 'fi', 'finnish': 'fi',
        'ces': 'cs', 'cs': 'cs', 'cze': 'cs', 'czech': 'cs',
        'hun': 'hu', 'hu': 'hu', 'hungarian': 'hu',
        'ron': 'ro', 'ro': 'ro', 'rum': 'ro', 'romanian': 'ro',
        'ukr': 'uk', 'uk': 'uk', 'ukrainian': 'uk',
        'ell': 'el', 'el': 'el', 'gre': 'el', 'greek': 'el',
        'heb': 'he', 'he': 'he', 'hebrew': 'he',
        'vie': 'vi', 'vi': 'vi', 'vietnamese': 'vi',
        'tha': 'th', 'th': 'th', 'thai': 'th',
        'und': 'en',
    }

    # Il modello è tenuto piccolo apposta: su 12 GB, con NF4, il batch è
    # limitato dalla lunghezza della risposta, non dai pesi.
    DEFAULT_BATCH_SIZE = 12

    # Codice lingua che il prompt di TranslateGemma dichiara come SORGENTE
    # (`source_lang_code` del suo chat template), indipendentemente dalla
    # lingua vera del file:
    #   'en'          = comportamento storico. L'adattatore LoRA e' stato
    #                   addestrato SEMPRE con source_lang_code "en", anche su
    #                   coppie non inglesi: e' la configurazione misurata.
    #   None / 'auto' = usa la lingua sorgente reale (`src` di translate_file).
    #   altra stringa = codice forzato (es. 'fr').
    # Un chiamante puo' cambiarlo su una singola istanza dopo la creazione
    # (`tr.source_label = 'fr'`) senza toccare la classe.
    SOURCE_LABEL: Optional[str] = 'en'

    # Serbatoio (L3) per il ramo LLM: NLLB fine-tuned.
    #
    # MISURATO su 39 righe dense di glossario (15 righe reali del serbatoio di
    # The Ark S03E06 + 24 da altri tre show con glossario attivo), NLLB-FT
    # contro Qwen2.5-14B, giudizio testa a testa nella stessa chiamata:
    #   - NLLB-FT preferito nel 64% dei segmenti contro il 26% di Qwen;
    #   - MQM pesato 1,41 contro 4,31 (più basso è meglio);
    #   - errori di grammatica 3 contro 12, zero critici contro 2, zero
    #     parole lasciate in inglese contro 3.
    # Qwen vince solo sulla conformità al glossario (98% contro 89%), perché
    # le istruzioni in prompt le esegue e NLLB no — ma quel divario si chiude
    # con `_apply_glossary_posthoc`, mentre gli errori di grammatica di Qwen
    # ("stiamo siendo trascinati", "la prossima step", "al diagnosi") no.
    RESERVOIR_DEFAULT = 'nllb_ft'

    def __init__(self, log_callback: Optional[Callable] = None,
                 context: Optional[str] = None,
                 glossary: Optional[Dict[str, str]] = None):
        super().__init__(log_callback, context, glossary)
        # Import LAZY: importare il package a livello di modulo tirerebbe
        # dentro torch/transformers all'avvio della GUI.
        from core.llm_subtitle_translator.engine import (DEFAULT_MODEL_KEY,
                                                         get_engine)
        self._get_engine = get_engine
        self._model_key = self._configured_model(DEFAULT_MODEL_KEY)
        self._adapter = self._configured_adapter()
        self._model_path = self._configured_model_path()
        self._engine = None
        # Copia d'istanza di SOURCE_LABEL: modificabile per singola istanza.
        self.source_label = self.SOURCE_LABEL

    # Forma dei codici ammessi come etichetta forzata: 2-3 lettere, con
    # eventuale sottotipo ('pt_BR' — il chat template sostituisce "_" con "-").
    # Non e' l'elenco delle lingue del template (non si legge il file): e' solo
    # una guardia sulla FORMA contro valori palesemente sbagliati (stringa
    # vuota, numeri, frasi). Le chiavi del template sono sensibili alle
    # maiuscole ('pt-BR') e ci sono solo codici ISO 639-1: per questo i codici
    # a 3 lettere o in maiuscolo ('fra', 'FR') si riportano prima a 639-1 con
    # LANGUAGE_CODES. Un codice ben formato ma assente dal template (es. 'xyz')
    # fa sollevare un errore Jinja: `_translate_mt` lo lascia risalire invece
    # di svuotare in silenzio ogni batch (vedi la', TemplateError).
    _SOURCE_LABEL_RE = re.compile(r'^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?$')

    @staticmethod
    def _resolve_source_label(src: Optional[str],
                              source_label: Optional[str]) -> str:
        """Sceglie il codice lingua sorgente da scrivere nel prompt.

        `source_label` None o 'auto' -> la lingua reale (`src`); qualunque
        altro valore valido -> quel codice (default 'en', comportamento
        storico). Codici 639-2 / maiuscoli ('fra', 'FR') diventano 639-1
        ('fr'). Se il risultato non ha la forma di un codice lingua ricade su
        'en' con un avviso: meglio il prompt storico che un errore del chat
        template su tutti i blocchi del file.
        """
        label = src if source_label in (None, 'auto') else source_label
        if isinstance(label, str):
            label = label.strip()
            label = LLMSubtitleTranslator.LANGUAGE_CODES.get(label.lower(), label)
        if (not isinstance(label, str)
                or not LLMSubtitleTranslator._SOURCE_LABEL_RE.match(label)):
            logger.warning(f"Etichetta lingua sorgente '{label}' non valida: "
                           f"uso 'en'")
            return 'en'
        return label

    @staticmethod
    def _run_with_isolated_unresolved(translator, fn):
        """Esegue `fn` (un giro di traduzione) con `translator.unresolved_ids`
        VUOTO e restituisce (risultato, id bocciati in QUESTO giro); alla fine
        ripristina l'unione con gli id gia' presenti.

        Serve alla fase L2. Prima si calcolava il delta
        `unresolved_ids - seen_before`: ma un blocco gia' bocciato in L1 E di
        nuovo in L2 non e' "nuovo" (aggiungerlo a un set che lo contiene gia'
        non cambia nulla), quindi spariva dal delta e L2 lo promuoveva come
        "recuperato" — proprio il caso che il controllo doveva fermare.
        Trovato il 27/09/2026: su un estratto tedesco e' passato cosi'
        "So, so. So, so. So, so. So, so." con l'audit "recuperati L2: 1".
        Vale per tutte le lingue, inglese compreso.
        """
        before = set(translator.unresolved_ids)
        translator.unresolved_ids = set()
        try:
            result = fn()
            flagged = set(translator.unresolved_ids)
        finally:
            translator.unresolved_ids = before | translator.unresolved_ids
        return result, flagged

    @staticmethod
    def _configured_model(default_key: str) -> str:
        """Quale modello occupa lo slot. Chiave di config, così cambiarlo non
        richiede toccare il codice.

        Ricade sul default in due casi, entrambi reali: la chiave assente o
        nulla (configurazioni anteriori alla sua introduzione) e la chiave che
        nomina un modello non più nel registro — chi aveva scelto Aya
        troverebbe altrimenti un errore di modello sconosciuto al primo file
        della coda.
        """
        from core.llm_subtitle_translator.engine import MODEL_SPECS
        try:
            if get_config:
                chiave = get_config().get('llm_translator_model', None)
                if chiave and chiave in MODEL_SPECS:
                    return chiave
                if chiave:
                    logger.warning(
                        f"Modello LLM '{chiave}' non più disponibile: "
                        f"uso '{default_key}'")
        except Exception:
            pass
        return default_key

    def _configured_adapter(self):
        """Adattatore LoRA da applicare sopra i pesi base, se configurato.

        Una cartella che non esiste NON e' un errore fatale: si prosegue col
        modello base e lo si dice a schermo. Far fallire una coda notturna
        perche' un percorso e' stato spostato costerebbe molto piu' di una
        traduzione fatta col modello non adattato.
        """
        import os
        try:
            if not get_config:
                return None
            p = (get_config().get('llm_translator_adapter', '') or '').strip()
        except Exception:
            return None
        if not p:
            return None
        if not os.path.isdir(p):
            self.log(tr('tl_adapter_not_found_using_the').format(p=p))
            return None
        self.log(tr('tl_lora_adapter').format(basename=os.path.basename(p.rstrip(os.sep))))
        return p

    def _configured_model_path(self):
        """Cartella locale che sovrascrive i pesi base del modello, se
        configurata (llm_translator_model_path). Stessa logica di
        _configured_adapter: un percorso inesistente non è fatale, si
        ricade sul model_id di default dello spec.
        """
        import os
        try:
            if not get_config:
                return None
            p = (get_config().get('llm_translator_model_path', '') or '').strip()
        except Exception:
            return None
        if not p:
            return None
        if not os.path.isdir(p):
            self.log(tr('tl_model_folder_not_found_using').format(p=p))
            return None
        return p

    def _acquire_engine(self):
        """Il motore LLM per questo file. Con `llm_translator_gguf_enabled` spento e' ESATTAMENTE la chiamata storica a
        `get_engine`; acceso (default dal 24/10), decide `path_router` (bf16 / NF4 / GGUF / None = NLLB-FT)."""
        gguf = False
        try:
            from utils.config import Config
            gguf = bool(get_config and get_config().get('llm_translator_gguf_enabled',
                                                      Config.DEFAULTS['llm_translator_gguf_enabled']))
        except Exception:
            gguf = False
        if not gguf:
            import sys as _sys
            gm = _sys.modules.get('core.llm_subtitle_translator.gguf_engine')
            if gm is not None:
                gm.unload_gguf_engine()     # flag spento a meta' coda: libera la VRAM del processo GGUF prima di NF4
            return self._get_engine(self._model_key, self.log_callback,
                                    adapter=self._adapter,
                                    model_path=self._model_path)
        from core.llm_subtitle_translator import path_router
        return path_router.acquire_engine(
            self._model_key, self.log_callback, self._adapter, self._model_path,
            get_engine_fn=self._get_engine, cfg_get=get_config().get, log=self.log)

    def _translate_via_nllb_ft(self, input_path, output_path, src_lang, tgt_lang,
                               context, glossary) -> bool:
        """Ripiego dichiarato del percorso GGUF: traduce tutto il file con NLLB fine-tuned (o NLLB base se il
        fine-tuned non e' utilizzabile), come fa `get_translator('nllb_finetuned')`."""
        try:
            try:
                nllb = NLLBFineTunedTranslator(self.log_callback, self.context, self.glossary)
            except Exception as exc:
                logger.error(f"NLLB fine-tuned non disponibile: {exc}")
                self.log(tr('gg_nllb_ft_unavailable').format(exc=exc))
                nllb = NLLBTranslator(self.log_callback, self.context, self.glossary)
            try:
                return nllb.translate_file(input_path, output_path, src_lang, tgt_lang,
                                           context, glossary)
            finally:
                try:
                    nllb.cleanup()
                except Exception as exc:
                    logger.debug(f"cleanup NLLB di ripiego: {exc}")
        except Exception as exc:
            logger.error(f"Errore nel ripiego NLLB: {exc}", exc_info=True)
            self.log(tr('tl_error').format(exc=exc))
            return False

    def _lang_to_iso(self, lang_code: str) -> Optional[str]:
        result = self.LANGUAGE_CODES.get(lang_code.lower())
        if result is None:
            logger.warning(f"Codice lingua '{lang_code}' non supportato")
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _srt_time_to_seconds(value: str) -> float:
        """'00:01:23,456' → 83.456. Zero se il formato non è riconoscibile."""
        try:
            hms, _, ms = value.strip().replace('.', ',').partition(',')
            hours, minutes, seconds = (int(p) for p in hms.split(':'))
            return hours * 3600 + minutes * 60 + seconds + int(ms or 0) / 1000
        except Exception:
            return 0.0

    def translate_file(self, input_path: Path, output_path: Path,
                       src_lang: str, tgt_lang: str,
                       context: Optional[str] = None,
                       glossary: Optional[Dict[str, str]] = None) -> bool:
        if isinstance(input_path, str):
            input_path = Path(input_path)
        if isinstance(output_path, str):
            output_path = Path(output_path)
        if context is not None:
            self.context = context
        if glossary is not None:
            self.glossary = glossary

        from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
        from core.llm_subtitle_translator.translator import (
            SubtitleLLMTranslator)

        try:
            src = self._lang_to_iso(src_lang)
            tgt = self._lang_to_iso(tgt_lang)
            if not src or not tgt:
                self.log(tr('tl_unsupported_language_code').format(src_lang=src_lang, tgt_lang=tgt_lang))
                return False
            if tgt != 'it':
                self.log(tr('tl_this_engine_only_produces_italian').format(tgt=tgt))
                return False

            subtitles = self._parse_srt(input_path)
            total = len(subtitles)
            if total == 0:
                self.log(tr('tl_srt_file_empty_or_parsing'))
                output_path.write_text("", encoding='utf-8')
                return True

            self.log(tr('tl_subtitle_adaptation').format(src=src, tgt=tgt, model_key=self._model_key))
            self.log(tr('tl_found_subtitles').format(total=total))

            # I placeholder proteggono le note musicali dal modello, e allo
            # stesso modo i termini di glossario (resa italiana fissa).
            # `originals` conserva il testo inglese NON mascherato di ogni
            # blocco: serve ai livelli di recupero L2/L3, che ritraducono
            # senza placeholder, e all'audit finale.
            units, placeholders, passthrough, originals = [], {}, {}, {}
            for index, start, end, text in subtitles:
                originals[index] = text
                gloss_text, gloss_holders = self._mask_glossary(
                    text, "LLM", self.glossary)
                masked, holders, only_masked = self._mask_text(gloss_text, "LLM")
                holders.update(gloss_holders)
                if only_masked or not masked.strip():
                    # Come nel ramo NLLB: una riga fatta SOLO di un termine
                    # di glossario arriva qui con skip=True, ma la resa
                    # fissa va comunque applicata (_unmask_text su testo
                    # senza placeholder di glossario è un no-op).
                    passthrough[index] = (self._unmask_text(masked, holders)
                                          if masked.strip() else text)
                    continue
                placeholders[index] = holders
                duration = max(
                    0.0,
                    self._srt_time_to_seconds(end)
                    - self._srt_time_to_seconds(start))
                units.append(SubtitleUnit(
                    id=index, text=masked, duration=duration,
                    is_dialogue='\n' in masked,
                ))

            engine = self._acquire_engine()
            if engine is None:
                # Percorso GGUF acceso e nessun percorso LLM praticabile su questa scheda: il motivo e' gia'
                # nel log. NLLB fine-tuned traduce il file intero, nessun blocco resta inglese.
                return self._translate_via_nllb_ft(input_path, output_path,
                                                   src_lang, tgt_lang,
                                                   context, glossary)
            self._engine = engine

            # Lingua sorgente dichiarata nel prompt: 'en' di default (come
            # l'adattatore e' stato addestrato), la lingua vera solo se
            # `source_label` e' None/'auto'. Vale per tutti i giri (primo,
            # retry singolo, L2), che passano da `_mt_prompt`.
            _richiesta = getattr(self, 'source_label', self.SOURCE_LABEL)
            label = self._resolve_source_label(src, _richiesta)
            if _richiesta not in (None, 'auto') and label != _richiesta:
                self.log(tr('tl_invalid_source_language_label_using').format(requested=_richiesta, label=label))
            if label != 'en':
                self.log(tr('tl_source_language_in_the_prompt').format(label=label))
            translator = SubtitleLLMTranslator(
                engine=engine,
                fallback=None,   # il ripiego passa dalle fasi B/C sotto
                batch_size=self.DEFAULT_BATCH_SIZE,
                log_callback=self.log,
                glossary=self.glossary,
                source_lang=label,
            )
            translated = translator.translate(units)

            # ------------------------------------------------------------
            # FASE A — risoluzione: unmask TOLLERANTE, nessun ripiego ancora.
            # Tre modi di finire in `pending`, distinti apposta: (1) output
            # vuoto; (2) placeholder di glossario/musica irrecuperabile anche
            # dopo riparazione; (3) `SubtitleLLMTranslator` lo ha già marcato
            # inservibile (copy-through/wrong_language/degenerate sopravvissuti
            # al suo retry interno — vedi UNUSABLE_CODES); (4) rete di
            # sicurezza indipendente: identico all'inglese sorgente anche se
            # l'unmask è "riuscito" (il caso in cui il modello preserva il
            # placeholder intatto ma il resto della frase resta inglese).
            # ------------------------------------------------------------
            resolved: Dict[int, str] = {}
            pending: Dict[int, str] = {}
            n_repaired = 0
            for u in units:
                raw = translated.get(u.id, "").strip()
                if not raw:
                    pending[u.id] = originals[u.id]
                    continue
                out, ok, rip = self._unmask_tolerant(raw, placeholders.get(u.id, {}))
                n_repaired += rip
                if (not ok or u.id in translator.unresolved_ids
                        or self._is_untranslated(out, originals[u.id])):
                    pending[u.id] = originals[u.id]
                    continue
                resolved[u.id] = out

            # ------------------------------------------------------------
            # FASE B — L2: motore primario ANCORA CARICO. Ritraduce il testo
            # inglese ORIGINALE (non mascherato): senza placeholder non c'è
            # più nessun token sintetico da perdere, quindi elimina la causa
            # invece di riprovare con lo stesso input che ha già fallito.
            # Il glossario si applica a posteriori sul risultato.
            # ------------------------------------------------------------
            n_l2 = 0
            confirmed_identical: Dict[int, str] = {}
            if pending:
                self.log(tr('tl_blocks_to_recover_retrying_without').format(n=len(pending)))
                unit_by_id = {u.id: u for u in units}
                retry_units = [
                    SubtitleUnit(
                        id=idx, text=originals[idx],
                        is_dialogue='\n' in originals[idx],
                        duration=unit_by_id[idx].duration
                        if idx in unit_by_id else 0.0)
                    for idx in pending]
                raw_l2, l2_bad = {}, set()
                translator._quiet_bar = True
                try:
                    # Delta di `unresolved_ids`: ciò che il validatore del
                    # motore boccia ANCHE al secondo giro (degenerato, lingua
                    # sbagliata, copy-through) non va accettato solo perché
                    # non è vuoto e non è identico al sorgente — senza questo
                    # controllo L2 poteva promuovere un output peggiore di
                    # quello che stava sostituendo.
                    work, rebuild = translator._expand_dialogue(retry_units)
                    raw_l2, l2_ids = self._run_with_isolated_unresolved(
                        translator, lambda: translator._translate_mt(work))
                    # `_expand_dialogue` conia id sintetici sopra il massimo
                    # degli id che riceve: quelli finiti in `unresolved_ids`
                    # vanno riportati al blocco padre, o il rifiuto colpirebbe
                    # l'id sbagliato.
                    parent_of = {pid: orig
                                 for orig, parts in rebuild.items()
                                 for pid, _ in parts}
                    l2_bad = {parent_of.get(i, i) for i in l2_ids}
                    raw_l2 = translator._rebuild_dialogue(raw_l2, rebuild)
                    from core.llm_subtitle_translator import postprocess
                    raw_l2 = postprocess.process(
                        raw_l2, order=[u.id for u in retry_units],
                        sources={u.id: originals[u.id] for u in retry_units})
                except Exception as exc:
                    logger.warning(f"L2 (retry senza masking) fallito: {exc}")
                    raw_l2 = {}
                finally:
                    translator._quiet_bar = False

                for idx in list(pending):
                    if idx in l2_bad:
                        continue
                    text = (raw_l2.get(idx) or "").strip()
                    if not text:
                        continue
                    text = self._apply_glossary_posthoc(text, originals[idx])
                    if self._is_untranslated(text, originals[idx]):
                        # Due generazioni indipendenti — una con i placeholder,
                        # una senza — hanno prodotto lo stesso testo del
                        # sorgente: è quasi sempre una riga che in italiano
                        # resta davvero identica (nomi propri, interiezioni,
                        # binomi latini: "Turdus merula.", "Mm-hmm."). Uno
                        # swap di modello da 1-2 minuti per queste non si
                        # ripaga, e capitano in quasi ogni episodio. Fuori dal
                        # serbatoio, ma l'audit finale le segnala comunque:
                        # resta "zero invisibile", non diventa "zero rumore".
                        confirmed_identical[idx] = originals[idx]
                        del pending[idx]
                        continue
                    resolved[idx] = text
                    del pending[idx]
                    n_l2 += 1

                if confirmed_identical:
                    self.log(tr('tl_blocks_confirmed_identical_to_the').format(n=len(confirmed_identical)))

            # ------------------------------------------------------------
            # FASE C — L3: serbatoio, un solo swap di modello per tutto ciò
            # che sopravvive a L1+L2 (scarica il 12B, carica Qwen).
            # ------------------------------------------------------------
            n_l3 = 0
            if pending:
                total_units = max(1, len(units))
                if len(pending) > total_units * 0.10:
                    self.log(tr('tl_warning_blocks_to_the_reservoir_2').format(n=len(pending), total_units=total_units))
                for idx, text in self._reservoir_translate(dict(pending)).items():
                    resolved[idx] = text
                    del pending[idx]
                    n_l3 += 1

            # ------------------------------------------------------------
            # FASE D — L4: inglese, ma rumoroso. Con L0-L3 attivi deve
            # restare vuoto; se non lo è, il numero è l'informazione che
            # dice dove intervenire — mai un fallimento silenzioso come
            # prima (il `logger.warning` che non arrivava né a schermo né
            # su file, vedi il fix del logger sopra).
            # ------------------------------------------------------------
            for idx in pending:
                self.log(tr('tl_warning_block_not_translated_stays_2').format(idx=idx, text=originals[idx][:60]))
                resolved[idx] = originals[idx]

            output = []
            for index, start, end, original in subtitles:
                if index in passthrough:
                    output.append((index, start, end, passthrough[index]))
                else:
                    output.append((index, start, end,
                                   resolved.get(index, original)))

            flagged = self._log_audit(
                {i: t for i, _, _, t in output}, originals,
                skip_ids=passthrough.keys(),
                counters={tr('tl_counter_repaired_l1'): n_repaired, tr('tl_counter_recovered_l2'): n_l2,
                         tr('tl_counter_reservoir_l3'): n_l3,
                         tr('tl_counter_confirmed_identical'): len(confirmed_identical)})

            if self._translation_exceeds_error_budget(len(flagged), total):
                return False

            output_path.write_text(self._generate_srt(output),
                                   encoding='utf-8')
            self.log(tr('tl_subtitles_written').format(name=output_path.name))

            return True

        except Exception as exc:
            logger.error(f"Errore nella traduzione LLM: {exc}", exc_info=True)
            self.log(tr('tl_error').format(exc=exc))
            return False

    def cleanup(self):
        """Libera la VRAM occupata dal modello."""
        try:
            from core.llm_subtitle_translator.engine import unload_engine
            self._engine = None
            try:
                unload_engine()
            finally:
                # Il motore GGUF esiste solo se il percorso GGUF e' stato acceso; il modulo si importa soltanto in
                # quel caso (con il flag spento questo blocco non cambia nulla). Scarico indipendente dal primo.
                import sys
                _gguf = sys.modules.get('core.llm_subtitle_translator.gguf_engine')
                if _gguf is not None:
                    _gguf.unload_gguf_engine()
        except Exception as exc:
            logger.error(f"Errore durante cleanup: {exc}")



# ============================================================================
# CLAUDE API TRANSLATOR (CLOUD-BASED, ZERO GPU)
# ============================================================================

class ClaudeTranslator(BaseTranslator):
    """
    Traduttore basato su Claude API di Anthropic
    
    CARATTERISTICHE:
    - Zero requisiti hardware (cloud-based)
    - Qualità traduzione superiore con comprensione contesto
    - Batch processing intelligente (4 sottotitoli per chiamata)
    - Gestione automatica rate limits con retry exponential backoff
    - Supporto nativo per oltre 100 lingue
    - Preservazione automatica formattazione, note musicali, tag HTML
    - Uso contesto TMDB per traduzioni più accurate
    """
    
    # Mappa ISO 639-2/1 a nomi lingua completi (Claude comprende nomi naturali)
    LANGUAGE_CODES = {
        'eng': 'English', 'en': 'English', 'english': 'English',
        'ita': 'Italian', 'it': 'Italian', 'italian': 'Italian',
        'fra': 'French', 'fr': 'French', 'fre': 'French', 'french': 'French',
        'deu': 'German', 'de': 'German', 'ger': 'German', 'german': 'German',
        'spa': 'Spanish', 'es': 'Spanish', 'spanish': 'Spanish',
        'por': 'Portuguese', 'pt': 'Portuguese', 'portuguese': 'Portuguese',
        'rus': 'Russian', 'ru': 'Russian', 'russian': 'Russian',
        'jpn': 'Japanese', 'ja': 'Japanese', 'japanese': 'Japanese',
        'chi': 'Chinese', 'zh': 'Chinese', 'zho': 'Chinese', 'chinese': 'Chinese',
        'ara': 'Arabic', 'ar': 'Arabic', 'arabic': 'Arabic',
        'kor': 'Korean', 'ko': 'Korean', 'korean': 'Korean',
        'hin': 'Hindi', 'hi': 'Hindi', 'hindi': 'Hindi',
        'pol': 'Polish', 'pl': 'Polish', 'polish': 'Polish',
        'tur': 'Turkish', 'tr': 'Turkish', 'turkish': 'Turkish',
        'nld': 'Dutch', 'nl': 'Dutch', 'dut': 'Dutch', 'dutch': 'Dutch',
        'swe': 'Swedish', 'sv': 'Swedish', 'swedish': 'Swedish',
        'dan': 'Danish', 'da': 'Danish', 'danish': 'Danish',
        'nor': 'Norwegian', 'no': 'Norwegian', 'norwegian': 'Norwegian',
        'fin': 'Finnish', 'fi': 'Finnish', 'finnish': 'Finnish',
        'ces': 'Czech', 'cs': 'Czech', 'cze': 'Czech', 'czech': 'Czech',
        'hun': 'Hungarian', 'hu': 'Hungarian', 'hungarian': 'Hungarian',
        'ron': 'Romanian', 'ro': 'Romanian', 'rum': 'Romanian', 'romanian': 'Romanian',
        'ukr': 'Ukrainian', 'uk': 'Ukrainian', 'ukrainian': 'Ukrainian',
        'ell': 'Greek', 'el': 'Greek', 'gre': 'Greek', 'greek': 'Greek',
        'heb': 'Hebrew', 'he': 'Hebrew', 'hebrew': 'Hebrew',
        'vie': 'Vietnamese', 'vi': 'Vietnamese', 'vietnamese': 'Vietnamese',
        'tha': 'Thai', 'th': 'Thai', 'thai': 'Thai',
        'cat': 'Catalan', 'ca': 'Catalan', 'catalan': 'Catalan',
        'bul': 'Bulgarian', 'bg': 'Bulgarian', 'bulgarian': 'Bulgarian',
        'hrv': 'Croatian', 'hr': 'Croatian', 'croatian': 'Croatian',
        'slk': 'Slovak', 'sk': 'Slovak', 'slo': 'Slovak', 'slovak': 'Slovak',
        'slv': 'Slovenian', 'sl': 'Slovenian', 'slovenian': 'Slovenian',
        'und': 'English',
    }
    
    BATCH_SIZE = 4
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2
    MODEL = "claude-sonnet-4-20250514"
    
    def __init__(self, api_key: Optional[str] = None, log_callback: Optional[Callable] = None, 
                 context: Optional[str] = None):
        super().__init__(log_callback, context)
        
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(tr('tl_library_anthropic_not_available_install'))
        
        if api_key is None:
            api_key = self._load_api_key()
        
        if not api_key:
            raise ValueError(tr('tl_claude_api_key_not_found'))
        
        self.client = Anthropic(api_key=api_key)
        self.api_key = api_key
        self.total_api_calls = 0
        self.total_tokens_input = 0
        self.total_tokens_output = 0
        
        self.log(tr('tl_claude_api_translator_initialized_model').format(MODEL=self.MODEL))
    
    def _load_api_key(self) -> Optional[str]:
        try:
            if get_config:
                config = get_config()
                api_key = config.settings.get('claude_api_key', '')
                if api_key and len(api_key) > 20:
                    return api_key
            return None
        except Exception as e:
            logger.error(f"Errore caricamento API key: {e}")
            return None
    
    def _get_language_name(self, lang_code: str) -> str:
        result = self.LANGUAGE_CODES.get(lang_code.lower(), 'English')
        if result == 'English' and lang_code.lower() not in ['eng', 'en', 'english', 'und']:
            logger.warning(f"Codice lingua '{lang_code}' non riconosciuto, uso English")
        return result
    
    def _create_translation_prompt(self, subtitles_batch: List[str], src_lang: str, 
                                   tgt_lang: str, context: Optional[str] = None) -> str:
        context_section = ""
        if context and context.strip():
            context_section = f"\nCONTEXT (movie/show synopsis):\n{context.strip()[:800]}\n\n"
        
        numbered_subtitles = [f"{i}. {sub}" for i, sub in enumerate(subtitles_batch, 1)]
        subtitles_text = "\n".join(numbered_subtitles)
        
        return f"""Translate these movie/TV show subtitles to {tgt_lang}.

{context_section}CRITICAL RULES:
1. TRANSLATE ALL TEXT to {tgt_lang}, regardless of source language(s)
2. If subtitles contain MULTIPLE languages (English, Japanese, Spanish, etc.), translate ALL of them to {tgt_lang}
3. DO NOT ask questions, DO NOT explain, DO NOT comment - JUST TRANSLATE
4. Preserve ALL formatting: line breaks, dashes (-), ellipsis (...), punctuation
5. Keep musical notes (♪) EXACTLY as they appear - DO NOT translate text between ♪...♪
6. Use natural, colloquial {tgt_lang} appropriate for spoken dialogue
7. Preserve speaker identification (like "JOHN:", "- Mary:")
8. Keep HTML tags if present (like <i>, <b>)
9. Return ONLY the numbered translations (1., 2., 3., etc.) - NO explanations, NO questions

IMPORTANT: Even if the source language appears inconsistent or mixed, your job is ONLY to translate everything to {tgt_lang}.

SUBTITLES TO TRANSLATE:
{subtitles_text}

Provide translations as a numbered list matching the input format exactly. DO NOT include any text other than the translations."""
    
    def _parse_claude_response(self, response_text: str, expected_count: int) -> List[str]:
        translations = []
        pattern = r'^\s*\d+\.\s*(.+)$'
        
        for line in response_text.split('\n'):
            match = re.match(pattern, line.strip())
            if match:
                translations.append(match.group(1).strip())
        
        if len(translations) == 0:
            translations = [line.strip() for line in response_text.split('\n') 
                          if line.strip() and not line.strip().startswith('#')]
        
        if len(translations) < expected_count:
            translations.extend([''] * (expected_count - len(translations)))
        elif len(translations) > expected_count:
            translations = translations[:expected_count]
        
        return translations
    
    def _is_valid_translation(self, response_text: str) -> bool:
        """
        Verifica se la risposta di Claude è una traduzione valida
        e non una domanda o spiegazione
        
        Returns:
            True se valida, False se contiene domande/spiegazioni
        """
        # Pattern che indicano che Claude sta facendo domande invece di tradurre
        question_patterns = [
            "could you please",
            "i notice",
            "there's a mismatch",
            "should i translate",
            "do you have",
            "can you clarify",
            "i'm not sure",
            "which language",
            "could you confirm",
            "it seems like",
            "the subtitles you provided",
            "appears to be",
            "inconsistent",
        ]
        
        response_lower = response_text.lower()
        
        # Se la risposta contiene questi pattern, non è una traduzione valida
        for pattern in question_patterns:
            if pattern in response_lower:
                logger.warning(f"Claude ha fatto domande invece di tradurre: contiene '{pattern}'")
                return False
        
        return True
    
    def _create_aggressive_translation_prompt(self, subtitles_batch: List[str], 
                                              tgt_lang: str, context: Optional[str] = None) -> str:
        """
        Prompt ultra-imperativo per retry quando Claude fa domande invece di tradurre.
        Rimuove completamente il riferimento alla lingua sorgente.
        """
        context_section = ""
        if context and context.strip():
            context_section = f"\nMOVIE/SHOW CONTEXT:\n{context.strip()[:800]}\n\n"
        
        numbered_subtitles = [f"{i}. {sub}" for i, sub in enumerate(subtitles_batch, 1)]
        subtitles_text = "\n".join(numbered_subtitles)
        
        return f"""TRANSLATE TO {tgt_lang} - NO QUESTIONS ALLOWED

{context_section}YOU ARE A TRANSLATION MACHINE. Your ONLY job is to translate text to {tgt_lang}.

ABSOLUTE RULES:
- DO NOT ask questions
- DO NOT explain anything  
- DO NOT comment on source language
- TRANSLATE EVERYTHING to {tgt_lang}, regardless of what language(s) the input is in
- Japanese? Translate to {tgt_lang}
- English? Translate to {tgt_lang}
- Mixed languages? Translate ALL to {tgt_lang}
- Unknown language? Still translate to {tgt_lang}

FORMAT RULES:
- Keep line breaks, dashes (-), ellipsis (...)
- Keep musical notes ♪ unchanged
- Keep speaker names (JOHN:, - Mary:)
- Keep HTML tags (<i>, <b>)

INPUT TEXT:
{subtitles_text}

OUTPUT: Return ONLY numbered translations (1., 2., 3., etc.). Nothing else. No questions. No explanations."""
    
    def _translate_batch_with_retry(self, subtitles_batch: List[str], src_lang: str, 
                                    tgt_lang: str, context: Optional[str] = None) -> List[str]:
        prompt = self._create_translation_prompt(subtitles_batch, src_lang, tgt_lang, context)
        
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.client.messages.create(
                    model=self.MODEL,
                    max_tokens=2048,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                response_text = response.content[0].text
                self.total_api_calls += 1
                self.total_tokens_input += response.usage.input_tokens
                self.total_tokens_output += response.usage.output_tokens
                
                # Valida che la risposta sia una traduzione e non domande
                if not self._is_valid_translation(response_text):
                    if attempt < self.MAX_RETRIES - 1:
                        self.log(tr('tl_claude_asked_questions_instead_of'))
                        # Prompt ancora più aggressivo per il retry
                        prompt = self._create_aggressive_translation_prompt(subtitles_batch, tgt_lang, context)
                        time.sleep(self.RETRY_DELAY_BASE)
                        continue
                    else:
                        # Ultimo tentativo fallito, usa sottotitoli originali come fallback
                        self.log(tr('tl_claude_keeps_asking_questions_using'))
                        return subtitles_batch
                
                return self._parse_claude_response(response_text, len(subtitles_batch))
                
            except RateLimitError:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAY_BASE * (2 ** attempt)
                    self.log(tr('tl_api_rate_limit_waiting_s').format(delay=delay))
                    time.sleep(delay)
                else:
                    raise
            
            except (APIError, APIConnectionError) as e:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY_BASE)
                else:
                    raise
        
        raise RuntimeError(tr('tl_translation_failed_after_attempts').format(MAX_RETRIES=self.MAX_RETRIES))
    
    def translate_file(self, input_path: Path, output_path: Path, 
                      src_lang: str, tgt_lang: str, context: Optional[str] = None) -> bool:
        try:
            # Converti stringhe a Path se necessario (per compatibilità con pipeline)
            if isinstance(input_path, str):
                input_path = Path(input_path)
            if isinstance(output_path, str):
                output_path = Path(output_path)
            
            subtitles, dash_flags = self._extract_dash_flags(
            self._parse_srt(input_path)
        )
            total = len(subtitles)
            
            if total == 0:
                self.log(tr('tl_empty_file').format(name=input_path.name))
                return False
            
            src_lang_name = self._get_language_name(src_lang)
            tgt_lang_name = self._get_language_name(tgt_lang)
            translation_context = context if context else self.context
            
            self.log(tr('tl_translation').format(name=input_path.name))
            self.log(tr('tl_subtitles').format(src_lang_name=src_lang_name, tgt_lang_name=tgt_lang_name, total=total))
            if translation_context:
                self.log(tr('tl_tmdb_context'))
            
            self.total_api_calls = 0
            self.total_tokens_input = 0
            self.total_tokens_output = 0
            
            translated_subtitles = []
            i = 0
            last_progress = -1
            _eta_tr = None

            while i < total:
                batch_end = min(i + self.BATCH_SIZE, total)
                batch = subtitles[i:batch_end]
                batch_texts = [text for _, _, _, text in batch]

                progress = int((i / total) * 100)
                if progress != last_progress:
                    from utils.events import emit as _tp_emit
                    if _eta_tr is None:
                        from utils.eta import EtaEstimator
                        _eta_tr = EtaEstimator()
                    _eta_txt = _eta_tr.update(i / total)
                    _tp_emit('bar', phase='translate', pct=progress, eta_s=_eta_tr.eta_seconds())
                    self.log(tr('tl_progress').format(progress=progress, i=i, total=total, eta_txt=_eta_txt))
                    last_progress = progress

                try:
                    translated_texts = self._translate_batch_with_retry(
                        batch_texts, src_lang_name, tgt_lang_name, translation_context
                    )

                    for j, (idx, start, end, _) in enumerate(batch):
                        translated_text = translated_texts[j] if j < len(translated_texts) else batch_texts[j]
                        translated_subtitles.append((idx, start, end, translated_text))
                    
                except Exception as e:
                    logger.error(f"Errore batch {i}-{batch_end}: {e}")
                    self.log(tr('tl_batch_error_using_the_original'))
                    translated_subtitles.extend(batch)
                
                i = batch_end

            from utils.events import emit as _tp_emit
            _tp_emit('bar', phase='translate', pct=100)
            self.log(tr('tl_progress_100').format(total=total))
            srt_content = self._generate_srt(translated_subtitles, dash_flags)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            self.log(tr('tl_completed').format(name=output_path.name))
            self.log(tr('tl_api_calls_tokens_in_out').format(total_api_calls=self.total_api_calls, total_tokens_input=self.total_tokens_input, total_tokens_output=self.total_tokens_output))
            
            return True
            
        except Exception as e:
            self.log(tr('tl_error_2').format(e=e))
            logger.error(f"Errore traduzione: {e}", exc_info=True)
            return False
    
    def cleanup(self):
        self.log(tr('tl_claude_session_calls_tokens').format(total_api_calls=self.total_api_calls, total_tokens_input=self.total_tokens_input, total_tokens_output=self.total_tokens_output))


# ============================================================================
# NLLB FINE-TUNED TRANSLATOR
# ============================================================================

class NLLBFineTunedTranslator(NLLBTranslator):
    """
    Traduttore NLLB-200 fine-tuned su dataset sottotitoli Plex.
    Identico a NLLBTranslator ma carica il modello locale fine-tuned
    invece del modello base da HuggingFace Hub.
    """

    def __init__(self, log_callback=None, context=None, glossary=None):
        # Bypassa NLLBTranslator.__init__ (che carica il modello base)
        # e usa direttamente le risorse fine-tuned
        BaseTranslator.__init__(self, log_callback, context, glossary)
        self.model, self.tokenizer, self.device = _get_nllb_ft_resources()

        from utils.adaptive_batch_manager import AdaptiveBatchSizeManager
        cfg = get_config().get_adaptive_batch_config() if get_config else {}

        def _batch_log(msg: str):
            logger.debug(msg)
            if 'Warm-up' in msg:
                self.log(msg)

        # Stesso cap del NLLBTranslator base (vedi commento lì) — il modello
        # fine-tuned ha lo stesso footprint VRAM del base.
        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=self.use_gpu,
            initial_size=cfg.get('initial_size'),
            min_size=cfg.get('min_size', self.MIN_BATCH_SIZE),
            max_size=min(cfg.get('max_size', self.MAX_BATCH_SIZE), self.MAX_BATCH_SIZE),
            warmup_batches=cfg.get('warmup_batches', 5),
            high_threshold=cfg.get('high_threshold', 0.85),
            low_threshold=cfg.get('low_threshold', 0.60),
            log_callback=_batch_log,
        )
        self.current_batch_size = self.batch_manager.current_batch_size

    def cleanup(self):
        """Scarica modello NLLB fine-tuned dalla VRAM (override: usa singleton FT, non base).

        Azzera prima le reference dell'istanza (self.model/tokenizer/device)
        e il batch_manager: sono copie/consumer diretti del singleton. Senza
        questo azzeramento il ref count del modello non scende a zero e
        _unload_nllb_ft_singleton() non libera la VRAM.
        """
        try:
            self.model = None
            self.tokenizer = None
            self.device = None
            self.batch_manager = None
            _unload_nllb_ft_singleton()
            self.log(tr('tl_fine_tuned_nllb_model_unloaded'))
        except Exception as e:
            logger.error(f"Errore durante cleanup NLLB FT: {e}")


# ============================================================================
# OPENAI API TRANSLATOR (CLOUD-BASED, ZERO GPU)
# ============================================================================

class OpenAITranslator(BaseTranslator):
    """
    Traduttore basato su OpenAI API (GPT-4o / GPT-4o-mini)

    CARATTERISTICHE:
    - Zero requisiti hardware (cloud-based)
    - Alta qualità con GPT-4o, economico con GPT-4o-mini
    - Batch processing (4 sottotitoli per chiamata)
    - Gestione automatica rate limits con retry exponential backoff
    - Supporto nativo per 50+ lingue
    """

    LANGUAGE_CODES = ClaudeTranslator.LANGUAGE_CODES

    BATCH_SIZE = 4
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2
    DEFAULT_MODEL = 'gpt-4o-mini'
    VALID_MODELS = ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo']

    def __init__(self, api_key=None, model=None, log_callback=None, context=None):
        super().__init__(log_callback, context)
        if not OPENAI_AVAILABLE:
            raise ImportError(tr('tl_library_openai_not_available_install'))
        if api_key is None:
            api_key = self._load_api_key()
        if not api_key:
            raise ValueError(tr('tl_openai_api_key_not_found'))
        self.client = OpenAIClient(api_key=api_key)
        self.model = model or self._load_model()
        self.total_calls = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.log(tr('tl_openai_translator_initialized_model').format(model=self.model))

    def _load_api_key(self):
        try:
            if get_config:
                cfg = get_config()
                key = cfg.get_openai_api_key()
                return key if key and len(key) > 20 else None
        except Exception:
            pass
        return None

    def _load_model(self):
        try:
            if get_config:
                return get_config().get_openai_model()
        except Exception:
            pass
        return self.DEFAULT_MODEL

    def _get_language_name(self, lang_code: str) -> str:
        result = self.LANGUAGE_CODES.get(lang_code.lower(), 'English')
        if result == 'English' and lang_code.lower() not in ['eng', 'en', 'english', 'und']:
            logger.warning(f"Codice lingua '{lang_code}' non riconosciuto, uso English")
        return result

    def _create_translation_prompt(self, subtitles_batch: List[str], src_lang: str,
                                   tgt_lang: str, context: Optional[str] = None) -> str:
        context_section = ""
        if context and context.strip():
            context_section = f"\nCONTEXT (movie/show synopsis):\n{context.strip()[:800]}\n\n"

        numbered_subtitles = [f"{i}. {sub}" for i, sub in enumerate(subtitles_batch, 1)]
        subtitles_text = "\n".join(numbered_subtitles)

        return f"""Translate these movie/TV show subtitles to {tgt_lang}.

{context_section}CRITICAL RULES:
1. TRANSLATE ALL TEXT to {tgt_lang}, regardless of source language(s)
2. If subtitles contain MULTIPLE languages, translate ALL of them to {tgt_lang}
3. DO NOT ask questions, DO NOT explain, DO NOT comment - JUST TRANSLATE
4. Preserve ALL formatting: line breaks, dashes (-), ellipsis (...), punctuation
5. Keep musical notes (\u266a) EXACTLY as they appear - DO NOT translate text between \u266a...\u266a
6. Use natural, colloquial {tgt_lang} appropriate for spoken dialogue
7. Preserve speaker identification (like "JOHN:", "- Mary:")
8. Keep HTML tags if present (like <i>, <b>)
9. Return ONLY the numbered translations (1., 2., 3., etc.) - NO explanations

SUBTITLES TO TRANSLATE:
{subtitles_text}

Provide translations as a numbered list matching the input format exactly. DO NOT include any text other than the translations."""

    def _parse_response(self, response_text: str, expected_count: int) -> List[str]:
        translations = []
        pattern = r'^\s*\d+\.\s*(.+)$'

        for line in response_text.split('\n'):
            match = re.match(pattern, line.strip())
            if match:
                translations.append(match.group(1).strip())

        if len(translations) == 0:
            translations = [line.strip() for line in response_text.split('\n')
                            if line.strip() and not line.strip().startswith('#')]

        if len(translations) < expected_count:
            translations.extend([''] * (expected_count - len(translations)))
        elif len(translations) > expected_count:
            translations = translations[:expected_count]

        return translations

    def _translate_batch_with_retry(self, subtitles_batch: List[str], src_lang: str,
                                    tgt_lang: str, context: Optional[str] = None) -> List[str]:
        prompt = self._create_translation_prompt(subtitles_batch, src_lang, tgt_lang, context)

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2048,
                    temperature=0.3,
                )

                response_text = response.choices[0].message.content
                self.total_calls += 1
                if response.usage:
                    self.total_tokens_in += response.usage.prompt_tokens
                    self.total_tokens_out += response.usage.completion_tokens

                return self._parse_response(response_text, len(subtitles_batch))

            except OpenAIRateLimitError:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAY_BASE * (2 ** attempt)
                    self.log(tr('tl_api_rate_limit_waiting_s').format(delay=delay))
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY_BASE)
                else:
                    raise

        raise RuntimeError(tr('tl_translation_failed_after_attempts').format(MAX_RETRIES=self.MAX_RETRIES))

    def translate_file(self, input_path: Path, output_path: Path,
                       src_lang: str, tgt_lang: str, context: Optional[str] = None) -> bool:
        try:
            if isinstance(input_path, str):
                input_path = Path(input_path)
            if isinstance(output_path, str):
                output_path = Path(output_path)

            subtitles, dash_flags = self._extract_dash_flags(
            self._parse_srt(input_path)
        )
            total = len(subtitles)

            if total == 0:
                self.log(tr('tl_empty_file').format(name=input_path.name))
                return False

            src_lang_name = self._get_language_name(src_lang)
            tgt_lang_name = self._get_language_name(tgt_lang)
            translation_context = context if context else self.context

            self.log(tr('tl_translation').format(name=input_path.name))
            self.log(tr('tl_subtitles').format(src_lang_name=src_lang_name, tgt_lang_name=tgt_lang_name, total=total))
            if translation_context:
                self.log(tr('tl_tmdb_context'))

            self.total_calls = 0
            self.total_tokens_in = 0
            self.total_tokens_out = 0

            translated_subtitles = []
            i = 0
            last_progress = -1
            _eta_tr = None

            while i < total:
                batch_end = min(i + self.BATCH_SIZE, total)
                batch = subtitles[i:batch_end]
                batch_texts = [text for _, _, _, text in batch]

                progress = int((i / total) * 100)
                if progress != last_progress:
                    from utils.events import emit as _tp_emit
                    if _eta_tr is None:
                        from utils.eta import EtaEstimator
                        _eta_tr = EtaEstimator()
                    _eta_txt = _eta_tr.update(i / total)
                    _tp_emit('bar', phase='translate', pct=progress, eta_s=_eta_tr.eta_seconds())
                    self.log(tr('tl_progress').format(progress=progress, i=i, total=total, eta_txt=_eta_txt))
                    last_progress = progress

                try:
                    translated_texts = self._translate_batch_with_retry(
                        batch_texts, src_lang_name, tgt_lang_name, translation_context
                    )
                    for j, (idx, start, end, _) in enumerate(batch):
                        translated_text = translated_texts[j] if j < len(translated_texts) else batch_texts[j]
                        translated_subtitles.append((idx, start, end, translated_text))
                except Exception as e:
                    logger.error(f"Errore batch {i}-{batch_end}: {e}")
                    self.log(tr('tl_batch_error_using_the_original'))
                    translated_subtitles.extend(batch)

                i = batch_end

            from utils.events import emit as _tp_emit
            _tp_emit('bar', phase='translate', pct=100)
            self.log(tr('tl_progress_100').format(total=total))
            srt_content = self._generate_srt(translated_subtitles, dash_flags)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            self.log(tr('tl_completed').format(name=output_path.name))
            self.log(tr('tl_api_calls_tokens_in_out_2').format(total_calls=self.total_calls, total_tokens_in=self.total_tokens_in, total_tokens_out=self.total_tokens_out))

            return True

        except Exception as e:
            self.log(tr('tl_error_2').format(e=e))
            logger.error(f"Errore traduzione OpenAI: {e}", exc_info=True)
            return False

    def cleanup(self):
        self.log(tr('tl_openai_session_calls_tokens').format(total_calls=self.total_calls, total_tokens_in=self.total_tokens_in, total_tokens_out=self.total_tokens_out))


# ============================================================================
# FACTORY E LEGACY FUNCTIONS (DA MANTENERE FUORI DALLE CLASSI)
# ============================================================================

def route_non_english_away_from_llm(selected_model: Optional[str],
                                    source_lang_639_1: str) -> Optional[str]:
    """Instradamento automatico (v1.25.0): se il motore scelto e' TranslateGemma
    ('llm'/'aya') e la sorgente non e' inglese, ricade su NLLB fine-tuned.

    Funzione condivisa (nessuna dipendenza da ProcessingPipeline/torch a livello
    di chiamata): usata sia dalla coda principale (`core/pipeline.py`) sia dal
    percorso OCR bitmap (`core/ocr_auto.py`, condiviso con Library Scanner), che
    altrimenti passerebbe di nascosto una lingua non inglese a TranslateGemma.

    TranslateGemma e' stato addestrato SEMPRE con source_lang_code "en" (vedi
    Gemma training/make_dataset.py): su sorgenti diverse dichiara una lingua
    falsa nel prompt. Misurato il 27/09/2026 su 140 blocchi francesi: NLLB
    fine-tuned batte sia l'etichetta storica 'en' sia quella vera 'fr' (che
    dimezza il francese residuo ma peggiora la fluidita' oltre la soglia della
    regola di misura). Verificato che ogni codice lingua accettato da
    `LLMSubtitleTranslator.LANGUAGE_CODES` e' anche chiave di
    `NLLBTranslator.LANGUAGE_CODES` (incluso 'und'): nessun codice orfano.
    Non tocca la scelta esplicita dell'utente per gli altri motori (NLLB base,
    Claude, OpenAI, OpenSubtitles): dichiarano gia' la lingua sorgente vera nel
    loro prompt. Vedi memoria traduzione_non_inglese_2026_09_27.md.
    """
    if (selected_model or '').lower() in ('llm', 'aya') and source_lang_639_1 != 'en':
        return 'nllb_finetuned'
    return selected_model


def get_translator(model_type: Optional[str] = None, context: Optional[str] = None,
                  use_aya: Optional[bool] = None,
                  glossary: Optional[Dict[str, str]] = None) -> BaseTranslator:
    """
    Factory function per ottenere il traduttore appropriato.

    Args:
        model_type: 'nllb', 'nllb_finetuned', 'llm', 'claude', 'openai',
                    'opensubtitles', o None (usa config)
        context: Contesto opzionale (es. sinossi TMDB) per migliorare traduzione
        use_aya: [DEPRECATO] Usa model_type='llm' invece
        glossary: Resa italiana fissa per termini ricorrenti (core/glossary.py).
            Applicato solo ai motori NLLB e LLM locale: gli altri (Claude,
            OpenAI, OpenSubtitles) lo ignorano — fuori scope, non richiesto.

    Returns:
        Istanza del traduttore appropriato
    """
    # Gestisci backward compatibility con use_aya
    if use_aya is not None:
        logger.warning("Parametro 'use_aya' deprecato, usa 'model_type' invece")
        model_type = 'llm' if use_aya else 'nllb'
    
    # Determina modello da usare
    if model_type is None:
        # Carica da config
        if get_config:
            try:
                config = get_config()
                model_type = config.get_translation_model()
                logger.info(f"Factory: Modello da config: {model_type.upper()}")
            except Exception as e:
                logger.warning(f"Impossibile caricare config: {e}, uso NLLB default")
                model_type = 'nllb'
        else:
            model_type = 'nllb'
    
    model_type = model_type.lower()
    
    # Crea traduttore appropriato
    if model_type == 'claude':
        if not ANTHROPIC_AVAILABLE:
            logger.error("Libreria 'anthropic' non disponibile, fallback su NLLB")
            logger.error("Installare con: pip install anthropic")
            return NLLBTranslator(context=context, glossary=glossary)
        
        logger.info("Factory: Creazione ClaudeTranslator")
        try:
            return ClaudeTranslator(context=context)
        except (ImportError, ValueError) as e:
            logger.error(f"Impossibile creare ClaudeTranslator: {e}")
            logger.error("Fallback su NLLBTranslator")
            return NLLBTranslator(context=context, glossary=glossary)
    
    elif model_type in ('llm', 'aya'):
        # 'aya' resta accettata perché è il valore salvato nelle
        # configurazioni esistenti: chi aveva scelto quel motore non deve
        # ritrovarsi la traduzione rotta al primo avvio dopo l'aggiornamento.
        # Il modello che occupa lo slot è `llm_translator_model`.
        if model_type == 'aya':
            logger.info("Factory: 'aya' è un valore storico, ora significa "
                        "'llm' (modello da llm_translator_model)")
        logger.info("Factory: Creazione LLMSubtitleTranslator")
        return LLMSubtitleTranslator(context=context, glossary=glossary)
    
    elif model_type == 'nllb_finetuned':
        logger.info("Factory: Creazione NLLBFineTunedTranslator")
        try:
            return NLLBFineTunedTranslator(context=context, glossary=glossary)
        except Exception as e:
            logger.error(f"Impossibile creare NLLBFineTunedTranslator: {e}")
            logger.error("Fallback su NLLBTranslator base")
            return NLLBTranslator(context=context, glossary=glossary)

    elif model_type == 'opensubtitles':
        logger.info("Factory: Creazione OpenSubtitlesAITranslator")
        try:
            from utils.opensubtitles_ai_translator import OpenSubtitlesAITranslator
            if get_config:
                cfg = get_config()
                creds = cfg.get_opensubtitles_credentials() or {}
            else:
                creds = {}
            if not creds.get('api_key'):
                logger.warning("OpenSubtitles AI: credenziali mancanti, fallback su NLLB")
                return NLLBTranslator(context=context, glossary=glossary)
            from utils.subtitle_uploader_interface import OPENSUBTITLES_USER_AGENT
            return OpenSubtitlesAITranslator(
                api_key=creds['api_key'],
                username=creds.get('username', ''),
                password=creds.get('password', ''),
                user_agent=creds.get('user_agent', OPENSUBTITLES_USER_AGENT),
                context=context,
            )
        except Exception as e:
            logger.error(f"Impossibile creare OpenSubtitlesAITranslator: {e}")
            logger.error("Fallback su NLLBTranslator")
            return NLLBTranslator(context=context, glossary=glossary)

    elif model_type == 'openai':
        logger.info("Factory: Creazione OpenAITranslator")
        if not OPENAI_AVAILABLE:
            logger.error("Libreria 'openai' non disponibile, fallback su NLLB")
            return NLLBTranslator(context=context, glossary=glossary)
        try:
            return OpenAITranslator(context=context)
        except (ImportError, ValueError) as e:
            logger.error(f"Impossibile creare OpenAITranslator: {e}, fallback su NLLB")
            return NLLBTranslator(context=context, glossary=glossary)

    else:  # 'nllb' o default
        logger.info("Factory: Creazione NLLBTranslator")
        return NLLBTranslator(context=context, glossary=glossary)

def get_nllb_translator(log_callback: Optional[Callable] = None, context: Optional[str] = None) -> NLLBTranslator:
    """Legacy function per ottenere solo il traduttore NLLB."""
    return NLLBTranslator(log_callback=log_callback, context=context)


