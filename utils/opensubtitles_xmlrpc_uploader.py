"""
OpenSubtitles XML-RPC Uploader - v3.7
File: utils/opensubtitles_xmlrpc_uploader.py

CORREZIONI v3.7:
- FIX CRITICO: rimossa doppia codifica Base64 di subcontent (xmlrpc.client.Binary rimosso)
- FIX: struttura UploadSubtitles corretta: {baseinfo: {...}, cd1: {...}}
- FIX: TryUploadSubtitles integrato nel flusso upload() prima di UploadSubtitles
"""
import xmlrpc.client
import hashlib
import struct
import os
import base64
import gzip
import re
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from utils.subtitle_uploader_interface import (
    SubtitleUploaderInterface,
    SubtitleMetadata,
    UploaderFactory
)

logger = logging.getLogger(__name__)


class OpenSubtitlesXMLRPCUploader(SubtitleUploaderInterface):
    """
    Implementazione XML-RPC per upload sottotitoli su OpenSubtitles.org
    """
    
    XMLRPC_URL = "https://api.opensubtitles.org/xml-rpc"
    DEFAULT_USER_AGENT = "TranscriberPro/1.0"
    
    def __init__(
        self,
        username: str = None,
        password: str = None,
        user_agent: str = None,
        api_key: str = None  # ignorato, presente per compatibilità con la factory
    ):
        self.username = username
        self.password = password
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.token = None
        self._ua_registered = False  # True solo dopo login 200 OK
        
        self.server = xmlrpc.client.ServerProxy(
            self.XMLRPC_URL,
            allow_none=True
        )
        
        logger.info(f"📡 OpenSubtitles XML-RPC Uploader inizializzato")
    
    # ✅ FIX: Firma con *args (che non usa Any), ma manteniamo l'import in caso di necessità
    def authenticate(self, *args, **kwargs) -> bool: 
        """
        Autentica utente con OpenSubtitles API (accetta args per conformità ABC)
        """
        current_username = self.username
        current_password = self.password
        
        if not current_username or not current_password:
            logger.error("❌ Username/password mancanti")
            return False
        
        try:
            logger.info(f"🔐 Autenticazione come: {current_username}")
            
            password_hash = hashlib.md5(current_password.encode('utf-8')).hexdigest()
            
            response = self.server.LogIn(
                current_username,
                password_hash,
                'en',
                self.user_agent
            )
            
            status = response.get('status', '')
            self.token = response.get('token')

            if self.token and status == '200 OK':
                self._ua_registered = True
                logger.info("✅ Autenticazione riuscita (200 OK) — upload abilitato")
                return True
            elif self.token and status == '401 Unauthorized':
                # 401 con token: UA non registrato. La ricerca funziona, ma gli UPLOAD
                # sono bloccati dal server (documentato: UA registration required for upload).
                # https://www.opensubtitles.org/addons/new per registrare il tuo UA.
                self._ua_registered = False
                logger.warning("⚠️  Login 401 — User-Agent NON registrato.")
                logger.warning("   Search funziona, ma gli UPLOAD saranno rifiutati dal server.")
                logger.warning("   Registra 'TranscriberPro v1.0.0' su: https://www.opensubtitles.org/addons/new")
                return True  # consente search; upload() uscirà con errore chiaro
            else:
                logger.error(f"❌ Autenticazione fallita: {status}")
                self.token = None
                return False
        
        except xmlrpc.client.Fault as err:
            logger.error(f"❌ Fault XML-RPC: {err.faultCode} - {err.faultString}")
            return False
        except Exception as e:
            logger.error(f"❌ Errore autenticazione: {e}", exc_info=True)
            return False

    def is_authenticated(self) -> bool:
        if not self.token: return False
        try:
            response = self.server.NoOperation(self.token)
            return response.get('status') == '200 OK'
        except: return False
    
    def check_exists(
        self,
        video_path: Path,
        subtitle_path: Path,
        metadata: SubtitleMetadata
    ) -> Tuple[bool, str]:
        """
        Verifica se sottotitolo esiste già nel database (TryUploadSubtitles)
        """
        if not self.token:
            return False, "Non autenticato - chiamare authenticate() prima"
        
        is_valid, error_msg = metadata.validate()
        if not is_valid:
            return False, f"Metadata non validi: {error_msg}"
        
        try:
            logger.info("🔍 Controllo esistenza sottotitolo...")
            
            # Calcolo hash
            movie_hash, movie_size = self.calculate_movie_hash(video_path)
            if not movie_hash: return False, "Impossibile calcolare hash video"
            # subhash = MD5 del contenuto stripped (no cue promo, no BOM) — identico a upload()
            _, stripped_bytes = self._prepare_subtitle_content(subtitle_path)
            if stripped_bytes is None: return False, "Impossibile preparare contenuto sottotitolo"
            sub_hash = hashlib.md5(stripped_bytes).hexdigest()
            
            # Prepara dati
            try_data = {
                'subhash': sub_hash,
                'subfilename': subtitle_path.name,
                'moviehash': movie_hash,
                'moviebytesize': str(movie_size), 
                'moviefilename': video_path.name,
            }
            
            if metadata.imdb_id:
                try_data['movieimdbid'] = metadata.imdb_id.replace('tt', '')
            
            # Chiamata API
            response = self.server.TryUploadSubtitles(self.token, [try_data])
            
            status = response.get('status', '')
            if status != '200 OK':
                return False, f"Errore check: {status}"
            
            already_in_db = response.get('alreadyindb', 0)
            
            if already_in_db == 1:
                return True, "Sottotitolo già presente"
            else:
                return False, "Pronto per upload"
        
        except xmlrpc.client.Fault as err:
            error_msg = f"Fault XML-RPC: {err.faultCode} - {err.faultString}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Errore check: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            return False, error_msg
    
    def upload(
        self,
        video_path: Path,
        subtitle_path: Path,
        metadata: SubtitleMetadata
    ) -> Tuple[bool, str]:
        """
        Upload sottotitolo su OpenSubtitles.

        Flusso:
        1. TryUploadSubtitles  — verifica se il sottotitolo è già nel DB
        2. UploadSubtitles     — invio effettivo solo se alreadyindb == 0
        """
        if not self.token:
            return False, "Non autenticato - chiamare authenticate() prima"

        if not self._ua_registered:
            msg = (
                "User-Agent non registrato — upload bloccato dal server OS. "
                "Registra 'TranscriberPro v1.0.0' su https://www.opensubtitles.org/addons/new "
                "poi riavvia l'applicazione."
            )
            logger.error(f"❌ {msg}")
            return False, msg

        is_valid, error_msg = metadata.validate()
        if not is_valid:
            return False, f"Metadata non validi: {error_msg}"

        try:
            logger.info(f"📤 Inizio upload: {subtitle_path.name}")

            # --- Calcolo hash ---
            movie_hash, movie_size = self.calculate_movie_hash(video_path)
            if not movie_hash:
                return False, "Impossibile calcolare hash video"

            imdb_numeric = metadata.imdb_id.replace('tt', '')

            # --- Prepara contenuto ---
            # I nostri SRT contengono un cue promozionale ("AI generated subtitles")
            # che OpenSubtitles rifiuta esplicitamente con 402 Invalid format.
            # Dobbiamo strippare il cue PRIMA di comprimere e hashare:
            #   - subcontent = gzip+base64(stripped_bytes)
            #   - subhash    = MD5(stripped_bytes)   ← stesso contenuto inviato
            # _prepare_subtitle_content() fa: strip BOM + normalizza CRLF→LF +
            # rimuove cue promozionali + re-encode UTF-8.
            _, stripped_bytes = self._prepare_subtitle_content(subtitle_path)
            if stripped_bytes is None:
                return False, "Impossibile preparare contenuto sottotitolo"
            # subcontent = base64(gzip(stripped)) come stringa XML-RPC <string>
            sub_hash = hashlib.md5(stripped_bytes).hexdigest()
            sub_content = base64.b64encode(gzip.compress(stripped_bytes)).decode('ascii')
            logger.info(f"   sub_hash (stripped, no-BOM): {sub_hash}")

            # --- Step 1: TryUploadSubtitles ---
            logger.info("   [1/2] Verifica esistenza sottotitolo (TryUploadSubtitles)...")
            try_data = {
                'subhash': sub_hash,
                'subfilename': subtitle_path.name,
                'moviehash': movie_hash,
                'moviebytesize': str(movie_size),
                'moviefilename': video_path.name,
            }
            if imdb_numeric:
                try_data['movieimdbid'] = imdb_numeric

            try_response = self.server.TryUploadSubtitles(self.token, [try_data])
            try_status = try_response.get('status', '')
            if try_status != '200 OK':
                return False, f"Errore verifica pre-upload: {try_status}"

            if try_response.get('alreadyindb', 0) == 1:
                logger.info("ℹ️  Sottotitolo già presente nel database")
                return True, "Sottotitolo già presente nel database"

            # --- Step 2: UploadSubtitles ---
            logger.info("   [2/2] Upload in corso (UploadSubtitles)...")

            # xmlrpc.client usa UTF-8 nativamente: non serve lo strip ASCII
            # (strip aggressivo corrompeva release con accenti o caratteri non-ASCII)
            safe_release_name = metadata.release_name or ''
            safe_comments = metadata.comments or ''
            safe_username = self.username or ''

            # Struttura corretta per UploadSubtitles: baseinfo + cd1
            upload_struct = {
                'baseinfo': {
                    'idmovieimdb': imdb_numeric,
                    'sublanguageid': metadata.language_code,
                    'moviereleasename': safe_release_name,
                    'movieaka': '',
                    'subauthorcomment': safe_comments or 'Uploaded via TranscriberPro',
                    'subtranslator': safe_username,
                    'automatictranslation': '1',  # sottotitoli generati da AI
                },
                'cd1': {
                    'subhash': sub_hash,
                    'subfilename': subtitle_path.name,
                    'moviehash': movie_hash,
                    'moviebytesize': str(movie_size),
                    'moviefilename': video_path.name,
                    'subcontent': sub_content,
                },
            }

            if metadata.subtitle_format:
                upload_struct['baseinfo']['subformat'] = metadata.subtitle_format

            response = self.server.UploadSubtitles(self.token, upload_struct)
            status = response.get('status', '')

            if status == '200 OK':
                subtitle_url = response.get('data', '')
                if subtitle_url:
                    logger.info(f"✅ Upload completato con successo!")
                    return True, subtitle_url
                else:
                    logger.info(f"✅ Upload completato (nessun URL fornito)")
                    return True, "Upload riuscito"
            else:
                error_msg = f"Upload fallito: {status}"
                logger.error(f"❌ {error_msg}")
                return False, error_msg

        except xmlrpc.client.Fault as err:
            error_msg = f"{err.faultCode} {err.faultString}"
            logger.error(f"❌ Upload fallito (Fault XML-RPC): {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Errore upload: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            return False, error_msg
    
    def logout(self, *args, **kwargs) -> None: 
        """
        Logout e invalidazione token sessione (con signature flessibile per ABC)
        """
        if not self.token:
            return
        
        try:
            logger.info("🔓 Logout...")
            self.server.LogOut(self.token)
            logger.info("✅ Logout completato")
        except xmlrpc.client.Fault as err:
            logger.warning(f"⚠️ Errore logout: {err.faultString}")
        except Exception as e:
            logger.warning(f"⚠️ Errore logout: {e}")
        finally:
            self.token = None
    
    def calculate_movie_hash(self, video_path: Path) -> Tuple[Optional[str], Optional[int]]:
        """
        Calcola OSDB hash per file video
        """
        try:
            file_size = os.path.getsize(video_path)
            
            if file_size < 131072: 
                logger.error(f"File troppo piccolo per hash: {file_size} bytes (minimo 128KB)")
                return None, None
            
            hash_value = file_size
            
            with open(video_path, 'rb') as f:
                # Hash primi 64KB
                for _ in range(8192):
                    chunk = f.read(8)
                    if len(chunk) < 8: break
                    (value,) = struct.unpack('<q', chunk)
                    hash_value += value
                    hash_value &= 0xFFFFFFFFFFFFFFFF
                
                # Hash ultimi 64KB
                f.seek(max(0, file_size - 65536), 0)
                for _ in range(8192):
                    chunk = f.read(8)
                    if len(chunk) < 8: break
                    (value,) = struct.unpack('<q', chunk)
                    hash_value += value
                    hash_value &= 0xFFFFFFFFFFFFFFFF
            
            hash_hex = f"{hash_value:016x}"
            return hash_hex, file_size
        
        except (IOError, struct.error) as e:
            logger.error(f"Errore calcolo hash video: {e}")
            return None, None

    def _calculate_subtitle_hash(self, subtitle_path: Path) -> Optional[str]:
        """Calcola MD5 del contenuto normalizzato (no-BOM, LF) — identico a upload()."""
        try:
            with open(subtitle_path, 'rb') as f:
                content = f.read()
            if content[:3] == b'\xef\xbb\xbf':
                content = content[3:]
            content = content.replace(b'\r\n', b'\n')
            return hashlib.md5(content).hexdigest()
        except IOError as e:
            logger.error(f"Errore calcolo hash sottotitolo: {e}")
            return None
    
    _CREDIT_PATTERNS = [
        'transcriber_pro', 'transcriber pro',
        'ai generated subtitles', 'ai-generated subtitles',
    ]

    def _strip_credit_cues(self, text: str) -> str:
        """Rimuove cue SRT promozionali e rinumera i cue rimanenti."""
        text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
        blocks = re.split(r'\n{2,}', text.strip())
        kept, removed = [], 0
        for block in blocks:
            lines = block.strip().splitlines()
            if len(lines) >= 3 and any(p in ' '.join(lines[2:]).lower() for p in self._CREDIT_PATTERNS):
                removed += 1
                logger.info(f"🧹 Rimosso cue promozionale: {lines[2]!r}")
            else:
                kept.append(block)
        if removed:
            renumbered = []
            for i, block in enumerate(kept, start=1):
                lines = block.strip().splitlines()
                if len(lines) >= 2 and '-->' in lines[1]:
                    lines[0] = str(i)
                renumbered.append('\n'.join(lines))
            kept = renumbered
        return '\n\n'.join(kept) + '\n'

    def _prepare_subtitle_content(self, subtitle_path: Path) -> Optional[str]:
        """
        Prepara contenuto sottotitolo per upload (gzip + base64).
        Rimuove anche il cue promozionale prima della compressione.
        """
        try:
            with open(subtitle_path, 'rb') as f:
                raw = f.read()

            # Rimuovi cue promozionali (stesso filtro del REST uploader)
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')
            cleaned = self._strip_credit_cues(text)
            content = cleaned.encode('utf-8')

            # gzip + base64 — formato richiesto dall'API XML-RPC OpenSubtitles
            encoded = base64.b64encode(gzip.compress(content)).decode('ascii')
            return encoded, content

        except IOError as e:
            logger.error(f"Errore preparazione contenuto: {e}")
            return None, None


# REGISTRA IMPLEMENTAZIONE
UploaderFactory.register_implementation('xmlrpc', OpenSubtitlesXMLRPCUploader)