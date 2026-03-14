"""
OpenSubtitles REST Uploader - FIXED v3.1 (Encoding & Retry for special chars)
File: utils/opensubtitles_rest_uploader.py

NOTE:
- Mantiene tutte le funzionalità precedenti (v3.0).
- Aggiunge invio JSON UTF-8 e retry con percent-encoding per password contenenti
  caratteri speciali che alcuni endpoint potrebbero interpretare male.
"""

import requests
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import os
import struct
import urllib.parse
import time

# Import corretto delle classi base dalla Factory globale
from utils.subtitle_uploader_interface import (
    SubtitleUploaderInterface,
    SubtitleMetadata,
    UploaderFactory
)

# --- CONFIGURAZIONE LOGGING ---
logger = logging.getLogger(__name__)

def set_debug_logging():
    """Attiva logging dettagliato per debugging"""
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(levelname)s [%(name)s]: %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.debug("✅ Debug logging attivato per REST uploader")

# Attiva debug logging automaticamente
set_debug_logging()


class OpenSubtitlesRESTUploader(SubtitleUploaderInterface):
    """
    Implementazione REST API v1 per upload sottotitoli su OpenSubtitles.com
    
    SPECIFICHE API:
    - Base URL: https://vip-api.opensubtitles.com/api/v1
    - Autenticazione: JWT Token (via login endpoint)
    - Upload: Multipart/form-data con metadata JSON
    - Rate Limit: Rispettato tramite JWT token con scadenza
    
    REQUISITI:
    - API Key REST (obbligatoria)
    - Username e Password OpenSubtitles
    - User-Agent personalizzato
    """
    
    BASE_URL = "https://api.opensubtitles.com/api/v1"
    LOGIN_URL = f"{BASE_URL}/login"
    LOGOUT_URL = f"{BASE_URL}/logout"
    UPLOAD_URL = f"{BASE_URL}/upload"
    
    def __init__(
        self,
        username: str = None,
        password: str = None,
        user_agent: str = None,
        api_key: str = None
    ):
        """
        Inizializza uploader REST
        
        Args:
            username: Username OpenSubtitles
            password: Password OpenSubtitles
            user_agent: User-Agent personalizzato (default: TranscriberPro v1.1.0)
            api_key: REST API Key (OBBLIGATORIA per REST API)
        """
        self.username = username
        self.password = password
        self.user_agent = user_agent or "TranscriberPro v1.1.0"
        self.api_key = api_key
        self.jwt_token: Optional[str] = None
        
        if not self.api_key:
            logger.error("❌ REST API Key non fornita!")
            logger.error("   Ottieni la tua API Key da: https://www.opensubtitles.com/en/consumers")
        else:
            logger.info(f"📡 OpenSubtitles REST Uploader inizializzato")
            logger.info(f"   API Key: ✅ Configurata ({self.api_key[:8]}...)")

    def _get_headers(self, include_content_type: bool = True) -> Dict[str, str]:
        """
        Crea headers HTTP per le richieste REST
        
        Args:
            include_content_type: Se True, include Content-Type: application/json
        
        Returns:
            Dict con headers completi
        
        Raises:
            ValueError: Se API Key non configurata
        """
        if not self.api_key:
            raise ValueError("REST API Key non configurata. Upload impossibile.")
            
        headers = {
            'Api-Key': self.api_key,
            'User-Agent': self.user_agent,
            'Accept': 'application/json'
        }
        
        if include_content_type:
            # Specifica charset per assicurare corretta interpretazione UTF-8
            headers['Content-Type'] = 'application/json; charset=utf-8'
        
        # Aggiungi JWT token se disponibile
        if self.jwt_token:
            headers['Authorization'] = f'Bearer {self.jwt_token}'
        
        return headers
    
    def authenticate(self) -> bool:
        """
        Esegue login per ottenere JWT Token
        
        Il JWT token è richiesto per tutte le operazioni di upload.
        Ha una scadenza limitata (controllare documentazione API).
        
        Questo metodo invia il payload JSON codificato in UTF-8 (ensure_ascii=False)
        per preservare i caratteri speciali. Se si riceve 401, effettua un retry
        con la password percent-encoded (URL-escaped) per compatibilità con
        endpoint che interpretianno male alcuni caratteri.
        
        Returns:
            True se login riuscito e token ottenuto
        """
        if not self.username or not self.password:
            logger.error("❌ Username o Password mancanti")
            return False
        
        if not self.api_key:
            logger.error("❌ API Key mancante (obbligatoria per REST)")
            return False
        
        try:
            logger.info(f"🔐 Login REST come: {self.username}")
            logger.info("=" * 80)
            logger.info("LOGIN REQUEST DETAILS:")
            logger.info("=" * 80)
            
            # Headers base (includiamo charset=utf-8)
            headers = self._get_headers(include_content_type=True)
            
            # Payload originale (username lowercase: la REST API restituisce 401 con maiuscole)
            payload = {
                'username': self.username.lower(),
                'password': self.password
            }
            
            # Log headers (mascherando dati sensibili)
            safe_headers = headers.copy()
            if 'Api-Key' in safe_headers:
                safe_headers['Api-Key'] = safe_headers['Api-Key'][:8] + '...'
            logger.info(f"URL: {self.LOGIN_URL}")
            logger.info(f"Headers: {json.dumps(safe_headers, indent=2)}")
            logger.info(f"Payload: {{'username': '{self.username}', 'password': '***'}}")
            
            # JSON dump con ensure_ascii=False per preservare caratteri unicode e speciali,
            # poi encode in utf-8 per assicurare il corretto byte-stream (evita problemi di
            # codifica sul wire)
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            
            response = requests.post(
                self.LOGIN_URL,
                headers=headers,
                data=body,
                timeout=30
            )
            
            logger.info(f"Response Status: {response.status_code}")
            logger.info(f"Response Headers: {dict(response.headers)}")
            
            if not response.ok:
                # Se riceviamo 401, proviamo un retry con password percent-encoded,
                # nel caso in cui il server interpreti male alcuni caratteri speciali.
                if response.status_code == 401:
                    logger.warning("⚠️  Ricevuto 401 durante primo tentativo di login.")
                    logger.warning("      Effettuo retry automatico inviando la password percent-encoded.")
                    
                    # Prepariamo payload con password percent-encoded
                    encoded_pw = urllib.parse.quote_plus(self.password, safe='')
                    retry_payload = {
                        'username': self.username.lower(),
                        'password': encoded_pw
                    }
                    safe_headers_2 = headers.copy()
                    if 'Api-Key' in safe_headers_2:
                        safe_headers_2['Api-Key'] = safe_headers_2['Api-Key'][:8] + '...'
                    logger.info("Retry URL: " + self.LOGIN_URL)
                    logger.info(f"Retry Headers: {json.dumps(safe_headers_2, indent=2)}")
                    logger.info("Retry Payload: {'username': '<redacted>', 'password': '<percent-encoded>'}")
                    
                    # Rispetta Retry-After dalla risposta 401 (default 1.5s per il rate limit 1 req/sec)
                    retry_after = float(response.headers.get('Retry-After', 1.5))
                    logger.info(f"Attesa {retry_after}s prima del retry (Retry-After header)...")
                    time.sleep(retry_after)
                    retry_body = json.dumps(retry_payload, ensure_ascii=False).encode('utf-8')
                    try:
                        response_retry = requests.post(
                            self.LOGIN_URL,
                            headers=headers,
                            data=retry_body,
                            timeout=30
                        )
                    except requests.exceptions.RequestException as e:
                        logger.error(f"❌ Retry login fallito: {e}")
                        return False
                    
                    logger.info(f"Retry Response Status: {response_retry.status_code}")
                    logger.info(f"Retry Response Headers: {dict(response_retry.headers)}")
                    
                    if not response_retry.ok:
                        logger.error("=" * 80)
                        logger.error(f"❌ LOGIN FAILED AFTER RETRY - Status {response_retry.status_code}")
                        logger.error("=" * 80)
                        try:
                            error_details = response_retry.json()
                            logger.error("ERROR DETAILS:")
                            logger.error(json.dumps(error_details, indent=2))
                        except json.JSONDecodeError:
                            logger.error("RAW ERROR RESPONSE:")
                            logger.error(response_retry.text[:500] if len(response_retry.text) > 500 else response_retry.text)
                        return False
                    else:
                        # Successo al retry
                        try:
                            data = response_retry.json()
                        except json.JSONDecodeError:
                            logger.error("❌ Login retry riuscito ma non è stato possibile parseare il JSON della risposta.")
                            return False
                        self.jwt_token = data.get('token')
                        if self.jwt_token:
                            logger.info("=" * 80)
                            logger.info("✅ LOGIN SUCCESSFUL (after retry with percent-encoded password)")
                            logger.info("=" * 80)
                            logger.info(f"JWT Token (first 30 chars): {self.jwt_token[:30]}...")
                            return True
                        else:
                            logger.error("❌ LOGIN FAILED - No token in retry response")
                            return False
                else:
                    logger.error("=" * 80)
                    logger.error(f"❌ LOGIN FAILED - Status {response.status_code}")
                    logger.error("=" * 80)
                    try:
                        error_details = response.json()
                        logger.error("ERROR DETAILS:")
                        logger.error(json.dumps(error_details, indent=2))
                    except json.JSONDecodeError:
                        logger.error("RAW ERROR RESPONSE:")
                        logger.error(response.text[:500] if len(response.text) > 500 else response.text)
                    return False
            
            # Se response.ok al primo tentativo
            logger.info("=" * 80)
            logger.info("LOGIN RESPONSE BODY:")
            logger.info("=" * 80)
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                logger.error("❌ Impossibile decodificare JSON di risposta al login")
                logger.error("Raw response:")
                logger.error(response.text[:1000] if len(response.text) > 1000 else response.text)
                return False
            
            logger.info(json.dumps(data, indent=2))
            
            self.jwt_token = data.get('token')
            
            if self.jwt_token:
                logger.info("=" * 80)
                logger.info("✅ LOGIN SUCCESSFUL")
                logger.info("=" * 80)
                logger.info(f"JWT Token (first 30 chars): {self.jwt_token[:30]}...")
                logger.info(f"JWT Token length: {len(self.jwt_token)} characters")
                
                # Verifica altri campi nella risposta
                for key, value in data.items():
                    if key != 'token':
                        logger.info(f"Response field '{key}': {value}")
                
                return True
            else:
                logger.error("=" * 80)
                logger.error("❌ LOGIN FAILED - No token in response")
                logger.error("=" * 80)
                logger.error("Response contained no 'token' field")
                return False
            
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout durante login - server non risponde")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("❌ Errore di connessione - verifica la rete")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Errore durante login: {type(e).__name__} - {e}")
            return False

    def check_exists(
        self,
        video_path: Path,
        subtitle_path: Path,
        metadata: SubtitleMetadata
    ) -> Tuple[bool, str]:
        """
        Controlla se sottotitolo esiste già nel database
        
        NOTA: La REST API non fornisce un endpoint dedicato per questo check.
        Il controllo avviene automaticamente durante l'upload.
        
        Returns:
            (False, messaggio) - indica di procedere all'upload
        """
        logger.info("ℹ️  REST API: Check esistenza non disponibile")
        logger.info("   Il controllo duplicati avverrà automaticamente durante upload")
        return False, "Check non supportato - procedi all'upload"
    
    def upload(
        self,
        video_path: Path,
        subtitle_path: Path,
        metadata: SubtitleMetadata,
        _is_retry: bool = False
    ) -> Tuple[bool, str]:
        """
        Esegue upload del sottotitolo su OpenSubtitles
        
        WORKFLOW:
        1. Valida autenticazione e metadata
        2. Calcola movie hash (OSDB standard)
        3. Prepara metadata JSON
        4. Invia richiesta multipart/form-data
        5. Gestisce risposta (successo/errori/duplicati)
        
        Args:
            video_path: Path al file video originale
            subtitle_path: Path al file sottotitolo da uploadare
            metadata: Metadata completi (IMDb, lingua, release)
        
        Returns:
            (success, message) dove:
            - success: True se upload riuscito
            - message: URL sottotitolo o descrizione errore
        """
        # Validazione autenticazione
        if not self.jwt_token:
            logger.error("❌ Upload fallito: non autenticato")
            return False, "Non autenticato - chiamare authenticate() prima"
        
        # Validazione metadata
        is_valid, error_msg = metadata.validate()
        if not is_valid:
            logger.error(f"❌ Metadata non validi: {error_msg}")
            return False, f"Metadata non validi: {error_msg}"
        
        try:
            logger.info(f"📤 Inizio upload REST: {subtitle_path.name}")
            logger.info("=" * 80)
            logger.info("UPLOAD PREPARATION:")
            logger.info("=" * 80)
            
            # Calcolo movie hash
            logger.info("📊 Calcolo movie hash...")
            movie_hash, movie_size = self._calculate_movie_hash(video_path)
            if not movie_hash:
                logger.error("❌ Impossibile calcolare movie hash")
                return False, "Impossibile calcolare hash video"
            
            logger.info(f"✅ Movie Hash: {movie_hash}")
            logger.info(f"✅ Movie Size: {movie_size:,} bytes ({movie_size / (1024**3):.2f} GB)")
            
            # Prepara metadata per upload
            imdb_numeric = metadata.imdb_id.replace('tt', '')
            upload_metadata = {
                "cd1": [
                    {
                        "sublanguageid": metadata.language_code,
                        "moviehash": movie_hash,
                        "moviebytesize": str(movie_size),
                        "moviefilename": video_path.name,
                        "moviereleasename": metadata.release_name,
                        "subfilename": subtitle_path.name
                    }
                ],
                "baseinfo": {
                    "idmovieimdb": imdb_numeric
                }
            }
            
            # Aggiungi campi opzionali se presenti
            if metadata.comments:
                upload_metadata["cd1"][0]["subauthorcomment"] = metadata.comments
            if metadata.movie_name:
                upload_metadata["cd1"][0]["moviename"] = metadata.movie_name
            if metadata.movie_year:
                upload_metadata["cd1"][0]["movieyear"] = str(metadata.movie_year)
            
            logger.info("=" * 80)
            logger.info("UPLOAD METADATA:")
            logger.info("=" * 80)
            logger.info(json.dumps(upload_metadata, indent=2))
            
            # Informazioni file sottotitolo
            subtitle_size = os.path.getsize(subtitle_path)
            logger.info("=" * 80)
            logger.info("SUBTITLE FILE INFO:")
            logger.info("=" * 80)
            logger.info(f"Path: {subtitle_path}")
            logger.info(f"Name: {subtitle_path.name}")
            logger.info(f"Size: {subtitle_size:,} bytes ({subtitle_size / 1024:.2f} KB)")
            
            # Leggi prime righe del sottotitolo per verifica
            try:
                with open(subtitle_path, 'r', encoding='utf-8') as f:
                    first_lines = ''.join(f.readlines()[:10])
                logger.info(f"First lines preview:\n{first_lines}")
            except Exception as e:
                logger.warning(f"⚠️  Impossibile leggere anteprima sottotitolo: {e}")
            
            # Prepara richiesta multipart/form-data
            logger.info("=" * 80)
            logger.info("PREPARING HTTP REQUEST:")
            logger.info("=" * 80)
            
            with open(subtitle_path, 'rb') as sub_file:
                files = {
                    'file': (subtitle_path.name, sub_file, 'text/plain')
                }
                data = {
                    'metadata': json.dumps(upload_metadata)
                }
                headers = self._get_headers(include_content_type=False)
                
                # Log headers (mascherando dati sensibili)
                safe_headers = headers.copy()
                if 'Api-Key' in safe_headers:
                    safe_headers['Api-Key'] = safe_headers['Api-Key'][:8] + '...'
                if 'Authorization' in safe_headers:
                    safe_headers['Authorization'] = safe_headers['Authorization'][:30] + '...'
                
                logger.info(f"URL: {self.UPLOAD_URL}")
                logger.info(f"Headers: {json.dumps(safe_headers, indent=2)}")
                logger.info(f"Files: {{'file': ('{subtitle_path.name}', '<binary data>', 'text/plain')}}")
                logger.info(f"Data: {{'metadata': '<JSON shown above>'}}")
                
                logger.info("=" * 80)
                logger.info("🚀 SENDING UPLOAD REQUEST...")
                logger.info("=" * 80)
                
                response = requests.post(
                    self.UPLOAD_URL,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=120
                )
            
            # Gestione risposta dettagliata
            logger.info("=" * 80)
            logger.info("UPLOAD RESPONSE RECEIVED:")
            logger.info("=" * 80)
            status_code = response.status_code
            logger.info(f"Status Code: {status_code}")
            logger.info(f"Response Headers: {dict(response.headers)}")
            logger.info(f"Response Size: {len(response.content)} bytes")
            
            # Log body completo
            response_body = response.text
            logger.info("=" * 80)
            logger.info("RESPONSE BODY (RAW):")
            logger.info("=" * 80)
            logger.info(response_body if response_body else "<empty>")
            logger.info("=" * 80)
            
            # Caso 1: Upload completato (204 No Content)
            if status_code == 204:
                logger.info("=" * 80)
                logger.info("✅ UPLOAD SUCCESSFUL - 204 NO CONTENT")
                logger.info("=" * 80)
                logger.info("Il server ha accettato il sottotitolo.")
                logger.info("Nessun body nella risposta (comportamento normale per 204).")
                return True, "Upload completato con successo"
            
            # Caso 2: Errore HTTP
            if not response.ok:
                # Fix Bug 3: Re-autenticazione automatica su 401 (una sola volta)
                if status_code == 401 and not _is_retry:
                    logger.warning("⚠️  JWT token scaduto durante upload - re-autenticazione in corso...")
                    if self.authenticate():
                        logger.info("✅ Re-autenticazione riuscita, ripeto upload...")
                        return self.upload(video_path, subtitle_path, metadata, _is_retry=True)
                    else:
                        logger.error("❌ Re-autenticazione fallita")
                        return False, "JWT token scaduto (401) e re-autenticazione fallita"

                logger.error("=" * 80)
                logger.error(f"❌ UPLOAD FAILED - HTTP {status_code}")
                logger.error("=" * 80)
                
                try:
                    response_json = response.json()
                    logger.error("ERROR DETAILS (JSON):")
                    logger.error(json.dumps(response_json, indent=2))
                    
                    # Estrai messaggio di errore
                    error_msg = response_json.get('message', f'Errore sconosciuto (Status {status_code})')
                    
                    # Log campi aggiuntivi se presenti
                    if 'errors' in response_json:
                        logger.error(f"Errors field: {response_json['errors']}")
                    if 'status' in response_json:
                        logger.error(f"Status field: {response_json['status']}")
                    
                    return False, f"Upload fallito: {error_msg}"
                    
                except json.JSONDecodeError:
                    logger.error("ERROR DETAILS (NON-JSON):")
                    logger.error(response_body[:1000] if len(response_body) > 1000 else response_body)
                    
                    # Gestisci errori noti
                    if status_code == 401:
                        logger.error("🔑 AUTHENTICATION ERROR - JWT token probabilmente scaduto")
                        return False, "JWT token scaduto (401) - riautenticarsi"
                    elif status_code == 402:
                        logger.error("📝 SUBTITLE FORMAT ERROR - Contenuto non valido")
                        return False, "Formato sottotitolo invalido (402) - rimuovi URL o contenuti pubblicitari"
                    elif status_code == 403:
                        logger.error("🚫 ACCESS DENIED - Verifica credenziali")
                        return False, "Accesso negato (403) - verifica credenziali e API key"
                    elif status_code == 406:
                        logger.error("⚠️  NOT ACCEPTABLE - Formato metadata non accettato")
                        return False, "Metadata non accettati (406) - verifica formato"
                    elif status_code == 415:
                        logger.error("📄 UNSUPPORTED MEDIA TYPE - Tipo file non supportato")
                        return False, "Tipo file non supportato (415)"
                    elif status_code == 503:
                        logger.error("🔧 SERVICE UNAVAILABLE - Server in manutenzione")
                        return False, "OpenSubtitles non disponibile (503) - riprova più tardi"
                    else:
                        return False, f"HTTP {status_code}: Risposta server non analizzabile"

            # Caso 3: Successo con body (200 OK)
            logger.info("=" * 80)
            logger.info("📨 PROCESSING SUCCESS RESPONSE (200 OK)")
            logger.info("=" * 80)
            
            try:
                response_json = response.json()
                logger.info("PARSED JSON RESPONSE:")
                logger.info(json.dumps(response_json, indent=2))
                
                # Sottotitolo già presente nel database
                if response_json.get('alreadyindb') == 1:
                    logger.info("=" * 80)
                    logger.info("⚠️  SUBTITLE ALREADY EXISTS IN DATABASE")
                    logger.info("=" * 80)
                    
                    subtitle_id = response_json.get('data', {}).get('IDSubtitle')
                    logger.info(f"Subtitle ID: {subtitle_id}")
                    
                    if subtitle_id:
                        url = f"https://www.opensubtitles.org/subtitles/{subtitle_id}"
                        logger.info(f"Subtitle URL: {url}")
                        return True, f"GIÀ PRESENTE - {url}"
                    else:
                        logger.warning("⚠️  Subtitle ID non trovato nella risposta")
                        return True, "GIÀ PRESENTE - Dettagli non disponibili"
                
                # Upload nuovo completato
                else:
                    logger.info("=" * 80)
                    logger.info("✅ NEW SUBTITLE UPLOADED SUCCESSFULLY")
                    logger.info("=" * 80)
                    
                    subtitle_url = response_json.get('url') or response_json.get('data', '')
                    
                    # Log tutti i campi della risposta
                    for key, value in response_json.items():
                        logger.info(f"Response field '{key}': {value}")
                    
                    if subtitle_url:
                        logger.info(f"Subtitle URL: {subtitle_url}")
                        return True, subtitle_url
                    else:
                        logger.warning("⚠️  URL del sottotitolo non trovato nella risposta")
                        return True, "Upload riuscito (URL non disponibile)"
            
            except json.JSONDecodeError:
                logger.error("=" * 80)
                logger.error("⚠️  UNEXPECTED: Response 200 but body is not valid JSON")
                logger.error("=" * 80)
                logger.error("Raw response body:")
                logger.error(response_body[:1000] if len(response_body) > 1000 else response_body)
                return True, "Upload probabilmente riuscito (risposta non standard)"

        except requests.exceptions.Timeout:
            logger.error("❌ Timeout durante upload - richiesta troppo lenta")
            return False, "Timeout durante upload - riprova"
        
        except requests.exceptions.ConnectionError:
            logger.error("❌ Errore di connessione durante upload")
            return False, "Errore di connessione - verifica la rete"
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Errore HTTP durante upload: {type(e).__name__} - {e}")
            return False, f"Errore di connessione: {str(e)}"
        
        except Exception as e:
            logger.error(f"❌ Errore imprevisto upload: {e}", exc_info=True)
            return False, f"Errore generico: {str(e)}"

    def logout(self) -> None:
        """
        Esegue logout sul server e rimuove JWT token locale.

        Chiama DELETE /api/v1/logout per invalidare il token sul server
        (altrimenti rimarrebbe valido per 24h).
        """
        if self.jwt_token:
            try:
                headers = self._get_headers(include_content_type=False)
                response = requests.delete(self.LOGOUT_URL, headers=headers, timeout=15)
                logger.info(f"🔓 Logout server: HTTP {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️  Logout server fallito (token rimosso localmente): {e}")
            self.jwt_token = None
        else:
            logger.debug("ℹ️  Logout chiamato senza token attivo")
    
    def _calculate_movie_hash(self, video_path: Path) -> Tuple[Optional[str], Optional[int]]:
        """
        Calcola OSDB movie hash (standard OpenSubtitles)
        
        ALGORITMO:
        1. Hash iniziale = dimensione file
        2. Leggi primi 64KB (8192 chunk da 8 byte)
        3. Leggi ultimi 64KB
        4. Somma tutti i valori in little-endian 64-bit
        5. Applica mask 64-bit ad ogni operazione
        
        Args:
            video_path: Path al file video
        
        Returns:
            (hash_hex, file_size) o (None, None) in caso di errore
        
        RIFERIMENTI:
        - https://trac.opensubtitles.org/projects/opensubtitles/wiki/HashSourceCodes
        """
        try:
            logger.debug(f"Calcolo hash per: {video_path}")
            
            # Verifica esistenza file
            if not os.path.exists(video_path):
                logger.error(f"❌ File video non trovato: {video_path}")
                return None, None
            
            file_size = os.path.getsize(video_path)
            logger.debug(f"File size: {file_size:,} bytes ({file_size / (1024**3):.2f} GB)")
            
            # Validazione dimensione minima
            if file_size < 131072:  # 128KB
                logger.error(f"❌ File troppo piccolo per hash: {file_size} bytes (minimo 128KB)")
                return None, None
            
            hash_value = file_size
            logger.debug(f"Hash iniziale (file_size): {hash_value}")
            
            chunks_read_start = 0
            chunks_read_end = 0
            
            with open(video_path, 'rb') as f:
                # Hash primi 64KB (8192 chunk da 8 byte = 65536 byte)
                logger.debug("Lettura primi 64KB...")
                for i in range(8192):
                    chunk = f.read(8)
                    if len(chunk) < 8:
                        logger.debug(f"  Chunk {i}: fine file prematura")
                        break
                    (value,) = struct.unpack('<q', chunk)  # Little-endian signed 64-bit
                    hash_value += value
                    hash_value &= 0xFFFFFFFFFFFFFFFF  # Mask 64-bit
                    chunks_read_start += 1
                
                logger.debug(f"Chunks letti (inizio): {chunks_read_start}")
                logger.debug(f"Hash dopo primi 64KB: {hash_value:016x}")
                
                # Hash ultimi 64KB
                seek_pos = max(0, file_size - 65536)
                logger.debug(f"Lettura ultimi 64KB (seek to: {seek_pos})...")
                f.seek(seek_pos, 0)
                
                for i in range(8192):
                    chunk = f.read(8)
                    if len(chunk) < 8:
                        logger.debug(f"  Chunk {i}: fine file")
                        break
                    (value,) = struct.unpack('<q', chunk)
                    hash_value += value
                    hash_value &= 0xFFFFFFFFFFFFFFFF
                    chunks_read_end += 1
                
                logger.debug(f"Chunks letti (fine): {chunks_read_end}")
                logger.debug(f"Hash finale (numerico): {hash_value}")
            
            # Converti in hex (16 caratteri)
            hash_hex = f"{hash_value:016x}"
            logger.debug(f"Hash finale (hex): {hash_hex}")
            
            return hash_hex, file_size
        
        except FileNotFoundError:
            logger.error(f"❌ File video non trovato: {video_path}")
            return None, None
        except PermissionError:
            logger.error(f"❌ Permessi insufficienti per leggere: {video_path}")
            return None, None
        except Exception as e:
            logger.error(f"❌ Errore calcolo movie hash: {e}", exc_info=True)
            return None, None


# ============================================================================
# REGISTRAZIONE NELLA FACTORY GLOBALE
# ============================================================================
# CRITICO: Questo deve essere eseguito quando il modulo viene importato
# per registrare l'implementazione nella Factory condivisa
UploaderFactory.register_implementation('rest', OpenSubtitlesRESTUploader)

logger.info("✅ Implementazione REST registrata nella Factory globale")
