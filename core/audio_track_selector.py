"""
Audio Track Selector - VERIFIED & COMPLETE
File: core/audio_track_selector.py

FUNZIONALITÀ:
✅ Rilevamento automatico tracce audio
✅ Selezione intelligente con priorità lingua
✅ Estrazione audio in formato WAV 16kHz mono
✅ Supporto multi-lingua con mapping ISO 639
✅ Logging dettagliato
"""
import subprocess
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class AudioTrackSelector:
    """Seleziona automaticamente la migliore traccia audio dal video"""
    
    # Ordine di preferenza lingue
    LANGUAGE_PRIORITY = ['ita', 'eng', 'spa', 'fre']
    
    # Mapping codici lingua ISO 639-2/3
    LANGUAGE_MAPPING = {
        'it': 'ita', 'ita': 'ita', 'italian': 'ita',
        'en': 'eng', 'eng': 'eng', 'english': 'eng',
        'es': 'spa', 'spa': 'spa', 'spanish': 'spa',
        'fr': 'fre', 'fre': 'fre', 'fra': 'fre', 'french': 'fre',
        'de': 'deu', 'deu': 'deu', 'ger': 'deu', 'german': 'deu',
        'pt': 'por', 'por': 'por', 'portuguese': 'por',
        'ru': 'rus', 'rus': 'rus', 'russian': 'rus',
        'ja': 'jpn', 'jpn': 'jpn', 'japanese': 'jpn',
    }
    
    def __init__(self, video_path: str):
        self.video_path = Path(video_path)
        self.audio_streams = []
    
    def detect_audio_streams(self) -> List[Dict]:
        """
        Rileva tutte le tracce audio nel video
        
        Returns:
            Lista di dict con info tracce audio
        """
        logger.info(f"Analisi tracce audio: {self.video_path.name}")
        
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                '-select_streams', 'a',  # Solo audio
                str(self.video_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode != 0:
                logger.error(f"Errore ffprobe: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            
            self.audio_streams = []
            
            for stream in streams:
                audio_info = {
                    'index': stream.get('index'),
                    'codec': stream.get('codec_name', 'unknown'),
                    'language': self._normalize_language(
                        stream.get('tags', {}).get('language', 'und')
                    ),
                    'title': stream.get('tags', {}).get('title', ''),
                    'channels': stream.get('channels', 0),
                    'sample_rate': stream.get('sample_rate', 0)
                }
                
                self.audio_streams.append(audio_info)
                
                logger.info(
                    f"  Traccia {audio_info['index']}: "
                    f"{audio_info['codec']} | "
                    f"Lang: {audio_info['language']} | "
                    f"Ch: {audio_info['channels']}"
                )
            
            logger.info(f"Trovate {len(self.audio_streams)} tracce audio")
            return self.audio_streams
            
        except json.JSONDecodeError as e:
            logger.error(f"Errore parsing JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Errore rilevamento audio: {e}", exc_info=True)
            return []
    
    def _normalize_language(self, lang_code: str) -> str:
        """Normalizza codice lingua a ISO 639-2"""
        lang_lower = lang_code.lower().strip()
        return self.LANGUAGE_MAPPING.get(lang_lower, lang_lower)
    
    def select_best_track(self) -> Optional[Dict]:
        """
        Seleziona migliore traccia audio seguendo priorità:
        1. Se una sola traccia → usa quella
        2. Se più tracce:
           - Cerca italiano
           - Se no, cerca in ordine: inglese, spagnolo, francese
           - Se no, usa prima traccia
        
        Returns:
            Dict con info traccia selezionata o None
        """
        if not self.audio_streams:
            self.detect_audio_streams()
        
        if not self.audio_streams:
            logger.error("Nessuna traccia audio trovata")
            return None
        
        # Caso 1: Una sola traccia
        if len(self.audio_streams) == 1:
            track = self.audio_streams[0]
            logger.info(f"Una sola traccia audio: {track['language']}")
            return track
        
        # Caso 2: Più tracce - segui priorità
        logger.info(f"Trovate {len(self.audio_streams)} tracce, selezione automatica...")
        
        # Cerca in ordine di priorità
        for preferred_lang in self.LANGUAGE_PRIORITY:
            for track in self.audio_streams:
                if track['language'] == preferred_lang:
                    logger.info(
                        f"Selezionata traccia {track['index']} "
                        f"(lingua: {track['language']})"
                    )
                    return track
        
        # Fallback: prima traccia
        track = self.audio_streams[0]
        logger.warning(
            f"Nessuna lingua preferita trovata, uso prima traccia "
            f"(index: {track['index']}, lang: {track['language']})"
        )
        return track
    
    def extract_audio_track(
        self, 
        output_path: Path, 
        track_index: Optional[int] = None
    ) -> bool:
        """
        Estrae traccia audio specifica in formato WAV 16kHz mono
        
        Args:
            output_path: Path file output
            track_index: Index traccia (None = auto-select)
        
        Returns:
            True se estrazione riuscita
        """
        # Auto-select se non specificato
        if track_index is None:
            best_track = self.select_best_track()
            if not best_track:
                return False
            track_index = best_track['index']
        
        logger.info(f"Estrazione traccia audio {track_index}...")
        
        try:
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(self.video_path),
                '-map', f'0:{track_index}',  # Seleziona traccia specifica
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # PCM 16-bit
                '-ar', '16000',  # 16kHz (Whisper standard)
                '-ac', '1',  # Mono
                str(output_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode != 0:
                logger.error(f"Errore estrazione: {result.stderr}")
                return False
            
            if not output_path.exists():
                logger.error("File audio non creato")
                return False
            
            logger.info(f"Audio estratto: {output_path.name}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout estrazione audio")
            return False
        except Exception as e:
            logger.error(f"Errore estrazione: {e}", exc_info=True)
            return False
    
    def get_selected_language(self) -> str:
        """
        Ottiene codice lingua della traccia selezionata
        
        Returns:
            Codice lingua (es: 'ita', 'eng') o 'und' se sconosciuto
        """
        best_track = self.select_best_track()
        if best_track:
            return best_track['language']
        return 'und'