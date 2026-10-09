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
from typing import Optional, Dict, List, Iterable

from core.subtitle_lang import (
    normalize_lang, lang_from_title, title_is_forced, title_is_hi, title_is_commentary,
)

logger = logging.getLogger(__name__)


class SubtitleExtractor:
    """Estrae sottotitoli incorporati dai video"""

    # PRIORITÀ LINGUE (in ordine decrescente)
    # (ISO 639-1; it/en hanno i loro gruppi in _rank_key, il resto segue quest'ordine)
    LANGUAGE_PRIORITY = ['it', 'en', 'es', 'fr', 'de', 'pt', 'ru', 'ja']

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
        self._cancelled: bool = False
        self._active_proc: Optional[subprocess.Popen] = None

    # Soglie per riconoscere come COMPLETA una traccia marcata forced (v. detect_subtitles)
    FULL_TRACK_MIN_EVENTS = 150
    FULL_TRACK_MIN_PER_MINUTE = 5.0

    # Bitmap per cui esiste un motore OCR (gli altri, es. dvb_subtitle/xsub, non sono candidabili)
    OCR_CODECS = {'hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub'}

    @staticmethod
    def _tag_int(tags: dict, name: str) -> Optional[int]:
        """Intero da un tag mkvmerge (NUMBER_OF_FRAMES o NUMBER_OF_FRAMES-<lingua>), None se assente."""
        for k, v in (tags or {}).items():
            if k.upper() == name or k.upper().startswith(name + '-'):
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None
        return None

    def cancel(self):
        """Segnala cancellazione e termina il sottoprocesso FFmpeg attivo."""
        self._cancelled = True
        if self._active_proc:
            try:
                self._active_proc.kill()
            except Exception:
                pass
    
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
                '-show_format',
                '-select_streams', 's',
                str(self.video_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Errore ffprobe: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            try:
                video_minutes = float((data.get('format') or {}).get('duration') or 0) / 60.0
            except (TypeError, ValueError):
                video_minutes = 0.0
            
            self.subtitle_streams = []
            
            for stream in streams:
                tags = stream.get('tags', {}) or {}
                tag_raw = tags.get('language', 'und')
                title = tags.get('title', '') or ''
                tag_lang = normalize_lang(tag_raw)
                title_lang = lang_from_title(title)
                # Lingua della traccia: il tag vale se riconosciuto; il titolo la completa solo se il tag
                # manca o non e' riconoscibile. Un tag che contraddice il titolo resta com'e' qui: sara' il
                # testo (estratto o OCR) a decidere, v. core/subtitle_lang.py.
                if tag_lang != 'und':
                    lang, lang_source = tag_lang, 'tag'
                elif title_lang:
                    lang, lang_source = title_lang, 'title'
                else:
                    lang, lang_source = 'und', 'none'
                disp = stream.get('disposition', {}) or {}
                flag_forced = disp.get('forced', 0) == 1
                forced_by_title = title_is_forced(title)
                frames = self._tag_int(tags, 'NUMBER_OF_FRAMES')
                codec_name = (stream.get('codec_name') or '').lower()
                # Battute stimate: i PGS hanno ~2 frame per battuta (mostra + cancella).
                events = (frames // 2 if codec_name in ('hdmv_pgs_subtitle', 'pgssub') else frames) if frames else None
                # Un flag "forced" sbagliato su una traccia che e' in realta' il sottotitolo completo
                # (release che marcano forced+default la traccia dei dialoghi: RahXephon, ~195 battute in 24
                # minuti) la farebbe scartare. Una vera forced ha poche battute (1-3 al minuto). Qui si
                # segna solo se la traccia "sembra completa"; la decisione e' nella passata dopo il ciclo.
                full_like = bool(events and video_minutes > 0
                                 and events >= self.FULL_TRACK_MIN_EVENTS
                                 and events / video_minutes >= self.FULL_TRACK_MIN_PER_MINUTE
                                 and codec_name not in ('ass', 'ssa'))
                forced = forced_by_title or flag_forced
                sub_info = {
                    'index': stream.get('index'),
                    'codec': stream.get('codec_name', 'unknown'),
                    'language': tag_raw,            # tag grezzo (compatibilita')
                    'lang': lang,                   # lingua effettiva ISO 639-1 ('und' se ignota)
                    'lang_source': lang_source,     # 'tag' | 'title' | 'text' | 'none'
                    'title_lang': title_lang,
                    'title': title,
                    'forced': forced,
                    'forced_flag': flag_forced,
                    'events': events,
                    'forced_by_title': forced_by_title,
                    'full_like': full_like,
                    'hearing_impaired': title_is_hi(title),
                    'commentary': title_is_commentary(title),
                }
                if title_lang and tag_lang != 'und' and title_lang != tag_lang:
                    logger.warning(
                        f"  ⚠️ Stream {sub_info['index']}: tag lingua '{tag_raw}' in contrasto col titolo "
                        f"'{title}' ({title_lang}): decide il contenuto")
                    sub_info['lang_conflict'] = True

                self.subtitle_streams.append(sub_info)

                logger.info(
                    f"  📄 Stream {sub_info['index']}: "
                    f"{sub_info['codec']} | "
                    f"Lang: {tag_raw}->{lang} ({lang_source}) | "
                    f"Title: '{title}' | "
                    f"Forced: {sub_info['forced']} | "
                    f"HI: {sub_info['hearing_impaired']}"
                )

            # Flag forced ignorato solo se la traccia sembra COMPLETA e non c'e' un'altra traccia non forced
            # nella stessa lingua (in quel caso la forced e' davvero una forced).
            for st in self.subtitle_streams:
                if st['forced_flag'] and not st['forced_by_title'] and st['full_like']:
                    others = [o for o in self.subtitle_streams
                              if o is not st and o['lang'] == st['lang'] and not o['forced']]
                    if not others:
                        st['forced'] = False
                        logger.warning(
                            f"  ⚠️ Stream {st['index']}: flag forced ignorato ({st['events']} battute in "
                            f"{video_minutes:.0f} min: sottotitolo completo marcato forced)")

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
    
    # ── Classifica unica delle tracce ─────────────────────────────────────
    def _is_bitmap(self, s: Dict) -> bool:
        return s['codec'].lower() in self.BITMAP_CODECS

    def _rank_key(self, s: Dict):
        """Ordine: testo it > bitmap it > testo en > bitmap en > altre lingue (testo, poi bitmap, nell'ordine di
        LANGUAGE_PRIORITY, 'und' in fondo); a parita' regolare > HI > commento, poi l'indice."""
        lang = s.get('lang') or 'und'
        group = 0 if lang == 'it' else 1 if lang == 'en' else 3 if lang == 'und' else 2
        if lang == 'und':
            prio = 99
        elif lang in self.LANGUAGE_PRIORITY:
            prio = self.LANGUAGE_PRIORITY.index(lang)
        else:
            prio = 50
        quality = 2 if s.get('commentary') else 1 if s.get('hearing_impaired') else 0
        return (group, 1 if self._is_bitmap(s) else 0, prio if group == 2 else 0, quality, s['index'])

    def rank_candidates(self, exclude: Iterable[int] = ()) -> List[Dict]:
        """Tracce non forced (testo E bitmap) in ordine di preferenza, senza gli indici in `exclude`."""
        if not self.subtitle_streams:
            self.detect_subtitles()
        skip = set(exclude)
        cands = [s for s in self.subtitle_streams if not s['forced'] and s['index'] not in skip
                 and (not self._is_bitmap(s) or s['codec'].lower() in self.OCR_CODECS)]
        return sorted(cands, key=self._rank_key)

    def select_best_candidate(self, exclude: Iterable[int] = ()) -> Optional[Dict]:
        """Prima traccia della classifica (testo o bitmap) o None."""
        cands = self.rank_candidates(exclude)
        if not cands:
            return None
        best = cands[0]
        logger.info(
            f"  ✅ Candidata: stream {best['index']} {best['lang'].upper()} "
            f"{'bitmap' if self._is_bitmap(best) else 'testo'} ({best['codec']}) - '{best['title']}'")
        return best

    def set_language(self, index: int, lang: str, source: str = 'text') -> None:
        """Corregge la lingua effettiva di una traccia (verdetto sul contenuto)."""
        for s in self.subtitle_streams:
            if s['index'] == index:
                s['lang'], s['lang_source'] = lang, source
                s.pop('lang_conflict', None)

    def select_best_subtitle(self) -> Optional[Dict]:
        """Miglior sottotitolo TESTO (forced scartati) secondo la classifica unica, o None."""
        if not self.subtitle_streams:
            self.detect_subtitles()
        if not self.subtitle_streams:
            logger.info("Nessun sottotitolo embedded")
            return None
        forced_count = sum(1 for s in self.subtitle_streams if s['forced'])
        if forced_count:
            logger.info(f"  🚫 Scartati {forced_count} sottotitoli forced")
        texts = [s for s in self.rank_candidates() if not self._is_bitmap(s)]
        if not texts:
            logger.info("Nessun sottotitolo testo disponibile")
            return None
        selected = texts[0]
        logger.info(
            f"  ✅ Selezionato: {selected['lang'].upper()} (Stream {selected['index']}) - '{selected['title']}'")
        return selected

    def select_best_bitmap_subtitle(self) -> Optional[Dict]:
        """Miglior sottotitolo BITMAP (PGS/VOBSUB/DVB) per l'OCR, forced scartati, stessa classifica."""
        if not self.subtitle_streams:
            self.detect_subtitles()
        bitmaps = [s for s in self.rank_candidates() if self._is_bitmap(s)]
        if not bitmaps:
            logger.info("Nessun sottotitolo bitmap disponibile")
            return None
        selected = bitmaps[0]
        logger.info(
            f"  ✅ Bitmap selezionato: {selected['lang'].upper()} "
            f"({selected['codec']}, Stream {selected['index']})")
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
            
            self._active_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            _stdout, _stderr = self._active_proc.communicate()
            _rc = self._active_proc.returncode
            self._active_proc = None
            if self._cancelled:
                raise InterruptedError("Operazione annullata")

            if _rc != 0:
                logger.error(f"❌ Errore estrazione: {_stderr}")
                return False
            
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("❌ File sottotitolo non creato o vuoto")
                return False
            
            logger.info(f"  ✅ Sottotitolo estratto: {output_path.stat().st_size / 1024:.1f} KB")
            return True
            
        except InterruptedError:
            raise
        except Exception as e:
            logger.error(f"❌ Errore estrazione sottotitolo: {e}", exc_info=True)
            return False

    def select_all_italian_bitmap_subtitles(self) -> List[Dict]:
        """
        Restituisce TUTTE le tracce bitmap italiane, ordinate per index.
        Incluse le tracce forced: la Library Scanner le rileva senza filtrarle
        e imposta has_italian_bitmap_sub=True su di esse.
        """
        if not self.subtitle_streams:
            self.detect_subtitles()
        result = sorted(
            [
                s for s in self.subtitle_streams
                if s['codec'].lower() in self.BITMAP_CODECS
                and s.get('lang') == 'it'
            ],
            key=lambda s: s['index'],
        )
        if result:
            logger.info(
                f"  Tracce bitmap italiane: {len(result)} "
                f"(stream {[s['index'] for s in result]})"
            )
        return result

    def has_subtitles(self) -> bool:
        """Verifica se il video ha sottotitoli"""
        if not self.subtitle_streams:
            self.detect_subtitles()
        return len(self.subtitle_streams) > 0