"""
OpenSubtitles Client - FIXED v2.1: Delega la serializzazione XML-RPC
File: utils/opensubtitles_client.py

CORREZIONI v2.1:
✅ FIX CRITICO: Il metodo 'upload_subtitle' ora delega completamente la preparazione 
   e l'upload all'istanza 'self.uploader' (OpenSubtitlesXMLRPCUploader), che gestisce 
   correttamente l'overflow convertendo moviebytesize in stringa.
✅ Rimosse le logiche di hash e zlib duplicate.
"""
import hashlib
from pathlib import Path
from typing import Optional, Tuple
import logging

from utils.subtitle_uploader_interface import SubtitleMetadata

logger = logging.getLogger(__name__)


class OpenSubtitlesClient:
    """
    Client per interagire con OpenSubtitles XML-RPC API
    
    È un WRAPPER che facilita l'uso dell'uploader XML-RPC
    """
    
    def __init__(self, xmlrpc_uploader):
        """
        Inizializza il client OpenSubtitles
        
        Args:
            xmlrpc_uploader: Istanza di OpenSubtitlesXMLRPCUploader (già autenticato)
        """
        self.uploader = xmlrpc_uploader
    
    def upload_subtitle(
        self,
        subtitle_path: Path,
        video_path: Path,
        force: bool = False,
        imdb_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Carica un sottotitolo su OpenSubtitles delegando all'uploader.
        
        Args:
            subtitle_path: Percorso del file sottotitolo (.srt)
            video_path: Percorso del file video
            force: Se True, forza l'upload anche se esiste già
            imdb_id: ID IMDB del film (es: 'tt1234567')
            
        Returns:
            Tuple[bool, str]: (success, message/url)
        """
        try:
            logger.info(f"📤 Inizio upload via client wrapper: {subtitle_path.name}")
            
            if not imdb_id:
                 return False, "IMDb ID mancante. Impossibile procedere."
            
            # STEP 1: Prepara Metadata Object
            
            # Estrai codice lingua dal nome file (necessario per Metadata)
            language_code = 'ita' # Default
            parts = subtitle_path.stem.split('.')
            for part in parts:
                if part.lower() in ['it', 'ita', 'italian']: language_code = 'ita'; break
                elif part.lower() in ['en', 'eng', 'english']: language_code = 'eng'; break
                elif part.lower() in ['es', 'spa', 'spanish']: language_code = 'spa'; break
                elif part.lower() in ['fr', 'fre', 'french']: language_code = 'fre'; break
                elif len(part) == 3 and part.isalpha(): language_code = part.lower()
            
            logger.info(f"   Lingua rilevata per upload: {language_code}")
            
            metadata = SubtitleMetadata(
                imdb_id=imdb_id,
                language_code=language_code, # 'ita' (3 lettere)
                release_name=video_path.stem
            )
            
            # STEP 2: Delega completamente l'upload all'OpenSubtitlesXMLRPCUploader
            logger.debug(f"Delega upload a {self.uploader.get_implementation_name()}...")
            
            success, url_or_error = self.uploader.upload(
                video_path=video_path,
                subtitle_path=subtitle_path,
                metadata=metadata
            )
            
            if success:
                logger.info("✅ Upload completato tramite uploader delegato.")
                return True, url_or_error
            else:
                logger.error(f"❌ Upload fallito tramite uploader delegato: {url_or_error}")
                return False, url_or_error
            
        except Exception as e:
            error_msg = f"Errore critico nel wrapper client: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.exception(e)
            return False, error_msg


def get_opensubtitles_client(xmlrpc_uploader):
    """
    Factory function per creare un'istanza di OpenSubtitlesClient
    """
    return OpenSubtitlesClient(xmlrpc_uploader)