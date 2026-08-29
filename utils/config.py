"""
Configuration Manager - COMPLETE VERSION WITH PROFILES SYSTEM
File: utils/config.py

VERSIONE: v4.3 - RIMOZIONE AYA, MIGRAZIONE A 'llm'

MODIFICHE v4.3:
- Rimossi i modelli Aya. 'translation_model' accetta ora 'llm' al loro posto,
  e il valore storico 'aya' viene migrato automaticamente alla lettura.
- Rimosse le chiavi e i metodi 'aya_model_path' / 'aya_model_download_status',
  che nessuno chiamava piu (e il flag risultava True col modello NON in cache).
- Rimossa la definizione DUPLICATA di get/set_translation_model: la seconda
  copia, senza validazione, sovrascriveva silenziosamente la prima.
- Nuova chiave 'llm_translator_model' (default 'translategemma-12b').

MODIFICHE v4.1:
- Supporto Token HuggingFace per i modelli gated
"""

import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Import necessario per delegare la logica dei profili
try:
    from .transcription_profiles import ProfileConfig, TranscriptionProfile
except ImportError as e:
    print(f"⚠️ Import ProfileConfig fallito: {e} - uso MOCK")
    # Fallback per evitare crash se il modulo non è ancora caricato
    class ProfileConfig:
        @staticmethod
        def get_profile_config(profile): return {'name': profile, 'num_workers': 0, 'beam_size': 0}
        @staticmethod
        def from_string(profile_str):
            if profile_str == 'balanced': return 'balanced'
            return 'fast' 
    class TranscriptionProfile:
        BALANCED = 'balanced'


class Config:
    """Gestisce configurazione e preferenze utente"""
    
    CONFIG_DIR = Path.home() / '.transcriberpro'
    CONFIG_FILE = CONFIG_DIR / 'config.json'
    
    # Default settings
    DEFAULTS = {
        # General settings
        'use_gpu': True,
        'language': 'auto',
        'last_input_folder': '',
        'shutdown_after_processing': False,
        
        # OpenSubtitles Upload Settings
        'opensubtitles_upload_enabled': True,
        'opensubtitles_auto_upload': True,
        'opensubtitles_check_duplicates': True,
        'opensubtitles_username': '',
        'opensubtitles_password': '',
        'opensubtitles_user_agent': 'TranscriberPro v1.1.0',
        'opensubtitles_api_key': '',  
        'opensubtitles_preferred_implementation': 'xmlrpc',
        
        # Transcription method
        'transcription_method': 'faster-whisper',

        # Sistema multi-engine trascrizione (routing automatico per lingua)
        'transcription_engine_mode': 'auto',   # 'auto' | 'canary' | 'qwen3' | 'faster-whisper'
        'canary_enabled': True,                # Canary-Qwen-2.5B (solo inglese, venv dedicato)
        'qwen3_enabled': True,                 # Qwen3-ASR-1.7B + ForcedAligner-0.6B
        'qwen3_asr_model_id': 'Qwen/Qwen3-ASR-1.7B',
        'qwen3_aligner_model_id': 'Qwen/Qwen3-ForcedAligner-0.6B',
        'canary_model_id': 'nvidia/canary-qwen-2.5b',
        'canary_python_path': '',              # vuoto = auto (<progetto>/venv_canary/Scripts/python.exe)

        # FFmpeg whisper settings (solo se transcription_method == 'ffmpeg')
        'ffmpeg_model_path': '',
        'ffmpeg_queue_size': 30,
        
        # Whisper model configuration
        'whisper_model': 'large-v3',
        'whisper_device': 'auto',
        'whisper_compute_type': 'auto',
        
        # Sistema profili dinamici trascrizione
        'transcription_profile': 'balanced',

        # Adaptive Batch Size
        'adaptive_batch_enabled': True,
        'adaptive_batch_initial_size': 0,   # 0 = auto-detect
        'adaptive_batch_max_size': 24,
        'adaptive_batch_min_size': 1,
        'adaptive_batch_warmup_batches': 5,
        'adaptive_batch_high_threshold': 0.85,
        'adaptive_batch_low_threshold': 0.60,
        
        # ========================================================================
        # Translation Model Settings (MODIFICATO v5.0 - Claude API Support)
        # ========================================================================
        'translation_model': 'nllb',  # vedi VALID_TRANSLATION_MODELS
        'target_language': 'ita',     # ISO 639-2 lingua target sottotitoli
        
        # Claude API (cloud-based translation)
        'claude_api_key': '',  # API key Anthropic per Claude

        # OpenAI API (cloud-based translation)
        'openai_api_key': '',
        'openai_model': 'gpt-4o-mini',
        
        # Traduttore LLM locale: quale modello occupa lo slot. Le chiavi
        # 'aya_model_path' e 'aya_model_download_status' sono state rimosse il
        # 2026-08-18 insieme ai modelli Aya; restano innocue nelle config
        # esistenti, semplicemente non le legge piu nessuno.
        'llm_translator_model': 'translategemma-12b',
        # Cartella di un adattatore LoRA da applicare sopra il modello
        # LLM. Vuota = modello base, che e' il comportamento storico.
        # Serve a mettere in produzione un fine-tuning senza toccare il
        # codice ne' sostituire i pesi base da 23 GB.
        'llm_translator_adapter': '',
        # Cartella locale dei pesi del modello LLM stesso (non l'adattatore).
        # Vuota = usa il model_id di default in MODEL_SPECS. Permette di
        # puntare a un merge diverso (es. una nuova promozione) senza
        # toccare il codice, stesso schema di 'nllb_finetuned_model_path'.
        'llm_translator_model_path': '',
        
        # NLLB model
        'nllb_model_path': '',  # Vuoto usa default HuggingFace
        'nllb_finetuned_model_path': '',  # Path al modello NLLB fine-tuned locale
        
        # HuggingFace token (per i modelli gated)
        'huggingface_token': '',

        # Speaker Diarization (pyannote.audio)
        'enable_diarization': False,
        'diarization_num_speakers': 0,   # 0 = auto-detect

        # Stile dialoghi professionale (trattini Netflix su cambio parlante):
        # attiva automaticamente la diarization per ogni trascrizione e la
        # formattazione SubtitleFormatter (richiede token HuggingFace)
        'dialogue_style_enabled': True,

        # Forced Alignment (whisperx + wav2vec2)
        'enable_forced_alignment': False,

        # Library Scanner Settings
        'library_scanner_url': 'http://192.168.1.18:6680',
        'library_scanner_api_key': 'IDu_J0LvpqcmJ0nCFjXc6rlu2oKNoDE2bEO8CUVrNng',
        'library_scanner_enabled': True,

        # Gender Correction (LLM post-traduzione)
        'gender_correction_enabled': False,
        'gender_correction_model_path': '',

        # Subtitle Synchronization ("Anchor & Match" pipeline)
        'sync_src_language':           'en',   # lingua embedded anchor (ISO 639-1)
        'sync_llm_window_size':        20,     # anchor per finestra Qwen
        'sync_allow_whisper_fallback': True,   # fallback Whisper se no embedded subs
    }
    
    # Profili validi
    VALID_PROFILES = ['fast', 'balanced', 'quality', 'maximum', 'batch']

    # Engine di trascrizione validi (sistema multi-engine)
    VALID_TRANSCRIPTION_ENGINE_MODES = ['auto', 'canary', 'qwen3', 'faster-whisper']
    
    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._ensure_config_dir()
        self.load()
    
    def _ensure_config_dir(self):
        """Crea directory configurazione se non esiste"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    def load(self):
        """Carica configurazione da file"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.settings = self._merge_defaults(loaded)
                    # Se abbiamo aggiunto nuovi default (come 'aya_model_download_status'), salva
                    if len(self.settings) > len(loaded):
                        self.save()
            except Exception as e:
                print(f"⚠️ Error loading config: {e}")
                self.settings = self.DEFAULTS.copy()
        else:
            self.settings = self.DEFAULTS.copy()
            self.save()
    
    def _merge_defaults(self, loaded: dict) -> dict:
        """Merge loaded config con defaults"""
        merged = self.DEFAULTS.copy()
        for key, value in loaded.items():
            if key in merged:
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            else:
                # Chiave non più in DEFAULTS (deprecata), la manteniamo comunque
                merged[key] = value
        
        # Assicura che tutte le chiavi default esistano
        for key, value in self.DEFAULTS.items():
             if key not in merged:
                 merged[key] = value
                 
        return merged
    
    def save(self):
        """Salva configurazione su file"""
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error saving config: {e}")
    
    def get(self, key: str, default=None) -> Any:
        """Ottieni valore configurazione"""
        return self.settings.get(key, default if default is not None else self.DEFAULTS.get(key))
    
    def set(self, key: str, value: Any, save: bool = True):
        """Imposta valore configurazione"""
        if key == 'transcription_profile':
            if value not in self.VALID_PROFILES:
                print(f"⚠️ Profilo '{value}' non valido. Uso 'balanced'.")
                value = 'balanced'

        if key == 'transcription_engine_mode':
            if value not in self.VALID_TRANSCRIPTION_ENGINE_MODES:
                print(f"⚠️ Engine '{value}' non valido. Uso 'auto'.")
                value = 'auto'

        self.settings[key] = value
        if save:
            self.save()
    
    def get_all(self) -> Dict[str, Any]:
        """Ottieni tutte le impostazioni"""
        return self.settings.copy()

    # ========================================================================
    # METODI HELPER per OpenSubtitles (MANTENUTI)
    # ========================================================================
    
    def is_opensubtitles_configured(self) -> bool:
        """Verifica se OpenSubtitles Ã¨ configurato correttamente per REST."""
        username = self.get('opensubtitles_username', '')
        password = self.get('opensubtitles_password', '')
        api_key = self.get('opensubtitles_api_key', '')
        return bool(username and password and api_key)
    
    def get_opensubtitles_credentials(self) -> Optional[Dict[str, str]]:
        """Ottiene credenziali OpenSubtitles"""
        if not self.is_opensubtitles_configured():
            return None
        
        return {
            'username': self.get('opensubtitles_username'),
            'password': self.get('opensubtitles_password'),
            'user_agent': self.get('opensubtitles_user_agent', 'TranscriberPro v1.1.0'),
            'api_key': self.get('opensubtitles_api_key')
        }
    
    def set_opensubtitles_credentials(self, username: str, password: str, api_key: str,
                                     user_agent: str = None):
        """Imposta credenziali OpenSubtitles"""
        self.set('opensubtitles_username', username, save=False)
        self.set('opensubtitles_password', password, save=False)
        self.set('opensubtitles_api_key', api_key, save=False)
        
        if user_agent:
            self.set('opensubtitles_user_agent', user_agent, save=False)
        
        self.save()
    
    def get_opensubtitles_config(self) -> Dict[str, Any]:
        """Ottiene tutta la configurazione OpenSubtitles"""
        return {
            'upload_enabled': self.get('opensubtitles_upload_enabled', True),
            'auto_upload': self.get('opensubtitles_auto_upload', True),
            'check_duplicates': self.get('opensubtitles_check_duplicates', True),
            'username': self.get('opensubtitles_username', ''),
            'password': self.get('opensubtitles_password', ''),
            'api_key': self.get('opensubtitles_api_key', ''),
            'user_agent': self.get('opensubtitles_user_agent', 'TranscriberPro v1.1.0'),
            'preferred_implementation': self.get('opensubtitles_preferred_implementation', 'rest')
        }
    
    def print_config_safe(self) -> str:
        """Stampa configurazione nascondendo dati sensibili"""
        safe_settings = self.settings.copy()
        
        if 'opensubtitles_password' in safe_settings:
            safe_settings['opensubtitles_password'] = '***HIDDEN***'
        if 'opensubtitles_api_key' in safe_settings:
            safe_settings['opensubtitles_api_key'] = '***HIDDEN***'
        if 'huggingface_token' in safe_settings and safe_settings['huggingface_token']:
            safe_settings['huggingface_token'] = '***HIDDEN***'
        if 'claude_api_key' in safe_settings and safe_settings['claude_api_key']:
            safe_settings['claude_api_key'] = '***HIDDEN***'
        if 'openai_api_key' in safe_settings and safe_settings['openai_api_key']:
            safe_settings['openai_api_key'] = '***HIDDEN***'
        if 'library_scanner_api_key' in safe_settings and safe_settings['library_scanner_api_key']:
            safe_settings['library_scanner_api_key'] = '***HIDDEN***'
        
        return json.dumps(safe_settings, indent=2, ensure_ascii=False)
    
    # ========================================================================
    # METODI HELPER per Profili Trascrizione (MANTENUTI)
    # ========================================================================
    
    def get_transcription_profile(self) -> str:
        """Ottieni profilo trascrizione corrente"""
        profile = self.get('transcription_profile', 'balanced')
        
        if profile not in self.VALID_PROFILES:
            print(f"⚠️ Profilo '{profile}' non valido. Uso 'balanced'.")
            profile = 'balanced'
            self.set('transcription_profile', profile)
        
        return profile
    
    def set_transcription_profile(self, profile: str):
        """Imposta profilo trascrizione con validazione"""
        if profile not in self.VALID_PROFILES:
            raise ValueError(
                f"Profilo '{profile}' non valido. "
                f"Profili disponibili: {', '.join(self.VALID_PROFILES)}"
            )
        
        self.set('transcription_profile', profile)
        print(f"✅Profilo trascrizione impostato: {profile}")
    
    def get_available_profiles(self) -> list:
        """Ottieni lista profili disponibili"""
        return self.VALID_PROFILES.copy()

    # ========================================================================
    # METODI HELPER per Engine di Trascrizione (NUOVO - sistema multi-engine)
    # ========================================================================

    def get_transcription_engine_mode(self) -> str:
        """Ottieni la modalità engine di trascrizione corrente
        ('auto' = routing automatico per lingua)."""
        mode = self.get('transcription_engine_mode', 'auto')

        if mode not in self.VALID_TRANSCRIPTION_ENGINE_MODES:
            print(f"⚠️ Engine '{mode}' non valido. Uso 'auto'.")
            mode = 'auto'
            self.set('transcription_engine_mode', mode)

        return mode

    def set_transcription_engine_mode(self, mode: str):
        """Imposta la modalità engine di trascrizione con validazione"""
        if mode not in self.VALID_TRANSCRIPTION_ENGINE_MODES:
            raise ValueError(
                f"Engine '{mode}' non valido. "
                f"Engine disponibili: {', '.join(self.VALID_TRANSCRIPTION_ENGINE_MODES)}"
            )

        self.set('transcription_engine_mode', mode)
        print(f"✅ Engine trascrizione impostato: {mode}")
    
    def get_profile_info(self, profile: str = None) -> Dict[str, Any]:
        """
        Ottieni informazioni su un profilo specifico
        """
        if profile is None:
            profile = self.get_transcription_profile()
        
        if profile not in self.VALID_PROFILES:
            print(f"⚠️ DEBUG: profile '{profile}' NON VALIDO")
            profile = 'balanced'
        
        profile_enum = ProfileConfig.from_string(profile)
        config_data = ProfileConfig.get_profile_config(profile_enum)
        
        result = {
            'name': config_data.get('name', profile),
            'workers': config_data.get('num_workers', 4),
            'beam': config_data.get('beam_size', 5),
            'speed': f"{config_data.get('speed_factor', 1.0) * 100:.0f}%" if config_data.get('speed_factor', 1.0) != 1.0 else '100%',
            'quality': f"{config_data.get('quality_percent', 95.0):.1f}%"
        }
        return result

    
    # ========================================================================
    # METODI HELPER per Translation Models (MODIFICATO v4.2)
    # ========================================================================
    
    VALID_TRANSLATION_MODELS = ['nllb', 'nllb_finetuned', 'llm', 'claude',
                                'opensubtitles', 'openai']

    # Valori salvati da versioni precedenti e il loro equivalente attuale. La
    # migrazione avviene alla lettura: chi aveva scelto Aya si ritrova il ramo
    # LLM (oggi TranslateGemma) invece di un errore di validazione seguito da
    # un ritorno silenzioso a NLLB.
    LEGACY_TRANSLATION_MODELS = {'aya': 'llm'}
    
    def get_translation_model(self) -> str:
        """Ottieni modello di traduzione corrente"""
        model = self.get('translation_model', 'nllb')

        if model in self.LEGACY_TRANSLATION_MODELS:
            nuovo = self.LEGACY_TRANSLATION_MODELS[model]
            logger.info(f"Modello '{model}' rinominato in '{nuovo}': "
                        f"aggiorno la configurazione")
            model = nuovo
            self.set('translation_model', model)

        if model not in self.VALID_TRANSLATION_MODELS:
            print(f"⚠️ Modello '{model}' non valido. Uso 'nllb'.")
            model = 'nllb'
            self.set('translation_model', model)
        
        return model
    
    def set_translation_model(self, model: str):
        """Imposta modello di traduzione con validazione"""
        if model not in self.VALID_TRANSLATION_MODELS:
            raise ValueError(
                f"Modello '{model}' non valido. "
                f"Modelli disponibili: {', '.join(self.VALID_TRANSLATION_MODELS)}"
            )
        
        self.set('translation_model', model)
        print(f"✅ Modello traduzione impostato: {model}")
    
    # RIMOSSI il 2026-08-18 insieme ai modelli Aya: `get_aya_model_path`,
    # `set_aya_model_path`, `set_aya_model_download_status`,
    # `is_aya_model_downloaded`. Non erano chiamati da nessuna parte tranne che
    # dalla GUI del download, ora puntata sul modello LLM in uso. Il flag
    # `aya_model_download_status` era per giunta inaffidabile: risultava True
    # con il modello NON in cache.

    def get_translation_model_info(self) -> Dict[str, Any]:
        """Ottieni informazioni sul modello di traduzione corrente"""
        current_model = self.get_translation_model()
        
        if current_model == 'nllb':
            return {
                'name': 'NLLB-200',
                'full_name': 'facebook/nllb-200-3.3B',
                'languages': '200+',
                'size': '~3.3B parametri (quantizzato 8-bit)',
                'vram': '~4-5 GB (quantizzazione 8-bit)',
                'speed': 'Veloce',
                'quality': 'Ottima',
                'status': 'Auto-download da HuggingFace (quantizzazione al volo)'
            }
        else:  # llm — traduttore LLM locale
            chiave = self.get('llm_translator_model', 'translategemma-12b')
            return {
                'name': 'TranslateGemma 12B',
                'full_name': f'modello in uso: {chiave}',
                'languages': 'multilingua',
                'size': '~12B parametri (quantizzato NF4)',
                'vram': '~8,4 GB di pesi, picco ~10,1 GB a batch 12',
                'speed': 'Lenta (circa 3 s per battuta)',
                'quality': 'Ottima su stile, piu debole su accuratezza',
                'status': 'Auto-download da HuggingFace (repo gated)'
            }
    
    # ========================================================================
    # METODI HELPER per Token HuggingFace (v4.1)
    # ========================================================================
    
    def get_huggingface_token(self) -> str:
        """
        Ottieni token HuggingFace
        """
        return self.get('huggingface_token', '')
    
    def set_huggingface_token(self, token: str):
        """
        Imposta token HuggingFace
        """
        token = token.strip()
        
        is_valid, error = self.validate_huggingface_token(token)
        if not is_valid and token:
            logger.warning(f"⚠️ Token HuggingFace potrebbe non essere valido: {error}")
        
        self.set('huggingface_token', token)
        logger.info(f"⚙️ Token HuggingFace {'configurato' if token else 'rimosso'}")
    
    def is_huggingface_token_set(self) -> bool:
        """
        Verifica se il token HuggingFace Ã¨ configurato
        """
        token = self.get_huggingface_token()
        return bool(token and token.strip())
    
    def validate_huggingface_token(self, token: str) -> tuple:
        """
        Valida formato del token HuggingFace
        """
        if not token or not token.strip():
            return (False, "Token vuoto")
        
        token = token.strip()
        
        if not token.startswith('hf_'):
            return (False, "Token deve iniziare con 'hf_'")
        
        if len(token) < 20:
            return (False, "Token troppo corto (minimo 20 caratteri)")
        
        if not all(c.isalnum() or c == '_' for c in token):
            return (False, "Token contiene caratteri non validi")
        
        return (True, "")
    
    # ========================================================================
    # METODI HELPER per Claude API (v5.0)
    # ========================================================================
    
    def get_claude_api_key(self) -> str:
        """Ottieni API key Claude/Anthropic"""
        return self.get('claude_api_key', '')
    
    def set_claude_api_key(self, api_key: str):
        """
        Imposta API key Claude/Anthropic
        
        Args:
            api_key: API key da Anthropic Console
        """
        api_key = api_key.strip()
        
        is_valid, error = self.validate_claude_api_key(api_key)
        if not is_valid and api_key:
            logger.warning(f"⚠️ API key Claude potrebbe non essere valida: {error}")
        
        self.set('claude_api_key', api_key)
        logger.info(f"✅ API key Claude {'configurata' if api_key else 'rimossa'}")
    
    def is_claude_api_key_set(self) -> bool:
        """Verifica se API key Claude è configurata"""
        api_key = self.get_claude_api_key()
        return bool(api_key and api_key.strip() and len(api_key) > 20)
    
    def validate_claude_api_key(self, api_key: str) -> tuple:
        """
        Valida formato API key Claude/Anthropic
        
        Returns:
            (is_valid: bool, error_message: str)
        """
        if not api_key or not api_key.strip():
            return (False, "API key vuota")
        
        api_key = api_key.strip()
        
        # Le API key Anthropic iniziano con 'sk-ant-'
        if not api_key.startswith('sk-ant-'):
            return (False, "API key deve iniziare con 'sk-ant-'")
        
        # Lunghezza minima ragionevole
        if len(api_key) < 40:
            return (False, "API key troppo corta (minimo 40 caratteri)")
        
        # Verifica caratteri validi (alfanumerici + underscore + trattino)
        if not all(c.isalnum() or c in '_-' for c in api_key):
            return (False, "API key contiene caratteri non validi")
        
        return (True, "")
    
    # ========================================================================
    # METODI HELPER per OpenAI API
    # ========================================================================

    def get_openai_api_key(self) -> str:
        return self.get('openai_api_key', '')

    def set_openai_api_key(self, api_key: str):
        api_key = api_key.strip()
        self.set('openai_api_key', api_key)

    def is_openai_api_key_set(self) -> bool:
        key = self.get_openai_api_key()
        return bool(key and len(key) > 20)

    def validate_openai_api_key(self, api_key: str) -> tuple:
        """Le chiavi OpenAI iniziano con 'sk-' (legacy) o 'sk-proj-' (project keys)."""
        if not api_key or not api_key.strip():
            return (False, "API key vuota")
        key = api_key.strip()
        if not (key.startswith('sk-') or key.startswith('sk-proj-')):
            return (False, "API key deve iniziare con 'sk-' o 'sk-proj-'")
        if len(key) < 30:
            return (False, "API key troppo corta")
        return (True, "")

    def get_openai_model(self) -> str:
        return self.get('openai_model', 'gpt-4o-mini')

    def set_openai_model(self, model: str):
        self.set('openai_model', model)

    # `get_translation_model` e `set_translation_model` erano definiti DUE
    # volte in questo file, e in Python vince l'ultima definizione: la coppia
    # che stava qui — senza validazione — sovrascriveva silenziosamente quella
    # completa piu in alto. Rimossa il 2026-08-18. Restano valide le versioni
    # sopra, che validano contro VALID_TRANSLATION_MODELS e migrano i valori
    # storici (vedi LEGACY_TRANSLATION_MODELS).

    def get_target_language(self) -> str:
        return self.get('target_language', 'ita')

    def set_target_language(self, lang: str) -> None:
        self.set('target_language', lang, save=True)

    # ========================================================================
    # METODI HELPER per il traduttore LLM locale (TranslateGemma e slot)
    # ========================================================================

    def get_llm_translator_model_path(self) -> str:
        """Cartella locale dei pesi del modello LLM, se sovrascritta."""
        return self.get('llm_translator_model_path', '')

    def set_llm_translator_model_path(self, path: str):
        """Imposta la cartella locale dei pesi del modello LLM."""
        self.set('llm_translator_model_path', str(path))

    # ========================================================================
    # METODI HELPER per NLLB Fine-Tuned
    # ========================================================================

    def get_nllb_finetuned_model_path(self) -> str:
        """Ottieni path del modello NLLB fine-tuned"""
        return self.get('nllb_finetuned_model_path', '')

    def set_nllb_finetuned_model_path(self, path: str):
        """Imposta path del modello NLLB fine-tuned"""
        self.set('nllb_finetuned_model_path', str(path))

    def is_nllb_finetuned_configured(self) -> bool:
        """Verifica se il modello fine-tuned è configurato e la cartella esiste"""
        path = self.get_nllb_finetuned_model_path()
        if not path:
            return False
        p = Path(path)
        return p.exists() and (p / 'config.json').exists()

    def get_nllb_num_beams(self) -> int:
        return int(self.get('nllb_num_beams', 7))

    def set_nllb_num_beams(self, value: int):
        self.set('nllb_num_beams', int(value))

    # ========================================================================
    # METODI HELPER per Gender Correction
    # ========================================================================

    def is_gender_correction_available(self) -> bool:
        if not self.get('gender_correction_enabled', False):
            return False
        p = self.get('gender_correction_model_path', '')
        return bool(p) and Path(p).exists()

    # ========================================================================
    # METODI HELPER per Adaptive Batch Size
    # ========================================================================

    def get_adaptive_batch_config(self) -> Dict[str, Any]:
        """Ottieni configurazione adaptive batch size"""
        raw_initial = self.get('adaptive_batch_initial_size', 0)
        return {
            'enabled':          self.get('adaptive_batch_enabled', True),
            'initial_size':     raw_initial or None,   # 0 → None (auto-detect)
            'max_size':         self.get('adaptive_batch_max_size', 24),
            'min_size':         self.get('adaptive_batch_min_size', 1),
            'warmup_batches':   self.get('adaptive_batch_warmup_batches', 5),
            'high_threshold':   self.get('adaptive_batch_high_threshold', 0.85),
            'low_threshold':    self.get('adaptive_batch_low_threshold', 0.60),
        }


# ============================================================================
# Singleton globale 
# ============================================================================

_config_instance = None


def get_config() -> Config:
    """Ottiene istanza singleton della configurazione"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reset_config():
    """Reset del singleton (utile per testing)"""
    global _config_instance
    _config_instance = None


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    """Test configurazione completa"""
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    print("\n" + "=" * 80)
    print("TEST CONFIGURAZIONE v4.2 (FIX STATO DOWNLOAD)")
    print("=" * 80 + "\n")
    
    config = get_config()
    
    # Test 1: Info profilo
    print("\n" + "-" * 80)
    print("Test Profilo Corrente:")
    config.set_transcription_profile('quality')
    profile_info = config.get_profile_info()
    print(f"  - Profilo: {profile_info['name']}")
    
    # Test 2: Migrazione dei valori storici del modello di traduzione
    print("\n" + "-" * 80)
    print("Test Migrazione 'aya' -> 'llm':")

    precedente = config.get('translation_model', 'nllb')
    config.set('translation_model', 'aya', save=False)
    migrato = config.get_translation_model()
    print(f"  'aya' letto come: {migrato} (Atteso: llm)")
    config.set('translation_model', precedente, save=True)

    print("\n" + "=" * 80)
    print("âœ… TEST COMPLETATI!")
    print("=" * 80 + "\n")