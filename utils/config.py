"""
Configuration Manager - COMPLETE VERSION WITH PROFILES SYSTEM
File: utils/config.py

VERSIONE: v4.2 - FIX STATO DOWNLOAD AYA

MODIFICHE v4.2:
- Aggiunto 'aya_model_download_status' (bool) per tracciare lo stato del download.
- 'is_aya_model_downloaded' ora legge questo flag (molto piÃ¹ affidabile).
- 'is_aya_model_downloaded' mantiene il controllo file come fallback
  per retrocompatibilitÃ  (se il flag Ã¨ False, controlla i file una volta).
- Aggiunto 'set_aya_model_download_status' per essere chiamato dalla GUI.

MODIFICHE v4.1:
- Supporto Token HuggingFace per modelli gated (Aya-23-8B)
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
    print("✅ Import ProfileConfig REALE riuscito")
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
        'opensubtitles_user_agent': 'TranscriberPro v1.0.0',
        'opensubtitles_api_key': '',  
        'opensubtitles_preferred_implementation': 'rest',  
        
        # Transcription method
        'transcription_method': 'faster-whisper',
        
        # FFmpeg whisper settings (solo se transcription_method == 'ffmpeg')
        'ffmpeg_model_path': '',
        'ffmpeg_queue_size': 30,
        
        # Whisper model configuration
        'whisper_model': 'large-v3',
        'whisper_device': 'auto',
        'whisper_compute_type': 'auto',
        
        # Sistema profili dinamici trascrizione
        'transcription_profile': 'balanced',
        
        # ========================================================================
        # Translation Model Settings (MODIFICATO v5.0 - Claude API Support)
        # ========================================================================
        'translation_model': 'nllb',  # 'nllb', 'aya', o 'claude'
        
        # Claude API (cloud-based translation)
        'claude_api_key': '',  # API key Anthropic per Claude

        # OpenAI API (cloud-based translation)
        'openai_api_key': '',
        'openai_model': 'gpt-4o-mini',
        
        # Aya model
        'aya_model_download_status': False,
        'aya_model_path': str(Path.home() / '.cache' / 'huggingface' / 'hub' / 'models--CohereForAI--aya-23-8B'),
        
        # NLLB model
        'nllb_model_path': '',  # Vuoto usa default HuggingFace
        'nllb_finetuned_model_path': '',  # Path al modello NLLB fine-tuned locale
        
        # HuggingFace token (per modelli gated come Aya)
        'huggingface_token': '',

        # Library Scanner Settings
        'library_scanner_url': 'http://192.168.1.18:6680',
        'library_scanner_api_key': '',
        'library_scanner_enabled': True,
    }
    
    # Profili validi
    VALID_PROFILES = ['fast', 'balanced', 'quality', 'maximum', 'batch']
    
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
            'user_agent': self.get('opensubtitles_user_agent', 'TranscriberPro v1.0.0'),
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
            'user_agent': self.get('opensubtitles_user_agent', 'TranscriberPro v1.0.0'),
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
    
    VALID_TRANSLATION_MODELS = ['nllb', 'aya', 'claude', 'nllb_finetuned', 'opensubtitles', 'openai']
    
    def get_translation_model(self) -> str:
        """Ottieni modello di traduzione corrente"""
        model = self.get('translation_model', 'nllb')
        
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
    
    def get_aya_model_path(self) -> Path:
        """Ottieni path del modello Aya (usato per fallback check)"""
        path_str = self.get('aya_model_path')
        return Path(path_str) if path_str else Path.home() / '.cache' / 'huggingface' / 'hub' / 'models--CohereForAI--aya-23-8B'
    
    def set_aya_model_path(self, path: str):
        """Imposta path del modello Aya"""
        self.set('aya_model_path', str(path))
    
    
    # --- NUOVA FUNZIONE v4.2 ---
    def set_aya_model_download_status(self, status: bool):
        """
        Imposta il flag di stato del download per Aya.
        """
        self.set('aya_model_download_status', status, save=True)
        logger.info(f"Stato download Aya impostato a: {status}")

    # --- FUNZIONE MODIFICATA v4.2 ---
    def is_aya_model_downloaded(self) -> bool:
        """
        Verifica se il modello Aya Ã¨ STATO scaricato (legge flag).
        
        NOTA: La vecchia logica (controllo file) Ã¨ stata rimossa perchÃ© 
        inaffidabile. Ora ci fidiamo di un flag impostato dalla GUI
        dopo il primo download riuscito.
        """
        # 1. Prova a leggere il nuovo flag (metodo affidabile)
        status = self.get('aya_model_download_status', False)
        if isinstance(status, bool) and status:
            return True
        
        # 2. --- Logica di fallback per vecchie config ---
        # Se il nuovo flag Ã¨ False, controlla il vecchio (e inaffidabile) 
        # metodo di controllo file, nel caso l'utente avesse giÃ  il modello.
        try:
            aya_path = self.get_aya_model_path()
            if (aya_path.exists() and 
                (aya_path / 'config.json').exists() and
                (any(aya_path.glob('*.safetensors')) or any(aya_path.glob('*.bin')))):
                
                # File trovati! Aggiorna il nuovo flag per il futuro.
                self.set_aya_model_download_status(True) 
                logger.info("Trovato modello Aya esistente tramite fallback. Flag aggiornato.")
                return True
        except Exception as e:
            logger.warning(f"Controllo fallback file Aya fallito: {e}")
            pass # Ignora errori di controllo file
        
        # 3. Se entrambi falliscono, non Ã¨ scaricato.
        return False
    
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
        else:  # aya
            # Ora usa la funzione affidabile
            is_downloaded = self.is_aya_model_downloaded()
            return {
                'name': 'Aya-23-8B',
                'full_name': 'CohereForAI/aya-23-8B',
                'languages': '23 lingue',
                'size': '~8B parametri',
                'vram': '~8-10 GB (FP16)',
                'speed': 'Media',
                'quality': 'Eccellente',
                'status': 'Scaricato' if is_downloaded else 'Da scaricare'
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

    def get_translation_model(self) -> str:
        """Ottieni modello traduzione selezionato ('nllb', 'aya', 'claude')"""
        return self.get('translation_model', 'nllb')
    
    def set_translation_model(self, model: str):
        """
        Imposta modello traduzione

        Args:
            model: 'nllb', 'aya', 'claude', o 'nllb_finetuned'
        """
        valid_models = ['nllb', 'aya', 'claude', 'nllb_finetuned', 'opensubtitles', 'openai']
        if model not in valid_models:
            raise ValueError(f"Modello non valido: {model}. Usa: {', '.join(valid_models)}")

        self.set('translation_model', model)
        logger.info(f"✅ Modello traduzione impostato: {model.upper()}")

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
    
    # Test 2: Test Logica Download Aya (Simulazione)
    print("\n" + "-" * 80)
    print("Test Logica Download Aya (Simulazione):")
    
    # Stato iniziale (fallback, i file non esistono)
    config.set('aya_model_download_status', False, save=True)
    is_down = config.is_aya_model_downloaded()
    print(f"  Stato Iniziale (Flag=False, File=No): {is_down} (Atteso: False)")
    
    # Simula download
    config.set_aya_model_download_status(True)
    is_down = config.is_aya_model_downloaded()
    print(f"  Stato Post-Download (Flag=True): {is_down} (Atteso: True)")
    
    # Resetta
    config.set_aya_model_download_status(False)
    
    print("\n" + "=" * 80)
    print("âœ… TEST COMPLETATI!")
    print("=" * 80 + "\n")