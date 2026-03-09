"""
OpenSubtitles Configuration Manager
File: utils/opensubtitles_config.py

GESTIONE CREDENZIALI:
- Credenziali caricate da file esterno (sicurezza)
- Supporta file JSON e TXT
- Fallback su credenziali vuote (upload disabilitato)
- Integrazione con sistema config esistente
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class OpenSubtitlesConfig:
    """
    Gestisce configurazione e credenziali OpenSubtitles
    
    FILE SUPPORTATI:
    1. opensubtitles_credentials.json (preferito)
       {
           "username": "your_username",
           "password": "your_password",
           "auto_upload": false
       }
    
    2. opensubtitles_credentials.txt (semplice)
       username
       password
    
    POSIZIONI RICERCA:
    - Directory root progetto
    - ~/.transcriberpro/
    - Directory corrente
    """
    
    def __init__(self):
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.auto_upload: bool = False
        self.upload_enabled: bool = False
        
        # Carica credenziali
        self._load_credentials()
    
    def _load_credentials(self) -> None:
        """
        Carica credenziali da file
        
        Cerca in ordine di priorità:
        1. JSON nella home .transcriberpro
        2. TXT nella home .transcriberpro
        3. JSON nel root progetto
        4. TXT nel root progetto
        """
        # Possibili percorsi
        home_dir = Path.home() / '.transcriberpro'
        project_root = Path(__file__).parent.parent
        
        search_paths = [
            home_dir / 'opensubtitles_credentials.json',
            home_dir / 'opensubtitles_credentials.txt',
            project_root / 'opensubtitles_credentials.json',
            project_root / 'opensubtitles_credentials.txt',
        ]
        
        # Cerca primo file valido
        for path in search_paths:
            if path.exists():
                if path.suffix == '.json':
                    if self._load_json(path):
                        return
                elif path.suffix == '.txt':
                    if self._load_txt(path):
                        return
        
        # Nessun file trovato
        logger.warning("⚠️ Credenziali OpenSubtitles non trovate")
        logger.info("💡 Per abilitare upload, crea uno di questi file:")
        logger.info(f"   - {home_dir / 'opensubtitles_credentials.json'}")
        logger.info(f"   - {home_dir / 'opensubtitles_credentials.txt'}")
        logger.info("📖 Formato JSON:")
        logger.info('   {"username": "user", "password": "pass", "auto_upload": false}')
        logger.info("📖 Formato TXT (2 righe):")
        logger.info('   username')
        logger.info('   password')
    
    def _load_json(self, path: Path) -> bool:
        """Carica credenziali da file JSON"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.username = data.get('username')
            self.password = data.get('password')
            self.auto_upload = data.get('auto_upload', False)
            
            if self.username and self.password:
                self.upload_enabled = True
                logger.info(f"✅ Credenziali caricate da: {path}")
                logger.info(f"👤 Username: {self.username}")
                logger.info(f"🔄 Auto-upload: {'Abilitato' if self.auto_upload else 'Disabilitato'}")
                return True
            else:
                logger.error(f"❌ File JSON incompleto: {path}")
                return False
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Errore parsing JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Errore lettura file: {e}")
            return False
    
    def _load_txt(self, path: Path) -> bool:
        """Carica credenziali da file TXT (2 righe)"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f.readlines()]
            
            if len(lines) >= 2:
                self.username = lines[0]
                self.password = lines[1]
                
                if self.username and self.password:
                    self.upload_enabled = True
                    logger.info(f"✅ Credenziali caricate da: {path}")
                    logger.info(f"👤 Username: {self.username}")
                    return True
            
            logger.error(f"❌ File TXT formato invalido: {path}")
            logger.info("   Formato atteso: 2 righe (username, password)")
            return False
        
        except Exception as e:
            logger.error(f"❌ Errore lettura file: {e}")
            return False
    
    def is_configured(self) -> bool:
        """Verifica se credenziali configurate"""
        return self.upload_enabled and self.username and self.password
    
    def get_credentials(self) -> Dict[str, str]:
        """
        Ritorna credenziali come dizionario
        
        Returns:
            {'username': '...', 'password': '...'}
        """
        return {
            'username': self.username or '',
            'password': self.password or ''
        }
    
    def should_auto_upload(self) -> bool:
        """
        Verifica se auto-upload abilitato
        
        Returns:
            True se credenziali OK e auto_upload=True
        """
        return self.is_configured() and self.auto_upload
    
    def set_credentials(self, username: str, password: str, auto_upload: bool = False) -> None:
        """
        Imposta credenziali programmaticamente (per testing o GUI)
        
        Args:
            username: Username OpenSubtitles
            password: Password
            auto_upload: Abilita upload automatico
        """
        self.username = username
        self.password = password
        self.auto_upload = auto_upload
        self.upload_enabled = bool(username and password)
        
        logger.info("✅ Credenziali impostate manualmente")
        logger.info(f"👤 Username: {username}")
        logger.info(f"🔄 Auto-upload: {'Abilitato' if auto_upload else 'Disabilitato'}")
    
    def save_to_json(self, path: Path = None) -> bool:
        """
        Salva credenziali correnti su file JSON
        
        Args:
            path: Path custom o None per default (~/.transcriberpro/)
        
        Returns:
            True se salvato con successo
        """
        if not path:
            config_dir = Path.home() / '.transcriberpro'
            config_dir.mkdir(parents=True, exist_ok=True)
            path = config_dir / 'opensubtitles_credentials.json'
        
        try:
            data = {
                'username': self.username or '',
                'password': self.password or '',
                'auto_upload': self.auto_upload
            }
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            logger.info(f"✅ Credenziali salvate in: {path}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Errore salvataggio: {e}")
            return False


# ========================================
# SINGLETON GLOBALE
# ========================================

_opensubtitles_config = None

def get_opensubtitles_config() -> OpenSubtitlesConfig:
    """
    Ottieni istanza singleton della configurazione
    
    Usage:
        config = get_opensubtitles_config()
        if config.is_configured():
            uploader = UploaderFactory.create_uploader(
                'xmlrpc',
                **config.get_credentials()
            )
    """
    global _opensubtitles_config
    if _opensubtitles_config is None:
        _opensubtitles_config = OpenSubtitlesConfig()
    return _opensubtitles_config
