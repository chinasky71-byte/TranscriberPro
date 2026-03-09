"""
Subtitle Uploader Interface - Design Pattern Adapter per Future-Proofing
File: utils/subtitle_uploader_interface.py

CORREZIONE v2.1:
âœ… FIX CRITICO: Rimosse le firme non necessarie da authenticate, check_exists, logout 
   per soddisfare il contratto di astrazione (ABC) basato sull'implementazione di XML-RPC.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class SubtitleMetadata:
    """
    Data class per metadata sottotitoli
    Centralizza tutte le informazioni necessarie per upload
    """
    def __init__(
        self,
        imdb_id: str,
        language_code: str,
        release_name: str,
        video_hash: Optional[str] = None,
        video_size: Optional[int] = None,
        subtitle_format: str = "srt",
        comments: str = "",
        movie_name: Optional[str] = None,
        movie_year: Optional[str] = None,
        movie_kind: str = "movie"
    ):
        self.imdb_id = imdb_id
        self.language_code = language_code
        self.release_name = release_name
        self.video_hash = video_hash
        self.video_size = video_size
        self.subtitle_format = subtitle_format
        self.comments = comments
        self.movie_name = movie_name
        self.movie_year = movie_year
        self.movie_kind = movie_kind
    
    def validate(self) -> Tuple[bool, str]:
        """
        Valida che i metadati minimi siano presenti
        """
        if not self.imdb_id:
            return False, "IMDb ID Ã¨ obbligatorio"
        
        if not self.imdb_id.startswith('tt'):
            return False, "IMDb ID deve iniziare con 'tt'"
        
        if not self.language_code:
            return False, "Codice lingua Ã¨ obbligatorio"
        
        if len(self.language_code) != 3:
            return False, "Codice lingua deve essere ISO 639-2 (3 lettere)"
        
        if not self.release_name:
            return False, "Nome release Ã¨ obbligatorio"
        
        return True, ""


class SubtitleUploaderInterface(ABC):
    """
    Interfaccia astratta per uploader di sottotitoli
    """
    
    @abstractmethod
    def authenticate(self) -> bool: # âœ… FIX: Rimosse username e password
        """
        Autentica utente con il servizio (usa le credenziali passate al costruttore).
        
        Returns:
            True se autenticazione riuscita
        """
        pass
    
    @abstractmethod
    def upload(
        self,
        video_path: Path,
        subtitle_path: Path,
        metadata: SubtitleMetadata
    ) -> Tuple[bool, str]:
        """
        Esegue upload del sottotitolo
        """
        pass
    
    @abstractmethod
    def check_exists(
        self,
        video_path: Path,
        subtitle_path: Path,
        metadata: SubtitleMetadata
    ) -> Tuple[bool, str]:
        """
        Controlla se sottotitolo esiste giÃ  nel database
        """
        pass
    
    @abstractmethod
    def logout(self) -> None: # âœ… FIX: Rimosse firme non necessarie
        """
        Chiude sessione e rilascia risorse
        """
        pass
    
    def get_implementation_name(self) -> str:
        """
        Ritorna nome implementazione corrente (per logging)
        """
        return self.__class__.__name__


class UploaderFactory:
    """
    Factory per creare istanze di uploader
    """
    
    _implementations = {}
    
    @classmethod
    def register_implementation(cls, name: str, uploader_class):
        """Registra una nuova implementazione"""
        cls._implementations[name] = uploader_class
        logger.info(f"✅ Registrata implementazione uploader: {name}")
    
    @classmethod
    def create_uploader(
        cls,
        implementation: str = 'xmlrpc',
        **kwargs
    ) -> SubtitleUploaderInterface:
        """
        Crea istanza di uploader basata su implementazione richiesta
        """
        if implementation not in cls._implementations:
            available = ', '.join(cls._implementations.keys())
            raise ValueError(
                f"Implementazione '{implementation}' non disponibile. "
                f"Disponibili: {available}"
            )
        
        uploader_class = cls._implementations[implementation]
        logger.info(f"✅ Creazione uploader: {implementation}")
        
        return uploader_class(**kwargs)
    
    @classmethod
    def get_available_implementations(cls) -> list:
        """Ritorna lista implementazioni disponibili"""
        return list(cls._implementations.keys())