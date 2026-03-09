"""
TMDB Client - ENHANCED: Parsing Ultra-Robusto + Triplo Fallback IMDb
File: utils/tmdb_client.py

VERSIONE: 4.1 - FIX ANNO + RELEASE GROUPS ITALIANI

MODIFICHE v4.1:
- FIX CRITICO: Anno (2023) ora viene PRESERVATO durante pre-clean
- Aggiunto supporto tag lingue: iTA, ENG, iTA-ENG, Ita.Eng, DUAL
- Aggiunti 11 release groups ITALIANI: MIRCrew, Dr4gon, iDN_CreW, etc.
- Rimuove parentesi vuote o con numeri non-anno: (1), (2), (123)
- Pattern più robusto per rimozione release groups

MODIFICHE v4.0:
- Parsing titolo completamente riscritto (più aggressivo)
- Gestione parentesi non chiuse: [YTS, (1080p
- Rimuove 14+ release groups comuni (YTS, RARBG, QxR, etc.)
- Rimuove "Extras", "+ Extras", "Bonus"
- Pattern multipli per codec/qualità/audio
- Pulizia caratteri junk residui

MODIFICHE v3.3:
- 'search_tv' ora tenta 'it-IT', e se la sinossi è vuota,
  prova 'en-US' prima di usare la sinossi della serie.
"""
import requests
import re
import logging
from pathlib import Path
from typing import Optional, Dict, List
from PIL import Image
from io import BytesIO

logger = logging.getLogger(__name__)

# Cinemagoer (ex IMDbPY) - Fallback 1
try:
    from imdb import Cinemagoer
    CINEMAGOER_AVAILABLE = True
    logger.debug("âœ… Cinemagoer disponibile (Fallback 1)")
except ImportError:
    CINEMAGOER_AVAILABLE = False
    logger.warning("âš ï¸ Cinemagoer non disponibile")

# OMDb Client - Fallback 2  
try:
    from utils.imdb_client import get_imdb_client
    OMDB_AVAILABLE = True
    logger.debug("âœ… OMDb Client disponibile (Fallback 2)")
except ImportError:
    OMDB_AVAILABLE = False
    logger.warning("âš ï¸ OMDb Client non disponibile")


class TMDBClient:
    """Client TMDB con triplo fallback per IMDb ID"""
    
    FALLBACK_API_KEY = "d7a0c191f50c48602f75b8a8eba4b3fc"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or self._load_api_key()
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"
        
        self.cache_dir = Path.home() / '.transcriberpro' / 'posters'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"TMDB Client inizializzato (API key: {'âœ…' if self.api_key else 'âŒ'})")
        
        # Mostra fallback disponibili
        fallback_status = []
        if CINEMAGOER_AVAILABLE:
            fallback_status.append("Cinemagoer")
        if OMDB_AVAILABLE:
            fallback_status.append("OMDb")
        
        if fallback_status:
            logger.info(f"âœ… Fallback IMDb disponibili: {', '.join(fallback_status)}")
        else:
            logger.warning("âš ï¸ Nessun fallback IMDb disponibile")
    
    def _load_api_key(self) -> str:
        """Carica API key dal file o usa fallback"""
        possible_paths = [
            Path(__file__).parent.parent / 'tmdb_api.txt',
            Path.home() / '.transcriberpro' / 'tmdb_api.txt',
            Path('tmdb_api.txt')
        ]
        
        for api_file in possible_paths:
            if api_file.exists():
                try:
                    with open(api_file, 'r', encoding='utf-8') as f:
                        api_key = f.read().strip()
                        if api_key and len(api_key) > 10:
                            logger.info(f"âœ… TMDB API key caricata da: {api_file}")
                            return api_key
                except Exception as e:
                    logger.error(f"Errore lettura {api_file}: {e}")
        
        logger.warning(f"âš ï¸ File tmdb_api.txt non trovato, uso fallback key")
        return self.FALLBACK_API_KEY
    
    def _get_imdb_id(self, media_type: str, tmdb_id: int, media_info: Optional[Dict] = None) -> Optional[str]:
        """
        Recupera IMDb ID con triplo fallback
        """
        # ========================================
        # FALLBACK 1: TMDB External IDs (Primario)
        # ========================================
        imdb_id = self._get_imdb_id_from_tmdb(media_type, tmdb_id)
        
        if imdb_id:
            logger.info(f"âœ… IMDb ID trovato via TMDB External IDs: {imdb_id}")
            return imdb_id
        
        logger.warning("âš ï¸ IMDb ID non trovato su TMDB, attivo fallback...")
        
        # Ottieni info media se non giÃ  disponibili (necessarie per fallback)
        if not media_info:
            media_info = self._get_tmdb_media_info(media_type, tmdb_id)
            
            if not media_info:
                logger.error("âŒ Impossibile recuperare info da TMDB per fallback")
                return None
        
        # ========================================
        # FALLBACK 2: Cinemagoer (Ricerca Python IMDb)
        # ========================================
        if CINEMAGOER_AVAILABLE:
            logger.info("ðŸ”„ Fallback 1: Tentativo ricerca Cinemagoer...")
            imdb_id = self._search_imdb_cinemagoer(media_type, media_info)
            
            if imdb_id:
                logger.info(f"âœ… IMDb ID trovato via Cinemagoer: {imdb_id}")
                return imdb_id
            
            logger.warning("âš ï¸ Cinemagoer non ha trovato risultati")
        else:
            logger.debug("â„¹ï¸ Cinemagoer non disponibile, skip fallback 1")
        
        # ========================================
        # FALLBACK 3: OMDb API (Ricerca API IMDb Ufficiale)
        # ========================================
        if OMDB_AVAILABLE:
            logger.info("ðŸ”„ Fallback 2: Tentativo ricerca OMDb API...")
            imdb_id = self._search_imdb_omdb(media_type, media_info)
            
            if imdb_id:
                logger.info(f"âœ… IMDb ID trovato via OMDb API: {imdb_id}")
                return imdb_id
            
            logger.warning("âš ï¸ OMDb API non ha trovato risultati")
        else:
            logger.debug("â„¹ï¸ OMDb Client non disponibile, skip fallback 2")
        
        # ========================================
        # TUTTI I FALLBACK FALLITI
        # ========================================
        logger.error("âŒ IMDb ID NON TROVATO dopo tutti i fallback")
        logger.error(f"   TMDB ID: {tmdb_id}")
        logger.error(f"   Titolo: {media_info.get('title', 'N/A')}")
        logger.error(f"   Anno: {media_info.get('year', 'N/A')}")
        logger.error(f"   Tipo: {media_type}")
        
        return None
    
    def _get_imdb_id_from_tmdb(self, media_type: str, tmdb_id: int) -> Optional[str]:
        """
        Recupera IMDb ID da TMDB external_ids (metodo primario)
        """
        try:
            logger.debug(f"ðŸ” Recupero IMDb ID da TMDB external_ids (ID: {tmdb_id})")
            
            response = requests.get(
                f"{self.base_url}/{media_type}/{tmdb_id}/external_ids",
                params={'api_key': self.api_key},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                imdb_id = data.get('imdb_id')
                
                if imdb_id and imdb_id.startswith('tt') and len(imdb_id) > 2:
                    return imdb_id
                else:
                    logger.debug(f"   IMDb ID non presente negli external_ids TMDB")
                    return None
            else:
                logger.warning(f"âš ï¸ TMDB external_ids API error: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"âŒ Errore recupero IMDb ID da TMDB: {e}")
            return None
    
    def _get_tmdb_media_info(self, media_type: str, tmdb_id: int) -> Optional[Dict]:
        """
        Recupera info complete media da TMDB (per ricerca IMDb)
        """
        try:
            response = requests.get(
                f"{self.base_url}/{media_type}/{tmdb_id}",
                params={'api_key': self.api_key, 'language': 'en-US'},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if media_type == 'movie':
                    return {
                        'title': data.get('title', ''),
                        'original_title': data.get('original_title', ''),
                        'year': data.get('release_date', '')[:4] if data.get('release_date') else None
                    }
                else:  # tv
                    return {
                        'title': data.get('name', ''),
                        'original_title': data.get('original_name', ''),
                        'year': data.get('first_air_date', '')[:4] if data.get('first_air_date') else None
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"âŒ Errore recupero info TMDB: {e}")
            return None
    
    def _search_imdb_cinemagoer(self, media_type: str, media_info: Dict) -> Optional[str]:
        """
        Ricerca diretta su IMDb usando Cinemagoer (Fallback 1)
        """
        try:
            ia = Cinemagoer()
            
            search_titles = [media_info.get('original_title'), media_info.get('title')]
            search_titles = [t for t in search_titles if t]
            
            for search_title in search_titles:
                logger.debug(f"   Cerco su IMDb: '{search_title}'")
                
                if media_type == 'movie':
                    results = ia.search_movie(search_title)
                else:
                    results = ia.search_movie(search_title)
                
                if not results:
                    continue
                
                best_match = self._find_best_imdb_match(results, media_info, media_type)
                
                if best_match:
                    imdb_id = f"tt{best_match.movieID}"
                    return imdb_id
            
            return None
            
        except Exception as e:
            logger.error(f"âŒ Errore ricerca Cinemagoer: {e}")
            return None
    
    def _search_imdb_omdb(self, media_type: str, media_info: Dict) -> Optional[str]:
        """
        Ricerca diretta su IMDb usando OMDb API (Fallback 2)
        """
        try:
            omdb_client = get_imdb_client()
            
            title = media_info.get('title') or media_info.get('original_title')
            year = media_info.get('year')
            
            if not title:
                logger.error("âŒ Titolo mancante per ricerca OMDb")
                return None
            
            if year and isinstance(year, str):
                try:
                    year = int(year)
                except ValueError:
                    year = None
            
            if media_type == 'movie':
                imdb_id = omdb_client.search_movie(title, year)
            else:
                imdb_id = omdb_client.search_series(title, year)
            
            return imdb_id
            
        except Exception as e:
            logger.error(f"âŒ Errore ricerca OMDb: {e}")
            return None
    
    def _find_best_imdb_match(self, results: List, media_info: Dict, media_type: str) -> Optional[any]:
        """
        Trova il miglior match IMDb basato su titolo, anno e tipo
        """
        title = media_info.get('title', '').lower()
        original_title = media_info.get('original_title', '').lower()
        year = media_info.get('year')
        
        target_kind = 'movie' if media_type == 'movie' else 'tv series'
        
        candidates = []
        
        for result in results[:10]:
            try:
                result_title = result.get('title', '').lower()
                result_year = result.get('year')
                result_kind = result.get('kind', '')
                
                score = 0
                
                if result_title == title or result_title == original_title:
                    score += 100
                elif title in result_title or result_title in title:
                    score += 50
                elif original_title and (original_title in result_title or result_title in original_title):
                    score += 50
                
                if year and result_year:
                    year_diff = abs(int(year) - int(result_year))
                    if year_diff == 0:
                        score += 50
                    elif year_diff <= 2:
                        score += 30
                
                if result_kind == target_kind:
                    score += 30
                elif media_type == 'tv' and result_kind in ['tv series', 'tv mini series']:
                    score += 25
                
                if score >= 80:
                    candidates.append((score, result))
                    logger.debug(f"   Candidato: {result_title} ({result_year}) [{result_kind}] - Score: {score}")
                
            except Exception as e:
                logger.debug(f"   Errore processing risultato: {e}")
                continue
        
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, best_match = candidates[0]
            logger.debug(f"   Best match: score {best_score}")
            return best_match
        
        return None
    
    def parse_filename(self, filename: str) -> Dict[str, any]:
        """
        Estrae informazioni dal nome file
        âœ… FIX CRITICO: Pulizia piÃ¹ aggressiva e mirata del titolo TV show
        """
        name = Path(filename).stem
        logger.debug(f"Parsing filename: {name}")
        
        # Pattern serie TV
        tv_patterns = [
            (r'[Ss](\d+)[Ee](\d+)', 'SxxExx'),
            (r'(\d+)x(\d+)', '1x01'),
            (r'Season\s*(\d+).*Episode\s*(\d+)', 'Season X Episode Y')
        ]
        
        for pattern, pattern_name in tv_patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                title_part = re.split(pattern, name, flags=re.IGNORECASE)[0].strip()
                
                # 1. Pre-pulizia (rimuove codec/risoluzione)
                title = self._pre_clean_title(title_part)
                
                year = None
                
                # 2. Estrazione e rimozione Anno
                year_match = re.search(r'\b(19|20)\d{2}\b', title)
                if year_match:
                    year = int(year_match.group(0))
                    title = re.sub(r'\b(19|20)\d{2}\b', '', title).strip()
                
                # 3. Pulizia aggressiva del titolo TV (rimuove punti/underscore non necessari)
                title = self._clean_title(title)
                
                # 4. Rimuovi qualsiasi numero finale residuo che potrebbe essere l'anno di nuovo
                title = re.sub(r'\s+\d{4}\s*$', '', title).strip()
                
                # 5. Pulizia finale da separatori residui
                title = re.sub(r'[._-]\s*$', '', title).strip() 
                
                season = int(match.group(1))
                episode = int(match.group(2))
                
                logger.debug(f"âœ… TV Show: {title} ({year if year else 'no year'}) S{season:02d}E{episode:02d}")
                
                return {
                    'type': 'tv',
                    'title': title,
                    'season': season,
                    'episode': episode,
                    'year': year
                }
        
        # Film
        title = self._pre_clean_title(name)
        
        year = None
        year_match = re.search(r'\b(19|20)\d{2}\b', title)
        if year_match:
            year = int(year_match.group(0))
            title = title[:year_match.start()].strip()
        
        title = self._clean_title(title)
        
        logger.debug(f"âœ… Movie: {title} ({year if year else 'no year'})")
        
        return {
            'type': 'movie',
            'title': title,
            'year': year
        }
    
    def _pre_clean_title(self, title: str) -> str:
        """
        Pre-pulizia AGGRESSIVA del titolo
        v4.1: Fix ordine estrazione anno + release groups italiani + tag lingue
        """
        original = title
        
        # 1. Rimuovi "Extras", "+ Extras", "Bonus", etc.
        title = re.sub(r'\s*[+&]\s*(Extras?|Bonus|Features?)\s*', ' ', title, flags=re.IGNORECASE)
        title = re.sub(r'\bExtras?\b', '', title, flags=re.IGNORECASE)
        
        # 2. Rimuovi TAG LINGUE (iTA, ENG, iTA-ENG, Ita.Eng, etc.)
        title = re.sub(r'\b(iTA|ENG|ITA|DUAL|iTALiAN|ENGLiSH)', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\b(iTA-ENG|ITA-ENG|Ita\.Eng)', '', title, flags=re.IGNORECASE)
        
        # 3. Rimuovi release groups comuni (INTERNAZIONALI + ITALIANI)
        release_groups = [
            # Internazionali
            'YTS', 'YIFY', 'RARBG', 'QxR', 'SAMPA', 'PSA', 'SPARKS',
            'EVO', 'NTb', 'NTG', 'AMRAP', 'ION10', 'CMRG', 'TGx',
            'GalaxyRG', 'FLUX', 'ShAaNiG', 'STUTTERSHIT', 'FGT',
            # Italiani (NUOVO)
            'MIRCrew', 'Dr4gon', 'iDN_CreW', 'Surviv4l', 'BHDStudio',
            'CHD', 'ViSiON', 'SiC', 'TRL', 'IGM', 'BLUWORLD'
        ]
        
        for group in release_groups:
            # Con parentesi: [MIRCrew], (MIRCrew)
            title = re.sub(rf'\[{group}[^\]]*\]', '', title, flags=re.IGNORECASE)
            title = re.sub(rf'\({group}[^\)]*\)', '', title, flags=re.IGNORECASE)
            # Senza parentesi: -MIRCrew-, .MIRCrew., MIRCrew$
            title = re.sub(rf'[-\.\s]{group}[-\.\s]', ' ', title, flags=re.IGNORECASE)
            title = re.sub(rf'\b{group}\b', '', title, flags=re.IGNORECASE)
        
        # 4. Rimuovi codec/qualità/audio
        quality_patterns = [
            r'\b(1080p|720p|480p|2160p|4K|HD|UHD|HDR10?|DV|SDR)\b',
            r'\b(BluRay|BRRip|BDRip|WEB-?DL|WEBRip|HDTV|DVDRip|DVD|BD|Web|Bluray)\b',
            r'\b(x264|x265|H\.?264|H\.?265|HEVC|AVC|VP9|AV1)\b',
            r'\b(AAC|AC3|DD5?\.1|DDP|Atmos|TrueHD|DTS|FLAC|MP3|E-?AC-?3|EAC3)\b',
            r'\b(8bit|10bit|12bit|Main10?|Profile)\b',
            r'\b(REPACK|PROPER|INTERNAL|LIMITED|UNRATED|EXTENDED|DC|Directors?\.?Cut)\b',
            r'\b(MULTI|MULTiSUBS?|DUAL)\b',
        ]
        
        for pattern in quality_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        
        # 5. CRITICO: Rimuovi TUTTO da parentesi aperte ma NON chiuse
        # [YTS fino alla fine → tutto rimosso
        title = re.sub(r'\[(?![^\]]*\]).*$', '', title)
        # (1080p fino alla fine → tutto rimosso  
        title = re.sub(r'\((?![^\)]*\)).*$', '', title)
        
        # 6. Rimuovi parentesi VUOTE o con SOLO numeri NON anno (es: (1), (2), ma NON (2023))
        # IMPORTANTE: Preserva parentesi con 4 cifre (anno)
        title = re.sub(r'\(\s*\d{1,3}\s*\)', '', title)  # Rimuove (1), (12), (123)
        title = re.sub(r'\[\s*\d{1,3}\s*\]', '', title)  # Rimuove [1], [12], [123]
        
        # 7. Rimuovi parentesi complete ma PRESERVA anno (19xx o 20xx)
        # Rimuove [qualcosa] se NON contiene 4 cifre
        title = re.sub(r'\[(?!.*\d{4})[^\]]*\]', '', title)
        # Rimuove (qualcosa) se NON contiene 4 cifre  
        title = re.sub(r'\((?!.*\d{4})[^\)]*\)', '', title)
        
        # 8. Pulisci spazi multipli e trim
        title = re.sub(r'\s+', ' ', title).strip()
        
        if title != original:
            logger.debug(f"   Pre-clean: '{original}' → '{title}'")
        
        return title
    
    def _clean_title(self, title: str) -> str:
        """
        Pulizia finale titolo
        v4.0: Più aggressiva, rimuove junk residuo
        """
        # 1. Sostituisci separatori con spazi
        title = re.sub(r'[._-]+', ' ', title)
        
        # 2. Rimuovi numeri isolati alla fine (potrebbe essere anno già estratto)
        title = re.sub(r'\s+\d{1,4}\s*$', '', title)
        
        # 3. Rimuovi caratteri speciali residui
        title = re.sub(r'[~`!@#$%^&*+={}|<>?]', '', title)
        
        # 4. Pulisci spazi multipli e trim
        title = re.sub(r'\s+', ' ', title).strip()
        
        return title
    
    def _generate_search_variants(self, title: str) -> List[str]:
        """Genera varianti titolo per ricerca"""
        variants = [title]
        
        no_articles = re.sub(r'\b(The|A|An|Il|La|Le|Lo|Gli|I|Un|Una)\b\s*', '', title, flags=re.IGNORECASE).strip()
        if no_articles and no_articles != title:
            variants.append(no_articles)
        
        main_title = re.split(r'[:\-]', title)[0].strip()
        if main_title and main_title != title:
            variants.append(main_title)
        
        no_numbers = re.sub(r'\s+\d+\s*$', '', title).strip()
        if no_numbers and no_numbers != title:
            variants.append(no_numbers)
        
        seen = set()
        return [x for x in variants if not (x in seen or seen.add(x))]
    
    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[Dict]:
        """Cerca film su TMDB con triplo fallback IMDb ID"""
        if not self.api_key:
            logger.error("âŒ API key non disponibile")
            return None
        
        search_variants = self._generate_search_variants(title)
        
        logger.info(f"ðŸ” Ricerca film: '{title}'" + (f" ({year})" if year else ""))
        if len(search_variants) > 1:
            logger.debug(f"   Varianti: {search_variants[1:]}")
        
        for variant in search_variants:
            try:
                params = {
                    'api_key': self.api_key,
                    'query': variant,
                    'language': 'it-IT' # Richiedi la sinossi in italiano
                }
                
                if year:
                    params['year'] = year
                
                response = requests.get(
                    f"{self.base_url}/search/movie",
                    params=params,
                    timeout=10
                )
                
                if response.status_code == 401:
                    logger.error("âŒ API key non valida!")
                    return None
                
                response.raise_for_status()
                data = response.json()
                
                if data.get('results'):
                    result = data['results'][0]
                    tmdb_id = result['id']
                    
                    logger.info(f"âœ… Trovato TMDB: {result.get('title', 'N/A')} ({result.get('release_date', 'N/A')[:4]})")
                    
                    media_info = {
                        'title': result.get('title', title),
                        'original_title': result.get('original_title', ''),
                        'year': result.get('release_date', '')[:4] if result.get('release_date') else year
                    }
                    
                    imdb_id = self._get_imdb_id('movie', tmdb_id, media_info)
                    
                    if imdb_id:
                        logger.info(f"âœ… IMDb ID finale: {imdb_id}")
                    else:
                        logger.warning(f"âš ï¸ IMDb ID NON trovato dopo tutti i fallback")
                    
                    return {
                        'id': tmdb_id,
                        'imdb_id': imdb_id,
                        'title': result.get('title', title),
                        'original_title': result.get('original_title', ''),
                        'poster_path': result.get('poster_path'),
                        'overview': result.get('overview', ''),
                        'release_date': result.get('release_date', ''),
                        'vote_average': result.get('vote_average', 0)
                    }
                else:
                    logger.debug(f"   Nessun risultato per: '{variant}'")
                    
            except requests.exceptions.Timeout:
                logger.error("âŒ Timeout TMDB")
            except requests.exceptions.RequestException as e:
                logger.error(f"âŒ Errore TMDB: {e}")
            except Exception as e:
                logger.error(f"âŒ Errore inatteso: {e}")
        
        logger.warning(f"âš ï¸ Nessun risultato per: {title}")
        return None
    
    def search_tv(self, title: str, season: int = None, episode: int = None, year: int = None) -> Optional[Dict]:
        """Cerca serie TV su TMDB con triplo fallback IMDb ID e fallback lingua episodio"""
        if not self.api_key:
            logger.error("âŒ API key non disponibile")
            return None
        
        search_variants = self._generate_search_variants(title)
        
        logger.info(f"ðŸ” Ricerca serie TV: '{title}'" + (f" ({year})" if year else ""))
        if len(search_variants) > 1:
            logger.debug(f"   Varianti: {search_variants[1:]}")
        
        for variant in search_variants:
            try:
                params = {
                    'api_key': self.api_key,
                    'query': variant,
                    'language': 'it-IT' # Richiedi la sinossi in italiano
                }
                
                if year:
                    params['first_air_date_year'] = year
                
                response = requests.get(
                    f"{self.base_url}/search/tv",
                    params=params,
                    timeout=10
                )
                
                if response.status_code == 401:
                    logger.error("âŒ API key non valida!")
                    return None
                
                response.raise_for_status()
                data = response.json()
                
                if data.get('results'):
                    result = data['results'][0]
                    tmdb_id = result['id']
                    
                    logger.info(f"âœ… Trovato TMDB: {result.get('name', 'N/A')} ({result.get('first_air_date', 'N/A')[:4]})")
                    
                    media_info = {
                        'title': result.get('name', title),
                        'original_title': result.get('original_name', ''),
                        'year': result.get('first_air_date', '')[:4] if result.get('first_air_date') else year
                    }
                    
                    imdb_id = self._get_imdb_id('tv', tmdb_id, media_info)
                    
                    if imdb_id:
                        logger.info(f"âœ… IMDb ID finale: {imdb_id}")
                    else:
                        logger.warning(f"âš ï¸ IMDb ID NON trovato dopo tutti i fallback")
                    
                    # --- MODIFICA v3.3: FALLBACK LINGUA EPISODIO ---
                    series_overview = result.get('overview', '')
                    episode_overview = None
                    
                    if season is not None and episode is not None:
                        logger.debug(f"ðŸ” Recupero sinossi episodio S{season}E{episode} (it-IT)...")
                        try:
                            # 1. Tenta di ottenere la sinossi in ITALIANO
                            ep_params_it = {
                                'api_key': self.api_key,
                                'language': 'it-IT'
                            }
                            ep_response_it = requests.get(
                                f"{self.base_url}/tv/{tmdb_id}/season/{season}/episode/{episode}",
                                params=ep_params_it,
                                timeout=5
                            )
                            
                            if ep_response_it.status_code == 200:
                                episode_overview = ep_response_it.json().get('overview')

                            # 2. Se la sinossi italiana Ã¨ vuota o l'API fallisce, TENTA IN INGLESE
                            if not episode_overview:
                                if ep_response_it.status_code != 200:
                                    logger.warning(f"âš ï¸ Impossibile trovare episodio in 'it-IT' (HTTP {ep_response_it.status_code}), tento 'en-US'...")
                                else:
                                    logger.info("â„¹ï¸ Sinossi 'it-IT' vuota. Tento fallback 'en-US'...")
                                
                                ep_params_en = {
                                    'api_key': self.api_key,
                                    'language': 'en-US' # Fallback in inglese
                                }
                                ep_response_en = requests.get(
                                    f"{self.base_url}/tv/{tmdb_id}/season/{season}/episode/{episode}",
                                    params=ep_params_en,
                                    timeout=5
                                )
                                
                                if ep_response_en.status_code == 200:
                                    episode_overview = ep_response_en.json().get('overview')

                            # 3. Valutazione finale
                            if episode_overview:
                                logger.info(f"âœ… Sinossi episodio trovata!")
                            else:
                                # Questo log ora significa che non c'Ã¨ nÃ© in IT nÃ© in EN
                                logger.warning(f"âš ï¸ Sinossi episodio vuota (anche in en-US), uso sinossi serie.")

                        except Exception as e:
                            logger.error(f"âŒ Errore recupero episodio: {e}. Uso sinossi serie.")
                    # --- FINE MODIFICA ---
                    
                    tv_info = {
                        'id': tmdb_id,
                        'imdb_id': imdb_id,
                        'title': result.get('name', title),
                        'original_title': result.get('original_name', ''),
                        'poster_path': result.get('poster_path'),
                        'overview': episode_overview or series_overview, 
                        'first_air_date': result.get('first_air_date', ''),
                        'vote_average': result.get('vote_average', 0),
                        'season': season,
                        'episode': episode
                    }
                    
                    return tv_info
                else:
                    logger.debug(f"   Nessun risultato per: '{variant}'")
                    
            except requests.exceptions.Timeout:
                logger.error("âŒ Timeout TMDB")
            except requests.exceptions.RequestException as e:
                logger.error(f"âŒ Errore TMDB: {e}")
            except Exception as e:
                logger.error(f"âŒ Errore inatteso: {e}")
        
        logger.warning(f"âš ï¸ Nessun risultato per: {title}")
        return None
    
    def download_poster(self, poster_path: str, media_title: str) -> Optional[Path]:
        """Scarica poster da TMDB"""
        try:
            poster_url = f"{self.image_base_url}{poster_path}"
            logger.info(f"ðŸ“¥ Download poster: {poster_url}")
            
            safe_title = re.sub(r'[^\w\s-]', '', media_title).strip().replace(' ', '_')
            cache_filename = f"{safe_title}_{poster_path.split('/')[-1]}"
            cache_path = self.cache_dir / cache_filename
            
            if cache_path.exists():
                logger.info(f"âœ… Poster in cache: {cache_path.name}")
                return cache_path
            
            response = requests.get(poster_url, timeout=15)
            response.raise_for_status()
            
            img = Image.open(BytesIO(response.content))
            img.save(cache_path, 'JPEG', quality=90)
            
            logger.info(f"âœ… Poster salvato: {cache_path.name}")
            return cache_path
            
        except Exception as e:
            logger.error(f"âŒ Errore download poster: {e}")
            return None
    
    def get_media_info(self, filename: str) -> Optional[Dict]:
        """Ottieni info complete con triplo fallback IMDb ID"""
        logger.info(f"\n{'='*60}")
        logger.info(f"ðŸŽ¬ Elaborazione: {Path(filename).name}")
        logger.info(f"{'='*60}")
        
        parsed = self.parse_filename(filename)
        
        info = None
        if parsed['type'] == 'movie':
            info = self.search_movie(parsed['title'], parsed.get('year'))
        else:
            info = self.search_tv(
                parsed['title'],
                parsed.get('season'),
                parsed.get('episode'),
                parsed.get('year')
            )
        
        if not info:
            logger.error("âŒ Nessuna informazione trovata su TMDB")
            return None
        
        if info.get('poster_path'):
            poster_local = self.download_poster(info['poster_path'], info['title'])
            info['poster_local_path'] = poster_local
        
        logger.info("="*60)
        return info


# Singleton
_tmdb_client = None

def get_tmdb_client() -> TMDBClient:
    """Ottieni istanza singleton"""
    global _tmdb_client
    if _tmdb_client is None:
        _tmdb_client = TMDBClient()
    return _tmdb_client


if __name__ == "__main__":
    # Test rapido
    logging.basicConfig(level=logging.INFO) # Abilita logging per test
    client = get_tmdb_client()
    
    # Test CRITICO: X.Factor.Italia.2025.S19E06.1080p.H265-TheBlackKing.mkv
    print("\n--- Test X-Factor (TV Show) ---")
    info = client.get_media_info("X.Factor.Italia.2025.S19E06.1080p.H265-TheBlackKing.mkv")
    if info:
        print(f"\nâœ… Test completato!")
        print(f"   Titolo estratto: {info['title']}")
        print(f"   IMDb ID: {info.get('imdb_id', 'N/A')}")
        print(f"   Tipo: TV Show")
        print(f"   Sinossi: {info.get('overview', 'N/A')[:50]}...")
        
    # Test film
    print("\n--- Test Matrix (Movie) ---")
    info = client.get_media_info("The.Matrix.1999.1080p.BluRay.x264.mp4")
    if info:
        print(f"\nâœ… Test completato!")
        print(f"   Titolo: {info['title']}")
        print(f"   IMDb ID: {info.get('imdb_id', 'N/A')}")
        print(f"   Tipo: Movie")
        print(f"   Sinossi: {info.get('overview', 'N/A')[:50]}...")