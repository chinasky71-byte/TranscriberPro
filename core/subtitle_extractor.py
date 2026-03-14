"""
Subtitle Extractor - FIXED v2.1 (Regular Priority)
File: core/subtitle_extractor.py

CORREZIONI:
✅ Nuova logica di priorità (Regolare > HI):
   1. ITA regular > 2. ITA HI > 3. ENG regular > 4. ENG HI > 5. Altre lingue (regular > HI)
✅ Forced SEMPRE scartati (tutte le lingue)
✅ Logging dettagliato per debug
"""
import subprocess
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class SubtitleExtractor:
    """Estrae sottotitoli incorporati dai video"""

    # PRIORITÀ LINGUE (in ordine decrescente)
    LANGUAGE_PRIORITY = ['ita', 'eng', 'spa', 'fra', 'deu', 'por', 'rus', 'jpn']

    # Codec bitmap: immagini non convertibili in testo SRT
    BITMAP_CODECS = {
        'hdmv_pgs_subtitle', 'pgssub',   # Blu-ray PGS
        'dvd_subtitle', 'dvdsub',         # DVD VOBSUB
        'dvb_subtitle', 'dvbsub',         # DVB bitmap
        'xsub',                           # DivX XSUB
    }
    
    def __init__(self, video_path: str):
        self.video_path = Path(video_path)
        self.subtitle_streams = []
    
    def detect_subtitles(self) -> List[Dict]:
        """
        Rileva tutti i sottotitoli incorporati nel video
        
        Returns:
            Lista di dict con info su ogni traccia sottotitoli
        """
        logger.info(f"🔍 Ricerca sottotitoli in: {self.video_path.name}")
        
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_streams',
                '-select_streams', 's',
                str(self.video_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Errore ffprobe: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            
            self.subtitle_streams = []
            
            for stream in streams:
                sub_info = {
                    'index': stream.get('index'),
                    'codec': stream.get('codec_name', 'unknown'),
                    'language': stream.get('tags', {}).get('language', 'und'),
                    'title': stream.get('tags', {}).get('title', ''),
                    'forced': stream.get('disposition', {}).get('forced', 0) == 1,
                    'hearing_impaired': False
                }
                
                # Rileva HI dal titolo
                title_lower = sub_info['title'].lower()
                if any(keyword in title_lower for keyword in ['sdh', 'hi', 'hearing impaired', 'cc', 'closed caption']):
                    sub_info['hearing_impaired'] = True
                
                self.subtitle_streams.append(sub_info)
                
                logger.info(
                    f"  📄 Stream {sub_info['index']}: "
                    f"{sub_info['codec']} | "
                    f"Lang: {sub_info['language']} | "
                    f"Title: '{sub_info['title']}' | "
                    f"Forced: {sub_info['forced']} | "
                    f"HI: {sub_info['hearing_impaired']}"
                )
            
            if not self.subtitle_streams:
                logger.info("  ℹ️  Nessun sottotitolo trovato")
            else:
                logger.info(f"  ✅ Trovati {len(self.subtitle_streams)} stream di sottotitoli")
            
            return self.subtitle_streams
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Errore parsing JSON ffprobe: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Errore rilevamento sottotitoli: {e}", exc_info=True)
            return []
    
    def select_best_subtitle(self) -> Optional[Dict]:
        """
        Seleziona il miglior sottotitolo seguendo la NUOVA LOGICA (Regolare > HI)
        
        ✅ PRIORITÀ COMPLETA:
        1. Forced → SEMPRE SCARTATI (tutte le lingue)
        2. ITA regular → Prima scelta
        3. ITA HI (Hearing Impaired) → Seconda scelta
        4. ENG regular → Terza scelta
        5. ENG HI → Quarta scelta
        6. SPA regular → Quinta scelta
        7. SPA HI → Sesta scelta
        ... e così via per altre lingue
        
        Returns:
            Dict con info sul sottotitolo selezionato o None
        """
        if not self.subtitle_streams:
            self.detect_subtitles()
        
        if not self.subtitle_streams:
            logger.warning("  ⚠️ Nessun sottotitolo disponibile")
            return None
        
        logger.info(f"  📊 Selezione automatica tra {len(self.subtitle_streams)} sottotitoli...")
        
        # ✅ STEP 1: Filtra TUTTI i forced (qualsiasi lingua)
        non_forced = [s for s in self.subtitle_streams if not s['forced']]

        if not non_forced:
            logger.warning("  ⚠️ Tutti i sottotitoli sono forced - Nessuno selezionabile")
            return None

        forced_count = len(self.subtitle_streams) - len(non_forced)
        if forced_count > 0:
            logger.info(f"  🚫 Scartati {forced_count} sottotitoli forced")

        # ✅ STEP 1b: Filtra codec bitmap (PGS, VOBSUB, DVB...) — non convertibili in SRT
        text_subs = [s for s in non_forced if s['codec'].lower() not in self.BITMAP_CODECS]

        bitmap_count = len(non_forced) - len(text_subs)
        if bitmap_count > 0:
            skipped = [s['codec'] for s in non_forced if s['codec'].lower() in self.BITMAP_CODECS]
            logger.info(f"  🚫 Scartati {bitmap_count} sottotitoli bitmap non estraibili: {skipped}")

        if not text_subs:
            logger.warning("  ⚠️ Nessun sottotitolo testo disponibile (solo bitmap)")
            return None

        non_forced = text_subs
        
        # ✅ STEP 2: Cerca seguendo la priorità LINGUA (ITA, ENG, SPA...)
        for lang_code in self.LANGUAGE_PRIORITY:
            # Filtra per lingua
            lang_subs = [s for s in non_forced if s['language'].lower().startswith(lang_code[:2])]
            
            if not lang_subs:
                continue
            
            # 💡 NUOVA LOGICA: Prima cerca REGULAR
            regular_subs = [s for s in lang_subs if not s['hearing_impaired']]
            
            if regular_subs:
                selected = regular_subs[0]
                logger.info(
                    f"  ✅ Selezionato: {selected['language'].upper()} regular "
                    f"(Stream {selected['index']}) - '{selected['title']}'"
                )
                return selected

            # Poi cerca HI (se non c'è il regular per questa lingua)
            hi_subs = [s for s in lang_subs if s['hearing_impaired']]
            if hi_subs:
                selected = hi_subs[0]
                logger.info(
                    f"  ✅ Selezionato: {selected['language'].upper()} HI "
                    f"(Stream {selected['index']}) - '{selected['title']}'"
                )
                return selected
        
        # ✅ STEP 3: Fallback - primo sottotitolo non-forced disponibile
        selected = non_forced[0]
        logger.warning(
            f"  ⚠️ Nessuna lingua prioritaria trovata, uso prima traccia: "
            f"{selected['language'].upper()} (Stream {selected['index']})"
        )
        return selected
    
    def extract_subtitle(self, output_path: Path, stream_index: Optional[int] = None) -> bool:
        """
        Estrae sottotitolo in formato SRT
        
        Args:
            output_path: Path dove salvare il file .srt
            stream_index: Indice dello stream (None = auto-select)
        
        Returns:
            True se estrazione riuscita
        """
        if stream_index is None:
            best_sub = self.select_best_subtitle()
            if not best_sub:
                logger.error("❌ Nessun sottotitolo da estrarre")
                return False
            stream_index = best_sub['index']
        
        logger.info(f"📤 Estrazione sottotitolo stream {stream_index} -> {output_path.name}")
        
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(self.video_path),
                '-map', f'0:{stream_index}',
                '-c:s', 'srt',
                str(output_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Errore estrazione: {result.stderr}")
                return False
            
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("❌ File sottotitolo non creato o vuoto")
                return False
            
            logger.info(f"  ✅ Sottotitolo estratto: {output_path.stat().st_size / 1024:.1f} KB")
            return True
            
        except Exception as e:
            logger.error(f"❌ Errore estrazione sottotitolo: {e}", exc_info=True)
            return False
    
    def has_subtitles(self) -> bool:
        """Verifica se il video ha sottotitoli"""
        if not self.subtitle_streams:
            self.detect_subtitles()
        return len(self.subtitle_streams) > 0