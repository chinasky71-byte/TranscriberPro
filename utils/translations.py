# -*- coding: utf-8 -*-
"""
Translations Manager - Sistema multilingua IT / EN
File: utils/translations.py

Copre tutte le stringhe UI di:
  main_window, library_scanner_widget, splash_screen, profile_dialog,
  translation_model_dialog, widgets, opensubtitles_settings_widget,
  adaptive_batch_settings_widget, workers
"""
import os


class Translations:
    """Gestione delle traduzioni per l'interfaccia (IT / EN)."""

    TEXTS = {

        # ── ENGLISH ──────────────────────────────────────────────────────────
        'en': {

            # ── main_window ───────────────────────────────────────────────
            'window_title':             'Transcriber Pro - AI Video Transcription',
            'add_files':                '📄 Add Files',
            'add_folder':               '📂 Add Folder',
            'clear_queue':              '🗑️ Clear',
            'start':                    '▶️ Start',
            'stop':                     '⏸️ Stop',
            'processing_queue':         'Processing Queue',
            'processing_log':           'Processing Log',
            'compact_log':              '📋 Compact Log',
            'upload_opensubtitles':     '📤 Upload OpenSubtitles',
            'shutdown_checkbox':        '💤 Shutdown when done',
            'translation_model_tip':    'Translation model',
            'batch_settings_tip':       'Adaptive Batch Size — memory settings',
            'select_video_files':       'Select video files',
            'select_folder':            'Select folder',
            'add_completed':            '✅ Added:',
            'add_queued':               '➕ Added to queue (processing):',
            'files_via_dragdrop':       'files via drag & drop',
            'confirm_exit':             'Confirm Exit',
            'processing_in_progress':   'Processing is in progress. Are you sure you want to exit?',
            'confirm_stop_title':       'Confirm stop',
            'confirm_stop_text':        'Stop processing and delete temporary files?',
            'stop_requested':           '⏹ Stopping...',
            'error':                    'Error',
            'processing_completed':     '🎉 Processing Completed',
            'all_files_processed':      'All files were processed successfully!',
            'no_preview':               'No preview\navailable',
            'loading_preview':          'Loading\npreview...',
            'profile_label':            'Profile:',
            'remaining_files':          'Remaining files:',
            'srt_language_label':       'SRT Language:',
            'opensubtitles_settings':   'OpenSubtitles — Credentials & Settings',
            'batch_settings_title':     'Adaptive Batch Size — Settings',
            'close':                    'Close',
            'language_label':           '🌐 Language:',
            'language_auto':            'Auto',
            'language_restart_title':   'Language',
            'language_restart_msg':     'Restart the application to apply the new language.',
            'general_settings_title':   'General Settings',
            'general_settings_btn_tip': 'General Settings',
            'general_settings_lang_group': 'Interface Language',
            'settings_dialog_title':    'Settings',
            'settings_tab_general':     'General',
            'settings_tab_transcription': 'Transcription',
            'settings_tab_translation': 'Translation',
            'settings_tab_batch':       'Adaptive Batch',
            'settings_tab_opensubtitles': 'OpenSubtitles',
            'job_options_title':        'Job options',
            'library_scanner_title':    'Library Scanner',
            'app_started':              '🎬 Transcriber Pro started',
            'translation_model_changed':'🌐 Translation model changed: {model}',

            # ── library_scanner_widget ────────────────────────────────────
            'library_scanner_title':    '📡 Library Scanner',
            'refresh':                  'Refresh',
            'search_placeholder':       'Search...',
            'type_filter':              'Type:',
            'all_types':                'All',
            'film_type':                'Film',
            'tv_series_type':           'TV Series',
            'days_filter':              '≥ Days:',
            'all_days':                 'All',
            'file_col':                 'File',
            'type_col':                 'Type',
            'days_col':                 'Days',
            'import_filtered':          'Import All Filtered',
            'waiting_connection':       'Waiting for connection...',
            'config_missing':           'Configuration missing (URL or API Key)',
            'loading':                  'Loading...',
            'already_queued':           'Already in queue',
            'error_status':             'Error: {message}',
            'files_stats':              '{without} without subs / {total} total',
            'files_imported_log':       '📡 Library Scanner: {added} files imported to queue',

            # ── splash_screen ─────────────────────────────────────────────
            'splash_subtitle':          'AI-Powered Video Transcription',
            'splash_credits':           'Powered by Whisper • NLLB • TMDB',
            'init_message':             'Initializing...',
            'loading_ai':               'Loading AI libraries...',
            'checking_gpu':             'Checking GPU...',
            'ready':                    'Ready!',
            'splash_loading_fonts':     'Loading fonts...',
            'splash_loading_theme':     'Applying theme...',
            'splash_checking_models':   'Checking model paths...',
            'splash_loading_window':    'Starting interface...',

            # ── profile_dialog ────────────────────────────────────────────
            'profiles_title':           'Transcription Profiles',
            'profiles_header':          '⚙️ Transcription Profiles',
            'profiles_desc':            'Select the optimal profile for your use case.',
            'cancel':                   '❌ Cancel',
            'confirm':                  '✅ Confirm',
            'recommended':              '⭐ RECOMMENDED',
            'profile_fast_name':        'Maximum Speed',
            'profile_fast_desc':        'Maximum speed for daily use and quick drafts',
            'profile_balanced_name':    'Balanced',
            'profile_balanced_desc':    'Optimal quality/speed balance (RECOMMENDED)',
            'profile_quality_name':     'High Quality',
            'profile_quality_desc':     'High quality for difficult audio or accents',
            'profile_maximum_name':     'Maximum Quality',
            'profile_maximum_desc':     'Maximum quality for critical cases (very slow)',
            'profile_maximum_warning':  'Very slow! Only for individual critical cases',
            'profile_batch_name':       'Fast Batch',
            'profile_batch_desc':       'Optimized for batch processing of many files',
            'profile_batch_warning':    'Monitor temperatures for long processing runs',

            # ── translation_model_dialog ──────────────────────────────────
            'tmd_title':                'Translation Models - Select Engine',
            'tmd_header':               'Translation Model Selection',
            'tmd_subtitle':             'Choose the translation engine for subtitle translation',
            'save_close':               'Save & Close',
            'model_folder_group':       'Model folder (merged_model)',
            'browse':                   'Browse...',
            'save_path':                'Save Path',
            'hf_token_group':           'HuggingFace Token (required)',
            'save_token':               'Save Token',
            'download_aya':             'Download Aya Model',
            'save_api_key':             'Save API Key',
            'save':                     'Save',
            'diarization_title':        '🎭 Speaker Diarization',
            'diarization_desc':         (
                'Identifies who is speaking in each subtitle. '
                'Adds a dash ( - ) at each speaker change, cinema dialogue style.'
            ),
            'forced_alignment_check':   'Forced Alignment (broadcast/cinema precision)',
            'diarization_check':        'Identify speakers (Speaker Diarization)',
            'speakers_label':           'No. of speakers:',
            'auto_speakers':            'auto',
            'speakers_tip':             '0 = automatic detection',
            'tmd_configured':           '✅ Model configured and ready',
            'tmd_not_configured':       '⚠️ Path not configured',
            'tmd_creds_configured':     '✅ Credentials configured',
            'tmd_creds_not_configured': (
                '⚠️ Credentials not configured '
                '(go to Settings > OpenSubtitles)'
            ),
            'path_empty':               'Empty path',
            'folder_not_found':         'Folder not found',
            'folder_invalid':           'Invalid folder',
            'path_saved_title':         'Saved',
            'path_saved_msg':           'Fine-tuned model path saved!',
            'creds_saved_title':        'Credentials Saved',
            'creds_saved_msg':          '✅ Credentials saved successfully.',
            'model_updated_title':      'Model updated',
            'model_updated_msg':        'Translation model changed: {model}',
            'close_btn':                'Close',
            'select_model_folder':      'Select merged_model folder',
            'token_empty':              'Empty token',
            'hf_token_label':           'HuggingFace Token',
            'test_download':            'Test pyannote model download',
            'creds_missing_title':      'Missing fields',
            'creds_missing_text':       'Username and Password are required.',
            'api_key_info_claude':      (
                '⚠️ Get API key from: console.anthropic.com\n'
                '💡 Free tier available with usage limits.\n'
                '🔑 Stored securely in local config.'
            ),
            'api_key_info_openai':      (
                '⚠️ Get API key from: platform.openai.com\n'
                '💡 Requires billing account.\n'
                '🔑 Stored securely in local config.'
            ),
            'os_creds_info':            (
                'OpenSubtitles credentials (username / password / API key)\n'
                'are configured in Settings > OpenSubtitles.'
            ),
            'tmd_error_title':          '⚠️ CRITICAL ERROR',

            # ── widgets (ResourceMonitor) ─────────────────────────────────
            'monitor_title':            '💻 Resource Monitor',
            'cpu_label':                '🔄 CPU:',
            'ram_label':                '🧠 RAM:',
            'gpu_label':                '🎮 GPU:',
            'vram_label':               '💾 VRAM:',
            'network_label':            '🌐 Network',

            # ── opensubtitles_settings_widget ─────────────────────────────
            'os_upload_group':          '📤 OpenSubtitles Upload',
            'os_credentials_group':     '🔑 Credentials',
            'os_username_ph':           'OpenSubtitles Username',
            'os_password_ph':           'Password',
            'os_apikey_ph':             'REST API Key (from opensubtitles.com/consumers)',
            'os_save_creds':            '💾 Save Credentials',
            'os_settings_group':        '⚙️ Settings',
            'os_auto_upload':           'Automatic upload after processing',
            'os_auto_upload_tip':       (
                'Automatically upload after each transcription/translation.\n'
                'If disabled, upload only on manual request.'
            ),
            'os_check_duplicates':      'Check for duplicates before upload',
            'os_check_dup_tip':         (
                'Checks if the subtitle already exists in the database\n'
                'before uploading.'
            ),
            'os_api_method':            'API Method:',
            'os_api_method_tip':        (
                'XML-RPC: classic API (opensubtitles.org) — recommended.\n'
                'REST: new API (opensubtitles.com) — requires API Key.'
            ),
            'os_test_conn':             '🔍 Test Connection',
            'os_test_conn_tip':         'Verify authentication with OpenSubtitles',
            'os_configure':             '⚙️ Configure Credentials',
            'os_configure_tip':         'Open documentation to configure credentials',
            'os_configured':            '✅ System configured and ready for upload',
            'os_account':               '👤 Account: {username}',
            'os_not_configured':        '⚠️ Credentials not configured',
            'os_not_available':         'OpenSubtitles upload is not available.',
            'os_configure_hint':        "💡 Click 'Configure Credentials' to start",
            'os_missing_fields_title':  'Missing fields',
            'os_missing_fields_msg':    'Username and Password are required.',
            'os_creds_saved_title':     'Credentials Saved',
            'os_creds_saved_msg':       '✅ Credentials saved successfully.',
            'os_missing_creds_title':   'Missing Credentials',
            'os_missing_creds_msg':     (
                'OpenSubtitles credentials are not configured.\n'
                'Please configure them first.'
            ),
            'os_testing':               'Testing...',
            'os_test_ok_title':         'Test Successful',
            'os_test_ok_msg':           '✅ Connection and authentication successful!\nYou can now upload subtitles.',
            'os_test_fail_title':       'Test Failed',
            'os_test_fail_msg':         '❌ Authentication failed. Check your credentials.',
            'os_error_title':           'Error',
            'os_error_msg':             '❌ Error during test: {error}',
            'os_guide_title':           'Configuration Guide',

            # ── adaptive_batch_settings_widget ────────────────────────────
            'abs_status_group':         'Status',
            'abs_enable':               'Enable Adaptive Batch Size',
            'abs_enable_tip':           'If disabled, each translator uses its fixed default batch size.',
            'abs_batch_group':          'Batch Size',
            'abs_initial_label':        'Initial size (0=auto):',
            'abs_initial_tip':          (
                '0 = auto-detect from available VRAM.\n'
                '>= 24 GB → 16 | >= 12 GB → 8 | >= 8 GB → 4 | < 8 GB → 2'
            ),
            'abs_min_label':            'Min size:',
            'abs_min_tip':              'Absolute minimum (panic fallback after 3 consecutive OOMs).',
            'abs_max_label':            'Max size:',
            'abs_max_tip':              'Maximum allowed during growth phase.',
            'abs_warmup_group':         'Warm-up & Memory Thresholds',
            'abs_warmup_label':         'Warmup batches:',
            'abs_warmup_tip':           (
                'Number of initial batches in which the system tries to increase\n'
                'the batch size (if memory allows).'
            ),
            'abs_high_thresh':          'High threshold (reduce):',
            'abs_high_tip':             'If VRAM usage > high threshold → reduce batch by 2. Default: 0.85 (85%)',
            'abs_low_thresh':           'Low threshold (increase):',
            'abs_low_tip':              'If VRAM usage < low threshold → increase batch by 1. Default: 0.60 (60%)',
            'abs_note':                 'Changes are applied at the next translation start.',
            'abs_restore_defaults':     'Restore Defaults',
            'abs_save':                 'Save',
            'abs_active_status':        'Active — initial={initial}, min={min}, max={max}, warmup={warmup}',
            'abs_disabled_status':      'Disabled — uses fixed batch size.',
            'abs_autodetect':           'Auto-detect',

            # ── gender correction ─────────────────────────────────────────
            'gender_correction_checkbox': 'Advanced gender correction (LLM)',

            # ── force audio transcription ─────────────────────────────────
            'force_audio_title':        'Force audio transcription',
            'force_audio_checkbox':     'Ignore embedded subtitles and always transcribe from audio',
            'force_audio_info':         'When enabled, the pipeline ignores subtitle tracks already present in the video file and always proceeds with audio transcription. Useful when embedded subtitles are low quality.',

            # ── workers (pipeline log messages) ───────────────────────────
            'worker_start':             '▶️ Starting processing of {n} files',
            'worker_file_header':       '🎬 File {current}/{total}: {filename}',
            'worker_start_single':      '▶️ Starting processing...',
            'worker_completed':         '✅ {filename} completed successfully',
            'worker_cancelled_file':    '⚠️ {filename} cancelled',
            'worker_failed':            '❌ {filename} failed',
            'worker_hint':              '⚠️ Hint: Check the log for details',
            'worker_critical_error':    '❌ Critical error processing {filename}: {error}',
            'worker_cancelled_user':    '\n⚠️ Processing cancelled by user',
            'worker_done_header':       '✅ PROCESSING COMPLETE',
            'worker_stats_completed':   '🎉 Completed: {n}',
            'worker_stats_failed':      '⚠️ Failed: {n}',
            'worker_stats_total':       'Total: {n}',

            # ── sync_dialog / sync_worker ─────────────────────────────────
            'sync_dialog_title':        '🔄 Synchronize SRT',
            'sync_files_group':         'Input Files',
            'sync_video_label':         'Video:',
            'sync_video_ph':            'Select video file...',
            'sync_srt_label':           'External SRT:',
            'sync_srt_ph':              'Select .srt file to synchronize...',
            'sync_browse_video':        'Select video',
            'sync_browse_srt':          'Select SRT file',
            'sync_start':               '▶ Start Synchronization',
            'sync_cancelling':          '⏹ Cancelling...',
            'sync_missing_video':       'Please select a video file.',
            'sync_missing_srt':         'Please select an SRT file.',
            'sync_done_title':          'Synchronization Complete',
            'sync_done_msg':            '✅ File saved:\n{output}',
            'warning':                  'Warning',

            # ── Library Scanner: filtro formato bitmap ────────────────────
            'format_filter':            'Format:',
            'all_formats':              'All',
            'ocr_convert_all':          'Convert all (OCR)',

            # ── OCR Sottotitoli (settings + review) ───────────────────────
            'ocr_section_title':        'Subtitle OCR',
            'ocr_strategy_group':       'Strategy',
            'ocr_strategy_review':      'Targeted review',
            'ocr_strategy_review_comment': 'Automatic OCR on everything; you only review the uncertain lines next to the image. Maximum fidelity, minimal effort.',
            'ocr_strategy_auto':        'Automatic only',
            'ocr_strategy_auto_comment': 'No review: fast but does NOT guarantee 100% fidelity (residual OCR errors possible).',
            'ocr_engine_group':         'OCR',
            'ocr_language_label':       'OCR language:',
            'ocr_language_ph':          'e.g. ita, eng, ita+eng',
            'ocr_language_tip':         'Tesseract language code (e.g. "ita", "eng", "ita+eng").',
            'ocr_conf_threshold_label': 'Confidence threshold:',
            'ocr_conf_threshold_tip':   'Below this threshold a line is flagged for targeted review.',
            'ocr_tesseract_path_label': 'Tesseract path:',
            'ocr_tesseract_path_ph':    'Empty = auto-detect',
            'ocr_tesseract_path_tip':   'Path to the tesseract binary. Leave empty to use the one on the system PATH.',
            'ocr_writeback_group':      'Result write-back',
            'ocr_writeback_label':      'Mode:',
            'ocr_writeback_mux':        'Remux into MKV',
            'ocr_writeback_sidecar':    '.srt file next to the video',
            'ocr_writeback_tip':        'Where to write the produced SRT: as a track in the MKV or as a separate file.',
            'ocr_review_title':         'OCR subtitle review',
            'ocr_review_instruction':   'Check that the text matches the image exactly. No automatic corrections: you decide.',
            'ocr_only_flagged':         'Flagged lines only',
            'ocr_counter':              'Events: {total} · Flagged: {flagged}',
            'ocr_text_label':           'OCR text',
            'ocr_no_image':             'No image',
            'ocr_empty_text':           '(empty)',
            'ocr_confidence':           'Confidence',
            'ocr_toggle_italic':        'Italic',
            'ocr_toggle_italic_tip':    'Wrap the selection (or whole text) in <i>...</i>',
            'ocr_prev':                 'Previous',
            'ocr_next':                 'Next',
            'ocr_verified':             'Verified',
            'ocr_verified_tip':         'Mark as verified and go to the next flagged line',
            'ocr_done':                 'Finish review',
            'ocr_state_verified':       'verified',
            'ocr_state_flagged':        'needs review',
            'ocr_state_ok':             'ok',
        },

        # ── ITALIANO ──────────────────────────────────────────────────────────
        'it': {

            # ── main_window ───────────────────────────────────────────────
            'window_title':             'Transcriber Pro - Trascrizione Video AI',
            'add_files':                '📄 Aggiungi File',
            'add_folder':               '📂 Aggiungi Cartella',
            'clear_queue':              '🗑️ Pulisci',
            'start':                    '▶️ Avvia',
            'stop':                     '⏸️ Ferma',
            'processing_queue':         'Coda di elaborazione',
            'processing_log':           'Log di elaborazione',
            'compact_log':              '📋 Log Sintetico',
            'upload_opensubtitles':     '📤 Upload OpenSubtitles',
            'shutdown_checkbox':        '💤 Spegni al completamento',
            'translation_model_tip':    'Modello di traduzione',
            'batch_settings_tip':       'Adaptive Batch Size — impostazioni memoria',
            'select_video_files':       'Seleziona file video',
            'select_folder':            'Seleziona cartella',
            'add_completed':            '✅ Aggiunto:',
            'add_queued':               '➕ Aggiunto alla coda (in elaborazione):',
            'files_via_dragdrop':       'file tramite drag & drop',
            'confirm_exit':             'Conferma uscita',
            'processing_in_progress':   'Elaborazione in corso. Sei sicuro di voler uscire?',
            'confirm_stop_title':       'Conferma interruzione',
            'confirm_stop_text':        "Interrompere l'elaborazione e cancellare i file temporanei?",
            'stop_requested':           '⏹ Interruzione in corso...',
            'error':                    'Errore',
            'processing_completed':     '🎉 Elaborazione Completata',
            'all_files_processed':      'Tutti i file sono stati elaborati correttamente!',
            'no_preview':               'Nessuna anteprima\ndisponibile',
            'loading_preview':          'Caricamento\nanteprima...',
            'profile_label':            'Profilo:',
            'remaining_files':          'File rimanenti:',
            'srt_language_label':       'Lingua SRT:',
            'opensubtitles_settings':   'OpenSubtitles — Credenziali e Impostazioni',
            'batch_settings_title':     'Adaptive Batch Size — Impostazioni',
            'close':                    'Chiudi',
            'language_label':           '🌐 Lingua:',
            'language_auto':            'Auto',
            'language_restart_title':   'Lingua',
            'language_restart_msg':     'Riavvia l\'applicazione per applicare la nuova lingua.',
            'general_settings_title':   'Impostazioni generali',
            'general_settings_btn_tip': 'Impostazioni generali',
            'general_settings_lang_group': 'Lingua interfaccia',
            'settings_dialog_title':    'Impostazioni',
            'settings_tab_general':     'Generali',
            'settings_tab_transcription': 'Trascrizione',
            'settings_tab_translation': 'Traduzione',
            'settings_tab_batch':       'Batch Adattivo',
            'settings_tab_opensubtitles': 'OpenSubtitles',
            'job_options_title':        'Opzioni job',
            'library_scanner_title':    'Library Scanner',
            'app_started':              '🎬 Transcriber Pro avviato',
            'translation_model_changed':'🌐 Modello traduzione cambiato: {model}',

            # ── library_scanner_widget ────────────────────────────────────
            'library_scanner_title':    '📡 Library Scanner',
            'refresh':                  'Aggiorna',
            'search_placeholder':       'Cerca...',
            'type_filter':              'Tipo:',
            'all_types':                'Tutti',
            'film_type':                'Film',
            'tv_series_type':           'Serie TV',
            'days_filter':              '≥ Giorni:',
            'all_days':                 'Tutti',
            'file_col':                 'File',
            'type_col':                 'Tipo',
            'days_col':                 'Giorni',
            'import_filtered':          'Importa Tutti i Filtrati',
            'waiting_connection':       'In attesa di connessione...',
            'config_missing':           'Configurazione mancante (URL o API Key)',
            'loading':                  'Caricamento...',
            'already_queued':           'Già in coda',
            'error_status':             'Errore: {message}',
            'files_stats':              '{without} senza sub / {total} totali',
            'files_imported_log':       '📡 Library Scanner: {added} file importati nella coda',

            # ── splash_screen ─────────────────────────────────────────────
            'splash_subtitle':          'AI-Powered Video Transcription',
            'splash_credits':           'Powered by Whisper • NLLB • TMDB',
            'init_message':             'Inizializzazione...',
            'loading_ai':               'Caricamento librerie AI...',
            'checking_gpu':             'Verifica GPU...',
            'ready':                    'Pronto!',
            'splash_loading_fonts':     'Caricamento font...',
            'splash_loading_theme':     'Applicazione tema...',
            'splash_checking_models':   'Verifica percorsi modelli...',
            'splash_loading_window':    'Avvio interfaccia...',

            # ── profile_dialog ────────────────────────────────────────────
            'profiles_title':           'Profili Trascrizione',
            'profiles_header':          '⚙️ Profili di Trascrizione',
            'profiles_desc':            'Seleziona il profilo ottimale per il tuo caso d\'uso.',
            'cancel':                   '❌ Annulla',
            'confirm':                  '✅ Conferma',
            'recommended':              '⭐ RACCOMANDATO',
            'profile_fast_name':        'Velocità Massima',
            'profile_fast_desc':        'Massima velocità per uso quotidiano e draft rapidi',
            'profile_balanced_name':    'Bilanciato',
            'profile_balanced_desc':    'Bilanciamento ottimale qualità/velocità (RACCOMANDATO)',
            'profile_quality_name':     'Alta Qualità',
            'profile_quality_desc':     'Alta qualità per audio difficile o accenti',
            'profile_maximum_name':     'Qualità Massima',
            'profile_maximum_desc':     'Qualità massima per casi critici (molto lento)',
            'profile_maximum_warning':  'Molto lento! Solo per casi critici singoli',
            'profile_batch_name':       'Batch Rapido',
            'profile_batch_desc':       'Ottimizzato per elaborazione batch di molti file',
            'profile_batch_warning':    'Monitora temperature per elaborazioni lunghe',

            # ── translation_model_dialog ──────────────────────────────────
            'tmd_title':                'Modelli di Traduzione - Seleziona Motore',
            'tmd_header':               'Selezione Modello di Traduzione',
            'tmd_subtitle':             'Scegli il motore di traduzione per i sottotitoli',
            'save_close':               'Salva e Chiudi',
            'model_folder_group':       'Cartella modello (merged_model)',
            'browse':                   'Sfoglia...',
            'save_path':                'Salva percorso',
            'hf_token_group':           'HuggingFace Token (richiesto)',
            'save_token':               'Salva Token',
            'download_aya':             'Scarica Modello Aya',
            'save_api_key':             'Salva API Key',
            'save':                     'Salva',
            'diarization_title':        '🎭 Speaker Diarization',
            'diarization_desc':         (
                'Identifica chi parla in ogni sottotitolo. '
                'Aggiunge un trattino ( - ) al cambio di parlante, stile dialogo cinema.'
            ),
            'forced_alignment_check':   'Forced Alignment (precisione broadcast/cinema)',
            'diarization_check':        'Identifica parlanti (Speaker Diarization)',
            'speakers_label':           'N° parlanti:',
            'auto_speakers':            'auto',
            'speakers_tip':             '0 = rilevamento automatico',
            'tmd_configured':           '✅ Modello configurato e pronto',
            'tmd_not_configured':       '⚠️ Percorso non configurato',
            'tmd_creds_configured':     '✅ Credenziali configurate',
            'tmd_creds_not_configured': (
                '⚠️ Credenziali non configurate '
                '(vai in Impostazioni > OpenSubtitles)'
            ),
            'path_empty':               'Percorso vuoto',
            'folder_not_found':         'Cartella non trovata',
            'folder_invalid':           'Cartella non valida',
            'path_saved_title':         'Salvato',
            'path_saved_msg':           'Percorso modello fine-tuned salvato!',
            'creds_saved_title':        'Credenziali Salvate',
            'creds_saved_msg':          '✅ Credenziali salvate correttamente.',
            'model_updated_title':      'Modello aggiornato',
            'model_updated_msg':        'Modello di traduzione cambiato: {model}',
            'close_btn':                'Chiudi',
            'select_model_folder':      'Seleziona cartella merged_model',
            'token_empty':              'Token vuoto',
            'hf_token_label':           'HuggingFace Token',
            'test_download':            'Testa download modello pyannote',
            'creds_missing_title':      'Campi mancanti',
            'creds_missing_text':       'Username e Password sono obbligatori.',
            'api_key_info_claude':      (
                '⚠️ Ottieni API key da: console.anthropic.com\n'
                '💡 Free tier disponibile con limiti di utilizzo.\n'
                '🔑 Salvata in modo sicuro nella config locale.'
            ),
            'api_key_info_openai':      (
                '⚠️ Ottieni API key da: platform.openai.com\n'
                '💡 Richiede account con fatturazione attiva.\n'
                '🔑 Salvata in modo sicuro nella config locale.'
            ),
            'os_creds_info':            (
                'Le credenziali OpenSubtitles (username / password / API key)\n'
                'si configurano nella scheda Impostazioni > OpenSubtitles.'
            ),
            'tmd_error_title':          '⚠️ ERRORE CRITICO',

            # ── widgets (ResourceMonitor) ─────────────────────────────────
            'monitor_title':            '💻 Monitor Risorse',
            'cpu_label':                '🔄 CPU:',
            'ram_label':                '🧠 RAM:',
            'gpu_label':                '🎮 GPU:',
            'vram_label':               '💾 VRAM:',
            'network_label':            '🌐 Rete',

            # ── opensubtitles_settings_widget ─────────────────────────────
            'os_upload_group':          '📤 OpenSubtitles Upload',
            'os_credentials_group':     '🔑 Credenziali',
            'os_username_ph':           'Username OpenSubtitles',
            'os_password_ph':           'Password',
            'os_apikey_ph':             'REST API Key (da opensubtitles.com/consumers)',
            'os_save_creds':            '💾 Salva Credenziali',
            'os_settings_group':        '⚙️ Impostazioni',
            'os_auto_upload':           'Upload automatico al termine elaborazione',
            'os_auto_upload_tip':       (
                'Esegui automaticamente l\'upload dopo ogni trascrizione/traduzione.\n'
                'Se disabilitato, upload solo su richiesta manuale.'
            ),
            'os_check_duplicates':      'Verifica duplicati prima dell\'upload',
            'os_check_dup_tip':         (
                'Controlla se il sottotitolo esiste già nel database\n'
                'prima di effettuare l\'upload.'
            ),
            'os_api_method':            'Metodo API:',
            'os_api_method_tip':        (
                'XML-RPC: API classica (opensubtitles.org) — consigliata.\n'
                'REST: nuova API (opensubtitles.com) — richiede API Key.'
            ),
            'os_test_conn':             '🔍 Test Connessione',
            'os_test_conn_tip':         'Verifica autenticazione con OpenSubtitles',
            'os_configure':             '⚙️ Configura Credenziali',
            'os_configure_tip':         'Apri documentazione per configurare credenziali',
            'os_configured':            '✅ Sistema configurato e pronto per l\'upload',
            'os_account':               '👤 Account: {username}',
            'os_not_configured':        '⚠️ Credenziali non configurate',
            'os_not_available':         'L\'upload su OpenSubtitles non è disponibile.',
            'os_configure_hint':        "💡 Clicca 'Configura Credenziali' per iniziare",
            'os_missing_fields_title':  'Campi mancanti',
            'os_missing_fields_msg':    'Username e Password sono obbligatori.',
            'os_creds_saved_title':     'Credenziali Salvate',
            'os_creds_saved_msg':       '✅ Credenziali salvate correttamente.',
            'os_missing_creds_title':   'Credenziali Mancanti',
            'os_missing_creds_msg':     (
                'Le credenziali OpenSubtitles non sono configurate.\n'
                'Configurale prima di procedere.'
            ),
            'os_testing':               'Test in corso...',
            'os_test_ok_title':         'Test Riuscito',
            'os_test_ok_msg':           '✅ Connessione e autenticazione riuscite!\nPuoi ora effettuare upload.',
            'os_test_fail_title':       'Test Fallito',
            'os_test_fail_msg':         '❌ Autenticazione fallita. Verifica le credenziali.',
            'os_error_title':           'Errore',
            'os_error_msg':             '❌ Errore durante il test: {error}',
            'os_guide_title':           'Guida Configurazione',

            # ── adaptive_batch_settings_widget ────────────────────────────
            'abs_status_group':         'Stato',
            'abs_enable':               'Abilita Adaptive Batch Size',
            'abs_enable_tip':           'Se disabilitato, ogni traduttore usa il batch size fisso predefinito.',
            'abs_batch_group':          'Batch Size',
            'abs_initial_label':        'Initial size (0=auto):',
            'abs_initial_tip':          (
                '0 = auto-detect dalla VRAM disponibile.\n'
                '>= 24 GB → 16 | >= 12 GB → 8 | >= 8 GB → 4 | < 8 GB → 2'
            ),
            'abs_min_label':            'Min size:',
            'abs_min_tip':              'Minimo assoluto (panic fallback dopo 3 OOM consecutivi).',
            'abs_max_label':            'Max size:',
            'abs_max_tip':              'Massimo consentito durante la fase di crescita.',
            'abs_warmup_group':         'Warm-up e Soglie Memoria',
            'abs_warmup_label':         'Warmup batches:',
            'abs_warmup_tip':           (
                'Numero di batch iniziali in cui il sistema prova ad aumentare\n'
                'il batch size (se la memoria lo consente).'
            ),
            'abs_high_thresh':          'Soglia alta (riduci):',
            'abs_high_tip':             'Se utilizzo VRAM > soglia alta → riduci batch di 2. Default: 0.85 (85%)',
            'abs_low_thresh':           'Soglia bassa (aumenta):',
            'abs_low_tip':              'Se utilizzo VRAM < soglia bassa → aumenta batch di 1. Default: 0.60 (60%)',
            'abs_note':                 'Le modifiche sono applicate al prossimo avvio della traduzione.',
            'abs_restore_defaults':     'Ripristina Default',
            'abs_save':                 'Salva',
            'abs_active_status':        'Attivo — initial={initial}, min={min}, max={max}, warmup={warmup}',
            'abs_disabled_status':      'Disabilitato — usa batch size fisso dei modelli.',
            'abs_autodetect':           'Auto-detect',

            # ── gender correction ─────────────────────────────────────────
            'gender_correction_checkbox': 'Correzione genere avanzata (LLM)',

            # ── force audio transcription ─────────────────────────────────
            'force_audio_title':        'Forza trascrizione da audio',
            'force_audio_checkbox':     'Ignora sottotitoli embedded e trascrivi sempre dall\'audio',
            'force_audio_info':         'Se attivata, la pipeline ignora le tracce di sottotitoli già presenti nel file video e procede sempre con trascrizione dall\'audio. Utile quando i sottotitoli embedded sono di bassa qualità.',

            # ── workers (pipeline log messages) ───────────────────────────
            'worker_start':             '▶️ Avvio elaborazione di {n} file',
            'worker_file_header':       '🎬 File {current}/{total}: {filename}',
            'worker_start_single':      '▶️ Avvio elaborazione...',
            'worker_completed':         '✅ {filename} completato con successo',
            'worker_cancelled_file':    '⚠️ {filename} annullato',
            'worker_failed':            '❌ {filename} fallito',
            'worker_hint':              '⚠️ Suggerimento: Controlla il log per dettagli',
            'worker_critical_error':    '❌ Errore critico elaborazione {filename}: {error}',
            'worker_cancelled_user':    '\n⚠️ Elaborazione annullata dall\'utente',
            'worker_done_header':       '✅ ELABORAZIONE COMPLETATA',
            'worker_stats_completed':   '🎉 Completati: {n}',
            'worker_stats_failed':      '⚠️ Falliti: {n}',
            'worker_stats_total':       'Totale: {n}',

            # ── sync_dialog / sync_worker ─────────────────────────────────
            'sync_dialog_title':        '🔄 Sincronizza SRT',
            'sync_files_group':         'File di Input',
            'sync_video_label':         'Video:',
            'sync_video_ph':            'Seleziona file video...',
            'sync_srt_label':           'SRT Esterno:',
            'sync_srt_ph':              'Seleziona file .srt da sincronizzare...',
            'sync_browse_video':        'Seleziona video',
            'sync_browse_srt':          'Seleziona file SRT',
            'sync_start':               '▶ Avvia Sincronizzazione',
            'sync_cancelling':          '⏹ Annullamento in corso...',
            'sync_missing_video':       'Seleziona un file video.',
            'sync_missing_srt':         'Seleziona un file SRT.',
            'sync_done_title':          'Sincronizzazione Completata',
            'sync_done_msg':            '✅ File salvato:\n{output}',
            'warning':                  'Avviso',

            # ── Library Scanner: filtro formato bitmap ────────────────────
            'format_filter':            'Formato:',
            'all_formats':              'Tutti',
            'ocr_convert_all':          'Converti tutti (OCR)',

            # ── OCR Sottotitoli (settings + review) ───────────────────────
            'ocr_section_title':        'OCR Sottotitoli',
            'ocr_strategy_group':       'Strategia',
            'ocr_strategy_review':      'Revisione mirata',
            'ocr_strategy_review_comment': 'OCR automatico su tutto; verifichi solo le righe incerte accanto all\'immagine. Massima fedeltà, sforzo minimo.',
            'ocr_strategy_auto':        'Solo automatico',
            'ocr_strategy_auto_comment': 'Nessuna revisione: veloce ma NON garantisce fedeltà 100% (errori OCR residui possibili).',
            'ocr_engine_group':         'OCR',
            'ocr_language_label':       'Lingua OCR:',
            'ocr_language_ph':          'es. ita, eng, ita+eng',
            'ocr_language_tip':         'Codice lingua Tesseract (es. "ita", "eng", "ita+eng").',
            'ocr_conf_threshold_label': 'Soglia confidenza:',
            'ocr_conf_threshold_tip':   'Sotto questa soglia la riga viene segnalata per la revisione mirata.',
            'ocr_tesseract_path_label': 'Path Tesseract:',
            'ocr_tesseract_path_ph':    'Vuoto = rilevamento automatico',
            'ocr_tesseract_path_tip':   'Percorso al binario tesseract. Lascia vuoto per usare quello nel PATH di sistema.',
            'ocr_writeback_group':      'Scrittura risultato',
            'ocr_writeback_label':      'Modalità:',
            'ocr_writeback_mux':        'Rimuxa nell\'MKV',
            'ocr_writeback_sidecar':    'File .srt accanto al video',
            'ocr_writeback_tip':        'Dove scrivere l\'SRT prodotto: come traccia nell\'MKV oppure come file separato.',
            'ocr_review_title':         'Revisione OCR sottotitoli',
            'ocr_review_instruction':   'Verifica che il testo corrisponda esattamente all\'immagine. Nessuna correzione automatica: decidi tu.',
            'ocr_only_flagged':         'Solo righe dubbie',
            'ocr_counter':              'Eventi: {total} · Dubbi: {flagged}',
            'ocr_text_label':           'Testo OCR',
            'ocr_no_image':             'Nessuna immagine',
            'ocr_empty_text':           '(vuoto)',
            'ocr_confidence':           'Confidenza',
            'ocr_toggle_italic':        'Corsivo',
            'ocr_toggle_italic_tip':    'Avvolge la selezione (o l\'intero testo) in <i>...</i>',
            'ocr_prev':                 'Precedente',
            'ocr_next':                 'Successivo',
            'ocr_verified':             'Verificato',
            'ocr_verified_tip':         'Marca come verificato e passa al prossimo dubbio',
            'ocr_done':                 'Fine revisione',
            'ocr_state_verified':       'verificato',
            'ocr_state_flagged':        'da rivedere',
            'ocr_state_ok':             'ok',
        },
    }

    def __init__(self):
        self.current_language = self._detect_language()

    def _detect_language(self) -> str:
        """
        Rileva la lingua del sistema operativo.
        Priorità: QLocale.system() → locale.getlocale() → variabili d'ambiente → 'en'
        """
        # 1. QLocale (migliore per Qt su Win+Linux, disponibile solo dopo QApplication)
        try:
            from PyQt6.QtCore import QLocale, QCoreApplication
            if QCoreApplication.instance() is not None:
                if QLocale.system().name().lower().startswith('it'):
                    return 'it'
        except Exception:
            pass

        # 2. locale module (fallback Python, funziona senza Qt)
        try:
            import locale
            loc = locale.getlocale()[0] or ''
            if loc.lower().startswith('it'):
                return 'it'
        except Exception:
            pass

        # 3. Variabili d'ambiente (Linux/macOS)
        for var in ('LANG', 'LANGUAGE', 'LC_ALL', 'LC_MESSAGES'):
            if os.environ.get(var, '').lower().startswith('it'):
                return 'it'

        return 'en'

    def get(self, key: str) -> str:
        """Restituisce la traduzione per la chiave data.
        Se la chiave non esiste, ritorna la chiave stessa (nessun crash)."""
        return self.TEXTS.get(self.current_language, self.TEXTS['en']).get(key, key)

    def set_language(self, lang_code: str):
        """Imposta manualmente la lingua."""
        if lang_code in self.TEXTS:
            self.current_language = lang_code


# ── Singleton globale ─────────────────────────────────────────────────────────

_translations = Translations()


def get_text(key: str) -> str:
    """Restituisce la traduzione per la chiave data."""
    return _translations.get(key)


# Alias breve usato da tutti i file GUI: from utils.translations import tr
tr = get_text


def get_translations() -> Translations:
    """Restituisce l'istanza singleton."""
    return _translations


def init_language(config) -> None:
    """
    Inizializza la lingua in base alla preferenza salvata nel config.
    Da chiamare in main.py DOPO QApplication(), PRIMA di MainWindow().

    Args:
        config: istanza ProfileConfig con metodo .get(key, default)
    """
    lang_pref = config.get('language', 'auto')
    if lang_pref in ('it', 'en'):
        _translations.set_language(lang_pref)
    else:
        # 'auto': rileva con QLocale (ora disponibile perché QApplication esiste)
        _translations.current_language = _translations._detect_language()
