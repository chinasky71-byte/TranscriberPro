"""
OpenSubtitles AI Translator
File: utils/opensubtitles_ai_translator.py

Traduce file SRT usando l'API AI di OpenSubtitles (ai.opensubtitles.com).
Workflow asincrono a due fasi:
  1. POST /ai/translate  -> ottiene correlation_id
  2. GET  /ai/translate/{correlation_id} -> polling fino a status "done"

Autenticazione: stesse credenziali dell'uploader REST (api_key, username, password).
Account VIP: 10 traduzioni gratuite/periodo (allowed_translations dal login).
"""

import json
import logging
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Callable

import requests

logger = logging.getLogger(__name__)


class OpenSubtitlesAITranslator:
    """
    Traduttore cloud basato su OpenSubtitles AI.

    Non richiede GPU. Invia il file SRT all'API remota e ne recupera
    la versione tradotta tramite polling.
    """

    MAIN_BASE_URL = "https://api.opensubtitles.com/api/v1"
    AI_BASE_URL   = "https://ai.opensubtitles.com"
    LOGIN_URL     = f"{MAIN_BASE_URL}/login"
    LOGOUT_URL    = f"{MAIN_BASE_URL}/logout"
    TRANSLATE_URL = f"{MAIN_BASE_URL}/ai/translate"

    POLL_TIMEOUT  = 300   # secondi massimi di attesa
    POLL_INTERVAL = 5     # secondi tra ogni poll

    # ISO 639-1: passthrough diretto (l'API OS AI usa 2 lettere)
    # Mappa codici 3-lettere (come potrebbero arrivare) -> 2-lettere
    LANG_3_TO_2 = {
        'eng': 'en', 'ita': 'it', 'fra': 'fr', 'deu': 'de', 'spa': 'es',
        'por': 'pt', 'rus': 'ru', 'jpn': 'ja', 'zho': 'zh', 'kor': 'ko',
        'ara': 'ar', 'nld': 'nl', 'pol': 'pl', 'swe': 'sv', 'nor': 'no',
        'dan': 'da', 'fin': 'fi', 'tur': 'tr', 'hun': 'hu', 'ces': 'cs',
        'ron': 'ro', 'hrv': 'hr', 'slk': 'sk', 'bul': 'bg', 'ukr': 'uk',
        'heb': 'he', 'hin': 'hi', 'tha': 'th', 'vie': 'vi', 'ind': 'id',
        'msa': 'ms', 'cat': 'ca', 'srp': 'sr', 'slv': 'sl', 'lit': 'lt',
        'lav': 'lv', 'est': 'et', 'ell': 'el',
    }

    # Provider validi per il parametro 'api' (dal FAQ ai.opensubtitles.com)
    VALID_PROVIDERS = ['DEEPL2', 'AWS', 'GEMINI25-FLASH', 'GEMINI25-LITE',
                       'GEMINI25-PRO', 'GEMINI3-FLASH', 'GEMINI3-PRO']
    DEFAULT_PROVIDER = 'DEEPL2'

    def __init__(
        self,
        api_key: str,
        username: str,
        password: str,
        user_agent: str = "TranscriberPro v1.0.0",
        translation_provider: str = 'DEEPL2',
        log_callback: Optional[Callable] = None,
        context: Optional[str] = None,
    ):
        self.api_key    = api_key
        self.username   = username
        self.password   = password
        self.user_agent = user_agent
        self.translation_provider = translation_provider.upper() if translation_provider else self.DEFAULT_PROVIDER
        self.log_callback = log_callback
        self.context    = context

        self.jwt_token: Optional[str] = None
        self._allowed_translations: Optional[int] = None

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def set_log_callback(self, callback: Optional[Callable]):
        """Imposta callback per logging verso GUI (compatibilità con BaseTranslator)."""
        self.log_callback = callback

    def log(self, message: str):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    # ------------------------------------------------------------------
    # Lingua helper
    # ------------------------------------------------------------------

    def _normalize_lang(self, lang: str) -> str:
        """Converte codice lingua a 2 lettere ISO 639-1."""
        lang = lang.strip().lower()
        if len(lang) == 3:
            return self.LANG_3_TO_2.get(lang, lang[:2])
        return lang

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _get_headers(self) -> dict:
        headers = {
            'Api-Key':    self.api_key,
            'User-Agent': self.user_agent,
            'Accept':     'application/json',
        }
        if self.jwt_token:
            headers['Authorization'] = f'Bearer {self.jwt_token}'
        return headers

    # ------------------------------------------------------------------
    # Autenticazione
    # ------------------------------------------------------------------

    def authenticate(self) -> bool:
        """
        Login su api.opensubtitles.com per ottenere JWT.
        Salva anche allowed_translations dal campo user della risposta.
        Usa la stessa logica retry dell'uploader REST (401 + percent-encode).
        """
        if not self.api_key or not self.username or not self.password:
            logger.error("OpenSubtitles AI: credenziali incomplete (api_key/username/password)")
            return False

        headers = self._get_headers()
        headers['Content-Type'] = 'application/json; charset=utf-8'

        payload = {'username': self.username.lower(), 'password': self.password}
        body    = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        self.log("OpenSubtitles AI: login in corso...")
        try:
            resp = requests.post(self.LOGIN_URL, headers=headers, data=body, timeout=30)
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenSubtitles AI: errore connessione login: {e}")
            return False

        if resp.status_code == 401:
            # Retry con password percent-encoded
            logger.warning("OpenSubtitles AI: 401 al primo tentativo, retry con password encoded")
            encoded_pw = urllib.parse.quote_plus(self.password, safe='')
            retry_payload = {'username': self.username.lower(), 'password': encoded_pw}
            retry_body    = json.dumps(retry_payload, ensure_ascii=False).encode('utf-8')
            retry_after   = float(resp.headers.get('Retry-After', 1.5))
            time.sleep(retry_after)
            try:
                resp = requests.post(self.LOGIN_URL, headers=headers, data=retry_body, timeout=30)
            except requests.exceptions.RequestException as e:
                logger.error(f"OpenSubtitles AI: errore connessione login (retry): {e}")
                return False

        if not resp.ok:
            logger.error(f"OpenSubtitles AI: login fallito HTTP {resp.status_code}")
            try:
                logger.error(resp.json())
            except Exception:
                logger.error(resp.text[:300])
            return False

        try:
            data = resp.json()
        except Exception:
            logger.error("OpenSubtitles AI: risposta login non JSON")
            return False

        self.jwt_token = data.get('token')
        if not self.jwt_token:
            logger.error("OpenSubtitles AI: nessun token nella risposta login")
            return False

        # Legge quota VIP
        user_info = data.get('user', {})
        self._allowed_translations = user_info.get('allowed_translations')
        self.log(
            f"OpenSubtitles AI: login OK. "
            f"Traduzioni disponibili: {self._allowed_translations}"
        )
        return True

    # ------------------------------------------------------------------
    # Traduzione file
    # ------------------------------------------------------------------

    def translate_file(
        self,
        input_path,
        output_path,
        src_lang: str,
        tgt_lang: str,
        context=None,
    ) -> bool:
        """
        Traduce un file SRT usando l'API AI di OpenSubtitles.

        Args:
            input_path:  Path (str o Path) del file SRT sorgente
            output_path: Path (str o Path) dove scrivere il file tradotto
            src_lang:    Lingua sorgente (ISO 639-1 o 639-2)
            tgt_lang:    Lingua target (ISO 639-1 o 639-2)

        Returns:
            True se la traduzione e il salvataggio sono riusciti, False altrimenti.
        """
        input_path  = Path(input_path)
        output_path = Path(output_path)

        # 1. Autenticazione lazy
        if not self.jwt_token:
            if not self.authenticate():
                return False

        # 2. Verifica quota
        if self._allowed_translations is not None and self._allowed_translations <= 0:
            self.log("OpenSubtitles AI: quota traduzioni esaurita (allowed_translations=0)")
            return False

        # 3. Normalizza lingue
        src = self._normalize_lang(src_lang)
        tgt = self._normalize_lang(tgt_lang)
        self.log(f"OpenSubtitles AI: traduzione {src} -> {tgt} per '{input_path.name}'")

        # 4. Invio file
        correlation_id = self._submit_translation(input_path, src, tgt)
        if not correlation_id:
            return False

        # 5. Polling
        translated_content = self._poll_translation(correlation_id)
        if translated_content is None:
            return False

        # 6. Scrittura output
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(translated_content, encoding='utf-8')
            self.log(f"OpenSubtitles AI: file tradotto salvato in '{output_path}'")
            return True
        except Exception as e:
            logger.error(f"OpenSubtitles AI: errore scrittura output: {e}")
            return False

    # ------------------------------------------------------------------
    # Step 1: invio
    # ------------------------------------------------------------------

    def _submit_translation(self, srt_path: Path, src: str, tgt: str) -> Optional[str]:
        """
        POST /ai/translate con il file SRT in multipart.
        Restituisce il correlation_id oppure None in caso di errore.
        """
        headers = self._get_headers()
        # NON aggiungere Content-Type: la lasceremo costruire a requests per il multipart

        self.log(f"OpenSubtitles AI: provider={self.translation_provider}")
        try:
            with open(srt_path, 'rb') as f:
                files = {'file': (srt_path.name, f, 'text/plain')}
                data  = {
                    'translate_from': src,
                    'translate_to':   tgt,
                    'api':            self.translation_provider,
                }
                resp  = requests.post(
                    self.TRANSLATE_URL,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60,
                )
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenSubtitles AI: errore invio traduzione: {e}")
            return None

        if resp.status_code == 401:
            # Token scaduto: re-autentica e riprova una volta
            self.log("OpenSubtitles AI: token scaduto durante invio, re-login...")
            self.jwt_token = None
            if not self.authenticate():
                return None
            return self._submit_translation(srt_path, src, tgt)

        if not resp.ok:
            logger.error(f"OpenSubtitles AI: invio fallito HTTP {resp.status_code}")
            try:
                err = resp.json()
                logger.error(err)
                msg = str(err.get('error', ''))
                if 'credit' in msg.lower():
                    self.log(
                        "OpenSubtitles AI: crediti AI insufficienti. "
                        "Acquista crediti su ai.opensubtitles.com o scegli un provider diverso."
                    )
            except Exception:
                logger.error(resp.text[:300])
            return None

        try:
            result = resp.json()
        except Exception:
            logger.error("OpenSubtitles AI: risposta invio non JSON")
            logger.error(resp.text[:300])
            return None

        logger.debug(f"OpenSubtitles AI submit response: {result}")

        # Il campo con il correlation_id potrebbe chiamarsi in vari modi.
        # Proviamo i candidati più probabili in ordine.
        for key in ('correlation_id', 'correlationId', 'id', 'task_id', 'taskId'):
            if key in result:
                cid = result[key]
                self.log(f"OpenSubtitles AI: traduzione avviata, correlation_id={cid}")
                return str(cid)

        # Se non troviamo un campo noto, logghiamo la risposta completa per debug
        logger.error(f"OpenSubtitles AI: correlation_id non trovato nella risposta: {result}")
        return None

    # ------------------------------------------------------------------
    # Step 2: polling
    # ------------------------------------------------------------------

    def _poll_translation(self, correlation_id: str) -> Optional[str]:
        """
        GET /ai/translate/{correlation_id} in loop fino a status "done" o timeout.
        Restituisce il contenuto SRT tradotto oppure None.
        """
        poll_url  = f"{self.TRANSLATE_URL}/{correlation_id}"
        headers   = self._get_headers()
        deadline  = time.time() + self.POLL_TIMEOUT
        attempt   = 0

        self.log(f"OpenSubtitles AI: attesa risultato traduzione (max {self.POLL_TIMEOUT}s)...")

        while time.time() < deadline:
            attempt += 1
            time.sleep(self.POLL_INTERVAL)

            try:
                resp = requests.get(poll_url, headers=headers, timeout=30)
            except requests.exceptions.RequestException as e:
                logger.warning(f"OpenSubtitles AI: errore poll #{attempt}: {e}")
                continue

            if not resp.ok:
                logger.warning(f"OpenSubtitles AI: poll #{attempt} HTTP {resp.status_code}")
                if resp.status_code in (404, 410):
                    logger.error("OpenSubtitles AI: traduzione non trovata (404/410), aborto")
                    return None
                continue

            try:
                result = resp.json()
            except Exception:
                logger.warning(f"OpenSubtitles AI: poll #{attempt} risposta non JSON")
                continue

            logger.debug(f"OpenSubtitles AI poll #{attempt}: {result}")

            # Legge status (vari nomi possibili)
            status = (
                result.get('status')
                or result.get('state')
                or result.get('Status')
                or ''
            ).lower()

            if status in ('done', 'completed', 'success'):
                self.log(f"OpenSubtitles AI: traduzione completata (poll #{attempt})")
                return self._extract_translated_content(result, poll_url, headers)

            if status in ('error', 'failed', 'failure'):
                logger.error(f"OpenSubtitles AI: traduzione fallita sul server: {result}")
                return None

            # Ancora in elaborazione
            if attempt % 5 == 0:
                self.log(f"OpenSubtitles AI: ancora in elaborazione... (poll #{attempt})")

        logger.error(f"OpenSubtitles AI: timeout dopo {self.POLL_TIMEOUT}s")
        return None

    # ------------------------------------------------------------------
    # Estrazione contenuto tradotto
    # ------------------------------------------------------------------

    def _extract_translated_content(
        self, result: dict, poll_url: str, headers: dict
    ) -> Optional[str]:
        """
        Dalla risposta "done" estrae il contenuto SRT tradotto.
        Gestisce sia contenuto inline che download tramite URL.
        """
        # Caso 1: contenuto direttamente nel JSON
        for key in ('content', 'data', 'subtitle', 'text', 'srt'):
            if key in result and isinstance(result[key], str) and result[key].strip():
                return result[key]

        # Caso 2: URL di download
        for key in ('download_url', 'url', 'file_url', 'link'):
            if key in result and result[key]:
                dl_url = result[key]
                self.log(f"OpenSubtitles AI: download risultato da {dl_url}")
                try:
                    dl_resp = requests.get(dl_url, headers=headers, timeout=60)
                    if dl_resp.ok:
                        return dl_resp.text
                    logger.error(f"OpenSubtitles AI: download fallito HTTP {dl_resp.status_code}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"OpenSubtitles AI: errore download risultato: {e}")
                return None

        # Caso 3: risposta inattesa
        logger.error(
            f"OpenSubtitles AI: struttura risposta 'done' sconosciuta, "
            f"impossibile estrarre contenuto: {result}"
        )
        return None

    # ------------------------------------------------------------------
    # Logout e cleanup
    # ------------------------------------------------------------------

    def logout(self) -> None:
        """Invalida il JWT sul server e lo rimuove localmente."""
        if not self.jwt_token:
            return
        try:
            headers = self._get_headers()
            resp = requests.delete(self.LOGOUT_URL, headers=headers, timeout=15)
            logger.info(f"OpenSubtitles AI: logout HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"OpenSubtitles AI: logout server fallito (token rimosso localmente): {e}")
        self.jwt_token = None

    def cleanup(self) -> None:
        """Alias cleanup per compatibilità con l'interfaccia BaseTranslator."""
        self.logout()
