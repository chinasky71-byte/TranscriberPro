# Changelog

Tutte le modifiche rilevanti di Transcriber Pro. Versioni secondo
[SemVer](https://semver.org/lang/it/): `APP_VERSION` in `main.py` è l'unica fonte di verità.

## [1.16.1] — 2026-09-17

### Fix: glossario per-show ignorato sui nomi propri identità con il motore LLM (TranslateGemma)
Diagnosi partita da un episodio reale (The Ark S03E08): il personaggio
"Garnet" tradotto come "Granato" (il nome comune inglese della pietra),
nonostante il glossario della serie avesse la voce corretta
`"Garnet": "Garnet"`.

- **Causa 1** (`core/translator.py::_mask_glossary`): le voci di glossario
  "a resa identità" (termine e resa uguali, es. `"FTL": "FTL"`,
  `"Garnet": "Garnet"`) non venivano mai mascherate su NESSUN motore — una
  regola pensata per NLLB (misurato: 8/24 blocchi rimasti in inglese per un
  singolo placeholder identità, decoder word-level che non regge un token
  opaco) ma applicata anche al motore LLM, dove non era mai stata misurata
  alcuna regressione analoga. Un'identità che coincide con una parola
  inglese comune restava quindi esposta alla traduzione letterale, e il
  controllo a valle (`_apply_glossary_posthoc`) non la intercetta perché
  cerca il termine INGLESE ancora presente nell'italiano, non una resa
  sbagliata plausibile. Il salto ora vale solo per NLLB.
- **Causa 2**, scoperta misurando il fix della causa 1 su TranslateGemma-12B
  reale: il placeholder veniva inserito con spazi fissi su entrambi i lati
  (`f" {token} "`), producendo doppio spazio o uno spazio prima della
  punteggiatura quando il termine confinava con virgola/punto
  ("you,  &lt;GLOSS0&gt; ."). Con questo artefatto TranslateGemma scartava
  silenziosamente il placeholder dalla generazione, facendo fallire la fase
  mascherata e facendo cadere il blocco nel recupero senza mascheramento —
  riesponendolo alla stessa causa 1. Normalizzata la spaziatura (solo spazi
  orizzontali, per non fondere i newline dei blocchi dialogo multi-parlante;
  solo fuori da NLLB, mai misurato lì). Verificato su rerun reale
  dell'episodio: blocchi da recuperare 29→21 su 719, nessuna riga di
  dialogo fusa, riga del personaggio corretta.

## [1.16.0] — 2026-09-08

### Fix: pipeline di trascrizione audio — 3 difetti reali diagnosticati e corretti su un film reale
Diagnosi partita da un file prodotto in produzione (Goodrich 2024, audio
italiano trascritto direttamente): duplicati da chunk sovrapposti, testo
sulla riga del personaggio sbagliato, ~30% dei blocchi senza punteggiatura
nelle scene di crosstalk/dialogo concitato.

- **Bug chunker** (`core/audio_processor.py::chunk_audio_intelligent`):
  l'estensione di un chunk troppo corto poteva sconfinare fisicamente nel
  chunk successivo → stessa battuta trascritta due volte con timestamp
  leggermente diversi. Fix + rete di sicurezza finale che garantisce
  `chunk[i].end <= chunk[i+1].start` per costruzione. Verificato: 12
  salti temporali all'indietro → 0 su rerun reale.
- **Gate di confidenza sul trattino di dialogo** (`core/subtitle_
  formatter.py`, `core/diarizer.py`): il trattino "- " veniva assegnato
  solo su gap/lunghezza, senza verificare l'affidabilità dell'attribuzione
  speaker — un'attribuzione debole diventava un trattino permanente sulla
  riga sbagliata. Nuovo campo `speaker_confidence` per segmento, soglia
  minima (`DASH_CONFIDENCE_MIN`) prima di concedere il trattino.
- **Chunk audio configurabili + cap per engine** (`asr_chunk_target/min/
  max_duration`, `ENGINE_CHUNK_CAP_S` in `core/audio_processor.py`):
  durata chunk non più fissa a 20s, cappata per engine (Canary ≤35s,
  Qwen3 ≤150s, whisper ≤30s) per non rompere i limiti di ciascun motore.
- **Fix `qwen3_max_new_tokens`**: il cap di generazione era fisso a 256,
  già al limite di troncamento su chunk densi da 25s. Ora 0 = calcolato
  automaticamente dalla durata massima dei chunk configurata.
- **Riscrittura assegnazione word-level** (dietro
  `diarization_word_vote_enabled`, default `False` — non ancora
  promossa): voto pesato sull'overlap invece del lookup a midpoint,
  politica esplicita sulle run corte (interiezioni come "Sì."/"No.")
  invece della fusione automatica nella run precedente. Percorso storico
  intatto e ancora attivo di default.
- **Nuovo modulo `core/punctuation_restorer.py`** — ripristino
  punteggiatura sui chunk ASR completamente privi di essa (modello
  dedicato `oliverguhr/fullstop-punctuation-multilang-large`, CPU,
  garanzia strutturale 1:1 parole/timestamp). **Promosso a default**
  (`punctuation_restore_mode='missing'`) dopo validazione mirata su 22
  frasi campione (invariante sempre rispettata, un solo errore che
  alterava il senso su 22 casi). Limite noto: il modello non produce mai
  "!" (classi di addestramento fisse, non un bug).
- **Soglia di clustering pyannote promossa a default**
  (`diarization_clustering_threshold=0.85`, contro lo 0,7046 calibrato
  dal produttore del modello): riduce nettamente il sovra-clustering
  (27→12 "parlanti" osservati) misurato con una campagna di taratura
  dedicata — nuovo banco riutilizzabile **`diar_eval/`** (`diar_bench.py`
  + `metrics.py`, sottocomandi prepare/run/gold-make/gold-score/sweep-c),
  50 coppie audio etichettate a mano come insieme oro. **Nota onesta**:
  un ricalcolo successivo ha mostrato che il segnale statistico sulla
  metrica aggregata era debole (differenza non significativa, test di
  McNemar p=1,00, su un campione di quella taglia) — la soglia resta una
  decisione esplicita, non un risultato schiacciante, da ricontrollare
  per primo se emergono sintomi di sovra-fusione su film di generi
  diversi da quello testato.
- Tre bug trovati dall'utente stesso durante l'etichettatura manuale
  dell'insieme oro (margine di contesto che mescolava due voci sui turni
  adiacenti, micro-turni pyannote da 17ms campionati per errore, parsing
  CSV che si rompeva su file salvati da Excel in locale italiano) —
  tutti corretti in `diar_eval/diar_bench.py`.

## [1.15.0] — 2026-09-06

### Fix: correzione della diagnosi PAL/NTSC della v1.14.0 — il drift non era il problema, era il gate
- **Origine**: l'utente ha messo in dubbio la voce "drift PAL/NTSC non gestito"
  della v1.14.0, facendo notare che gli anchor sono timestamp VERI per-riga
  presi dalla traccia embedded del video stesso (o da Whisper sul suo
  audio), non un offset/fattore di scala globale — quindi il matching
  per-riga dovrebbe essere di per sé immune al drift.
- **Verificato con un bugcheck dedicato**: con un matcher semanticamente
  perfetto (zero allucinazioni, solo drift PAL simulato) e il gate di
  offset DISATTIVATO: 100% esatto, errore massimo 0,0s. Confermato: il
  gate introdotto nei round precedenti confrontava ogni timestamp
  candidato con la posizione ORIGINALE (sempre più sbagliata su un file
  con drift) del sottotitolo esterno, scartando come "implausibili" match
  CORRETTI verso la fine del film; la stessa cattura delle finestre non
  proponeva il 65% delle righe di fine film alla finestra giusta.
- **Fix implementato**: `core/subtitle_synchronizer.py` — nuovo modello di
  shift lineare (`_expected_shift`/`_learn_shift`, fit Theil-Sen sui match
  già accettati, raffinato finestra dopo finestra, con controllo di
  qualità obbligatorio che disattiva il modello — comportamento identico a
  prima — se il fit non è affidabile). Il gate di plausibilità e lo slack
  di cattura ora confrontano con la posizione ATTESA (appresa) invece di
  quella originale grezza.
- **Verificato**: drift PAL puro (matcher perfetto) → 100% esatto, errore
  massimo 0,0s, pendenza appresa 0,0427 (vero rapporto 25/23,976); nessun
  drift + 100% allucinazioni → modello resta disattivato, comportamento
  identico a prima (nessuna regressione).

## [1.14.0] — 2026-09-05

### Fix: sincronizzazione SRT "Anchor & Match" — mai validata prima, tre giri di revisione
- **Causa radice (BUG1+2+3+4 combinati)**: finestre di matching sovrapposte
  con merge "vince la prima finestra arrivata" + fallback posizionale che
  sparge le righe non risolte su tutto il film + split codice morto (timestamp
  identici per le due metà) + un formatter di un'altra feature che fondeva
  cue con timestamp identici perdendo battute. Misurato: 50% delle righe
  sbagliate in silenzio su una simulazione di film intero, nessun errore,
  "Sincronizzazione Completata".
- **Fix round 1**: merge per confidence migliore invece che per ordine di
  arrivo; nuovo `_interpolate_fallback` (shift dai vicini risolti, non
  rapporto d'indice su tutto il film); split riscritto (`match_type`
  controllato prima dei timestamp, nuovo `_find_split_partner`); rimosso
  `SubtitleFormatter` dal percorso di scrittura (scrive solo i tempi,
  preserva testo/formattazione utente); +8 fix minori (lingua anchor mai
  rilevata, correzione genere no-op per `video_path` mancante, buco di
  copertura finestre in coda, ecc.). Verificato: 100% esatto sulla stessa
  simulazione.
- **Fix round 2** (dopo che una seconda revisione ha misurato il fix del
  merge come solo parziale — 22% di righe ancora sbagliate, perché la
  confidence auto-riportata da Qwen è quasi sempre ≈1.0 anche sui match
  sbagliati): **gate di offset globale** — nessuna riga può spostarsi oltre
  `sync_max_offset_sec` (nuova chiave config) dalla sua posizione originale,
  indipendentemente da cosa dichiari il modello. Slack di cattura
  disaccoppiato dal gate di plausibilità. Corretta anche una regressione
  introdotta nello stesso giro: normalizzare la lingua dell'anchor senza
  gestire tag reali come `pob`/`pt-BR`/`en-US` faceva fallire l'intera
  sincronizzazione invece di limitarsi a tradurre peggio.
- **Fix round 3** (bugcheck + bugfix diretto): il gate del round 2 aveva un
  bypass completo sul ramo split (fino a 176s di errore, non coperto dal
  gate); slack di cattura matematicamente sbagliato (`2×` invece del bound
  stretto `offset+5`); collisione a 3+ cue con lo stesso timestamp non
  gestita; **regressione GUI**: chiudere il dialog con la X ora chiamava sia
  `closeEvent` sia `reject()`, raddoppiando l'attesa di spegnimento a 60s.
  Tutti corretti. Verificato su un episodio reale da 794 righe (20%
  allucinazioni + 10% split simulati): 0 cue invertite, 0 sovrapposte, errore
  massimo 38.0s contro un limite teorico di 39.5s.
- Sincronizzazione, coda principale e strumento glossario ora mutuamente
  esclusivi (stessa GPU).
- **Aperto, non affrontato**: rilevazione del drift progressivo PAL/NTSC
  (25↔23,976fps) — il desync che cresce lungo il file invece di restare
  costante non viene riconosciuto come caso a parte. Misurato ~79% delle
  righe fuori tolleranza su un file con questo tipo di drift. Il gate
  rifiuta correttamente di indovinare oltre `sync_max_offset_sec` (logga un
  avviso esplicito quando succede) invece di produrre un risultato sbagliato
  con sicurezza, ma non risolve il problema: serve un fix di design
  dedicato (es. stima e compensazione di un fattore di scala lineare sul
  tempo, non solo di un offset costante).
- Aperto, rimandato: l'intera pipeline gira ancora nel processo GUI invece
  che in un subprocess isolato (`core/sync_cli.py` sul modello di
  `core/gender_corrector_cli.py`); l'annullamento non interrompe una singola
  chiamata al modello già in corso; le chiavi `sync_*` non hanno UI nelle
  Opzioni.

## [1.13.0] — 2026-09-05

### Fix: upload OpenSubtitles — funzionante per la prima volta, verificato con 4 upload reali
- **Causa radice**: `utils/opensubtitles_xmlrpc_uploader.py` comprimeva
  `subcontent` con gzip; il protocollo XML-RPC di opensubtitles.org si aspetta
  zlib. Il server decomprimeva a stringa vuota → sia "403 SubHashes non
  corrispondono" sia "402 formato non valido" da un'unica causa. Corretto
  (`zlib.compress`) e verificato con 4 upload reali riusciti (Brilliant Minds
  S02E17-E20, IDSubtitle 14025912/14025925/14025926/14025927).
- opensubtitles.org e opensubtitles.com sono account separati con credenziali
  proprie: nuove chiavi config dedicate `opensubtitles_xmlrpc_username`/
  `_password` (`utils/config.py`) + campi Opzioni separati
  (`gui/opensubtitles_settings_widget.py`). La diagnosi storica "User-Agent
  non registrato" per il 401 di XML-RPC era sbagliata (quella registrazione
  non è più disponibile dal 2022): `authenticate()` ora riporta "credenziali
  sbagliate per questo account".
- L'endpoint REST `/upload` usato dal codice non esisteva (404, percorso
  inventato). Il percorso reale `/api/v1/subtitles/upload` risponde
  `403 uploads_not_enabled` per API key normali — funzione opt-in, va
  richiesta a OpenSubtitles. Costante corretta; REST non è più il default
  per l'upload (lo è XML-RPC), rimosso il fallback automatico verso REST
  (non poteva mai funzionare, indipendentemente dall'esito XML-RPC).
- `utils/tmdb_client.py`: IMDb ID di episodio (non solo di serie) per gli
  upload di serie TV, via `external_ids` per-episodio con fallback a quello
  di serie.
- `core/pipeline.py`: tabella esplicita ISO 639-1→639-2 per l'upload (prima
  una dict-comprehension d'inversione sceglieva il codice sbagliato per
  tedesco/olandese/ceco/**rumeno→russo**/greco); `utils/opensubtitles_rest_uploader.py`
  ritorna `None` su codice lingua non mappato invece di indovinare — l'upload
  si interrompe invece di inviare la lingua sbagliata.
- Fix crash: "Test connessione" con credenziali incomplete sollevava
  `AttributeError` fuori dal `try/except` del metodo, abbattendo l'app.
- Rimossi `utils/opensubtitles_client.py`, `utils/opensubtitles_integration.py`,
  `utils/opensubtitles_config.py` (mai usati in produzione; uno di questi
  fingeva sempre successo senza chiamare alcuna API).
- Altri: credenziali non salvate cancellate cambiando metodo API; tooltip
  non aggiornato; gate credenziali del traduttore "OpenSubtitles AI"
  disallineato da quello dell'upload; controllo duplicati ridondante con
  quello già interno all'upload XML-RPC.

**Nota**: un test diagnostico dal vivo contro l'API reale (prima del fix) ha
pubblicato anonimamente un sottotitolo grezzo (non ripulito) per l'episodio
S02E17 — resta online accanto a quello corretto, non rimovibile da codice
(nessun account associato), segnalazione a OpenSubtitles necessaria.

## [1.12.2] — 2026-09-05

### Fix: strumento glossario per-show — cartelle stagione, subprocess GPU orfano, contesa GPU con la coda
- Corretto `tmdb_id` sbagliato scritto in silenzio quando la cartella scelta è
  la sottocartella stagione di una libreria Plex (`V:\Show\Season N\...`): il
  nome "Season 2" degradava a "Season" nel parsing e trovava un risultato TMDB
  estraneo. `gui/glossary_dialog.py`: riconoscimento cartelle stagione/speciali
  multilingua + lista di titoli candidati (cartella padre, poi titolo estratto
  dal primo file episodio) prima di chiamare `search_tv()`.
- `gui/glossary_worker.py`: annullare il tool lasciava un subprocess GPU orfano
  con ~9GB residenti in VRAM (il canale Qwen lo lancia sul venv principale,
  `terminate()` su Windows non si propaga ai discendenti) — ora traccia il PID
  e uccide l'intero albero (`taskkill /T`).
- `gui/main_window.py`: strumento glossario e coda di trascrizione/traduzione
  resi mutuamente esclusivi (stessa GPU, contesa altrimenti silenziosa).
- `qwen_n_gpu_layers` reso configurabile per-show (`core/glossary_builder_cli.py`,
  prima cablato nel codice).

## [1.12.1] — 2026-09-05

### Fix: batch manager adattivo cieco alla contesa GPU esterna
- Misurato su un run reale: due traduzioni NLLB in parallelo hanno fatto salire
  la memoria dal 50% all'85% mentre il nostro batch restava a 24, e il gestore
  lo riduceva comunque — non libera memoria altrui, e ha misurabilmente
  peggiorato il tempo per frase del 62% (0,271s → 0,438s).
- Nuovo `_external_pressure_gb()` (`utils/adaptive_batch_manager.py`):
  `torch.cuda.memory_reserved()` (quota di questo processo) vs memoria totale
  usata; sopra 1,5GB di scarto il gestore tiene la dimensione invece di ridurre.
- **Bug trovato e corretto nella stessa guardia durante il bugcheck**: campionava
  solo dentro `mem > high_threshold`, quindi su un file che incontra la contesa
  a metà la prima lettura cadeva già a contesa iniziata e la registrava come
  normale — guardia inerte esattamente sul caso per cui esisteva. Corretto
  campionando a ogni batch.
- Guardia temporale ms/token (NLLB) e ms/carattere (LLM) in `core/translator.py`
  e `core/llm_subtitle_translator/translator.py`: zero eventi OOM reali in tutto
  lo storico dei log (WDDM pagina in RAM di sistema invece di sollevare
  un'eccezione CUDA) — l'unica firma reale è il tempo che risale. Solo
  diagnostica (un log se ≥2× più lento del ritmo migliore del file), nessuna
  riduzione automatica.
- Risalita del batch moltiplicativa invece di +1 dopo la fine di una contesa.
- Analisi su 875 batch reali (23 run) pubblicata come artifact: la soglia di
  riduzione esistente (85%) è già ben calibrata — non toccata.

## [1.12.0] — 2026-09-05

### Fix: righe non tradotte rimaste silenziosamente in inglese (glossario per-show)
- Causa radice: quando un placeholder di mascheramento del glossario (`<GLOSS0>`) non
  veniva riprodotto fedelmente dal modello, il ripiego esistente riportava l'originale
  inglese — ma l'avviso passava da `logger.warning()` con un `logging.getLogger()` nudo,
  mai attaccato al file di log condiviso né alla GUI: il fallimento non lasciava
  **nessuna** traccia diagnosticabile.
- Sostituita la logica con una catena di recupero a 5 livelli, condivisa da ramo NLLB e
  ramo LLM: (L0) il glossario non maschera più i termini a resa identica (es. "FTL"→"FTL"),
  che non avevano nulla da guadagnare dal placeholder e tutto da perdere; (L1) unmask
  tollerante che ripara placeholder storpiati (spazi, maiuscole, parentesi perse); (L2)
  ritraduzione senza mascheramento sul motore primario ancora in VRAM, con glossario
  applicato a posteriori; (L3) "serbatoio" — un solo swap di modello a fine file per ciò
  che sopravvive, deduplicato per testo sorgente; (L4) inglese, ma con log rumoroso e
  visibile, mai più silenzioso.
- Nuovo audit indipendente a fine file (`_is_untranslated`/`_log_audit`): confronto di
  identità normalizzata sorgente↔output, indipendente da qualunque meccanismo di
  recupero — cattura anche cause future non ancora previste.
- Motore del serbatoio (`reservoir_engine`, nuova chiave config) scelto da una misura
  reale: valutazione testa a testa GEMBA-MQM su 39 righe corte dense di glossario da 4
  show ha trovato NLLB fine-tuned nettamente migliore di Qwen2.5-14B (64% vs 26% di
  preferenza, MQM pesato 1,41 vs 4,31). Default: sempre un motore diverso dal primario
  già in uso (NLLB-FT se il primario è l'LLM, Qwen se il primario è NLLB).
- Nuovo `core/fallback_translate_cli.py`: entrypoint subprocess isolato per il motore
  Qwen del serbatoio (stesso contratto di `core/gender_corrector_cli.py`).
- 8 bug aggiuntivi trovati e corretti in revisione, tra cui una chiamata a
  `_apply_fallback` mai definita nel progetto (crashava l'intera traduzione del file su
  un singolo blocco vuoto), sostituzione di glossario a posteriori che si fermava alla
  prima occorrenza di un termine ripetuto, e un bug preesistente di batch duplicato nel
  percorso di retry-errore del ramo NLLB.
- Verificato su episodio reale con glossario attivo (24/24 righe prima silenziosamente
  inglesi risolte) e su batch di produzione di 21 file (20 con glossario + 1 senza, come
  controllo di non-regressione).

## [1.10.1.22.8.26] — 2026-08-22

### Fix: cache del modello LLM di produzione cancellata a ogni fine coda
- Il modello LLM che occupa lo slot di produzione (oggi TranslateGemma-12B)
  veniva scaricato nella cache HuggingFace e poi ricancellato a fine coda da
  `cache_cleaner.py`: la lista di preservazione copriva solo i motori ASR
  (whisper/wav2vec), non il ramo di traduzione LLM. L'adattatore LoRA
  fine-tuned promosso in produzione non era coinvolto (vive su disco fuori
  dalla cache HF). Il cleaner ora risolve a runtime quale modello occupa lo
  slot (chiave config `llm_translator_model`, con lo stesso ripiego sul
  default già usato da `LLMSubtitleTranslator`) e lo preserva; i modelli
  usati solo per confronti sperimentali continuano a essere cancellati come
  prima.

## [1.10.1] — 2026-08-18

### Rimosso il percorso "adapt" del ramo LLM: disallineava battute e tempi
- Il ramo LLM interrogava il modello in due modi: "mt" (una battuta per
  conversazione, l'output è direttamente la traduzione) e "adapt" (un gruppo
  di blocchi in JSON con id, che il modello doveva restituire intatti). Sotto
  una certa taglia i modelli sbagliavano gli id — fondevano due blocchi e
  scrivevano le traduzioni successive nel posto sbagliato — con i tempi
  ancora corretti, quindi il file sembrava sano. Il percorso era ormai
  irraggiungibile dall'interfaccia (nessun motore attivo lo usa più, dopo la
  rimozione di Aya in v1.10.0) e rischiava di essere ereditato per difetto da
  un futuro modello aggiunto senza dichiararlo esplicitamente. Rimosso
  interamente; resta solo "mt", immune al problema per costruzione (una
  conversazione per battuta, nessun id da sbagliare). Validato end-to-end col
  modello di produzione su un SRT con tutti i casi (marcatore musicale,
  lirica, dialogo coi trattini, turpiloquio): zero retry.

## [1.10.0] — 2026-08-17

### Motore di traduzione LLM riscritto, TranslateGemma-12B sostituisce Aya
- Il ramo LLM (`core/llm_subtitle_translator/`) è stato riscritto come
  package model-agnostic con un registro `MODEL_SPECS`, correggendo quattro
  difetti del vecchio ramo Aya che ne rendevano la misura priva di senso:
  prompt senza chat template, `padding_side` di default che corrompeva ogni
  batch maggiore di uno, `output.split('\n')[0]` che scartava la seconda
  battuta di ogni dialogo, fallback che scriveva la frase inglese originale
  nell'SRT finale.
- Valutazione su banco sintetico prima e su film reali poi (Deadpool 2, A Man
  Called Otto, con i sottotitoli professionali come riferimento): il banco
  sintetico dava TranslateGemma-12B vincente, ma sui blocchi reali il
  verdetto si ribalta — **NLLB fine-tuned resta il motore di produzione**,
  davanti a TranslateGemma-12B e Aya su tutte le varianti testate (giudice
  GEMBA-MQM, 400 segmenti per confronto, due film). Instradamento per quality
  estimation (CometKiwi) testato e bocciato: indovina il motore migliore solo
  nel 59% dei casi.
- Aya rimossa dal registro (perdeva ogni confronto e il suo percorso "adapt"
  poteva disallineare battute e tempi su blocchi consecutivi, vedi v1.10.1).
  `DEFAULT_MODEL_KEY` passa a `translategemma-12b`; le configurazioni
  esistenti con `aya` vengono migrate automaticamente.
- **Bug critico trovato eseguendo per la prima volta il percorso reale della
  pipeline** (STEP 6 → `get_translator` → `translate_file` → `_polish`, mai
  esercitato prima su un file vero): NLLB traduceva il **contesto** (la trama
  del film) al posto della battuta stessa, non essendo un modello con prompt
  di sistema. Il contesto resta passato e utile solo ai motori che sanno
  usarlo (ramo LLM, Claude, OpenAI).
- Blocchi di dialogo a due voci consegnati appiattiti su una riga sola dal
  ramo NLLB: nuova riparazione in post-processing che li divide di nuovo sul
  trattino interno.
- Marcatori musicali in convenzione USA (`**testo**`, non solo `♪testo♪`)
  allucinati dal modello TranslateGemma 48 volte su 48 nei test: la maschera
  che protegge i blocchi non traducibili ora copre qualunque blocco senza
  nessuna lettera, non solo l'elenco esplicito di simboli.
- Post-processing tipografico condiviso in `BaseTranslator._generate_srt`:
  righe fuori norma dal 59,3% al 9,7%, per tutti i motori (NLLB, Claude,
  OpenAI, ramo LLM).
- Barra di progresso del ramo LLM allineata a quella di NLLB (si aggiorna
  in-place invece di riempire il registro riga per riga), con stima del
  tempo rimanente.
- `.gitignore`: chiusi quattro buchi da complessivamente ~12 GB
  (`venv_canary/`, `venv_comet/`, corpus di addestramento Gemma in crescita,
  checkpoint NLLB fine-tuned) — il pattern copriva solo la cartella `venv/`
  esatta, non le altre virtual-env del progetto.

## [1.9.7] — 2026-08

### Fix fusione battute nei blocchi dialogo multi-parlante
- NLLB non garantisce la preservazione dell'a capo quando traduce un blocco
  di sottotitoli a due parlanti (testo con newline interno tra le due
  battute): a volte le fondeva in un'unica riga, a volte inseriva persino
  trattini propri spuri, producendo blocchi come "- Vorrei che tu fossi
  qui. Anch'io." invece di due righe separate correttamente attribuite. I
  blocchi dialogo (identificati dai marcatori "- " già tracciati) vengono
  ora tradotti riga per riga anziché come blocco unico, garantendo per
  costruzione che il conteggio righe post-traduzione resti sempre fedele
  all'originale.

## [1.9.6] — 2026-08

### Fix critico: lingua sorgente NLLB ignorata per qualunque lingua diversa dall'inglese
- Il tokenizer NLLB richiede `tokenizer.src_lang` impostato ad ogni chiamata
  per taggare correttamente la lingua del testo in input. Questo valore non
  veniva mai impostato e restava bloccato sul default caricato al momento
  del `from_pretrained()` (`eng_Latn`) — qualunque traduzione con sorgente
  diversa dall'inglese (tedesco, francese, spagnolo, russo, ecc.) veniva
  quindi tokenizzata come se il testo fosse inglese, causando frasi lasciate
  non tradotte o allucinazioni del modello. Verificato empiricamente su un
  campione di frasi tedesche: 5/10 non tradotte senza il fix, 0/10 con il
  fix applicato. Il bug era presente fin dall'introduzione del modulo NLLB e
  ha interessato ogni traduzione con sorgente non inglese.

### Fix minori (naming file e correzione genere su input .srt)
- Quando l'input della pipeline è già un file `.srt` con codice lingua nel
  nome (es. `Movie.en.srt`), il nome del file finale non includeva più
  correttamente solo la lingua di destinazione (produceva `Movie.en.it.srt`
  invece di `Movie.it.srt`).
- La correzione di genere grammaticale (STEP 6.5) andava in errore quando
  l'input della pipeline era già un `.srt`: tentava di estrarre l'audio con
  ffmpeg direttamente dal file dei sottotitoli invece di risolvere il video
  reale corrispondente nella stessa cartella.

## [1.9.5] — 2026-07

### Fix batch adattivo di traduzione, seconda puntata
- Il tetto statico per classe introdotto in v1.9.3 (NLLB `max_size=24`)
  riduceva ma non eliminava lo sconfinamento sostenuto in RAM condivisa in
  alcuni run reali, e non era legato alla lingua sorgente come ipotizzato
  inizialmente: erano due lacune nella logica reattiva del batch manager.
  (1) Durante il warm-up il manager poteva solo *aumentare* il batch — non
  controllava mai la pressione di memoria per ridurlo, quindi sui file corti
  (la maggior parte delle traduzioni gira in meno di 10 batch) l'intero file
  poteva concludersi con un batch sovradimensionato e la memoria GPU satura.
  (2) `torch.cuda.empty_cache()` girava solo ogni 10 batch, soglia che quegli
  stessi file corti non raggiungevano mai, quindi la cache dell'allocator di
  PyTorch non veniva mai restituita al driver. Entrambi i punti ora reagiscono
  alla lettura di memoria reale ad ogni batch, warm-up incluso. Verificato
  sullo stesso file che aveva causato la segnalazione originale: lo step di
  traduzione è passato da 800 s (13 m 13 s) con 2,44 GB di sconfinamento
  sostenuto in RAM condivisa a 196 s (3 m 16 s) con solo un picco transitorio
  di ~19 s.

## [1.9.4] — 2026-07

### Fix spaziatura diarization multi-engine
- Le frasi divise dalla speaker diarization per cambio di parlante potevano
  comparire con le parole attaccate ("Sièe trasferitadapoco" invece di "Si è
  trasferita da poco") quando la trascrizione proveniva dagli engine
  Qwen3-ASR o Canary. Causa: la ricostruzione del testo del sotto-segmento
  assumeva la convenzione di spaziatura di faster-whisper (spazio incorporato
  a inizio parola), non valida per gli altri due engine. Corretto con una
  normalizzazione della spaziatura indipendente dall'engine.

## [1.9.3] — 2026-07

### Fix batch adattivo di traduzione
- Il batch manager di NLLB / NLLB fine-tuned / Aya-23 ignorava il tetto
  storico della propria classe e seguiva solo la soglia di configurazione
  condivisa con la trascrizione, causando in alcuni casi lo sforamento della
  VRAM dedicata con spillover silenzioso in RAM condivisa (Windows/WDDM non
  genera un errore di memoria in quel caso, solo un forte rallentamento).
  Ora ogni traduttore rispetta il proprio tetto di batch storicamente sicuro.

## [1.9.2] — 2026-07

### Ancoraggio sottotitoli alle battute + fix batch adattivo
- La regola anti-frammento riunisce la coda corta solo se è un vero frammento
  della stessa frase (pausa ≤ 0,8 s e frase non conclusa) — niente più blocchi
  con due battute distanti nella stessa riga.
- Fix batch adattivo trascrizione: lettura memoria a livello device, cap batch
  16, tetto VRAM-aware anche in modalità classica (su Windows/WDDM lo
  sforamento VRAM non dà OOM ma spillover silenzioso in RAM condivisa).
- Barra di progresso non più interrotta dai log di aggiustamento batch.

## [1.9.1] — 2026-07

### Ottimizzazione picco memoria Demucs
- Tensori residenti su CPU: `apply_model` sposta sulla GPU solo il segmento in
  lavorazione → picco VRAM costante (~0,6 GB) indipendente dalla durata del
  file (prima: >21 GB GPU committed su un episodio da 83 min).
- Unload anticipato di Demucs e Whisper a fine STEP 3 quando l'engine
  pianificato è Qwen3 / Canary.

## [1.9.0] — 2026-07

### Stile dialoghi professionale (Netflix)
- Trattini "- " solo quando due parlanti condividono lo stesso blocco SRT
  (una battuta per riga); speaker diarization estesa a tutti gli engine
  (opzione `dialogue_style_enabled`, default ON, richiede token HuggingFace).
- Trattini preservati anche negli SRT tradotti (tutti e 4 i backend).
- Nuovo `core/subtitle_formatter.py`: CPL 42, anti-flash, merge frammenti,
  raggruppamento dialoghi.

## [1.8.1] — 2026-07

- Fix: il gender corrector non gira più sulle trascrizioni in italiano nativo
  (senza traduzione).

## [1.8.0] — 2026-07

### Trascrizione multi-engine con routing automatico per lingua
- **NVIDIA Canary-Qwen-2.5B** (solo inglese, WER migliore; opzionale, richiede
  `venv_canary` dedicato con NeMo 2.7.3).
- **Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B** (pacchetto pip `qwen-asr`):
  11 lingue con timestamp word-level (zh, en, yue, fr, de, it, ja, ko, pt, ru,
  es), auto-detect lingua nativo.
- **Faster-Whisper large-v3** come fallback universale garantito: la pipeline
  non fallisce mai per colpa di un engine nuovo.
- Un solo engine ASR in VRAM per volta.
- Nuove chiavi config: `transcription_engine_mode` (auto / canary / qwen3 /
  faster-whisper), `canary_enabled`, `qwen3_enabled`; combo di selezione
  engine nelle impostazioni profilo.

## [1.7.0] — 2026-07-16

### Avvio senza freeze UI
- Tab Traduzione da 3719 ms a 15 ms; I/O asincrono; torch mai importato nel
  processo GUI (check ambiente via CLI esterna); splash in ~2 s.

## [1.6.1] — 2026-07-15

- Fix (GUI): rimosso "(LLM)" dall'etichetta della checkbox correzione genere.

## [1.6.0] — 2026-07-15

### Gender Corrector v2 — redesign completo (audio-driven, deterministico)

Il correttore di genere LLM (Qwen2.5-14B GGUF) è stato sostituito integralmente:
misurato sul benchmark, correggeva 2 errori su ~90 (+0,66 punti — di fatto inerte).

**Nuovo approccio**: il genere di chi parla non è deducibile dal testo
("I'm tired" non dice se parla un uomo o una donna) — ma è nella **voce**.

- **Speaker Gender Map** (`core/speaker_gender.py`): diarization pyannote +
  classificatore ECAPA (VoxCeleb2) → genere di ogni parlante con confidenza.
  Accuratezza 95,0% (validata su 22 episodi contro sottotitoli professionali).
- **Selettore morfosintattico** (`core/gender_line_selector.py`, spaCy in venv
  separato): individua le sole forme di 1ª/2ª persona che concordano col
  parlante/interlocutore; esclusioni blindate (participi con *avere*,
  modificatori nominali, dialoghi doppi, impersonali...).
- **Riscrittura deterministica + validatore** (`core/gender_rewriter.py`):
  flip morfologico (-o↔-a + tabella articoli/pronomi) accettato solo se ogni
  parola cambiata è una coppia di flessione plausibile → allucinazioni
  impossibili per costruzione. Il motore deterministico ha battuto Qwen2.5-14B
  nel confronto diretto (86,8% vs 83,1%).
- **2ª persona** ("sei stanca?"): genere dell'interlocutore dai turni di
  dialogo (91,4%, modalità strict) e dai vocativi col cast TMDB
  ("Sei cresciuta, Veronica").
- **Riuso diarization**: i turni calcolati in trascrizione vengono riusati
  dallo STEP 6.5 (~1-2 minuti risparmiati a film).

**Risultati** (ground-truth auto-estratto da sottotitoli professionali dual-track):
| Metrica | Prima (NLLB) | Dopo |
|---|---|---|
| 1ª persona femminile (corpus) | 19,3% | **86,8%** |
| 1ª persona maschile (corpus) | 89,3% | **93,3%** |
| A/B episodio reale, femminili | 0% | **60%** |
| A/B episodio reale, maschili | 100% | **100%** (mai degradato) |

**Migrazione**: il modello GGUF non serve più. Per la correzione genere ora
servono: venv NLP separato con spaCy (`venv_nlp/`, vedi README → Installation)
e un token HuggingFace (pyannote). Nuove chiavi config:
`gender_correction_second_person` (default on), `gender_selector_python`
(auto-discovery se vuota). UI impostazioni aggiornata.

Include inoltre: harness di valutazione completo in `gender_eval/`
(benchmark MT-GenEval, ground-truth builder dai film dual-track, A/B runner).

## [1.5.x] — 2026-06/07

Versioni precedenti al changelog: modulo OCR bitmap PGS/VOBSUB → SRT
(Tesseract parallelo, review UI, writeback mux/sidecar), integrazione Library
Scanner (badge bitmap, batch OCR, Superpower), routing OCR nella coda
principale, GUI revamp (icone SVG, settings unificati, i18n IT/EN),
ottimizzazione avvio (~2s), fix import bitmap in coda. Vedi la cronologia git.
