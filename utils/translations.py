"""
Translations Manager - Sistema multilingua
File: utils/translations.py
AGGIORNATO: Aggiunta traduzione per checkbox OpenSubtitles
"""
import locale
import os

class Translations:
    """Gestione delle traduzioni per l'interfaccia"""
    
    # Traduzioni
    TEXTS = {
        'en': {
            # Window
            'window_title': 'Transcriber Pro - AI Video Transcription',
            
            # Buttons
            'add_files': 'Add Files',
            'add_folder': 'Add Folder',
            'clear_queue': 'Clear Queue',
            'start': 'Start',
            'pause': 'Pause',
            'resume': 'Resume',
            'cancel': 'Cancel',
            
            # Labels
            'processing_queue': 'Processing Queue:',
            'video_preview': 'Video Preview:',
            'overall_progress': 'Overall Progress:',
            'processing_log': 'Processing Log:',
            'system_resources': 'System Resources',
            'cpu_usage': 'CPU Usage:',
            'ram_usage': 'RAM Usage:',
            'gpu_usage': 'GPU Usage:',
            'vram_usage': 'VRAM Usage:',
            'network_status': 'Network Status:',
            'download_speed': 'Download:',
            'upload_speed': 'Upload:',
            
            # ✅ NUOVO: OpenSubtitles Upload
            'enable_opensubtitles_upload': 'Upload to OpenSubtitles',
            
            # Messages
            'no_file_selected': 'No file selected',
            'loading_preview': 'Loading preview...',
            'extracting_thumbnail': 'Extracting thumbnail...',
            'selected': 'Selected',
            'could_not_load_preview': '(Could not load preview)',
            'preview_not_available': '(Preview not available)',
            'added': 'Added',
            'files_from_folder': 'files from folder',
            'queue_cleared': 'Queue cleared',
            'processing_started': 'Processing started...',
            'processing_paused': 'Processing paused',
            'processing_resumed': 'Processing resumed',
            'cancelling_processing': 'Cancelling processing...',
            'processing_completed': 'Processing completed!',
            'items_via_dragdrop': 'items via drag-and-drop',
            
            # Dialogs
            'warning': 'Warning',
            'error': 'Error',
            'success': 'Success',
            'confirm_exit': 'Confirm Exit',
            'no_files_in_queue': 'No files in queue',
            'cannot_clear_while_processing': 'Cannot clear queue while processing',
            'all_files_processed': 'All files processed successfully!',
            'processing_failed': 'Processing failed',
            'processing_in_progress': 'Processing is in progress. Are you sure you want to exit?',
            
            # File dialog
            'select_video_files': 'Select Video Files',
            'video_files': 'Video Files',
            'all_files': 'All Files',
            'select_folder': 'Select Folder',
            
            # Shutdown
            'shutdown_when_done': 'Shutdown computer when done',
            'shutting_down': 'Shutting down computer...',
        },
        'it': {
            # Finestra
            'window_title': 'Transcriber Pro - Trascrizione Video AI',
            
            # Pulsanti
            'add_files': 'Aggiungi File',
            'add_folder': 'Aggiungi Cartella',
            'clear_queue': 'Svuota Coda',
            'start': 'Avvia',
            'pause': 'Pausa',
            'resume': 'Riprendi',
            'cancel': 'Annulla',
            
            # Etichette
            'processing_queue': 'Coda di Elaborazione:',
            'video_preview': 'Anteprima Video:',
            'overall_progress': 'Progresso Generale:',
            'processing_log': 'Log di Elaborazione:',
            'system_resources': 'Risorse di Sistema',
            'cpu_usage': 'Uso CPU:',
            'ram_usage': 'Uso RAM:',
            'gpu_usage': 'Uso GPU:',
            'vram_usage': 'Uso VRAM:',
            'network_status': 'Stato Rete:',
            'download_speed': 'Download:',
            'upload_speed': 'Upload:',
            
            # ✅ NUOVO: OpenSubtitles Upload
            'enable_opensubtitles_upload': 'Upload su OpenSubtitles',
            
            # Messaggi
            'no_file_selected': 'Nessun file selezionato',
            'loading_preview': 'Caricamento anteprima...',
            'extracting_thumbnail': 'Estrazione miniatura...',
            'selected': 'Selezionato',
            'could_not_load_preview': '(Impossibile caricare anteprima)',
            'preview_not_available': '(Anteprima non disponibile)',
            'added': 'Aggiunto',
            'files_from_folder': 'file dalla cartella',
            'queue_cleared': 'Coda svuotata',
            'processing_started': 'Elaborazione avviata...',
            'processing_paused': 'Elaborazione in pausa',
            'processing_resumed': 'Elaborazione ripresa',
            'cancelling_processing': 'Annullamento elaborazione...',
            'processing_completed': 'Elaborazione completata!',
            'items_via_dragdrop': 'elementi tramite drag-and-drop',
            
            # Dialoghi
            'warning': 'Attenzione',
            'error': 'Errore',
            'success': 'Successo',
            'confirm_exit': 'Conferma Uscita',
            'no_files_in_queue': 'Nessun file in coda',
            'cannot_clear_while_processing': 'Impossibile svuotare la coda durante elaborazione',
            'all_files_processed': 'Tutti i file elaborati con successo!',
            'processing_failed': 'Elaborazione fallita',
            'processing_in_progress': "L'elaborazione è in corso. Sei sicuro di voler uscire?",
            
            # Dialogo file
            'select_video_files': 'Seleziona File Video',
            'video_files': 'File Video',
            'all_files': 'Tutti i File',
            'select_folder': 'Seleziona Cartella',
            
            # Spegnimento
            'shutdown_when_done': 'Spegni il computer al termine',
            'shutting_down': 'Spegnimento del computer...',
        }
    }
    
    def __init__(self):
        """Rileva automaticamente la lingua di sistema"""
        self.current_language = self._detect_language()
        
    def _detect_language(self):
        """Rileva la lingua del sistema operativo"""
        try:
            # Prova con locale
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                lang_code = system_locale.split('_')[0].lower()
                if lang_code == 'it':
                    return 'it'
        except:
            pass
        
        # Prova con variabile d'ambiente
        try:
            lang_env = os.environ.get('LANG', '')
            if 'it' in lang_env.lower():
                return 'it'
        except:
            pass
        
        # Default a inglese
        return 'en'
    
    def get(self, key):
        """Ottieni la traduzione per una chiave"""
        return self.TEXTS.get(self.current_language, self.TEXTS['en']).get(key, key)
    
    def set_language(self, lang_code):
        """Imposta manualmente la lingua"""
        if lang_code in self.TEXTS:
            self.current_language = lang_code

# Istanza globale
_translations = Translations()

def get_text(key):
    """Funzione helper per ottenere traduzioni"""
    return _translations.get(key)

def get_translations():
    """Ottieni l'istanza delle traduzioni"""
    return _translations
