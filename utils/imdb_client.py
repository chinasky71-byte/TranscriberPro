"""
IMDb Client - OMDb API Fallback per IMDb ID
File: utils/imdb_client.py

FUNZIONALITÀ:
✅ Ricerca diretta su IMDb tramite OMDb API
✅ Fallback automatico quando TMDB non ha IMDb ID
✅ Gratuito (1000 richieste/giorno)
✅ Cache locale per evitare richieste duplicate
✅ Rate limiting automatico
"""
import requests
import json
import logging
from pathlib import Path
from typing import Optional, Dict
import time

logger = logging.getLogger(__name__)


class IMDbClient:
    """Client per ricerca diretta IMDb tramite OMDb API"""
    
    # OMDb API endpoint
    OMDB_URL = "http://www.omdbapi.com/"
    
    # API key di fallback (sostituisci con la tua)
    FALLBACK_API_KEY = "placeholder"
    
    def __init__(self, api_key: str = None):
        """
        Inizializza client OMDb
        
        Args:
            api_key: API key OMDb (gratis su omdbapi.com)
        """
        self.api_key = api_key or self._load_api_key()
        
        # Cache locale
        self.cache_file = Path.home() / '.transcriberpro' / 'imdb_cache.json'
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache = self._load_cache()
        
        # Rate limiting (1000 req/day = ~1 req/90sec per 24h)
        self.last_request_time = 0
        self.min_request_interval = 1  # 1 secondo tra richieste
        
        # Statistiche
        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'found': 0,
            'not_found': 0
        }
        
        logger.info("🎬 IMDb Client (OMDb) inizializzato")
        if self.api_key and self.api_key != "placeholder":
            logger.info("   ✅ API key configurata")
        else:
            logger.warning("   ⚠️ API key non configurata (richieste limitate)")
            logger.info("   💡 Registra gratis su: http://www.omdbapi.com/apikey.aspx")
    
    def _load_api_key(self) -> str:
        """Carica API key da file"""
        possible_paths = [
            Path(__file__).parent.parent / 'omdb_api.txt',
            Path.home() / '.transcriberpro' / 'omdb_api.txt',
            Path('omdb_api.txt')
        ]
        
        for api_file in possible_paths:
            if api_file.exists():
                try:
                    with open(api_file, 'r', encoding='utf-8') as f:
                        api_key = f.read().strip()
                        if api_key and len(api_key) > 5:
                            logger.info(f"✅ OMDb API key caricata da: {api_file}")
                            return api_key
                except Exception as e:
                    logger.error(f"Errore lettura {api_file}: {e}")
        
        logger.warning("⚠️ File omdb_api.txt non trovato")
        return self.FALLBACK_API_KEY
    
    def _load_cache(self) -> Dict:
        """Carica cache ricerche"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    logger.debug(f"Cache caricata: {len(cache_data)} entries")
                    return cache_data
            except Exception as e:
                logger.error(f"Errore caricamento cache: {e}")
                return {}
        return {}
    
    def _save_cache(self):
        """Salva cache"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2)
            logger.debug(f"Cache salvata: {len(self.cache)} entries")
        except Exception as e:
            logger.error(f"Errore salvataggio cache: {e}")
    
    def _rate_limit(self):
        """Rate limiting semplice"""
        now = time.time()
        elapsed = now - self.last_request_time
        
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            logger.debug(f"Rate limit: attesa {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[str]:
        """
        Cerca film su IMDb tramite OMDb
        
        Args:
            title: Titolo film
            year: Anno (opzionale ma consigliato)
        
        Returns:
            IMDb ID (formato tt1234567) o None
        """
        self.stats['total_requests'] += 1
        
        # Cache key
        cache_key = f"movie_{title}_{year or 'no_year'}"
        
        # Check cache
        if cache_key in self.cache:
            logger.debug(f"🔍 IMDb ID da cache: {self.cache[cache_key]}")
            self.stats['cache_hits'] += 1
            return self.cache[cache_key]
        
        logger.info(f"🔍 Ricerca IMDb (OMDb): {title}" + (f" ({year})" if year else ""))
        
        if self.api_key == "placeholder":
            logger.warning("⚠️ API key placeholder - Richiesta saltata")
            logger.info("💡 Configura API key in omdb_api.txt")
            return None
        
        try:
            self._rate_limit()
            self.stats['api_calls'] += 1
            
            params = {
                'apikey': self.api_key,
                't': title,  # Titolo
                'type': 'movie',  # Tipo: movie
            }
            
            if year:
                params['y'] = str(year)
            
            response = requests.get(self.OMDB_URL, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ OMDb HTTP {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get('Response') == 'True':
                imdb_id = data.get('imdbID')
                
                if imdb_id:
                    logger.info(f"✅ IMDb ID trovato: {imdb_id}")
                    logger.info(f"   Titolo: {data.get('Title')}")
                    logger.info(f"   Anno: {data.get('Year')}")
                    
                    # Salva in cache
                    self.cache[cache_key] = imdb_id
                    self._save_cache()
                    
                    self.stats['found'] += 1
                    return imdb_id
                else:
                    logger.warning(f"⚠️ Risposta OMDb senza IMDb ID")
                    self.stats['not_found'] += 1
                    return None
            else:
                error = data.get('Error', 'Unknown error')
                logger.warning(f"⚠️ OMDb: {error}")
                self.stats['not_found'] += 1
                
                # Cache anche risultati negativi
                self.cache[cache_key] = None
                self._save_cache()
                
                return None
        
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout OMDb API")
            return None
        except Exception as e:
            logger.error(f"❌ Errore ricerca OMDb: {e}")
            return None
    
    def search_series(self, title: str, year: Optional[int] = None) -> Optional[str]:
        """
        Cerca serie TV su IMDb tramite OMDb
        
        Args:
            title: Titolo serie
            year: Anno prima messa in onda (opzionale)
        
        Returns:
            IMDb ID (formato tt1234567) o None
        """
        self.stats['total_requests'] += 1
        
        # Cache key
        cache_key = f"series_{title}_{year or 'no_year'}"
        
        # Check cache
        if cache_key in self.cache:
            logger.debug(f"🔍 IMDb ID da cache: {self.cache[cache_key]}")
            self.stats['cache_hits'] += 1
            return self.cache[cache_key]
        
        logger.info(f"🔍 Ricerca IMDb serie (OMDb): {title}" + (f" ({year})" if year else ""))
        
        if self.api_key == "placeholder":
            logger.warning("⚠️ API key placeholder - Richiesta saltata")
            logger.info("💡 Configura API key in omdb_api.txt")
            return None
        
        try:
            self._rate_limit()
            self.stats['api_calls'] += 1
            
            params = {
                'apikey': self.api_key,
                't': title,  # Titolo
                'type': 'series',  # Tipo: series
            }
            
            if year:
                params['y'] = str(year)
            
            response = requests.get(self.OMDB_URL, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ OMDb HTTP {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get('Response') == 'True':
                imdb_id = data.get('imdbID')
                
                if imdb_id:
                    logger.info(f"✅ IMDb ID trovato: {imdb_id}")
                    logger.info(f"   Serie: {data.get('Title')}")
                    logger.info(f"   Anni: {data.get('Year')}")
                    
                    # Salva in cache
                    self.cache[cache_key] = imdb_id
                    self._save_cache()
                    
                    self.stats['found'] += 1
                    return imdb_id
                else:
                    logger.warning(f"⚠️ Risposta OMDb senza IMDb ID")
                    self.stats['not_found'] += 1
                    return None
            else:
                error = data.get('Error', 'Unknown error')
                logger.warning(f"⚠️ OMDb: {error}")
                self.stats['not_found'] += 1
                
                # Cache anche risultati negativi
                self.cache[cache_key] = None
                self._save_cache()
                
                return None
        
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout OMDb API")
            return None
        except Exception as e:
            logger.error(f"❌ Errore ricerca OMDb: {e}")
            return None
    
    def get_stats(self) -> Dict:
        """Ottieni statistiche utilizzo"""
        return self.stats.copy()
    
    def print_stats(self):
        """Stampa statistiche"""
        logger.info("\n" + "="*60)
        logger.info("📊 STATISTICHE OMDb CLIENT")
        logger.info("="*60)
        logger.info(f"Richieste totali:     {self.stats['total_requests']}")
        logger.info(f"  📦 Cache hits:      {self.stats['cache_hits']}")
        logger.info(f"  🌐 API calls:       {self.stats['api_calls']}")
        logger.info(f"  ✅ Trovati:         {self.stats['found']}")
        logger.info(f"  ❌ Non trovati:     {self.stats['not_found']}")
        
        if self.stats['total_requests'] > 0:
            cache_rate = (self.stats['cache_hits'] / self.stats['total_requests']) * 100
            logger.info(f"\nCache hit rate: {cache_rate:.1f}%")
        
        if self.stats['api_calls'] > 0:
            success_rate = (self.stats['found'] / self.stats['api_calls']) * 100
            logger.info(f"Success rate: {success_rate:.1f}%")
        
        logger.info("="*60)


# Singleton
_imdb_client = None

def get_imdb_client() -> IMDbClient:
    """Ottieni istanza singleton"""
    global _imdb_client
    if _imdb_client is None:
        _imdb_client = IMDbClient()
    return _imdb_client