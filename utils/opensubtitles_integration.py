"""
Esempio Integrazione OpenSubtitles con IMDb ID
File: utils/opensubtitles_client.py (esempio)

IMPORTANTE: OpenSubtitles richiede IMDb ID (tt1234567), non TMDB ID
"""
import logging
from pathlib import Path
from typing import Optional
from utils.tmdb_client import get_tmdb_client

logger = logging.getLogger(__name__)


class OpenSubtitlesClient:
    """Client per upload sottotitoli su OpenSubtitles"""
    
    def upload_subtitle(self, video_path: str, subtitle_path: str) -> bool:
        """
        Upload sottotitoli su OpenSubtitles
        
        Args:
            video_path: Path al file video
            subtitle_path: Path al file SRT
        
        Returns:
            True se upload riuscito
        """
        try:
            # STEP 1: Ottieni info media da TMDB (include IMDb ID)
            tmdb = get_tmdb_client()
            media_info = tmdb.get_media_info(video_path)
            
            if not media_info:
                logger.error("❌ Impossibile ottenere info media da TMDB")
                return False
            
            # STEP 2: ✅ VERIFICA IMDb ID (OBBLIGATORIO)
            imdb_id = media_info.get('imdb_id')
            
            if not imdb_id:
                logger.warning("⚠️ Upload saltato: IMDb ID non disponibile")
                logger.info("💡 IMDb ID è obbligatorio per upload OpenSubtitles")
                return False
            
            # STEP 3: Verifica formato IMDb ID
            if not imdb_id.startswith('tt'):
                logger.error(f"❌ IMDb ID non valido: {imdb_id}")
                return False
            
            logger.info(f"✅ IMDb ID trovato: {imdb_id}")
            
            # STEP 4: Prepara payload per OpenSubtitles API
            upload_data = {
                'imdb_id': imdb_id,  # ✅ USA IMDb ID (non TMDB ID!)
                'movie_name': media_info.get('title'),
                'movie_year': media_info.get('release_date', '')[:4] if media_info.get('release_date') else None,
                'subtitle_file': subtitle_path,
                'language': 'ita'
            }
            
            # Serie TV: aggiungi stagione/episodio
            if media_info.get('season') is not None:
                upload_data['season'] = media_info['season']
                upload_data['episode'] = media_info['episode']
                logger.info(f"📺 Serie TV: S{media_info['season']:02d}E{media_info['episode']:02d}")
            
            # STEP 5: Upload (da implementare con API OpenSubtitles)
            logger.info(f"📤 Upload a OpenSubtitles...")
            logger.info(f"   IMDb ID: {imdb_id}")
            logger.info(f"   Titolo: {upload_data['movie_name']}")
            
            # TODO: Implementa chiamata API OpenSubtitles qui
            # response = requests.post("https://api.opensubtitles.com/api/v1/upload", ...)
            
            logger.info("✅ Upload completato")
            return True
            
        except Exception as e:
            logger.error(f"❌ Errore upload OpenSubtitles: {e}", exc_info=True)
            return False


# Esempio utilizzo
def example_usage():
    """Esempio di come usare il client"""
    
    client = OpenSubtitlesClient()
    
    # Caso 1: Film
    video_path = "The.Matrix.1999.1080p.BluRay.mp4"
    subtitle_path = "The.Matrix.1999.ita.srt"
    
    success = client.upload_subtitle(video_path, subtitle_path)
    
    if success:
        print("✅ Sottotitoli caricati su OpenSubtitles")
    else:
        print("❌ Upload fallito (controlla se IMDb ID è disponibile)")
    
    # Caso 2: Serie TV
    video_path = "Breaking.Bad.S01E01.1080p.WEB.mp4"
    subtitle_path = "Breaking.Bad.S01E01.ita.srt"
    
    success = client.upload_subtitle(video_path, subtitle_path)


if __name__ == "__main__":
    example_usage()
