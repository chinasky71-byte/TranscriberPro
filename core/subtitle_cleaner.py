"""
Subtitle Cleaner - Pulisce sottotitoli da formattazioni + Fix Overlapping CONSERVATIVO
File: core/subtitle_cleaner.py

VERSIONE CONSERVATIVA + PUNTEGGIATURA PRESERVATA:
âœ… NON modifica MAI i tempi di inizio
âœ… Modifica SOLO i tempi di fine quando c'Ã¨ overlap  
âœ… Preserva completamente la sincronia originale
âœ… Algoritmo multi-pass per garantire risoluzione completa
âœ… Intervento minimo possibile sui timing

PULIZIA TESTO RAFFINATA v2.0:
âœ… Preserva TUTTA la punteggiatura standard (. , ! ? ; : - ... etc)
âœ… Gestisce correttamente virgolette, apostrofi, parentesi
âœ… Normalizza caratteri Unicode (apostrofi tipografici, trattini lunghi, etc)
âœ… Sistema spazi in modo intelligente (rimuove prima, mantiene dopo punteggiatura)
âœ… Rimuove solo tag markup e descrizioni audio
âœ… Massima leggibilitÃ  del testo finale
"""
import re
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Subtitle:
    """Rappresentazione strutturata di un sottotitolo"""
    index: int
    start_time: str
    end_time: str
    text: str
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    original_start_seconds: float = 0.0  # Preserva timing originale
    original_end_seconds: float = 0.0    # Preserva timing originale
    
    def __post_init__(self):
        """Calcola automaticamente i secondi dai timestamp"""
        if self.start_time:
            self.start_seconds = self._timestamp_to_seconds(self.start_time)
            self.original_start_seconds = self.start_seconds
        if self.end_time:
            self.end_seconds = self._timestamp_to_seconds(self.end_time)
            self.original_end_seconds = self.end_seconds
    
    def _timestamp_to_seconds(self, timestamp: str) -> float:
        """Converte timestamp SRT in secondi"""
        time_parts = timestamp.replace(',', '.').split(':')
        hours = float(time_parts[0])
        minutes = float(time_parts[1])
        seconds = float(time_parts[2])
        return hours * 3600 + minutes * 60 + seconds
    
    def _seconds_to_timestamp(self, seconds: float) -> str:
        """Converte secondi in timestamp SRT"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        millis = int((secs % 1) * 1000)
        secs = int(secs)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    def update_end_time(self, end_sec: float):
        """
        Aggiorna SOLO il tempo di fine (MAI il tempo di inizio!)
        Questo preserva la sincronia con l'audio
        """
        self.end_seconds = end_sec
        self.end_time = self._seconds_to_timestamp(end_sec)


class SubtitleCleaner:
    """Pulisce e normalizza file SRT con fix overlapping CONSERVATIVO"""
    
    # Parametri configurabili per fix overlapping
    MIN_SUBTITLE_DURATION = 0.3    # Durata minima di un sottotitolo (300ms)
    MIN_GAP_SECONDS = 0.042        # Gap minimo tra sottotitoli (42ms ~ 1 frame a 24fps)
    MAX_ITERATIONS = 10             # Massimo numero di passate
    
    def __init__(self, srt_path: Path):
        self.srt_path = Path(srt_path)
        self.subtitles: List[Subtitle] = []
        self.overlap_stats = {
            'initial_overlaps': 0,
            'final_overlaps': 0,
            'iterations_needed': 0,
            'total_fixes': 0,
            'time_reduced_total': 0.0,
            'subtitles_modified': set()
        }
    
    def load(self) -> bool:
        """
        Carica file SRT con gestione robusta encoding
        Prova UTF-8-sig (con BOM), poi UTF-8, poi Latin-1
        """
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(self.srt_path, 'r', encoding=encoding) as f:
                    content = f.read()
                
                # Parse SRT in oggetti Subtitle strutturati
                self.subtitles = self._parse_srt(content)
                logger.info(f"📖 Caricati {len(self.subtitles)} sottotitoli da {self.srt_path.name} (encoding: {encoding})")
                return True
                
            except (UnicodeDecodeError, UnicodeError):
                # Prova con encoding successivo
                continue
            except Exception as e:
                logger.error(f"❌ Errore caricamento SRT: {e}")
                return False
        
        logger.error(f"❌ Impossibile leggere {self.srt_path.name} con nessun encoding supportato")
        return False
    def _parse_srt(self, content: str) -> List[Subtitle]:
        """Parse contenuto SRT in oggetti Subtitle"""
        subtitles = []
        
        # Split per blocchi (separati da righe vuote)
        blocks = re.split(r'\n\s*\n', content.strip())
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
            
            try:
                # Linea 1: Index
                index = int(lines[0].strip())
                
                # Linea 2: Timestamp
                time_match = re.match(
                    r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', 
                    lines[1]
                )
                if not time_match:
                    continue
                
                start_time = time_match.group(1)
                end_time = time_match.group(2)
                
                # Linee successive: Testo
                text = '\n'.join(lines[2:])
                
                # Crea oggetto Subtitle strutturato
                subtitle = Subtitle(
                    index=index,
                    start_time=start_time,
                    end_time=end_time,
                    text=text
                )
                
                subtitles.append(subtitle)
                
            except (ValueError, IndexError) as e:
                logger.debug(f"Skipping malformed subtitle block: {e}")
                continue
        
        return subtitles
    
    def clean(self) -> 'SubtitleCleaner':
        """Pulisce sottotitoli da formattazioni non standard"""
        logger.info("ðŸ§¹ Pulizia sottotitoli...")
        
        cleaned_subtitles = []
        
        for subtitle in self.subtitles:
            # Pulisci testo
            cleaned_text = self._clean_text(subtitle.text)
            
            # Salta sottotitoli vuoti
            if cleaned_text.strip():
                subtitle.text = cleaned_text
                cleaned_subtitles.append(subtitle)
        
        removed = len(self.subtitles) - len(cleaned_subtitles)
        self.subtitles = cleaned_subtitles
        
        logger.info(f"  âœ… Pulizia testo completata: {len(self.subtitles)} sottotitoli (rimossi {removed})")
        return self
    
    def _clean_text(self, text: str) -> str:
        """
        Pulisce testo sottotitolo da tag e formattazioni
        VERSIONE RAFFINATA: preserva tutta la punteggiatura legittima
        """
        # ============================================================
        # FASE 1: Rimozione tag e markup
        # ============================================================
        
        # Rimuovi tag HTML (es: <i>, <b>, <font>)
        text = re.sub(r'<[^>]+>', '', text)
        
        # Rimuovi tag ASS/SSA (es: {\an8}, {\pos(x,y)})
        text = re.sub(r'\{[^}]+\}', '', text)
        
        # Rimuovi tag VTT (WebVTT)
        text = re.sub(r'<v\s+[^>]+>', '', text)
        text = re.sub(r'</v>', '', text)
        text = re.sub(r'<c\.[^>]+>', '', text)
        text = re.sub(r'</c>', '', text)
        
        # ============================================================
        # FASE 2: Rimozione descrizioni audio e note
        # ============================================================
        
        # Rimuovi descrizioni sonore tra parentesi/quadre
        # Pattern piÃ¹ completo con maggiori varianti
        sound_patterns = [
            r'\[(?:MUSIC|SOUND|AUDIO|APPLAUSE|LAUGHTER|SIGHS?|GROANS?|SCREAMS?|DOOR|PHONE|BELL|KNOCK|FOOTSTEPS|WIND|RAIN|THUNDER|EXPLOSION|GUNSHOT|SIRENS?)[^\]]*\]',
            r'\((?:MUSIC|SOUND|AUDIO|APPLAUSE|LAUGHTER|SIGHS?|GROANS?|SCREAMS?|DOOR|PHONE|BELL|KNOCK|FOOTSTEPS|WIND|RAIN|THUNDER|EXPLOSION|GUNSHOT|SIRENS?)[^\)]*\)',
            r'\[.*?(?:musica|suono|audio|applausi|risate|sospir[io]|gem[ie]|url[oa]|porta|telefono).*?\]',
            r'\(.*?(?:musica|suono|audio|applausi|risate|sospir[io]|gem[ie]|url[oa]|porta|telefono).*?\)'
        ]
        for pattern in sound_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Rimuovi note del traduttore (italiano e inglese)
        text = re.sub(r'\(N\.?d\.?T\.?:[^\)]+\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[N\.?d\.?T\.?:[^\]]+\]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\(T\.?N\.?:[^\)]+\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[T\.?N\.?:[^\]]+\]', '', text, flags=re.IGNORECASE)
        
        # ============================================================
        # FASE 3: Normalizzazione caratteri Unicode
        # ============================================================
        
        # Normalizza apostrofi (converte tutti a apostrofo standard)
        # Preserviamo l'apostrofo ma lo normalizziamo
        text = text.replace('\u2019', "'")  # Apostrofo tipografico destro (')
        text = text.replace('\u2018', "'")  # Apostrofo tipografico sinistro (')
        text = text.replace('`', "'")       # Backtick
        text = text.replace('\u00B4', "'")  # Accento acuto (´)
        
        # Normalizza virgolette (converte a virgolette dritte per coerenza)
        # Questo è opzionale - se preferisci mantenere quelle tipografiche, commenta queste righe
        text = text.replace('\u201C', '"')  # Virgolette tipografiche sinistra (")
        text = text.replace('\u201D', '"')  # Virgolette tipografiche destra (")
        text = text.replace('\u00AB', '"')  # Virgolette angolari sinistra («)
        text = text.replace('\u00BB', '"')  # Virgolette angolari destra (»)
        
        # Normalizza trattini (converti tutti i trattini lunghi a trattino medio)
        text = text.replace('\u2014', '-')  # Em dash (—)
        text = text.replace('\u2013', '-')  # En dash (–)
        text = text.replace('\u2212', '-')  # Minus sign (−)
        
        # Normalizza puntini di sospensione
        text = text.replace('\u2026', '...')  # Carattere ellipsis Unicode (…)
        
        # ============================================================
        # FASE 4: Rimozione caratteri di controllo
        # ============================================================
        
        # Rimuovi SOLO caratteri di controllo (non stampabili)
        # Preserva: tab (\x09), newline (\x0A), carriage return (\x0D)
        # Rimuove: \x00-\x08, \x0B, \x0C, \x0E-\x1F, \x7F (DEL)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        
        # ============================================================
        # FASE 5: Pulizia spazi (PRESERVANDO PUNTEGGIATURA)
        # ============================================================
        
        # Rimuovi spazi multipli (ma mantieni newline)
        text = re.sub(r'[ \t]+', ' ', text)
        
        # IMPORTANTE: Rimuovi spazi PRIMA della punteggiatura
        # Include: . , ! ? ; : ) ] } " '
        # Ma NON ( [ { che hanno bisogno dello spazio prima
        text = re.sub(r' +([,.!?;:\)\]\}"\'])', r'\1', text)
        
        # Aggiungi spazio DOPO punteggiatura se seguito da lettera/numero
        # Ma solo se non c'è già uno spazio
        # ECCEZIONE: Non aggiungere spazio dopo punto se è parte di:
        # - Email (es: name@example.com)
        # - URL (es: www.example.com)
        # - Numeri decimali (es: 3.14)
        # - Abbreviazioni (es: U.S.A., Dr., etc.)
        
        # Pattern più intelligente: aggiungi spazio dopo punteggiatura
        # solo se seguito da lettera maiuscola o altra parola
        text = re.sub(r'([.!?])([A-ZÀ-ÖØ-Þ])', r'\1 \2', text)  # Dopo . ! ? se maiuscola
        text = re.sub(r'([,:;])([^\s\n])', r'\1 \2', text)      # Dopo , : ; sempre
        
        # Gestione speciale per parentesi e virgolette
        # Rimuovi spazi DOPO apertura: ( [ { "
        text = re.sub(r'([\(\[\{"])\s+', r'\1', text)
        
        # Rimuovi spazi PRIMA chiusura: ) ] } "
        text = re.sub(r'\s+([\)\]\}"])', r'\1', text)
        
        # Ma aggiungi spazio DOPO chiusura se seguito da lettera/numero
        text = re.sub(r'([\)\]\}"])([A-Za-z0-9À-ÿ])', r'\1 \2', text)
        
        # Aggiungi spazio DOPO virgoletta chiusa se seguita da parola
        text = re.sub(r'"([A-Za-z0-9À-ÿ])', r'" \1', text)
        
        # Fix per trattini in dialoghi: assicura spazio dopo trattino iniziale
        text = re.sub(r'^-([^\s])', r'- \1', text, flags=re.MULTILINE)
        
        # ============================================================
        # FASE 6: Pulizia newline
        # ============================================================
        
        # Pulisci newline multipli (max 2 consecutive)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Rimuovi spazi a inizio/fine riga
        text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
        
        # ============================================================
        # FASE 7: Trim finale
        # ============================================================
        
        text = text.strip()
        
        return text
    
    def fix_overlaps(self) -> 'SubtitleCleaner':
        """
        Fix overlapping CONSERVATIVO con algoritmo multi-pass
        - NON modifica MAI i tempi di inizio (preserva sincronia)
        - Modifica SOLO i tempi di fine quando necessario
        - Intervento minimo possibile
        """
        if len(self.subtitles) < 2:
            logger.info("  â„¹ï¸ Nessun overlap da controllare (< 2 sottotitoli)")
            return self
        
        logger.info("ðŸ”§ Fix overlapping temporale (modalitÃ  conservativa)...")
        
        # Reset statistiche
        self.overlap_stats = {
            'initial_overlaps': 0,
            'final_overlaps': 0,
            'iterations_needed': 0,
            'total_fixes': 0,
            'time_reduced_total': 0.0,
            'subtitles_modified': set()
        }
        
        # Conta overlapping iniziali
        self.overlap_stats['initial_overlaps'] = self._count_overlaps()
        
        if self.overlap_stats['initial_overlaps'] == 0:
            logger.info("  âœ… Nessun overlap rilevato - Timing perfetto!")
            return self
        
        # Algoritmo multi-pass CONSERVATIVO
        iteration = 0
        previous_overlaps = self.overlap_stats['initial_overlaps']
        
        while iteration < self.MAX_ITERATIONS:
            iteration += 1
            
            # Esegui una passata di fix
            fixes_in_this_pass = self._fix_overlaps_single_pass()
            
            # Conta overlapping rimanenti
            current_overlaps = self._count_overlaps()
            
            logger.debug(f"  Iterazione {iteration}: {fixes_in_this_pass} fix applicati, {current_overlaps} overlap rimanenti")
            
            # Condizioni di uscita
            if current_overlaps == 0:
                # Tutti gli overlap risolti
                break
            
            if fixes_in_this_pass == 0:
                # Nessun fix applicato, non possiamo fare di meglio
                logger.warning(f"  âš ï¸ Non riesco a risolvere {current_overlaps} overlap rimanenti senza modificare i tempi di inizio")
                break
            
            if current_overlaps == previous_overlaps and iteration > 3:
                # Situazione stagnante
                logger.warning(f"  âš ï¸ Situazione stagnante dopo {iteration} iterazioni")
                break
            
            previous_overlaps = current_overlaps
        
        self.overlap_stats['iterations_needed'] = iteration
        self.overlap_stats['final_overlaps'] = self._count_overlaps()
        
        # Log riepilogo
        self._log_overlap_stats()
        
        return self
    
    def _fix_overlaps_single_pass(self) -> int:
        """
        Esegue una singola passata di fix overlapping
        Approccio CONSERVATIVO: modifica SOLO end time e SOLO se necessario
        
        Returns:
            Numero di fix applicati in questa passata
        """
        fixes_applied = 0
        
        for i in range(len(self.subtitles) - 1):
            curr = self.subtitles[i]
            next_sub = self.subtitles[i + 1]
            
            # Calcola overlap (positivo = c'Ã¨ sovrapposizione)
            overlap = curr.end_seconds - next_sub.start_seconds
            
            if overlap > self.MIN_GAP_SECONDS:
                # C'Ã¨ overlap significativo, dobbiamo fixare
                
                # Calcola il nuovo end time (appena prima del prossimo start)
                new_end = next_sub.start_seconds - self.MIN_GAP_SECONDS
                
                # Verifica che non rendiamo il sottotitolo troppo corto
                duration_after_fix = new_end - curr.start_seconds
                
                if duration_after_fix >= self.MIN_SUBTITLE_DURATION:
                    # Fix sicuro: accorcia il sottotitolo corrente
                    time_reduced = curr.end_seconds - new_end
                    curr.update_end_time(new_end)
                    
                    fixes_applied += 1
                    self.overlap_stats['total_fixes'] += 1
                    self.overlap_stats['time_reduced_total'] += time_reduced
                    self.overlap_stats['subtitles_modified'].add(i + 1)
                    
                    logger.debug(f"    Fix sottotitolo {i+1}: ridotto end di {time_reduced:.3f}s")
                
                elif duration_after_fix < self.MIN_SUBTITLE_DURATION and duration_after_fix > 0:
                    # Il sottotitolo diventerebbe troppo corto ma non impossibile
                    # Applichiamo comunque il fix ma con durata minima
                    
                    # Opzione 1: Mantieni durata minima se possibile
                    min_acceptable_end = curr.start_seconds + self.MIN_SUBTITLE_DURATION
                    
                    if min_acceptable_end < next_sub.start_seconds:
                        # Possiamo mantenere durata minima
                        time_reduced = curr.end_seconds - min_acceptable_end
                        curr.update_end_time(min_acceptable_end)
                        
                        fixes_applied += 1
                        self.overlap_stats['total_fixes'] += 1
                        self.overlap_stats['time_reduced_total'] += time_reduced
                        self.overlap_stats['subtitles_modified'].add(i + 1)
                        
                        logger.debug(f"    Fix sottotitolo {i+1} (durata min): ridotto end di {time_reduced:.3f}s")
                    else:
                        # Non possiamo mantenere durata minima senza creare overlap
                        # Accettiamo una durata piÃ¹ corta come male minore
                        new_end = next_sub.start_seconds - self.MIN_GAP_SECONDS
                        time_reduced = curr.end_seconds - new_end
                        curr.update_end_time(new_end)
                        
                        fixes_applied += 1
                        self.overlap_stats['total_fixes'] += 1
                        self.overlap_stats['time_reduced_total'] += time_reduced
                        self.overlap_stats['subtitles_modified'].add(i + 1)
                        
                        logger.debug(f"    Fix sottotitolo {i+1} (durata ridotta): ridotto end di {time_reduced:.3f}s")
                else:
                    # Caso estremo: il sottotitolo inizia dopo o contemporaneamente al successivo
                    # Non possiamo fare nulla senza modificare start time
                    logger.warning(f"    âš ï¸ Sottotitolo {i+1}: overlap troppo grave per fix conservativo")
        
        return fixes_applied
    
    def _count_overlaps(self) -> int:
        """Conta il numero totale di overlapping"""
        count = 0
        for i in range(len(self.subtitles) - 1):
            if self.subtitles[i].end_seconds > self.subtitles[i + 1].start_seconds + 0.001:  # Tolleranza 1ms
                count += 1
        return count
    
    def renumber(self) -> 'SubtitleCleaner':
        """Rinumera sottotitoli sequenzialmente"""
        for i, subtitle in enumerate(self.subtitles, 1):
            subtitle.index = i
        
        logger.info(f"  âœ… Rinumerazione completata: {len(self.subtitles)} sottotitoli")
        return self
    
    def save(self, output_path: Path = None) -> bool:
        """Salva sottotitoli puliti"""
        if output_path is None:
            output_path = self.srt_path
        
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Genera contenuto SRT
            srt_content = self._generate_srt()
            
            # Salva con UTF-8 (con BOM per compatibilità)
            with open(output_path, 'w', encoding='utf-8-sig') as f:
                f.write(srt_content)
            
            logger.info(f"ðŸ’¾ Salvato: {output_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"âŒ Errore salvataggio: {e}")
            return False
    
    def _generate_srt(self) -> str:
        """Genera contenuto SRT dai sottotitoli"""
        lines = []
        
        for subtitle in self.subtitles:
            lines.append(str(subtitle.index))
            lines.append(f"{subtitle.start_time} --> {subtitle.end_time}")
            lines.append(subtitle.text)
            lines.append("")  # Riga vuota tra blocchi
        
        return '\n'.join(lines)
    
    def _log_overlap_stats(self):
        """Log riepilogo statistiche overlap fix"""
        stats = self.overlap_stats
        
        logger.info(f"  ðŸ“Š Riepilogo Fix Overlapping (Conservativo):")
        logger.info(f"    â€¢ Overlap iniziali: {stats['initial_overlaps']}")
        logger.info(f"    â€¢ Overlap finali: {stats['final_overlaps']}")
        
        if stats['initial_overlaps'] > 0:
            reduction_pct = ((stats['initial_overlaps'] - stats['final_overlaps']) / stats['initial_overlaps']) * 100
            logger.info(f"    â€¢ Riduzione: {reduction_pct:.1f}%")
        
        logger.info(f"    â€¢ Iterazioni: {stats['iterations_needed']}")
        logger.info(f"    â€¢ Fix totali applicati: {stats['total_fixes']}")
        logger.info(f"    â€¢ Sottotitoli modificati: {len(stats['subtitles_modified'])}")
        logger.info(f"    â€¢ Tempo totale ridotto: {stats['time_reduced_total']:.2f}s")
        
        if stats['final_overlaps'] == 0:
            logger.info(f"  âœ… Tutti gli overlapping risolti!")
        else:
            logger.info(f"  âš ï¸ {stats['final_overlaps']} overlap non risolvibili senza modificare i tempi di inizio")
            logger.info(f"     (preservata sincronia audio a costo di overlap minori)")
    
    @staticmethod
    def extract_text_only(input_path: Path) -> str:
        """
        Estrae solo il testo puro da un file SRT (per calcolo WER)
        
        Args:
            input_path: Path file SRT pulito
            
        Returns:
            Stringa singola contenente tutto il testo, tokenizzato in minuscolo
        """
        logger.debug(f"Estraendo testo puro da: {input_path.name}")
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Pattern per identificare linee di testo
            lines = content.strip().split('\n')
            text_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Esclude indice (numeri) e timestamp (contiene '-->')
                if re.match(r'^\d+$', line):
                    continue
                if '-->' in line:
                    continue
                
                # Aggiunge solo la linea di testo
                text_lines.append(line)
            
            # Unisci il testo con uno spazio e converti in minuscolo
            return ' '.join(text_lines).lower()
            
        except Exception as e:
            logger.error(f"âŒ Errore estrazione testo puro: {e}")
            return ""
    
    @staticmethod
    def clean_file(input_path: Path, output_path: Path = None) -> Path:
        """
        Metodo statico per pulire un file SRT
        
        Args:
            input_path: Path file input
            output_path: Path file output (None = sovrascrivi)
        
        Returns:
            Path al file pulito
        """
        if output_path is None:
            output_path = input_path
        
        cleaner = SubtitleCleaner(input_path)
        
        if not cleaner.load():
            return input_path
        
        # Pipeline completa con algoritmo conservativo
        cleaner.clean().fix_overlaps().renumber()
        
        if cleaner.save(output_path):
            return output_path
        else:
            return input_path
    
    def get_overlap_stats(self) -> Dict[str, any]:
        """Ottieni statistiche overlap fix"""
        return self.overlap_stats.copy()