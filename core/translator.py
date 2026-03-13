"""
Translator - MULTI-MODEL ARCHITECTURE (NLLB + Aya-23-8B + Claude API)
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

VERSIONE: v5.4 - FIX ALLUCINAZIONI E RIPETIZIONI AYA
(Riscrittura completa della generazione Aya con parametri anti-ripetizione
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
âœ… Caricamento token HuggingFace per Aya-23-8B (Gated Repo)
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
    
    def _generate_srt(self, subtitles: List[SRT_SUBTITLE]) -> str:
        """
        Genera contenuto SRT da lista sottotitoli
        
        Args:
            subtitles: Lista di tuple (index, start_time, end_time, text)
            
        Returns:
            Stringa contenuto SRT formattato
        """
        srt_content = []
        for index, start, end, text in subtitles:
            srt_content.append(f"{index}")
            srt_content.append(f"{start} --> {end}")
            srt_content.append(text)
            srt_content.append("")
        
        return "\n".join(srt_content)

    def _mask_text(self, text: str, model_prefix: str) -> Tuple[str, Dict[str, str], bool]:
        """
        Maschera il testo per la traduzione, preservando blocchi specifici.

        Logica:
        - I blocchi tra Ã¢â„¢Âª...Ã¢â„¢Âª sono *sempre* mascherati e preservati (copia esatta).
        - I blocchi tra [...] non vengono mascherati, ma sono gestiti dalla traduzione
          del modello (verranno tradotti all'interno delle quadre).

        Args:
            text: Testo del sottotitolo originale.
            model_prefix: Prefisso unico per il placeholder (e.g., 'NLLB' o 'AYA').

        Returns:
            Tuple: (Testo da tradurre, Mappa dei placeholder {placeholder: contenuto originale}, Solo contenuti mascherati)
        """
        placeholders = {}
        
        # 1. Maschera il testo tra Ã¢â„¢Âª...Ã¢â„¢Âª per impedirne la traduzione e garantirne la copia esatta.
        # Usa un placeholder XML-like piÃƒÂ¹ robusto
        def masking_replacer(match):
            index = len(placeholders) 
            placeholder = f" <[{model_prefix}_MUSIC_PRESERVE_{index}]> " # Aggiungi spazi per isolare
            placeholders[placeholder] = match.group(0)
            return placeholder

        # Regex (non-greedy, multi-line) che cattura tutto tra le due note, incluse le singole note
        masked_text = re.sub(r'Ã¢â„¢Âª.*?Ã¢â„¢Âª', masking_replacer, text, flags=re.DOTALL)
        
        # 2. Verifica se il testo rimanente, una volta ripulito dagli spazi, ÃƒÂ¨ vuoto.
        text_without_placeholders = masked_text
        for placeholder in placeholders:
            text_without_placeholders = text_without_placeholders.replace(placeholder, ' ') 
        
        text_without_placeholders_cleaned = re.sub(r'^-', '', text_without_placeholders).strip()
        
        only_masked = text_without_placeholders_cleaned == ""

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
                            torch_dtype=torch.float16,
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
    """Scarica il modello NLLB base dalla VRAM (thread-safe)."""
    global _nllb_model, _nllb_tokenizer
    with _nllb_lock:
        if _nllb_model is not None:
            del _nllb_model
            _nllb_model = None
        if _nllb_tokenizer is not None:
            del _nllb_tokenizer
            _nllb_tokenizer = None
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
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
                            torch_dtype=torch.float16,
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
    """Scarica il modello NLLB fine-tuned dalla VRAM (thread-safe)."""
    global _nllb_ft_model, _nllb_ft_tokenizer
    with _nllb_ft_lock:
        if _nllb_ft_model is not None:
            del _nllb_ft_model
            _nllb_ft_model = None
        if _nllb_ft_tokenizer is not None:
            del _nllb_ft_tokenizer
            _nllb_ft_tokenizer = None
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
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
        'fra': 'fra_Latn', 'fr': 'fr_Latn', 'fre': 'fra_Latn', 'french': 'fra_Latn',
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
        'und': 'eng_Latn', 
    }

    # Parametri ottimizzati per qualitÃƒÂ  / performance
    NUM_BEAMS = 7 
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

        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=self.use_gpu,
            initial_size=cfg.get('initial_size'),
            min_size=cfg.get('min_size', self.MIN_BATCH_SIZE),
            max_size=cfg.get('max_size', self.MAX_BATCH_SIZE),
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

    def _run_translation(self, texts: List[str], src_lang: str, tgt_lang: str, add_context: bool = True) -> List[str]:
        """
        Esegue traduzione batch con gestione OOM dinamica
        """
        if add_context and self._prepared_context:
            texts = [self._prepared_context + text for text in texts]
        
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
                    num_beams=self.NUM_BEAMS,
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
        
        if not isinstance(output_path, Path):
            try:
                output_path = Path(output_path)
            except Exception as e:
                error_msg = f"Ã¢ÂÅ’ Errore conversione output_path in Path: {e}"
                self.log(error_msg)
                logger.error(error_msg, exc_info=True)
                return False

        try:
            model_label = 'FT' if isinstance(self, NLLBFineTunedTranslator) else 'base'
            load_mode = 'fp16' if (self.use_gpu and torch.cuda.mem_get_info()[0] / 1024**3 >= 7.0) else '8-bit'
            self.log(f"  🌐 Traduzione NLLB ({model_label}, {load_mode}): {src_lang} → {tgt_lang} | beams:{self.NUM_BEAMS}")

            if self._prepared_context:
                context_preview = self._prepared_context[:70].replace('\n', ' ')
                self.log(f"  📖 Context attivo: {context_preview}...")

            src_nllb = self._nllb_to_iso(src_lang)
            tgt_nllb = self._nllb_to_iso(tgt_lang)

            if not src_nllb or not tgt_nllb:
                self.log(f"  ❌ Codice lingua non supportato: {src_lang} o {tgt_lang}")
                return False

            parsed_subtitles = self._parse_srt(input_path)
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
                texts_to_translate: List[str] = []
                current_batch_placeholders: List[Dict[str, str]] = []
                skip_translation_flags: List[bool] = []
                original_texts: List[str] = [item[3] for item in batch]

                for text in original_texts:
                    final_text, placeholders, only_masked = self._mask_text(text, "NLLB")

                    texts_to_translate.append(final_text)
                    current_batch_placeholders.append(placeholders)
                    skip_translation_flags.append(only_masked)

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
                        post_processed_results = []
                        for j, (index, start, end, original_text) in enumerate(batch):
                            final_text_to_translate = texts_to_translate[j]
                            placeholders_map = current_batch_placeholders[j]

                            if skip_translation_flags[j] or not final_text_to_translate.strip():
                                post_processed_results.append(original_text)
                            
                            else:
                                if translated_index < len(results):
                                    translated_text = results[translated_index]
                                    
                                    if translated_text.strip().lower() == "# non lo so #":
                                         self.log(f"   ATTENZIONE: Rilevata allucinazione per riga {index}. Mantengo originale.")
                                         post_processed_results.append(original_text)
                                    else:
                                        final_text = self._unmask_text(translated_text, placeholders_map)
                                        post_processed_results.append(final_text)
                                        
                                    translated_index += 1
                                    
                                else:
                                    self.log(f"   ATTENZIONE: Nessun output NLLB per riga {index}. Mantengo originale.")
                                    post_processed_results.append(original_text)
                                    
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
                            original_texts = [item[3] for item in batch]
                            texts_to_translate, current_batch_placeholders, skip_translation_flags = [], [], []
                            for text in original_texts:
                                final_text, placeholders, only_masked = self._mask_text(text, "NLLB")
                                texts_to_translate.append(final_text)
                                current_batch_placeholders.append(placeholders)
                                skip_translation_flags.append(only_masked)

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
            srt_content = self._generate_srt(translated_subtitles)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            return True
            
        except Exception as e:
            error_msg = f" Ã¢ÂÅ’ Errore traduzione file {output_path.name}: {e}"
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            return False
    
    def cleanup(self):
        """Scarica modello NLLB base dalla VRAM."""
        try:
            _unload_nllb_singleton()
            self.log("  ✅ Modello NLLB scaricato dalla VRAM")
        except Exception as e:
            logger.error(f"Errore durante cleanup NLLB: {e}")
            logger.error(f" Ã¢ÂÅ’ Errore durante cleanup GPU: {e}")


# ============================================================================
# AYA TRANSLATOR (NEW)
# ============================================================================

# Variabili globali singleton Aya
_aya_model = None
_aya_tokenizer = None
_aya_lock = Lock()


def _load_aya_model(model_name: str = "CohereForAI/aya-23-8B"):
    """
    Carica il modello e il tokenizer Aya una sola volta (thread-safe)
    """
    global _aya_model, _aya_tokenizer
    
    if _aya_model is None:
        with _aya_lock:
            if _aya_model is not None:
                return

            try:
                # --- MODIFICA v5.2: Carica il token dalla config ---
                token = None
                if get_config:
                    try:
                        config = get_config()
                        token = config.get_huggingface_token()
                        if token:
                            logger.info("  -> Token HuggingFace trovato. Autenticazione in corso...")
                        else:
                            logger.warning("  -> Token HuggingFace non trovato. Tentativo anonimo.")
                    except Exception as e:
                        logger.error(f"  -> Errore durante il caricamento del config: {e}")
                else:
                     logger.warning("  -> get_config non disponibile. Tentativo anonimo.")
                # --- FINE MODIFICA ---
                
                logger.info(f"-> Caricamento modello Aya-23-8B: {model_name}...")
                if _use_gpu:
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()

                # Carica tokenizer
                _aya_tokenizer = AutoTokenizer.from_pretrained(
                    model_name,
                    trust_remote_code=True,
                    token=token  # <--- AGGIUNTO TOKEN
                )
                
                logger.info("  -> Caricamento CausalLM (decoder-only)...")
                
                # Configurazione 8-bit ottimizzata per RTX 3060 (BitsAndBytesConfig)
                quantization_config = BitsAndBytesConfig(
                    load_in_8bit=True,
                    llm_int8_threshold=6.0,
                    llm_int8_has_fp16_weight=False,
                    llm_int8_enable_fp32_cpu_offload=True
                ) if _use_gpu else None
                
                # Gestione memoria: RTX 3060 12GB -> Riserva 10GB per modello, 2GB per overhead
                max_memory = {0: "10GiB", "cpu": "16GiB"} if _use_gpu else None
                
                _aya_model = AutoModelForCausalLM.from_pretrained(
                    model_name,
                    quantization_config=quantization_config,
                    device_map="auto" if _use_gpu else None,
                    max_memory=max_memory,
                    low_cpu_mem_usage=True,
                    trust_remote_code=True,
                    token=token  # <--- AGGIUNTO TOKEN
                )
                
                # Imposta pad_token se mancante (necessario per batch)
                if _aya_tokenizer.pad_token is None:
                    _aya_tokenizer.pad_token = _aya_tokenizer.eos_token
                    _aya_model.config.pad_token_id = _aya_tokenizer.eos_token_id
                    logger.info("  -> pad_token configurato")
                
                if not _use_gpu and _aya_model:
                    _aya_model.to(_device)
                
                _aya_model.eval()

                logger.info(f"-> Modello Aya caricato su {_device} (8-bit)")
            except Exception as e:
                logger.critical(f"Ã¢ÂÅ’ Errore caricamento Aya-23-8B: {e}")
                _aya_model = None
                _aya_tokenizer = None
                raise


def _get_aya_translator_resources():
    """Ritorna modello, tokenizer e device globali Aya"""
    if _aya_model is None or _aya_tokenizer is None:
        _load_aya_model()
    return _aya_model, _aya_tokenizer, _device


def _unload_aya_singleton():
    """Scarica il modello Aya-23-8B dalla VRAM (thread-safe)."""
    global _aya_model, _aya_tokenizer
    with _aya_lock:
        if _aya_model is not None:
            del _aya_model
            _aya_model = None
        if _aya_tokenizer is not None:
            del _aya_tokenizer
            _aya_tokenizer = None
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    logger.info("-> Aya-23-8B scaricato dalla VRAM")


class AyaTranslator(BaseTranslator):
    """
    Traduttore Aya-23-8B con BATCH SIZE ADATTIVO
    """
    
    # Mappa codici lingua ISO 639-2/1 → codici Aya
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
    
    # Parametri di generazione Aya (Decoder-only) - OTTIMIZZATI per evitare ripetizioni
    TEMPERATURE = 0.3  # Ridotto per output piÃ¹ deterministico
    TOP_P = 0.85  # Ridotto leggermente
    MAX_NEW_TOKENS = 150  # Ridotto per sottotitoli (piÃ¹ appropriato)
    REPETITION_PENALTY = 1.2  # Penalizza fortemente le ripetizioni
    NO_REPEAT_NGRAM_SIZE = 3  # Impedisce ripetizione di trigrammi
    
    # Batch Size Adattivo (RTX 3060 12GB VRAM)
    BATCH_SIZE_ADAPTIVE = 8  # Ridotto per maggiore stabilitÃ 
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 10

    def __init__(self, log_callback: Optional[Callable] = None, context: Optional[str] = None):
        """Inizializza il traduttore Aya usando l'istanza singleton"""
        super().__init__(log_callback, context)
        self.model, self.tokenizer, self.device = _get_aya_translator_resources()

        from utils.adaptive_batch_manager import AdaptiveBatchSizeManager
        cfg = get_config().get_adaptive_batch_config() if get_config else {}
        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=self.use_gpu,
            initial_size=cfg.get('initial_size'),
            min_size=cfg.get('min_size', self.MIN_BATCH_SIZE),
            max_size=cfg.get('max_size', self.MAX_BATCH_SIZE),
            warmup_batches=cfg.get('warmup_batches', 5),
            high_threshold=cfg.get('high_threshold', 0.85),
            low_threshold=cfg.get('low_threshold', 0.60),
            log_callback=self.log,
        )
        self.current_batch_size = self.batch_manager.current_batch_size
    
    def _aya_to_iso(self, lang_code: str) -> Optional[str]:
        """Converte codice ISO 639-2/1 in codice Aya"""
        result = self.LANGUAGE_CODES.get(lang_code.lower(), None)
        if result is None:
            logger.warning(f"Codice lingua '{lang_code}' non trovato in LANGUAGE_CODES")
        return result
    
    def _create_prompt(self, text: str, src_lang_code: str, tgt_lang_code: str) -> str:
        """
        Crea il prompt di traduzione in formato Aya con contesto opzionale.
        Prompt ottimizzato per evitare allucinazioni e ripetizioni.
        """
        src_name = next((k for k, v in self.LANGUAGE_CODES.items() if v == src_lang_code and len(k) > 2), src_lang_code).capitalize()
        tgt_name = next((k for k, v in self.LANGUAGE_CODES.items() if v == tgt_lang_code and len(k) > 2), tgt_lang_code).capitalize()

        context_prefix = ""
        if self._prepared_context:
            context_prefix = self._prepared_context

        # Prompt semplificato e diretto
        prompt = (
            f"{context_prefix}Translate from {src_name} to {tgt_name}:\n{text}\nTranslation:"
        )
        return prompt

    def _run_translation(self, texts: List[str], src_lang: str, tgt_lang: str) -> List[str]:
        """
        Esegue traduzione batch con gestione OOM dinamica e anti-ripetizione (Aya - Decoder Only)
        """
        prompts = [self._create_prompt(text, src_lang, tgt_lang) for text in texts]
        
        try:
            inputs = self.tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512  # Ridotto per stabilitÃ 
            ).to(self.device)
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    do_sample=True,  # Abilita sampling per temperatura
                    temperature=self.TEMPERATURE,
                    top_p=self.TOP_P,
                    max_new_tokens=self.MAX_NEW_TOKENS,
                    repetition_penalty=self.REPETITION_PENALTY,  # Anti-ripetizione
                    no_repeat_ngram_size=self.NO_REPEAT_NGRAM_SIZE,  # Impedisce ripetizione trigrammi
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    early_stopping=True  # Ferma quando genera EOS
                )
            
            # CORREZIONE: Estrai solo i token generati, non l'intero output (prompt + generazione)
            input_length = inputs.input_ids.shape[1]
            generated_tokens = outputs[:, input_length:]
            
            # Decodifica solo la parte generata
            decoded_outputs = self.tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)
            
            translations = []
            for i, output in enumerate(decoded_outputs):
                # Pulisci l'output: prendi solo la prima riga e rimuovi spazi
                translation = output.split('\n')[0].strip()
                
                # CONTROLLI DI QUALITÃ€ per evitare allucinazioni
                if not translation:
                    # Se vuoto, usa originale
                    logger.warning(f"Output vuoto per testo #{i+1}, uso originale")
                    translations.append(texts[i])
                    continue
                
                # Controlla ripetizioni eccessive (stesso pattern ripetuto >3 volte)
                words = translation.split()
                if len(words) > 10:
                    # Controlla se ci sono pattern ripetitivi
                    pattern_length = min(5, len(words) // 4)
                    if pattern_length > 0:
                        pattern = ' '.join(words[:pattern_length])
                        pattern_count = translation.count(pattern)
                        if pattern_count > 3:
                            logger.warning(f"Rilevata ripetizione eccessiva per testo #{i+1} (pattern '{pattern}' ripetuto {pattern_count} volte), uso originale")
                            translations.append(texts[i])
                            continue
                
                # Controlla lunghezza anomala (>3x rispetto all'originale)
                original_length = len(texts[i])
                if len(translation) > original_length * 3 and original_length > 10:
                    logger.warning(f"Output anomalo per testo #{i+1} (troppo lungo: {len(translation)} vs {original_length}), uso originale")
                    translations.append(texts[i])
                    continue
                
                # Se passa tutti i controlli, usa la traduzione
                translations.append(translation)

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
        Traduce file SRT (Aya-23-8B)
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
        
        if not isinstance(output_path, Path):
            try:
                output_path = Path(output_path)
            except Exception as e:
                error_msg = f"Ã¢ÂÅ’ Errore conversione output_path in Path: {e}"
                self.log(error_msg)
                logger.error(error_msg, exc_info=True)
                return False

        try:
            self.log(f" Traduzione Aya-23-8B (8-bit): {src_lang} → {tgt_lang}")
            
            src_aya = self._aya_to_iso(src_lang)
            tgt_aya = self._aya_to_iso(tgt_lang)
            
            if not src_aya or not tgt_aya:
                self.log(f" Codice lingua non supportato: {src_lang} o {tgt_lang}")
                return False
            
            parsed_subtitles = self._parse_srt(input_path)
            total = len(parsed_subtitles)
            translated_subtitles = []
            
            if total == 0:
                self.log("  File SRT vuoto o parsing fallito")
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write("")
                return True
            
            self.log(f"  Trovati {total} sottotitoli da tradurre")
            
            self.batch_manager.reset()
            self.current_batch_size = self.batch_manager.current_batch_size

            i = 0
            last_progress = -1
            max_retries_per_batch = 3

            while i < total:
                self.current_batch_size = self.batch_manager.current_batch_size
                batch_index = (i // self.current_batch_size) + 1
                total_batches = (total + self.current_batch_size - 1) // self.current_batch_size

                batch = parsed_subtitles[i:i + self.batch_manager.get_batch_size()]
                texts_to_translate: List[str] = []
                current_batch_placeholders: List[Dict[str, str]] = []
                skip_translation_flags: List[bool] = []
                original_texts: List[str] = [item[3] for item in batch]

                for text in original_texts:
                    final_text, placeholders, only_masked = self._mask_text(text, "AYA")

                    texts_to_translate.append(final_text)
                    current_batch_placeholders.append(placeholders)
                    skip_translation_flags.append(only_masked)

                progress = int((i / total) * 100)
                if progress != last_progress and not self.batch_manager.is_warming_up:
                    self.log(f"   Progresso: {progress}% ({i}/{total})")
                    last_progress = progress

                retries = 0
                batch_success = False
                
                while retries < max_retries_per_batch and not batch_success:
                    try:
                        texts_for_aya = [
                            t for t, skip in zip(texts_to_translate, skip_translation_flags) 
                            if not skip and t.strip()
                        ]
                        
                        results = []
                        if texts_for_aya:
                            results = self._run_translation(texts_for_aya, src_aya, tgt_aya)

                        translated_index = 0
                        post_processed_results = []
                        for j, (index, start, end, original_text) in enumerate(batch):
                            final_text_to_translate = texts_to_translate[j]
                            placeholders_map = current_batch_placeholders[j]

                            if skip_translation_flags[j] or not final_text_to_translate.strip():
                                post_processed_results.append(original_text)
                            else:
                                if translated_index < len(results):
                                    translated_text = results[translated_index]
                                    
                                    if translated_text.strip().lower() == "# non lo so #":
                                         self.log(f"   ATTENZIONE: Rilevata allucinazione per riga {index}. Mantengo originale.")
                                         post_processed_results.append(original_text)
                                    else:
                                        final_text = self._unmask_text(translated_text, placeholders_map)
                                        post_processed_results.append(final_text)
                                        
                                    translated_index += 1
                                else:
                                    self.log(f"   ATTENZIONE: Nessun output Aya per riga {index}. Mantengo originale.")
                                    post_processed_results.append(original_text)
                                    
                        for j, (index, start, end, _) in enumerate(batch):
                            translated_subtitles.append((index, start, end, post_processed_results[j]))
                        
                        batch_success = True
                        self.batch_manager.record_success()
                        i += len(batch)

                    except Exception as e:
                        retries += 1

                        if 'Out of Memory - Batch Size Ridotto' in str(e):
                            self.log(f"   Retry #{retries}/{max_retries_per_batch} con batch size ridotto...")
                            self.current_batch_size = self.batch_manager.current_batch_size
                            batch = parsed_subtitles[i:i + self.current_batch_size]
                            original_texts = [item[3] for item in batch]
                            texts_to_translate, current_batch_placeholders, skip_translation_flags = [], [], []
                            for text in original_texts:
                                final_text, placeholders, only_masked = self._mask_text(text, "AYA")
                                texts_to_translate.append(final_text)
                                current_batch_placeholders.append(placeholders)
                                skip_translation_flags.append(only_masked)

                        elif 'Out of Memory - GPU Memoria Insufficiente' in str(e):
                            self.log(f" ERRORE CRITICO: GPU memoria insufficiente. Batch saltato.")
                            for item in batch:
                                translated_subtitles.append(item)
                            i += len(batch)
                            break

                        else:
                            self.log(f" Errore sconosciuto nel batch ({str(e)[:100]}). Batch saltato.")
                            for item in batch:
                                translated_subtitles.append(item)
                            i += len(batch)
                            break

                if not batch_success and retries >= max_retries_per_batch:
                    self.log(f" Batch fallito dopo {max_retries_per_batch} tentativi. Mantengo originali.")
                    for item in batch:
                        translated_subtitles.append(item)
                    i += len(batch)

            self.batch_manager.log_summary()
            self.log(f"   Progresso: 100% ({total}/{total})")
            srt_content = self._generate_srt(translated_subtitles)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

            self.log(f" Traduzione Aya completata: {output_path.name}")
            self.log(f"   Sottotitoli tradotti: {len(translated_subtitles)}/{total}")
            
            return True
            
        except Exception as e:
            error_msg = f"  Ã¢ÂÅ’ Errore traduzione file {output_path.name}: {e}"
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            return False
    
    def cleanup(self):
        """Scarica modello Aya dalla VRAM."""
        try:
            _unload_aya_singleton()
            self.log("  ✅ Modello Aya scaricato dalla VRAM")
        except Exception as e:
            logger.error(f"Errore durante cleanup Aya: {e}")
            logger.error(f" Ã¢ÂÅ’ Errore durante cleanup GPU: {e}")




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
            
            subtitles = self._parse_srt(input_path)
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
            srt_content = self._generate_srt(translated_subtitles)
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

        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=self.use_gpu,
            initial_size=cfg.get('initial_size'),
            min_size=cfg.get('min_size', self.MIN_BATCH_SIZE),
            max_size=cfg.get('max_size', self.MAX_BATCH_SIZE),
            warmup_batches=cfg.get('warmup_batches', 5),
            high_threshold=cfg.get('high_threshold', 0.85),
            low_threshold=cfg.get('low_threshold', 0.60),
            log_callback=_batch_log,
        )
        self.current_batch_size = self.batch_manager.current_batch_size

    def cleanup(self):
        """Scarica modello NLLB fine-tuned dalla VRAM (override: usa singleton FT, non base)."""
        try:
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

            subtitles = self._parse_srt(input_path)
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
            srt_content = self._generate_srt(translated_subtitles)
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

try:
    from utils.config import get_config
    
    try:
        CONFIG = get_config()
    except Exception:
        CONFIG = None
        logger.warning("Impossibile caricare Config. Uso configurazione NLLB di default.")
        
except ImportError:
    logger.warning("Modulo 'config' non trovato. Uso configurazione NLLB di default.")
    CONFIG = None

def get_translator(model_type: Optional[str] = None, context: Optional[str] = None, 
                  use_aya: Optional[bool] = None) -> BaseTranslator:
    """
    Factory function per ottenere il traduttore appropriato.
    
    Args:
        model_type: 'nllb', 'aya', 'claude', o None (usa config)
        context: Contesto opzionale (es. sinossi TMDB) per migliorare traduzione
        use_aya: [DEPRECATED] Usa model_type='aya' invece
    
    Returns:
        Istanza del traduttore appropriato
    """
    # Gestisci backward compatibility con use_aya
    if use_aya is not None:
        logger.warning("Parametro 'use_aya' deprecato, usa 'model_type' invece")
        model_type = 'aya' if use_aya else 'nllb'
    
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
    
    elif model_type == 'aya':
        logger.info("Factory: Creazione AyaTranslator")
        return AyaTranslator(context=context)
    
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
                user_agent=creds.get('user_agent', 'TranscriberPro v1.0.0'),
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


