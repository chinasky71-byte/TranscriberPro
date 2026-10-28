"""
Configuration Manager - COMPLETE VERSION WITH PROFILES SYSTEM
File: utils/config.py

VERSIONE: v4.3 - RIMOZIONE AYA, MIGRAZIONE A 'llm'

MODIFICHE v4.3:
- Rimossi i modelli Aya. 'translation_model' accetta ora 'llm' al loro posto,
  e il valore storico 'aya' viene migrato automaticamente alla lettura.
- Rimosse le chiavi e i metodi 'aya_model_path' / 'aya_model_download_status',
  che nessuno chiamava piu (e il flag risultava True col modello NON in cache).
- Rimossa la definizione DUPLICATA di get/set_translation_model: la seconda
  copia, senza validazione, sovrascriveva silenziosamente la prima.
- Nuova chiave 'llm_translator_model' (default 'translategemma-12b').

MODIFICHE v4.1:
- Supporto Token HuggingFace per i modelli gated
"""

import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .subtitle_uploader_interface import OPENSUBTITLES_USER_AGENT
from .platform_compat import is_foreign_windows_path

logger = logging.getLogger(__name__)

# Import necessario per delegare la logica dei profili
try:
    from .transcription_profiles import ProfileConfig, TranscriptionProfile
except ImportError as e:
    print(f"⚠️ Import ProfileConfig fallito: {e} - uso MOCK")
    # Fallback per evitare crash se il modulo non è ancora caricato
    class ProfileConfig:
        @staticmethod
        def get_profile_config(profile): return {'name': profile, 'num_workers': 0, 'beam_size': 0}
        @staticmethod
        def from_string(profile_str):
            if profile_str == 'balanced': return 'balanced'
            return 'fast' 
    class TranscriptionProfile:
        BALANCED = 'balanced'


ENGINE_MODE = 'qwen3'
LEGACY_ENGINE_MODE = 'auto'


class Config:
    """Gestisce configurazione e preferenze utente"""

    # TP_DATA_DIR lets containers and the WebUI keep config/logs outside the home.
    CONFIG_DIR = (Path(os.environ['TP_DATA_DIR']).expanduser()
                  if os.environ.get('TP_DATA_DIR') else Path.home() / '.transcriberpro')
    CONFIG_FILE = CONFIG_DIR / 'config.json'
    
    # Default settings
    DEFAULTS = {
        # General settings
        'use_gpu': True,
        'language': 'auto',
        # Roots accepted by the WebUI for media paths (empty = the user's home).
        'allowed_media_roots': [],
        # Folder the WebUI file picker opens on (empty = the first allowed
        # root). It must stay under an allowed root to be usable.
        'picker_start_dir': '',
        # Glossario a resa fissa senza TMDB (nessuna chiave): nome della serie,
        # es. 'monster-2022' -> ~/.transcriberpro/glossary/manual_monster-2022.json
        'glossary_id': '',
        'last_input_folder': '',
        'shutdown_after_processing': False,
        
        # OpenSubtitles Upload Settings.
        # ATTENZIONE: opensubtitles.org (XML-RPC) e opensubtitles.com (REST)
        # sono DUE ACCOUNT SEPARATI con credenziali proprie, anche se il
        # nome utente coincide — non è garantito che coincida anche la
        # password. Da qui i due set di credenziali distinti sotto.
        'opensubtitles_upload_enabled': True,
        # Credenziali .com (REST + traduttore "OpenSubtitles AI")
        'opensubtitles_username': '',
        'opensubtitles_password': '',
        'opensubtitles_api_key': '',
        # Credenziali .org (XML-RPC)
        'opensubtitles_xmlrpc_username': '',
        'opensubtitles_xmlrpc_password': '',
        'opensubtitles_user_agent': OPENSUBTITLES_USER_AGENT,
        # 'xmlrpc': la REST API v1 non ha oggi un upload abilitato per i
        # consumer normali (l'endpoint esiste ma risponde 403
        # "uploads_not_enabled" finché OpenSubtitles non lo whitelista su
        # richiesta) — XML-RPC resta l'unica via realmente funzionante,
        # purché configurato con le credenziali .org (non quelle .com).
        'opensubtitles_preferred_implementation': 'xmlrpc',

        # Transcription method
        'transcription_method': 'faster-whisper',

        # Sistema multi-engine trascrizione (routing automatico per lingua)
        'transcription_engine_mode': 'qwen3',   # ADR-008: 'qwen3' e basta; 'auto' resta un alias
        'qwen3_enabled': True,                 # Qwen3-ASR-1.7B + ForcedAligner-0.6B
        'qwen3_asr_model_id': 'Qwen/Qwen3-ASR-1.7B',
        'qwen3_aligner_model_id': 'Qwen/Qwen3-ForcedAligner-0.6B',
        # v1.29.0 (core/qwen3_lang_retry.py, trovato su X Factor 28-29/09/2026): i chunk
        # "sospetti" (vuoti, poche parole rispetto alla voce presente, o pieni di parole
        # inglesi pur forzati in un'altra lingua — tipico di canzoni/citazioni in inglese
        # dentro un audio di un'altra lingua) vengono ritrascritti con rilevamento lingua e
        # tenuti solo se la lingua rilevata e' diversa, allineabile e accettata. Verificato
        # su 9 clip reali: recupera il canto inglese, 0 rumore fuori dai chunk toccati.
        'qwen3_lang_retry_enabled': True,
        # Solo l'inglese e' validato (il LID su rumore/applausi puo' allucinare altre
        # lingue: v. docstring del modulo). Vuota o rimossa la chiave = ['en'].
        'qwen3_lang_retry_accept_langs': ['en'],
        # v1.30.0 (core/whisper_lang_retry.py): stessa correzione per Faster-Whisper, attiva SOLO quando la
        # lingua e' forzata (mai in auto-detect). Utile soprattutto quando l'utente forza Faster-Whisper dal
        # menu del motore (Impostazioni > Profilo) al posto di Qwen3. Esamina anche i VUOTI fra i segmenti
        # (il VAD di Whisper spesso non rileva affatto il canto) e li divide in sotto-finestre se lunghi.
        'whisper_lang_retry_enabled': True,
        'whisper_lang_retry_accept_langs': ['en'],
        # Pulizia della cache modelli (HF/torch) a fine coda: v. utils/cache_cleaner.py. I modelli dei motori
        # configurati sono comunque preservati; False = non cancella nulla.
        'model_cache_cleanup_enabled': True,
        # Sostituisce nell'MKV la traccia dichiarata italiana ma con testo straniero con il sidecar italiano.
        'replace_mislabeled_italian_track': True,
        # Opzione job: incorpora nel MKV il sottotitolo creato (il sidecar resta accanto al video).
        'mux_subtitle_into_video': False,
        # faster-whisper: divide i segmenti lunghi sui confini di frase invece che a
        # 80 caratteri / 6 s (core/whisper_sentence_split.py). Blocchi a meta' frase
        # 37-47% -> 6-11%, parole identiche. False = comportamento precedente.
        'whisper_split_sentence_aware': True,
        # Lingue in cui lo split per frasi e' attivo (codici a 2 lettere): inglese (3 campioni + 2
        # di conferma), italiano (regole proprie, confermate su 2 set di file interi, soprattutto
        # film doppiati) e francese (v1.27.0: regole proprie; conferma su 9 film "non vincente" per
        # il criterio che conta anche i tagli su virgola, tagli senza punteggiatura 41,6% -> 2,1%;
        # acceso per scelta dell'utente) e tedesco (v1.28.0: regole proprie; conferma su 8 film: tagli senza
        # punteggiatura ne' congiunzione 37,0% -> 2,7%, "non vincente" per un sotto-criterio di densita'; acceso per
        # scelta dell'utente) e spagnolo (v1.29.0: regole proprie; nessuna conferma su file interi ancora fatta,
        # ma acceso insieme al passaggio a Whisper per lo spagnolo — scelta dell'utente 29/09/2026: coi blocchi
        # nativi di Whisper i tagli senza punteggiatura erano al 37,7%). Le altre lingue usano lo split originale.
        'whisper_split_sentence_langs': ['en', 'it', 'fr', 'de', 'es'],
        # Versione della lista sopra gia' applicata a questa config (migrazione una tantum in load()).
        'whisper_split_sentence_langs_rev': 4,

        # FFmpeg whisper settings (solo se transcription_method == 'ffmpeg')
        'ffmpeg_model_path': '',
        'ffmpeg_queue_size': 30,
        
        # Whisper model configuration
        # VAD di faster-whisper (default = comportamento storico). Alzare la soglia
        # taglia il parlato debole: misurato su una reference umana, v.
        # docs/benchmarks/2026-10-26-asr-reference-clip-a.md
        # Preload di Whisper prima di Demucs: 'always' = comportamento storico
        # (inizializza ctranslate2 a contesto CUDA vergine, evita un abort in
        # caso di fallback tardivo); 'auto' = solo se l'engine pianificato E'
        # faster-whisper (nessuno spreco con qwen3/canary).
        # Modello Whisper specializzato per lingua (ISO 639-1). In modalita' 'auto' queste
        # lingue vanno su faster-whisper con il modello indicato invece che su Qwen3/Canary.
        # Valore: id HF ("utente/repo"), id HF con sottocartella ("utente/repo/sottocartella")
        # o percorso locale di una cartella CTranslate2. Se il caricamento fallisce si usa
        # 'whisper_model'. fr: misura del 28/09/2026 (mt_eval/asr_fr/RESULT.md); de: scelta
        # dell'utente, NON misurata. es: misura del 29/09/2026 (mt_eval/asr_es/RESULT.md) —
        # Whisper large-v3 pari a Qwen3 sul riconoscimento ma piu' veloce, meno VRAM, meno
        # invenzioni, e coi blocchi molto migliori con lo split per frasi spagnolo; nessuno dei
        # candidati nuovi (Canary-1B-v2, Cohere Transcribe, HiTZ) ha superato la soglia della
        # regola. 'large-v3' = il modello Whisper standard, NON uno specializzato: qui la voce
        # serve solo a instradare lo spagnolo su faster-whisper invece che su Qwen3.
        'whisper_device': 'auto',
        'whisper_compute_type': 'auto',
        
        # Sistema profili dinamici trascrizione.
        # Decisione 02/10/2026: Whisper sempre a Qualita' Massima (Qwen3 e Canary non
        # ne traggono vantaggio: il profilo cambia solo il batch). Con
        # 'transcription_profile_locked' True get_transcription_profile() restituisce
        # sempre 'maximum' e la scelta dell'utente e' ignorata; per riattivare i profili
        # basta impostarlo a False nel config.json (la chiave viene scritta al primo salvataggio;
        # il codice dei profili e la GUI sono solo nascosti).
        'transcription_profile': 'maximum',
        'transcription_profile_locked': True,

        # Adaptive Batch Size
        'adaptive_batch_enabled': True,
        'adaptive_batch_initial_size': 0,   # 0 = auto-detect
        'adaptive_batch_max_size': 24,
        'adaptive_batch_min_size': 1,
        'adaptive_batch_warmup_batches': 5,
        'adaptive_batch_high_threshold': 0.85,
        'adaptive_batch_low_threshold': 0.60,
        
        # ========================================================================
        # Translation Model Settings (MODIFICATO v5.0 - Claude API Support)
        # ========================================================================
        'translation_model': 'translategemma-12b-gguf',  # vedi VALID_TRANSLATION_MODELS
        # Traduzione considerata FALLITA se la percentuale di blocchi che
        # restano nella lingua di partenza supera questo valore (0-100).
        # 80 = molto permissivo: serve a intercettare i fallimenti sistemici
        # (es. tutti i batch saltati per un errore GPU) senza bocciare un
        # film per poche righe. Abbassarlo rende il criterio piu' severo.
        'translation_max_untranslated_pct': 80.0,
        'target_language': 'ita',     # ISO 639-2 lingua target sottotitoli

        # LEGACY — chiavi dei motori cloud rimossi con ADR-009. Nessun motore
        # le legge: restano solo perche' la GUI Qt congelata
        # (gui/translation_model_dialog.py) le scrive ancora, e per non
        # perdere il valore gia' salvato in un config.json esistente.
        # Claude API (cloud-based translation)
        'claude_api_key': '',  # API key Anthropic per Claude

        # OpenAI API (cloud-based translation)
        'openai_api_key': '',
        'openai_model': 'gpt-4o-mini',
        
        # Traduttore LLM locale: quale modello occupa lo slot. Le chiavi
        # 'aya_model_path' e 'aya_model_download_status' sono state rimosse il
        # 2026-08-18 insieme ai modelli Aya; restano innocue nelle config
        # esistenti, semplicemente non le legge piu nessuno.
        'llm_translator_model': 'translategemma-12b',
        # Cartella di un adattatore LoRA. ADR-009: i pesi GGUF sono gia' fusi e
        # il percorso transformers non esiste piu', quindi questo valore non
        # viene piu' applicato — il traduttore lo dice nel log se lo trova
        # impostato, invece di ignorarlo in silenzio. La chiave resta perche'
        # la Qt (congelata) la scrive.
        'llm_translator_adapter': '',
        # Cartella locale dei pesi. ADR-009: il percorso di produzione e' il
        # GGUF, quindi questa chiave vale come ALTERNATIVA a
        # `llm_translator_gguf_dir` (la Qt congelata fa scegliere da qui).
        'llm_translator_model_path': '',
        # Pesi GGUF del traduttore (TranslateGemma quantizzato, llama.cpp):
        # l'unico motore di traduzione (ADR-009).
        'llm_translator_gguf_dir': '',          # vuoto = models/translategemma-12b-gguf
        'llm_translator_gguf_quant': 'Q4_K_M',  # Q4_K_M | Q3_K_M | IQ3_M (niente piu' 'auto': vedi utils/gguf_quant.py)
        'llm_translator_gguf_parallel': 4,      # sequenze decodificate insieme (KV cache = parallel x 512 token)
        
        # NLLB model
        'nllb_model_path': '',  # Vuoto usa default HuggingFace
        'nllb_finetuned_model_path': '',  # Path al modello NLLB fine-tuned locale
        
        # HuggingFace token (per i modelli gated)
        'huggingface_token': '',

        # Speaker Diarization (pyannote.audio)
        'enable_diarization': False,
        'diarization_num_speakers': 0,   # 0 = auto-detect. ATTENZIONE: >0 = numero ESATTO (non un tetto) e disattiva la soglia di clustering

        # Stile dialoghi professionale (trattini Netflix su cambio parlante):
        # attiva automaticamente la diarization per ogni trascrizione e la
        # formattazione SubtitleFormatter (richiede token HuggingFace)
        'dialogue_style_enabled': True,

        # A/B diarization (v. piano_fix_pipeline_trascrizione punto A).
        # 'diarization_audio_source' e gli altri override restano al
        # comportamento storico; 'diarization_clustering_threshold' è stato
        # PROMOSSO A DEFAULT DI PRODOTTO l'08/09/2026 dopo una campagna di
        # taratura con 50 coppie etichettate a mano su un film (Goodrich
        # 2024): riduce nettamente il sovra-clustering (27→12 "parlanti").
        # Nota onesta: il segnale statistico sulla singola metrica
        # aggregata era debole (differenza non significativa a un test
        # esatto su un campione di quella taglia) — la decisione di
        # tenerlo è stata presa consapevolmente dall'utente, non perché il
        # dato fosse schiacciante. SE EMERGONO SINTOMI DI SOVRA-FUSIONE
        # (personaggi diversi assegnati allo stesso speaker, meno "parlanti"
        # del previsto) su film futuri, riconsiderare per primo QUESTO
        # valore — non è stato validato oltre un singolo film/genere.
        # Pipeline pyannote da usare. Default = 3.1, il comportamento
        # storico e l'unico su cui 'diarization_clustering_threshold' è
        # stato tarato. 'pyannote/speaker-diarization-community-1'
        # (pyannote.audio 4.x, clustering VBx) è l'alternativa in
        # valutazione (v. diar_eval/): NON condivide la taratura della
        # soglia — su VBx la soglia inizializza solo il clustering
        # agglomerativo preliminare (default del modello 0.6 contro 0.7046,
        # intervallo previsto dagli autori 0.5-0.8) e 'diarization_min_
        # cluster_size' NON esiste affatto (v. Diarizer._apply_clustering_
        # overrides). Cambiare questo valore SENZA rifare la campagna su
        # diar_eval/ + gender_eval/ significa buttare via entrambe le
        # tarature senza accorgersene.
        'diarization_model':                'pyannote/speaker-diarization-3.1',
        'diarization_audio_source':         'vocals',  # 'vocals' | 'original'
        # RIPORTATO A 0.0 (default di fabbrica 0.7046) il 24/09/2026: il banco
        # gender_eval su 8 episodi (63 punti, Veronica Mars) ha mostrato che a
        # 0.85 la mappa voce->genere dello STEP 6.5 perde copertura (60% contro
        # 98%: cluster fusi, confidenza sotto soglia -> nessuna correzione in
        # 1a persona). Accuratezza/copertura: 0.7046 auto 91.9%/98.4%; 0.85
        # auto 86.8%/60.3%; num_speakers=10 75.0%/76.2%. Sul dialogo il
        # confronto Goodrich non aveva mostrato differenze (v. sopra).
        'diarization_clustering_threshold': 0.0,       # 0.0 = default modello (0.7046)
        'diarization_min_cluster_size':     0,         # 0 = default modello (12)
        'diarization_max_speakers':         0,         # 0 = nessun tetto
        'diarization_min_speakers':         0,         # 0 = nessun pavimento

        # Riscrittura assegnazione word-level (v. piano_fix_pipeline_
        # trascrizione punto C) — False = lookup a midpoint storico.
        'diarization_word_vote_enabled': False,
        'diarization_word_tolerance_ms': 100,

        # Forced Alignment (whisperx + wav2vec2)

        # Durata chunk audio per la trascrizione (v. piano_fix_pipeline_
        # trascrizione punto B) — default = comportamento storico. Cappati
        # per engine in AudioProcessor (Canary ≤35s, Qwen3 ≤150s, whisper
        # ≤30s): valori più alti qui vengono clippati, mai ignorati in
        # silenzio (log di avviso).
        'asr_chunk_target_duration': 20,
        'asr_chunk_min_duration':    10,
        'asr_chunk_max_duration':    25,

        # Cap di generazione Qwen3-ASR — 0 (default) = calcolato dalla durata
        # massima dei chunk (v. _compute_max_new_tokens in qwen3_asr_engine.py).
        # NON 256: il vecchio valore fisso era già al limite di troncamento
        # su chunk da 25s densi (bug-check Opus, v. piano_fix_pipeline_
        # trascrizione punto D.5) — tenerlo come default avrebbe vanificato
        # anche il punto B (chunk più lunghi troncati anche peggio).
        'qwen3_max_new_tokens': 0,

        # Ripristino punteggiatura sui chunk ASR che ne sono privi (v.
        # piano_fix_pipeline_trascrizione punto D). PROMOSSO A DEFAULT DI
        # PRODOTTO l'08/09/2026 dopo validazione mirata (22 frasi a mano,
        # invariante 1:1 sempre rispettata, un solo errore che alterava il
        # senso su 22 casi). Limite noto: il modello non produce mai "!"
        # (classi fisse di addestramento, non un bug — v. TODO backlog per
        # alternative). 'missing' tocca SOLO i chunk completamente privi di
        # punteggiatura, mai quelli che l'ASR ha già punteggiato da sé
        # usando il segnale acustico.
        # Leggibilità dei sottotitoli trascritti (SubtitleFormatter): unisce le
        # frasi brevissime consecutive dello stesso speaker e allunga i blocchi
        # troppo veloci da leggere (v. core/subtitle_formatter.py, READ_*).
        # Misurato su Goodrich: blocchi <0,83 s 234 -> 49, >20 cps 311 -> 155.
        'subtitle_readability_enabled': True,

        # 'auto' (default) = segue il motore di trascrizione scelto nel widget:
        # ogni engine dichiara il proprio valore in PUNCT_AUTO_MODE (Canary e
        # Qwen3: 'missing'; faster-whisper non usa il ripristino, la sua
        # punteggiatura e' nativa). 'off'|'missing'|'all' forzano il valore
        # per tutti gli engine.
        'punctuation_restore_mode': 'auto',      # 'auto' | 'off' | 'missing' | 'all'
        'punctuation_model_id':     'oliverguhr/fullstop-punctuation-multilang-large',
        'punctuation_device':       'cpu',
        'punctuation_min_density':  0.0,     # 0.0 = solo testi senza ALCUNA punteggiatura

        # Library Scanner Settings
        'library_scanner_url': 'http://192.168.1.12:6680',
        'library_scanner_path_map': '',   # una regola per riga: <prefisso server>=<prefisso locale> (Linux/macOS; vuoto = invariato)
        'library_scanner_api_key': 'IDu_J0LvpqcmJ0nCFjXc6rlu2oKNoDE2bEO8CUVrNng',
        'library_scanner_enabled': True,

        # Gender Correction (LLM post-traduzione)
        'gender_correction_enabled': False,
        'gender_correction_model_path': '',
        'llm_model_preference': 'auto',   # ripiego automatico 14B/7B (utils.llm_model_select)
        # Il serbatoio L3 (`fallback_translator_model_path`, `reservoir_engine`)
        # e' stato rimosso con ADR-009: non c'e' un secondo modello. Chiavi
        # rimaste in un config.json esistente: innocue, nessuno le legge.

        # Subtitle Synchronization ("Anchor & Match" pipeline).
        # ADR-009: allineamento SOLO temporale. Le chiavi del percorso 'llm'
        # (sync_llm_window_size, sync_qwen_model_path, sync_engine) sono state
        # rimosse insieme a NLLB e al matcher Qwen: restano innocue in un
        # config.json esistente, semplicemente non le legge piu' nessuno.
        'sync_src_language':           'en',   # lingua della traccia embedded usata per gli anchor (ISO 639-1)
        'sync_allow_whisper_fallback': True,   # se il video non ha sottotitoli usabili: anchor dai tempi del parlato (VAD)
        'sync_max_offset_sec':         30,     # tolleranza di desync massima attesa (± secondi)
    }
    
    # Profili validi
    VALID_PROFILES = ['fast', 'balanced', 'quality', 'maximum', 'batch']

    # Engine di trascrizione validi (sistema multi-engine)
    # ADR-008: un solo engine. 'auto' e i nomi degli engine rimossi restano
    # accettati e vengono migrati su 'qwen3' alla lettura.
    VALID_TRANSCRIPTION_ENGINE_MODES = ['qwen3', 'auto']
    
    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._ensure_config_dir()
        self.load()
    
    def _ensure_config_dir(self):
        """Crea directory configurazione se non esiste"""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    def load(self):
        """Carica configurazione da file"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                self.settings = self._merge_defaults(loaded)
                migrated = self._migrate_split_langs(loaded)
                # Se abbiamo aggiunto nuovi default (come 'aya_model_download_status'), salva.
                # FUORI dal with: su Windows os.replace (salvataggio atomico) fallisce con
                # WinError 5 se lo stesso processo ha ancora il file aperto, e il salvataggio
                # non avveniva mai (con 2,4 s di tentativi persi a ogni avvio).
                if len(self.settings) > len(loaded) or migrated:
                    self.save()
            except Exception as e:
                print(f"⚠️ Error loading config: {e}")
                # Il prossimo save() sovrascriverebbe il file illeggibile con i
                # default: se ne conserva una copia per il recupero manuale.
                try:
                    import shutil, time
                    shutil.copy2(self.CONFIG_FILE, Path(str(self.CONFIG_FILE) +
                                 f".illeggibile-{time.strftime('%Y%m%d-%H%M%S')}"))
                except Exception:
                    pass
                self.settings = self.DEFAULTS.copy()
        else:
            self.settings = self.DEFAULTS.copy()
            self.save()
    
    # default di whisper_split_sentence_langs per revisione (rev 1 = prima della migrazione, config salvate fino
    # alla v1.26.0): una config che ha ancora il default della SUA revisione passa al default attuale
    _SPLIT_LANGS_BY_REV = {1: ['en', 'it'], 2: ['en', 'it', 'fr'], 3: ['en', 'it', 'fr', 'de']}

    def _migrate_split_langs(self, loaded: dict) -> bool:
        """Migrazione una tantum di whisper_split_sentence_langs (v1.27.0: +fr, v1.28.0: +de). Il load salva i
        default nella config, quindi cambiare DEFAULTS non basterebbe. Si aggiorna solo se la lista salvata e' ancora
        il default della revisione con cui e' stata salvata; una lista personalizzata non si tocca. Il marcatore
        'whisper_split_sentence_langs_rev' impedisce di rifarla (se l'utente toglie una lingua, resta tolta)."""
        target = int(self.DEFAULTS['whisper_split_sentence_langs_rev'])
        rev = int(loaded.get('whisper_split_sentence_langs_rev', 1) or 1)
        if rev >= target:
            return False
        cur = loaded.get('whisper_split_sentence_langs')
        old_default = self._SPLIT_LANGS_BY_REV.get(rev)
        if isinstance(cur, list) and old_default is not None and                 [str(x).strip().lower() for x in cur] == old_default:
            self.settings['whisper_split_sentence_langs'] = list(self.DEFAULTS['whisper_split_sentence_langs'])
        self.settings['whisper_split_sentence_langs_rev'] = target
        return True

    def _merge_defaults(self, loaded: dict) -> dict:
        """Merge loaded config con defaults"""
        merged = self.DEFAULTS.copy()
        for key, value in loaded.items():
            if key in merged:
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
            else:
                # Chiave non più in DEFAULTS (deprecata), la manteniamo comunque
                merged[key] = value
        
        # Assicura che tutte le chiavi default esistano
        for key, value in self.DEFAULTS.items():
             if key not in merged:
                 merged[key] = value
                 
        return merged
    
    def save(self):
        """Salva configurazione su file"""
        # Scrittura ATOMICA (file temporaneo UNICO per processo + replace): un
        # processo figlio che legge mentre la GUI salva, o un crash a meta'
        # scrittura, non vedono mai un config.json troncato (che farebbe
        # ricadere sui default). Il nome unico evita che due processi
        # scrivano lo stesso .tmp.
        import tempfile, time
        tmp_path = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(self.CONFIG_FILE.parent),
                                            prefix=self.CONFIG_FILE.name + '.',
                                            suffix='.tmp')
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            # Su Windows os.replace fallisce (PermissionError) se un altro
            # processo ha il file aperto in lettura in quell'istante: pochi
            # tentativi brevi. Mai una scrittura diretta non atomica.
            for attempt in range(10):
                try:
                    os.replace(tmp_path, self.CONFIG_FILE)
                    tmp_path = None
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except Exception as e:
            print(f"⚠️ Error saving config: {e}")
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    def set_overlay(self, overlay) -> None:
        """Sovrapposizione IN MEMORIA (eccezioni per file, vedi utils/job_overrides.py): get() la legge per prima; save() scrive
        sempre solo `self.settings`, quindi la sovrapposizione non finisce mai su disco. Vuota/None = nessuna."""
        self._overlay = dict(overlay) if overlay else {}

    def get(self, key: str, default=None) -> Any:
        """Ottieni valore configurazione"""
        fallback = default if default is not None else self.DEFAULTS.get(key)
        _ov = getattr(self, '_overlay', None)
        if _ov and key in _ov:
            return _ov[key]
        value = self.settings.get(key, fallback)
        if isinstance(value, str) and key != 'library_scanner_path_map' and is_foreign_windows_path(value):
            return fallback  # config copiata da Windows: il percorso con lettera di unita' qui non esiste
        return value
    
    def set(self, key: str, value: Any, save: bool = True):
        """Imposta valore configurazione"""
        if key == 'transcription_profile':
            if value not in self.VALID_PROFILES:
                print(f"⚠️ Profilo '{value}' non valido. Uso 'maximum'.")
                value = 'maximum'

        if key == 'transcription_engine_mode':
            if value not in self.VALID_TRANSCRIPTION_ENGINE_MODES:
                print(f"⚠️ Engine '{value}' non valido. Uso 'auto'.")
                value = 'auto'

        self.settings[key] = value
        if save:
            self.save()
    
    def get_all(self) -> Dict[str, Any]:
        """Ottieni tutte le impostazioni"""
        return self.settings.copy()

    # ========================================================================
    # METODI HELPER per OpenSubtitles (MANTENUTI)
    # ========================================================================
    
    def is_opensubtitles_configured(self) -> bool:
        """
        Verifica se OpenSubtitles è configurato per l'implementazione
        attualmente selezionata. opensubtitles.org (xmlrpc) e
        opensubtitles.com (rest) sono account separati con credenziali
        proprie: questo controllo guarda SOLO al set di credenziali
        rilevante per l'implementazione scelta.
        """
        if self.get('opensubtitles_preferred_implementation', 'xmlrpc') == 'rest':
            return bool(
                self.get('opensubtitles_username', '')
                and self.get('opensubtitles_password', '')
                and self.get('opensubtitles_api_key', '')
            )
        return bool(
            self.get('opensubtitles_xmlrpc_username', '')
            and self.get('opensubtitles_xmlrpc_password', '')
        )

    def is_opensubtitles_rest_configured(self) -> bool:
        """
        Verifica se sono presenti le credenziali per la REST API di
        opensubtitles.com a prescindere dall'implementazione preferita per
        l'upload: la REST richiede sempre l'api_key, mentre
        is_opensubtitles_configured() la richiede solo se 'xmlrpc' non è
        selezionato. (Il motore di traduzione "OpenSubtitles AI" che usava
        questo metodo è stato rimosso con ADR-009; la GUI congelata lo legge
        ancora.)
        """
        return bool(
            self.get('opensubtitles_username', '')
            and self.get('opensubtitles_password', '')
            and self.get('opensubtitles_api_key', '')
        )

    def get_opensubtitles_credentials(self) -> Dict[str, str]:
        """
        Ottiene le credenziali .com (REST + traduttore "OpenSubtitles AI"),
        sempre come dict anche se incomplete o vuote. Per sapere se sono
        sufficienti per fare upload usare is_opensubtitles_configured(): i
        due controlli sono volutamente disaccoppiati (un consumatore può
        aver bisogno di un solo campo, es. la sola api_key per il
        traduttore AI). Per le credenziali .org (XML-RPC) vedi
        get_opensubtitles_xmlrpc_credentials(): sono un account separato,
        non intercambiabile con questo.
        """
        return {
            'username': self.get('opensubtitles_username', ''),
            'password': self.get('opensubtitles_password', ''),
            'user_agent': self.get('opensubtitles_user_agent', OPENSUBTITLES_USER_AGENT),
            'api_key': self.get('opensubtitles_api_key', '')
        }

    def set_opensubtitles_credentials(self, username: str, password: str, api_key: str,
                                     user_agent: str = None):
        """Imposta le credenziali .com (REST + traduttore AI)."""
        self.set('opensubtitles_username', username, save=False)
        self.set('opensubtitles_password', password, save=False)
        self.set('opensubtitles_api_key', api_key, save=False)

        if user_agent:
            self.set('opensubtitles_user_agent', user_agent, save=False)

        self.save()

    def get_opensubtitles_xmlrpc_credentials(self) -> Dict[str, str]:
        """
        Ottiene le credenziali .org (XML-RPC), sempre come dict anche se
        incomplete o vuote. Account separato da quello .com: stesso
        username non implica stessa password (vedi is_opensubtitles_configured).
        """
        return {
            'username': self.get('opensubtitles_xmlrpc_username', ''),
            'password': self.get('opensubtitles_xmlrpc_password', ''),
            'user_agent': self.get('opensubtitles_user_agent', OPENSUBTITLES_USER_AGENT),
        }

    def set_opensubtitles_xmlrpc_credentials(self, username: str, password: str):
        """Imposta le credenziali .org (XML-RPC)."""
        self.set('opensubtitles_xmlrpc_username', username, save=False)
        self.set('opensubtitles_xmlrpc_password', password, save=False)
        self.save()

    def get_opensubtitles_config(self) -> Dict[str, Any]:
        """Ottiene tutta la configurazione OpenSubtitles"""
        return {
            'upload_enabled': self.get('opensubtitles_upload_enabled', True),
            'username': self.get('opensubtitles_username', ''),
            'password': self.get('opensubtitles_password', ''),
            'api_key': self.get('opensubtitles_api_key', ''),
            'xmlrpc_username': self.get('opensubtitles_xmlrpc_username', ''),
            'xmlrpc_password': self.get('opensubtitles_xmlrpc_password', ''),
            'user_agent': self.get('opensubtitles_user_agent', OPENSUBTITLES_USER_AGENT),
            'preferred_implementation': self.get('opensubtitles_preferred_implementation', 'xmlrpc')
        }
    
    def print_config_safe(self) -> str:
        """Stampa configurazione nascondendo dati sensibili"""
        safe_settings = self.settings.copy()
        
        if 'opensubtitles_password' in safe_settings:
            safe_settings['opensubtitles_password'] = '***HIDDEN***'
        if 'opensubtitles_api_key' in safe_settings:
            safe_settings['opensubtitles_api_key'] = '***HIDDEN***'
        if 'huggingface_token' in safe_settings and safe_settings['huggingface_token']:
            safe_settings['huggingface_token'] = '***HIDDEN***'
        if 'claude_api_key' in safe_settings and safe_settings['claude_api_key']:
            safe_settings['claude_api_key'] = '***HIDDEN***'
        if 'openai_api_key' in safe_settings and safe_settings['openai_api_key']:
            safe_settings['openai_api_key'] = '***HIDDEN***'
        if 'library_scanner_api_key' in safe_settings and safe_settings['library_scanner_api_key']:
            safe_settings['library_scanner_api_key'] = '***HIDDEN***'
        
        return json.dumps(safe_settings, indent=2, ensure_ascii=False)
    
    # ========================================================================
    # METODI HELPER per Profili Trascrizione (MANTENUTI)
    # ========================================================================
    
    def get_transcription_profile(self) -> str:
        """Ottieni profilo trascrizione corrente.

        Con 'transcription_profile_locked' (default True) il profilo e' fisso su
        'maximum' (v. DEFAULTS): e' il punto unico di blocco, letto da Whisper e Qwen3.
        """
        if self.get('transcription_profile_locked', True):
            return 'maximum'

        profile = self.get('transcription_profile', 'maximum')

        if profile not in self.VALID_PROFILES:
            print(f"⚠️ Profilo '{profile}' non valido. Uso 'maximum'.")
            profile = 'maximum'
            self.set('transcription_profile', profile)

        return profile
    
    def set_transcription_profile(self, profile: str):
        """Imposta profilo trascrizione con validazione"""
        if profile not in self.VALID_PROFILES:
            raise ValueError(
                f"Profilo '{profile}' non valido. "
                f"Profili disponibili: {', '.join(self.VALID_PROFILES)}"
            )
        
        self.set('transcription_profile', profile)
        if self.get('transcription_profile_locked', True):
            print("⚠️ Profilo bloccato su 'maximum': scelta salvata ma ignorata "
                  "(transcription_profile_locked)")
        print(f"✅Profilo trascrizione impostato: {profile}")
    
    def get_available_profiles(self) -> list:
        """Ottieni lista profili disponibili"""
        return self.VALID_PROFILES.copy()

    # ========================================================================
    # METODI HELPER per Engine di Trascrizione (NUOVO - sistema multi-engine)
    # ========================================================================

    def get_transcription_engine_mode(self) -> str:
        """Engine di trascrizione: sempre `qwen3` (ADR-008).

        `auto` resta accettato come alias storico; i valori delle versioni
        precedenti (`canary`, `faster-whisper`) vengono migrati su `qwen3` alla
        lettura, con un avviso, perché quegli engine non esistono più.
        """
        mode = str(self.get('transcription_engine_mode', LEGACY_ENGINE_MODE) or LEGACY_ENGINE_MODE)
        if mode == LEGACY_ENGINE_MODE:
            return ENGINE_MODE
        if mode not in self.VALID_TRANSCRIPTION_ENGINE_MODES:
            print(f"⚠️ Engine '{mode}' non più disponibile (ADR-008): uso '{ENGINE_MODE}'.")
        self.set('transcription_engine_mode', ENGINE_MODE)
        return ENGINE_MODE

    def set_transcription_engine_mode(self, mode: str):
        """Imposta la modalità engine di trascrizione con validazione"""
        if mode not in self.VALID_TRANSCRIPTION_ENGINE_MODES:
            raise ValueError(
                f"Engine '{mode}' non valido. "
                f"Engine disponibili: {', '.join(self.VALID_TRANSCRIPTION_ENGINE_MODES)}"
            )

        self.set('transcription_engine_mode', mode)
        print(f"✅ Engine trascrizione impostato: {mode}")
    
    def get_profile_info(self, profile: str = None) -> Dict[str, Any]:
        """
        Ottieni informazioni su un profilo specifico
        """
        if profile is None:
            profile = self.get_transcription_profile()
        
        if profile not in self.VALID_PROFILES:
            print(f"⚠️ DEBUG: profile '{profile}' NON VALIDO")
            profile = 'maximum'
        
        profile_enum = ProfileConfig.from_string(profile)
        config_data = ProfileConfig.get_profile_config(profile_enum)
        
        result = {
            'name': config_data.get('name', profile),
            'workers': config_data.get('num_workers', 4),
            'beam': config_data.get('beam_size', 5),
            'speed': f"{config_data.get('speed_factor', 1.0) * 100:.0f}%" if config_data.get('speed_factor', 1.0) != 1.0 else '100%',
            'quality': f"{config_data.get('quality_percent', 95.0):.1f}%"
        }
        return result

    
    # ========================================================================
    # METODI HELPER per Translation Models (MODIFICATO v4.2)
    # ========================================================================
    
    # ADR-009: un solo motore di traduzione. Il valore canonico e' il GGUF di
    # TranslateGemma; ogni valore scritto dalle versioni precedenti (o dalla Qt
    # congelata) viene ricondotto a questo alla lettura, con una riga di log.
    TRANSLATION_MODEL = 'translategemma-12b-gguf'
    VALID_TRANSLATION_MODELS = [TRANSLATION_MODEL]

    LEGACY_TRANSLATION_MODELS = {
        'nllb': TRANSLATION_MODEL,
        'nllb_finetuned': TRANSLATION_MODEL,
        'llm': TRANSLATION_MODEL,
        'aya': TRANSLATION_MODEL,
        'claude': TRANSLATION_MODEL,
        'openai': TRANSLATION_MODEL,
        'opensubtitles': TRANSLATION_MODEL,
    }

    def get_translation_model(self) -> str:
        """Il motore di traduzione: sempre `TRANSLATION_MODEL`.

        I valori storici (`nllb`, `nllb_finetuned`, `llm`, `aya`, `claude`,
        `openai`, `opensubtitles`) sono accettati e riscritti: chi ha un
        config.json vecchio non deve vedere un errore al primo file della coda.
        """
        model = self.get('translation_model', self.TRANSLATION_MODEL)
        migrato = self.LEGACY_TRANSLATION_MODELS.get(model)
        if migrato:
            logger.info(f"Motore di traduzione '{model}' non esiste piu' "
                        f"(ADR-009): uso '{migrato}'")
            model = migrato
        if model not in self.VALID_TRANSLATION_MODELS:
            logger.warning(f"Motore di traduzione '{model}' sconosciuto: "
                           f"uso '{self.TRANSLATION_MODEL}'")
            model = self.TRANSLATION_MODEL
        if self.get('translation_model') != model:
            self.set('translation_model', model)
        return model

    def set_translation_model(self, model: str):
        """Accetta il valore canonico e i nomi storici (la Qt congelata li manda),
        rifiutando solo cio' che non e' mai esistito."""
        canonico = self.LEGACY_TRANSLATION_MODELS.get(model, model)
        if canonico not in self.VALID_TRANSLATION_MODELS:
            raise ValueError(
                f"Motore di traduzione '{model}' non valido. "
                f"Motori disponibili: {', '.join(self.VALID_TRANSLATION_MODELS)}")
        if canonico != model:
            logger.info(f"Motore di traduzione '{model}' non esiste piu' "
                        f"(ADR-009): salvo '{canonico}'")
        self.set('translation_model', canonico)

    # RIMOSSI il 2026-08-18 insieme ai modelli Aya: `get_aya_model_path`,
    # `set_aya_model_path`, `set_aya_model_download_status`,
    # `is_aya_model_downloaded`. Non erano chiamati da nessuna parte tranne che
    # dalla GUI del download, ora puntata sul modello LLM in uso. Il flag
    # `aya_model_download_status` era per giunta inaffidabile: risultava True
    # con il modello NON in cache.

    # ========================================================================
    # METODI HELPER per Token HuggingFace (v4.1)
    # ========================================================================
    
    def get_huggingface_token(self) -> str:
        """
        Ottieni token HuggingFace
        """
        return self.get('huggingface_token', '')
    
    def set_huggingface_token(self, token: str):
        """
        Imposta token HuggingFace
        """
        token = token.strip()
        
        is_valid, error = self.validate_huggingface_token(token)
        if not is_valid and token:
            logger.warning(f"⚠️ Token HuggingFace potrebbe non essere valido: {error}")
        
        self.set('huggingface_token', token)
        logger.info(f"⚙️ Token HuggingFace {'configurato' if token else 'rimosso'}")
    
    def is_huggingface_token_set(self) -> bool:
        """
        Verifica se il token HuggingFace è configurato
        """
        token = self.get_huggingface_token()
        return bool(token and token.strip())
    
    def validate_huggingface_token(self, token: str) -> tuple:
        """
        Valida formato del token HuggingFace
        """
        if not token or not token.strip():
            return (False, "Token vuoto")
        
        token = token.strip()
        
        if not token.startswith('hf_'):
            return (False, "Token deve iniziare con 'hf_'")
        
        if len(token) < 20:
            return (False, "Token troppo corto (minimo 20 caratteri)")
        
        if not all(c.isalnum() or c == '_' for c in token):
            return (False, "Token contiene caratteri non validi")
        
        return (True, "")
    
    # `get_translation_model` e `set_translation_model` erano definiti DUE
    # volte in questo file, e in Python vince l'ultima definizione: la coppia
    # che stava qui — senza validazione — sovrascriveva silenziosamente quella
    # completa piu in alto. Rimossa il 2026-08-18. Restano valide le versioni
    # sopra, che validano contro VALID_TRANSLATION_MODELS e migrano i valori
    # storici (vedi LEGACY_TRANSLATION_MODELS).

    # ========================================================================
    # METODI LEGACY per le API cloud (Claude/OpenAI)
    # ADR-009: i motori cloud sono stati rimossi, quindi NESSUN motore
    # legge piu' queste chiavi. I metodi restano perche' la GUI Qt
    # congelata (gui/translation_model_dialog.py) li chiama: togliere
    # l'API sotto la GUI la romperebbe, e la GUI non si tocca.
    # ========================================================================

    # ========================================================================
    # METODI HELPER per Claude API (v5.0)
    # ========================================================================
    
    def get_claude_api_key(self) -> str:
        """Ottieni API key Claude/Anthropic"""
        return self.get('claude_api_key', '')
    
    def set_claude_api_key(self, api_key: str):
        """
        Imposta API key Claude/Anthropic
        
        Args:
            api_key: API key da Anthropic Console
        """
        api_key = api_key.strip()
        
        is_valid, error = self.validate_claude_api_key(api_key)
        if not is_valid and api_key:
            logger.warning(f"⚠️ API key Claude potrebbe non essere valida: {error}")
        
        self.set('claude_api_key', api_key)
        logger.info(f"✅ API key Claude {'configurata' if api_key else 'rimossa'}")
    
    def is_claude_api_key_set(self) -> bool:
        """Verifica se API key Claude è configurata"""
        api_key = self.get_claude_api_key()
        return bool(api_key and api_key.strip() and len(api_key) > 20)
    
    def validate_claude_api_key(self, api_key: str) -> tuple:
        """
        Valida formato API key Claude/Anthropic
        
        Returns:
            (is_valid: bool, error_message: str)
        """
        if not api_key or not api_key.strip():
            return (False, "API key vuota")
        
        api_key = api_key.strip()
        
        # Le API key Anthropic iniziano con 'sk-ant-'
        if not api_key.startswith('sk-ant-'):
            return (False, "API key deve iniziare con 'sk-ant-'")
        
        # Lunghezza minima ragionevole
        if len(api_key) < 40:
            return (False, "API key troppo corta (minimo 40 caratteri)")
        
        # Verifica caratteri validi (alfanumerici + underscore + trattino)
        if not all(c.isalnum() or c in '_-' for c in api_key):
            return (False, "API key contiene caratteri non validi")
        
        return (True, "")
    
    # ========================================================================
    # METODI HELPER per OpenAI API
    # ========================================================================

    def get_openai_api_key(self) -> str:
        return self.get('openai_api_key', '')

    def set_openai_api_key(self, api_key: str):
        api_key = api_key.strip()
        self.set('openai_api_key', api_key)

    def is_openai_api_key_set(self) -> bool:
        key = self.get_openai_api_key()
        return bool(key and len(key) > 20)

    def validate_openai_api_key(self, api_key: str) -> tuple:
        """Le chiavi OpenAI iniziano con 'sk-' (legacy) o 'sk-proj-' (project keys)."""
        if not api_key or not api_key.strip():
            return (False, "API key vuota")
        key = api_key.strip()
        if not (key.startswith('sk-') or key.startswith('sk-proj-')):
            return (False, "API key deve iniziare con 'sk-' o 'sk-proj-'")
        if len(key) < 30:
            return (False, "API key troppo corta")
        return (True, "")

    def get_openai_model(self) -> str:
        return self.get('openai_model', 'gpt-4o-mini')

    def set_openai_model(self, model: str):
        self.set('openai_model', model)

    # `get_translation_model` e `set_translation_model` erano definiti DUE
    # volte in questo file, e in Python vince l'ultima definizione: la coppia
    # che stava qui — senza validazione — sovrascriveva silenziosamente quella
    # completa piu in alto. Rimossa il 2026-08-18. Restano valide le versioni
    # sopra, che validano contro VALID_TRANSLATION_MODELS e migrano i valori
    # storici (vedi LEGACY_TRANSLATION_MODELS).

    def get_target_language(self) -> str:
        return self.get('target_language', 'ita')

    def set_target_language(self, lang: str) -> None:
        self.set('target_language', lang, save=True)

    # ========================================================================
    # METODI HELPER per il traduttore LLM locale (TranslateGemma e slot)
    # ========================================================================

    def get_llm_translator_model_path(self) -> str:
        """Cartella locale dei pesi del modello LLM, se sovrascritta."""
        return self.get('llm_translator_model_path', '')

    def set_llm_translator_model_path(self, path: str):
        """Imposta la cartella locale dei pesi del modello LLM."""
        self.set('llm_translator_model_path', str(path))

    # ========================================================================
    # METODI HELPER per NLLB Fine-Tuned
    # ========================================================================

    def get_nllb_finetuned_model_path(self) -> str:
        """Ottieni path del modello NLLB fine-tuned"""
        return self.get('nllb_finetuned_model_path', '')

    def set_nllb_finetuned_model_path(self, path: str):
        """Imposta path del modello NLLB fine-tuned"""
        self.set('nllb_finetuned_model_path', str(path))

    def is_nllb_finetuned_configured(self) -> bool:
        """Verifica se il modello fine-tuned è configurato e la cartella esiste"""
        path = self.get_nllb_finetuned_model_path()
        if not path:
            return False
        p = Path(path)
        return p.exists() and (p / 'config.json').exists()

    def get_nllb_num_beams(self) -> int:
        return int(self.get('nllb_num_beams', 7))

    def set_nllb_num_beams(self, value: int):
        self.set('nllb_num_beams', int(value))

    # ========================================================================
    # METODI HELPER per Gender Correction
    # ========================================================================

    def is_gender_correction_available(self) -> bool:
        if not self.get('gender_correction_enabled', False):
            return False
        return bool(self.resolve_llm_model('gender_correction_model_path')[0])

    def resolve_llm_model(self, key: str = 'gender_correction_model_path', preference=None):
        """(percorso GGUF, n_gpu_layers) del Qwen locale. Percorso configurato in `key`
        e file esistente -> invariato, n_gpu_layers=-1 (comportamento storico). Altrimenti
        ripiego automatico 14B/7B in base alla VRAM (utils.llm_model_select) dentro models/.
        `preference` (per singolo job) ha la precedenza sulla chiave
        'llm_model_preference' (default 'auto'); conta solo nel ripiego automatico.
        Nessun modello disponibile -> ('', 0)."""
        p = self.get(key, '')
        if p and Path(p).exists():
            return p, -1
        try:
            from utils.llm_model_select import detect_vram_mib, pick_qwen_model
            vram = getattr(self, '_llm_vram_mib', None)
            if vram is None:
                vram = detect_vram_mib()
                if vram is not None:        # un errore momentaneo di nvidia-smi non resta in cache per tutta la sessione
                    self._llm_vram_mib = vram
            pref = preference or self.get('llm_model_preference', 'auto')
            auto, ngl = pick_qwen_model(Path(__file__).resolve().parent.parent / 'models', vram, pref)
            if auto:
                return auto, ngl
        except Exception as e:
            logger.warning(f"Scelta automatica modello Qwen fallita: {e}")
        return '', 0

    # ========================================================================
    # METODI HELPER per Adaptive Batch Size
    # ========================================================================

    def get_adaptive_batch_config(self) -> Dict[str, Any]:
        """Ottieni configurazione adaptive batch size"""
        raw_initial = self.get('adaptive_batch_initial_size', 0)
        return {
            'enabled':          self.get('adaptive_batch_enabled', True),
            'initial_size':     raw_initial or None,   # 0 → None (auto-detect)
            'max_size':         self.get('adaptive_batch_max_size', 24),
            'min_size':         self.get('adaptive_batch_min_size', 1),
            'warmup_batches':   self.get('adaptive_batch_warmup_batches', 5),
            'high_threshold':   self.get('adaptive_batch_high_threshold', 0.85),
            'low_threshold':    self.get('adaptive_batch_low_threshold', 0.60),
        }


# ============================================================================
# Singleton globale 
# ============================================================================

_config_instance = None


def get_config() -> Config:
    """Ottiene istanza singleton della configurazione"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reset_config():
    """Reset del singleton (utile per testing)"""
    global _config_instance
    _config_instance = None


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    """Test configurazione completa"""
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    print("\n" + "=" * 80)
    print("TEST CONFIGURAZIONE v4.2 (FIX STATO DOWNLOAD)")
    print("=" * 80 + "\n")
    
    config = get_config()
    
    # Test 1: Info profilo
    print("\n" + "-" * 80)
    print("Test Profilo Corrente:")
    config.set_transcription_profile('quality')
    profile_info = config.get_profile_info()
    print(f"  - Profilo: {profile_info['name']}")
    
    # Test 2: Migrazione dei valori storici del modello di traduzione
    print("\n" + "-" * 80)
    print("Test Migrazione dei motori storici -> TranslateGemma GGUF:")

    precedente = config.get('translation_model', Config.TRANSLATION_MODEL)
    config.set('translation_model', 'aya', save=False)
    migrato = config.get_translation_model()
    print(f"  'aya' letto come: {migrato} (Atteso: {Config.TRANSLATION_MODEL})")
    config.set('translation_model', precedente, save=True)

    print("\n" + "=" * 80)
    print("âœ… TEST COMPLETATI!")
    print("=" * 80 + "\n")