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
e controlli di qualitÃ  per eliminare allucinazioni e ripetizioni infinite)

CORREZIONI v5.4:
âœ… FIX CRITICO: Parametri anti-ripetizione
   - repetition_penalty=1.2 per penalizzare ripetizioni
   - no_repeat_ngram_size=3 per impedire ripetizioni di trigrammi
   - TEMPERATURE ridotto a 0.3 per output piÃ¹ deterministico
   - MAX_NEW_TOKENS ridotto a 150 (piÃ¹ appropriato per sottotitoli)
âœ… FIX CRITICO: Controlli di qualitÃ  output
   - Rilevamento ripetizioni eccessive (pattern ripetuto >3 volte)
   - Controllo lunghezza anomala (>3x originale)
   - Fallback su testo originale per output problematici
âœ… MIGLIORAMENTO: Prompt semplificato e piÃ¹ diretto
âœ… MIGLIORAMENTO: early_stopping=True per fermare alla generazione EOS
âœ… MIGLIORAMENTO: Batch size ridotto a 8 per maggiore stabilitÃ 

CORREZIONI v5.3:
âœ… FIX CRITICO: Corretta estrazione traduzione in _run_translation()
   - Estrae solo i token generati dal modello (outputs[:, input_length:])
   - Elimina il metodo fragile output.replace(prompt, '')

FUNZIONALITÃ€ v5.2:
âœ… Impedita l'invio di stringhe vuote/solo contenuti mascherati
âœ… Controllo esplicito allucinazione ("# non lo so #") con fallback
âœ… Logica di copia dell'originale gestita robustamente
âœ… Caricamento token HuggingFace per i modelli gated
"""
import logging
import torch
import re
import time
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Dict, Any
from abc import ABC, abstractmethod
# NOTE: ÃƒË† necessario installare bitsandbytes e accelerate per la quantizzazione
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

logger = logging.getLogger(__name__)

# --- MODIFICA v5.2: Importa get_config per caricare il token ---
try:
    from utils.config import get_config
except ImportError:
    # Fallback nel caso in cui il file venga eseguito da solo
    logger.warning("Impossibile importare 'utils.config'. Il caricamento di modelli gated fallirÃƒÂ .")
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
    
    def __init__(self, log_callback: Optional[Callable] = None, context: Optional[str] = None):
        """
        Inizializza il traduttore
        
        Args:
            log_callback: Callback opzionale per logging verso GUI
            context: Contesto opzionale (es. sinossi film/episodio) per migliorare la traduzione
        """
        self.log_callback = log_callback
        self.use_gpu = torch.cuda.is_available()
        self.device = 'cuda' if self.use_gpu else 'cpu'
        self.context = context
        
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
            placeholder = f" <[{model_prefix}_MUSIC_PRESERVE_{index}]> "
            placeholders[placeholder] = match.group(0)
            return placeholder

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
        
        # 2. Verifica se il testo rimanente, una volta ripulito dagli spazi, ÃƒÂ¨ vuoto.
        text_without_placeholders = masked_text
        for placeholder in placeholders:
            text_without_placeholders = text_without_placeholders.replace(placeholder, ' ') 
        
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

    def _unmask_text(self, translated_text: str, placeholders_map: Dict[str, str]) -> str:
        """
        Re-inserisce il contenuto originale non tradotto dai placeholder.
        """
        post_processed_result = translated_text
        
        for placeholder, original_content in placeholders_map.items():
            post_processed_result = post_processed_result.replace(placeholder, original_content)
            
        return post_processed_result.strip()


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
                            device_map="auto",
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
                            device_map="auto",
                            low_cpu_mem_usage=True
                        )
                else:
                    _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
                    _nllb_model.to(_device)

                _nllb_model.eval()

                logger.info(f"-> Modello NLLB caricato su {_device}")
            except Exception as e:
                logger.critical(f"Ã¢ÂÅ’ Errore caricamento NLLB-200: {e}")
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
                    "Path modello NLLB fine-tuned non configurata. "
                    "Impostala in: Modelli → NLLB Fine-Tuned (Plex)"
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
                            device_map="auto",
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
                            device_map="auto",
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

    # Parametri ottimizzati per qualitÃƒÂ  / performance
    NO_REPEAT_NGRAM_SIZE = 3
    MAX_LENGTH_SENTENCE = 256

    # Batch Size Adattivo (RTX 3060 12GB VRAM)
    BATCH_SIZE_ADAPTIVE = 12
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 24

    def __init__(self, log_callback: Optional[Callable] = None, context: Optional[str] = None):
        """Inizializza il traduttore NLLB usando l'istanza singleton"""
        super().__init__(log_callback, context)
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
        # 'adaptive_batch_max_size' è condivisa con la trascrizione whisper
        # (dove 62 ha senso) — qui, lasciata passare senza tetto, ha spinto
        # il batch a 36+ con beam=7 su un modello già da ~6.6GB in VRAM,
        # causando spillover in RAM condivisa WDDM (stesso bug corretto in
        # v1.9.2 per faster_whisper_engine, qui mancava il cap analogo).
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
                    final_text, placeholders, only_masked = self._mask_text(line, "NLLB")
                    unit_specs.append((j, line_idx))
                    texts_to_translate.append(final_text)
                    current_batch_placeholders.append(placeholders)
                    skip_translation_flags.append(only_masked)
                    unit_original_texts.append(line)
            else:
                final_text, placeholders, only_masked = self._mask_text(text, "NLLB")
                unit_specs.append((j, None))
                texts_to_translate.append(final_text)
                current_batch_placeholders.append(placeholders)
                skip_translation_flags.append(only_masked)
                unit_original_texts.append(text)

        return (unit_specs, texts_to_translate, current_batch_placeholders,
                skip_translation_flags, unit_original_texts)

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

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos_token_id,
                    num_beams=get_config().get_nllb_num_beams(),
                    no_repeat_ngram_size=self.NO_REPEAT_NGRAM_SIZE,
                    max_length=self.MAX_LENGTH_SENTENCE
                )
            
            translations = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)
            return translations
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                self.batch_manager.record_oom()
                self.current_batch_size = self.batch_manager.current_batch_size

                if self.batch_manager.current_batch_size > self.MIN_BATCH_SIZE or self.current_batch_size > self.MIN_BATCH_SIZE:
                    raise Exception("Out of Memory - Batch Size Ridotto")
                else:
                    self.log(f"   OPS! OOM critico con batch_size=1. Memoria GPU insufficiente.")
                    raise Exception("Out of Memory - GPU Memoria Insufficiente")
            else:
                raise


    def translate_file(self, input_path: Path, output_path: Path,
                      src_lang: str, tgt_lang: str, context: Optional[str] = None) -> bool:
        """
        Traduce file SRT da lingua sorgente a lingua target
        """
        # Converti stringhe a Path se necessario (per compatibilità con pipeline)
        if isinstance(input_path, str):
            input_path = Path(input_path)
        if isinstance(output_path, str):
            output_path = Path(output_path)
        
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
            self.log(f"  🌐 Traduzione NLLB ({model_label}, {load_mode}): {src_lang} → {tgt_lang} | beams:{num_beams}")

            if self._prepared_context:
                # Non "attivo": ricevuto e ignorato di proposito. Vedi la nota
                # in `_run_translation`.
                self.log("  📖 Contesto dell'opera ricevuto — NLLB non lo usa "
                         "(traduce segmento per segmento)")

            src_nllb = self._nllb_to_iso(src_lang)
            tgt_nllb = self._nllb_to_iso(tgt_lang)

            if not src_nllb or not tgt_nllb:
                self.log(f"  ❌ Codice lingua non supportato: {src_lang} o {tgt_lang}")
                return False

            parsed_subtitles, dash_flags = self._extract_dash_flags(
                self._parse_srt(input_path)
            )
            total = len(parsed_subtitles)
            translated_subtitles = []

            if total == 0:
                self.log("  File SRT vuoto o parsing fallito")
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write("")
                return True

            self.log(f"  📋 Trovati {total} sottotitoli da tradurre")

            self.batch_manager.reset()
            self.current_batch_size = self.batch_manager.current_batch_size
            is_first_batch = True

            import time as _time
            t0 = _time.time()
            # Barra iniziale (aggiornata in-place dal pattern "Traduzione: [")
            self.log(f"  🌐 Traduzione: [░░░░░░░░░░]   0% (0/{total}) │ batch:-")

            i = 0
            last_progress = -1
            max_retries_per_batch = 3

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
                    self.log(f"  🌐 Traduzione: [{bar}] {progress:3d}% ({i}/{total}) │ batch:{bs}")
                    last_progress = progress

                retries = 0
                batch_success = False
                
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
                                unit_result = unit_original

                            else:
                                if translated_index < len(results):
                                    translated_text = results[translated_index]

                                    if translated_text.strip().lower() == "# non lo so #":
                                         self.log(f"   ATTENZIONE: Rilevata allucinazione per riga {index}. Mantengo originale.")
                                         unit_result = unit_original
                                    else:
                                        unit_result = self._unmask_text(translated_text, placeholders_map)

                                    translated_index += 1

                                else:
                                    self.log(f"   ATTENZIONE: Nessun output NLLB per riga {index}. Mantengo originale.")
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
                        retries += 1

                        if 'Out of Memory - Batch Size Ridotto' in str(e):
                            self.log(f"   Retry #{retries}/{max_retries_per_batch} con batch size ridotto...")
                            self.current_batch_size = self.batch_manager.current_batch_size
                            batch = parsed_subtitles[i:i + self.current_batch_size]
                            (unit_specs, texts_to_translate, current_batch_placeholders,
                             skip_translation_flags, unit_original_texts) = self._build_translation_units(
                                batch, dash_flags)

                        elif 'Out of Memory - GPU Memoria Insufficiente' in str(e):
                            self.log(f" ERRORE CRITICO: GPU memoria insufficiente. Batch saltato.")
                            for item in batch:
                                translated_subtitles.append(item)
                            is_first_batch = False
                            i += len(batch)
                            break

                        else:
                            self.log(f" Errore sconosciuto nel batch ({str(e)[:100]}). Batch saltato.")
                            for item in batch:
                                translated_subtitles.append(item)
                            is_first_batch = False
                            i += len(batch)
                            break

                if not batch_success and retries >= max_retries_per_batch:
                    self.log(f" Batch fallito dopo {max_retries_per_batch} tentativi. Mantengo originali.")
                    for item in batch:
                        translated_subtitles.append(item)
                    is_first_batch = False
                    i += len(batch)

            elapsed = _time.time() - t0
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            self.log(f"  ✅ Traduzione: [██████████] 100% ({total}/{total}) │ {time_str}")

            self.batch_manager.log_summary()
            srt_content = self._generate_srt(translated_subtitles, dash_flags)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            return True
            
        except Exception as e:
            error_msg = f" Ã¢ÂÅ’ Errore traduzione file {output_path.name}: {e}"
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
            self.log("  ✅ Modello NLLB scaricato dalla VRAM")
        except Exception as e:
            logger.error(f"Errore durante cleanup NLLB: {e}")
            logger.error(f" Ã¢ÂÅ’ Errore durante cleanup GPU: {e}")


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

    def __init__(self, log_callback: Optional[Callable] = None,
                 context: Optional[str] = None):
        super().__init__(log_callback, context)
        # Import LAZY: importare il package a livello di modulo tirerebbe
        # dentro torch/transformers all'avvio della GUI.
        from core.llm_subtitle_translator.engine import (DEFAULT_MODEL_KEY,
                                                         get_engine)
        self._get_engine = get_engine
        self._model_key = self._configured_model(DEFAULT_MODEL_KEY)
        self._engine = None

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
                       context: Optional[str] = None) -> bool:
        if isinstance(input_path, str):
            input_path = Path(input_path)
        if isinstance(output_path, str):
            output_path = Path(output_path)
        if context is not None:
            self.context = context

        from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
        from core.llm_subtitle_translator.translator import (
            SubtitleLLMTranslator)

        try:
            src = self._lang_to_iso(src_lang)
            tgt = self._lang_to_iso(tgt_lang)
            if not src or not tgt:
                self.log(f" Codice lingua non supportato: {src_lang}/{tgt_lang}")
                return False
            if tgt != 'it':
                self.log(f" Questo motore produce solo italiano, non '{tgt}'")
                return False

            subtitles = self._parse_srt(input_path)
            total = len(subtitles)
            if total == 0:
                self.log("  File SRT vuoto o parsing fallito")
                output_path.write_text("", encoding='utf-8')
                return True

            self.log(f" Adattamento sottotitoli {src} → {tgt} "
                     f"({self._model_key})")
            self.log(f"  Trovati {total} sottotitoli")

            # I placeholder proteggono le note musicali dal modello.
            units, placeholders, passthrough = [], {}, {}
            for index, start, end, text in subtitles:
                masked, holders, only_masked = self._mask_text(text, "LLM")
                if only_masked or not masked.strip():
                    passthrough[index] = text
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

            engine = self._get_engine(self._model_key, self.log_callback)
            self._engine = engine

            translator = SubtitleLLMTranslator(
                engine=engine,
                fallback=None,   # il ripiego gira dopo, a modello scaricato
                batch_size=self.DEFAULT_BATCH_SIZE,
                log_callback=self.log,
            )
            translated = translator.translate(units)

            # Blocchi che il modello non è riuscito a produrre: si affidano al
            # traduttore di base, ma solo DOPO aver liberato la VRAM — due
            # modelli da 8B insieme non stanno in 12 GB.
            unresolved = [u for u in units
                          if not translated.get(u.id, "").strip()]
            if unresolved:
                self.log(f"  {len(unresolved)} blocchi al traduttore di "
                         f"riserva")
                self.cleanup()
                for index, text in self._fallback_translate(
                        unresolved, src_lang, tgt_lang).items():
                    translated[index] = text

            output = []
            for index, start, end, original in subtitles:
                if index in passthrough:
                    output.append((index, start, end, passthrough[index]))
                    continue
                text = translated.get(index, "").strip()
                if not text:
                    logger.warning(f"Blocco {index} non tradotto")
                    text = original
                elif placeholders.get(index):
                    text = self._unmask_text(text, placeholders[index])
                output.append((index, start, end, text))

            output_path.write_text(self._generate_srt(output),
                                   encoding='utf-8')
            self.log(f"  Sottotitoli scritti: {output_path.name}")
            return True

        except Exception as exc:
            logger.error(f"Errore nella traduzione LLM: {exc}", exc_info=True)
            self.log(f"  Errore: {exc}")
            return False

    def _fallback_translate(self, units, src_lang, tgt_lang) -> Dict[int, str]:
        """Traduce con NLLB fine-tuned i blocchi che l'LLM non ha risolto."""
        try:
            base = NLLBFineTunedTranslator(self.log_callback)
        except Exception as exc:
            logger.error(f"Traduttore di riserva non disponibile: {exc}")
            return {}

        try:
            src = base._nllb_to_iso(src_lang) if hasattr(
                base, '_nllb_to_iso') else 'eng_Latn'
            tgt = 'ita_Latn'
            texts = [u.text for u in units]
            results = base._run_translation(texts, src, tgt, add_context=False)
            return {u.id: t for u, t in zip(units, results)}
        except Exception as exc:
            logger.error(f"Traduttore di riserva fallito: {exc}")
            return {}
        finally:
            try:
                base.cleanup()
            except Exception:
                pass

    def cleanup(self):
        """Libera la VRAM occupata dal modello."""
        try:
            from core.llm_subtitle_translator.engine import unload_engine
            self._engine = None
            unload_engine()
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
            raise ImportError("Libreria 'anthropic' non disponibile. Installare con: pip install anthropic")
        
        if api_key is None:
            api_key = self._load_api_key()
        
        if not api_key:
            raise ValueError("API key Claude non trovata. Configurare in Settings.")
        
        self.client = Anthropic(api_key=api_key)
        self.api_key = api_key
        self.total_api_calls = 0
        self.total_tokens_input = 0
        self.total_tokens_output = 0
        
        self.log(f"Claude API Translator inizializzato (Modello: {self.MODEL})")
    
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
                        self.log(f"   ⚠️ Claude ha fatto domande invece di tradurre, riprovo con prompt più chiaro...")
                        # Prompt ancora più aggressivo per il retry
                        prompt = self._create_aggressive_translation_prompt(subtitles_batch, tgt_lang, context)
                        time.sleep(self.RETRY_DELAY_BASE)
                        continue
                    else:
                        # Ultimo tentativo fallito, usa sottotitoli originali come fallback
                        self.log(f"   ⚠️ Claude continua a fare domande, uso sottotitoli originali per questo batch")
                        return subtitles_batch
                
                return self._parse_claude_response(response_text, len(subtitles_batch))
                
            except RateLimitError:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAY_BASE * (2 ** attempt)
                    self.log(f"⏳ Rate limit API, attesa {delay}s...")
                    time.sleep(delay)
                else:
                    raise
            
            except (APIError, APIConnectionError) as e:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY_BASE)
                else:
                    raise
        
        raise RuntimeError(f"Traduzione fallita dopo {self.MAX_RETRIES} tentativi")
    
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
                self.log(f"⚠️ File vuoto: {input_path.name}")
                return False
            
            src_lang_name = self._get_language_name(src_lang)
            tgt_lang_name = self._get_language_name(tgt_lang)
            translation_context = context if context else self.context
            
            self.log(f"📝 Traduzione: {input_path.name}")
            self.log(f"   {src_lang_name} → {tgt_lang_name} | Sottotitoli: {total}")
            if translation_context:
                self.log(f"   Contesto TMDB: ✓")
            
            self.total_api_calls = 0
            self.total_tokens_input = 0
            self.total_tokens_output = 0
            
            translated_subtitles = []
            i = 0
            last_progress = -1

            while i < total:
                batch_end = min(i + self.BATCH_SIZE, total)
                batch = subtitles[i:batch_end]
                batch_texts = [text for _, _, _, text in batch]

                progress = int((i / total) * 100)
                if progress != last_progress:
                    self.log(f"   Progresso: {progress}% ({i}/{total})")
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
                    self.log(f"⚠️ Errore batch, uso originale")
                    translated_subtitles.extend(batch)
                
                i = batch_end

            self.log(f"   Progresso: 100% ({total}/{total})")
            srt_content = self._generate_srt(translated_subtitles, dash_flags)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            self.log(f"✅ Completato: {output_path.name}")
            self.log(f"   API calls: {self.total_api_calls} | Tokens: {self.total_tokens_input:,} in, {self.total_tokens_output:,} out")
            
            return True
            
        except Exception as e:
            self.log(f"❌ Errore: {e}")
            logger.error(f"Errore traduzione: {e}", exc_info=True)
            return False
    
    def cleanup(self):
        self.log(f"📊 Sessione Claude: {self.total_api_calls} calls, {self.total_tokens_input:,} + {self.total_tokens_output:,} tokens")


# ============================================================================
# NLLB FINE-TUNED TRANSLATOR
# ============================================================================

class NLLBFineTunedTranslator(NLLBTranslator):
    """
    Traduttore NLLB-200 fine-tuned su dataset sottotitoli Plex.
    Identico a NLLBTranslator ma carica il modello locale fine-tuned
    invece del modello base da HuggingFace Hub.
    """

    def __init__(self, log_callback=None, context=None):
        # Bypassa NLLBTranslator.__init__ (che carica il modello base)
        # e usa direttamente le risorse fine-tuned
        BaseTranslator.__init__(self, log_callback, context)
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
            self.log("  ✅ Modello NLLB fine-tuned scaricato dalla VRAM")
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
            raise ImportError("Libreria 'openai' non disponibile. Installare con: pip install openai")
        if api_key is None:
            api_key = self._load_api_key()
        if not api_key:
            raise ValueError("OpenAI API key non trovata. Configurare in Settings.")
        self.client = OpenAIClient(api_key=api_key)
        self.model = model or self._load_model()
        self.total_calls = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.log(f"OpenAI Translator inizializzato (Modello: {self.model})")

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
                    self.log(f"\u23f3 Rate limit API, attesa {delay}s...")
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY_BASE)
                else:
                    raise

        raise RuntimeError(f"Traduzione fallita dopo {self.MAX_RETRIES} tentativi")

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
                self.log(f"\u26a0\ufe0f File vuoto: {input_path.name}")
                return False

            src_lang_name = self._get_language_name(src_lang)
            tgt_lang_name = self._get_language_name(tgt_lang)
            translation_context = context if context else self.context

            self.log(f"\U0001f4dd Traduzione: {input_path.name}")
            self.log(f"   {src_lang_name} \u2192 {tgt_lang_name} | Sottotitoli: {total}")
            if translation_context:
                self.log(f"   Contesto TMDB: \u2713")

            self.total_calls = 0
            self.total_tokens_in = 0
            self.total_tokens_out = 0

            translated_subtitles = []
            i = 0
            last_progress = -1

            while i < total:
                batch_end = min(i + self.BATCH_SIZE, total)
                batch = subtitles[i:batch_end]
                batch_texts = [text for _, _, _, text in batch]

                progress = int((i / total) * 100)
                if progress != last_progress:
                    self.log(f"   Progresso: {progress}% ({i}/{total})")
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
                    self.log(f"\u26a0\ufe0f Errore batch, uso originale")
                    translated_subtitles.extend(batch)

                i = batch_end

            self.log(f"   Progresso: 100% ({total}/{total})")
            srt_content = self._generate_srt(translated_subtitles, dash_flags)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            self.log(f"\u2705 Completato: {output_path.name}")
            self.log(f"   API calls: {self.total_calls} | Tokens: {self.total_tokens_in:,} in, {self.total_tokens_out:,} out")

            return True

        except Exception as e:
            self.log(f"\u274c Errore: {e}")
            logger.error(f"Errore traduzione OpenAI: {e}", exc_info=True)
            return False

    def cleanup(self):
        self.log(f"\U0001f4ca Sessione OpenAI: {self.total_calls} calls, {self.total_tokens_in:,} + {self.total_tokens_out:,} tokens")


# ============================================================================
# FACTORY E LEGACY FUNCTIONS (DA MANTENERE FUORI DALLE CLASSI)
# ============================================================================

def get_translator(model_type: Optional[str] = None, context: Optional[str] = None, 
                  use_aya: Optional[bool] = None) -> BaseTranslator:
    """
    Factory function per ottenere il traduttore appropriato.
    
    Args:
        model_type: 'nllb', 'nllb_finetuned', 'llm', 'claude', 'openai',
                    'opensubtitles', o None (usa config)
        context: Contesto opzionale (es. sinossi TMDB) per migliorare traduzione
        use_aya: [DEPRECATO] Usa model_type='llm' invece

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
            return NLLBTranslator(context=context)
        
        logger.info("Factory: Creazione ClaudeTranslator")
        try:
            return ClaudeTranslator(context=context)
        except (ImportError, ValueError) as e:
            logger.error(f"Impossibile creare ClaudeTranslator: {e}")
            logger.error("Fallback su NLLBTranslator")
            return NLLBTranslator(context=context)
    
    elif model_type in ('llm', 'aya'):
        # 'aya' resta accettata perché è il valore salvato nelle
        # configurazioni esistenti: chi aveva scelto quel motore non deve
        # ritrovarsi la traduzione rotta al primo avvio dopo l'aggiornamento.
        # Il modello che occupa lo slot è `llm_translator_model`.
        if model_type == 'aya':
            logger.info("Factory: 'aya' è un valore storico, ora significa "
                        "'llm' (modello da llm_translator_model)")
        logger.info("Factory: Creazione LLMSubtitleTranslator")
        return LLMSubtitleTranslator(context=context)
    
    elif model_type == 'nllb_finetuned':
        logger.info("Factory: Creazione NLLBFineTunedTranslator")
        try:
            return NLLBFineTunedTranslator(context=context)
        except Exception as e:
            logger.error(f"Impossibile creare NLLBFineTunedTranslator: {e}")
            logger.error("Fallback su NLLBTranslator base")
            return NLLBTranslator(context=context)

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
                return NLLBTranslator(context=context)
            return OpenSubtitlesAITranslator(
                api_key=creds['api_key'],
                username=creds.get('username', ''),
                password=creds.get('password', ''),
                user_agent=creds.get('user_agent', 'TranscriberPro v1.1.0'),
                context=context,
            )
        except Exception as e:
            logger.error(f"Impossibile creare OpenSubtitlesAITranslator: {e}")
            logger.error("Fallback su NLLBTranslator")
            return NLLBTranslator(context=context)

    elif model_type == 'openai':
        logger.info("Factory: Creazione OpenAITranslator")
        if not OPENAI_AVAILABLE:
            logger.error("Libreria 'openai' non disponibile, fallback su NLLB")
            return NLLBTranslator(context=context)
        try:
            return OpenAITranslator(context=context)
        except (ImportError, ValueError) as e:
            logger.error(f"Impossibile creare OpenAITranslator: {e}, fallback su NLLB")
            return NLLBTranslator(context=context)

    else:  # 'nllb' o default
        logger.info("Factory: Creazione NLLBTranslator")
        return NLLBTranslator(context=context)

def get_nllb_translator(log_callback: Optional[Callable] = None, context: Optional[str] = None) -> NLLBTranslator:
    """Legacy function per ottenere solo il traduttore NLLB."""
    return NLLBTranslator(log_callback=log_callback, context=context)


