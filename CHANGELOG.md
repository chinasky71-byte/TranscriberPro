# Changelog

Tutte le modifiche rilevanti di Transcriber Pro. Versioni secondo
[SemVer](https://semver.org/lang/it/): `APP_VERSION` in `main.py` è l'unica fonte di verità.

## [1.23.0] — 2026-09-26

### Split per frasi attivo anche per l'italiano
`whisper_split_sentence_langs` passa da `["en"]` a `["en", "it"]`: con faster-whisper anche l'italiano divide i
segmenti sui confini di frase (le altre lingue restano sullo split originale). Per tornare al solo inglese:
`"whisper_split_sentence_langs": ["en"]` in `~/.transcriberpro/config.json`.
- **Perché è stato acceso:** conferma su 8 file italiani nuovi con regola congelata prima della selezione
  (blocchi a metà frase 46,8% → 11,2%, blocchi su articolo/preposizione/congiunzione 24,9% → 2,1%, parole identiche,
  ogni file migliora). Vedi 1.22.0 e `whisper_split_eval/README.md`.
- **Riserve invariate:** film doppiati in prevalenza (3 file in italiano originale, con un miglioramento più debole
  su *Sono qui per Caos*: 68% → 30%), effetto sulla traduzione e ascolto umano non misurati.
- **Pulizia:** cancellato l'audio dei dati di prova di `whisper_split_eval/` (~19 GB in locale); nel repository non
  cambia nulla.
- README aggiornato (badge di versione e sezione Changelog, inglese e italiano).

## [1.22.0] — 2026-09-26

### Split per frasi: regole per l'italiano (pronte e confermate, NON attive di default)
`core/whisper_sentence_split.py` ha ora un ramo `lang='it'` (abbreviazioni, articoli, preposizioni e
congiunzioni, locuzioni tipo «quello che»/«solo che», iniziali maiuscole). Il motore legge la lista di lingue
`whisper_split_sentence_langs` (nuova chiave, default `['en']`): con il default il comportamento non cambia
(inglese sì, italiano no, altre lingue split originale). Per accenderlo: `"whisper_split_sentence_langs": ["en", "it"]`
in `~/.transcriberpro/config.json`. Nessuna voce nella GUI.
- **Effetto misurato sull'italiano** (file interi, Demucs a chunk, Whisper di produzione): blocchi a metà frase
  46,8% → 11,2% (professionali 10,8%), blocchi che finiscono su articolo/preposizione/congiunzione/ausiliare
  (controllo indipendente con spaCy) 24,9% → 2,1%, parole identiche, ogni file migliora, blocchi >84 caratteri 1,3% → 0.
- **Prove:** taratura su 3 file; conferma round 1 su 7 file (NON VINCENTE per un criterio: elisioni con un salto di
  10-15 s dentro la parola, timestamp errati di Whisper); correzione; conferma round 2 su 8 file NUOVI con regola
  congelata prima della selezione: VINCENTE. Dettagli, riserve e una nota di trasparenza sull'analisi del round 2 in
  `whisper_split_eval/README.md` e `whisper_split_eval/results/`.
- **Riserve:** quasi tutti i file sono film doppiati (l'italiano originale è coperto da 3 file); i sottotitoli
  professionali dei doppiati sono traduzioni e servono solo per la forma dei blocchi; effetto sulla traduzione e
  ascolto umano non misurati.
- **Correzione valida anche per l'inglese:** un token attaccato (elisione, trattino) preceduto da un salto di 9 s
  o più non appartiene più alla parola precedente. Prima una parola con un timestamp errato (es. «Cos» a 1423 s e
  «'è» a 1529 s) produceva un blocco di 111 s mostrato 100 s in anticipo. Sull'inglese l'output resta identico su
  2323 segmenti di 5 campioni; con il default l'inglese di due file della v5 resta identico anche su GPU.
- **Test:** 76 (fixture con dialoghi reali solo in locale, mai su GitHub: i test relativi si saltano se mancano).

## [1.21.1] — 2026-09-25

### Demucs a chunk oltre i 60 minuti (prima 90)
`AudioProcessor.STANDARD_PATH_THRESHOLD` passa da 5400 s a 3600 s: i file tra 60 e 90
minuti, che prima usavano lo standard path (audio e risultato a 4 sorgenti interi in
RAM), ora usano il percorso a chunk da 5 minuti con overlap di 10 s. Motivo: sulla
macchina da 32 GB lo standard path su file da ~90 minuti portava la RAM di sistema a
0 GB liberi (picco di 23-25 GB), mentre il percorso a chunk è arrivato a circa 8 GB su
un film da 107 minuti. Nessun altro cambiamento: sotto i 60 minuti tutto invariato.
- **Non misurato:** l'effetto dei vocals a chunk (overlap con giunzioni) sull'accuratezza
  della trascrizione per i file tra 60 e 90 minuti. I tempi sono simili (194 s per 89,7
  minuti nello standard path, 210 s per 107 minuti a chunk).

## [1.21.0] — 2026-09-25

### Split di Whisper sui confini di frase (attivo di default, solo inglese)
`faster-whisper` divideva i segmenti lunghi a 80 caratteri / 6 s senza guardare la
punteggiatura: il 37-43% dei blocchi finiva a metà frase e la traduzione riceveva
frammenti. Ora, per l'**inglese**, i segmenti si dividono preferendo i confini di
frase (`core/whisper_sentence_split.py`, opzione `whisper_split_sentence_aware`,
default `true`; `false` ripristina il comportamento precedente). Altre lingue:
split originale, invariato. Vale solo per faster-whisper in modalità batched
(Qwen3 e Canary non sono coinvolti).
- **Effetto misurato** (3 campioni indipendenti, regole congelate prima dei dati):
  blocchi a metà frase 37-43% → 6-9%, parole e testo identici, blocchi > 84 caratteri
  ~1% → 0, blocchi con più di 2 righe quasi azzerati, opzione spenta bit-identica.
  Ogni singolo file dei 6 interi migliora. I blocchi diventano un po' più numerosi e
  brevi (per esempio 6,6 → 8,0 al minuto; i sottotitoli professionali ne hanno 12,4).
- **Correzione del ripiego** (trovato dalla prova su file interi): un segmento di
  ripetizioni attaccate («Boop-a-doop-a» ×5) veniva rimandato allo split originale, che
  taglia dentro le parole. Ora non si taglia mai dentro una parola; aggiunte le
  abbreviazioni italiane (Sig., Dott., Avv., …) nell'elenco.
- **Prove:** v2 NON VINCENTE solo per i criteri sui blocchi brevi (+23% contro +15%),
  criterio ricalibrato sul riferimento professionale → v3b VINCENTE su 45 finestre
  nuove; v4 su 6 file interi NON VINCENTE per un solo caso di taglio dentro parola
  (presente anche nello split originale), poi corretto e verificato offline sugli
  stessi dati (un solo segmento cambia; 40 test verdi). Dettagli e riserve in
  `whisper_split_eval/README.md`.
- **Riserve dichiarate:** criterio (f) ricalibrato dopo il fallimento della v2; margine
  0 s nella v3b (meno indipendenza dalla v2); correzione del ripiego non riconfermata
  su dati nuovi; effetto sulla traduzione e leggibilità dei blocchi più brevi non
  misurati. Non attivo per le altre lingue perché non misurato (abbreviazioni e regole
  sono inglesi).

## [1.20.1] — 2026-09-25

### Rimossa la ricomposizione delle frasi spezzate (vicolo cieco)
Il controllo umano alla cieca su 100 coppie di file reali (8 titoli) non ha
confermato il vantaggio misurato da GEMBA/COMET: ricomposizione 38, base 30,
pari 32 (p unilaterale 0,198). Regola congelata: ARCHIVIA. In 13 delle 22
coppie con difetti segnalati la traduzione ricomposta perdeva una parte del
testo (la coda dell'unità).
- Rimossi `core/sentence_recompose.py`, l'opzione `translation_recompose_sentences`
  e il ramo relativo in `core/pipeline.py`: il percorso di traduzione torna
  quello della 1.19.x (già identico con l'opzione spenta).
- Rimossi il controllo cieco (`blind_check/`) e il prototipo/banco di
  `split_eval/`; resta solo la misura `midcut` usata da `asr_eval`. Esiti e
  motivazioni in `split_eval/README.md`.
- Le voci 1.20.0 sotto restano come storico.

## [1.20.0] — 2026-09-24

### Ricomposizione delle frasi spezzate prima della traduzione (OPT-IN, spenta di default)
Nuova opzione `translation_recompose_sentences` (default `false`; si attiva in
`~/.transcriberpro/config.json`). Quando è attiva, i blocchi che finiscono a
metà frase vengono riuniti in unità di frase, tradotti interi e la traduzione
viene ridistribuita sui blocchi originali (stessi numeri, stessi tempi).
- **Ambito**: solo NLLB / NLLB fine-tuned, solo inglese → italiano, solo SRT
  da trascrizione (i sottotitoli già presenti, embedded o da OCR, e gli altri
  motori ignorano l'opzione con un messaggio nel log). Non coperti: OCR
  (`core/ocr_auto.py`) e sync (`core/subtitle_synchronizer.py`).
- **Sicurezza**: con l'opzione spenta il percorso di traduzione è identico
  alla 1.19.x (nessun import del modulo nuovo). Se qualcosa non torna
  (unità tradotte in numero sbagliato, testo vuoto, eccezione) si ripiega sul
  percorso normale senza far fallire la traduzione; i blocchi a due voci con
  trattino, le etichette di speaker (`MARY:`) e le didascalie (`[laughs]`) non
  si uniscono mai; la cancellazione è rispettata; il traduttore viene
  ricreato se il serbatoio L3 l'ha scaricato.
- **Modulo**: `core/sentence_recompose.py` (solo libreria standard). Il
  prototipo misurato resta in `split_eval/`.
- **Evidenza** (prova confermativa con regole v2 su dati nuovi, Qwen3, NLLB-FT):
  giudice GEMBA B 179 contro A 48 (pari 23), COMET +0,04 in 7 film su 7.
  La ridivisione è stata migliorata offline dopo il verdetto formale «archivia»
  del banco (blocchi vuoti 1,94% → 0,48%, ripiego 4% → 1%, sbilanciamento
  p90 0,236 → 0,154): correzioni progettate sulle stesse 200 unità, quindi
  post-hoc, con un margine stretto sullo sbilanciamento. Prova con NLLB-FT
  vero su 14 finestre: indici e tempi identici, nessun blocco vuoto, traduttore
  ricreato dopo lo scarico. Un bugcheck Opus ha trovato e corretto: etichette di
  speaker unite oltre il cambio di voce, ambito esteso ai sottotitoli
  embedded, ridivisione lenta su traduzioni anomale.
- **Da fare prima di attivarla**: controllo alla cieca su file reali (l'SRT
  non porta lo speaker: due persone che si passano una frase senza trattino
  potrebbero essere unite).

### Controllo alla cieca della ricomposizione su file reali (`blind_check/`)
Strumenti per confrontare, senza sapere quale sia quale, la traduzione normale
con quella ricomposta su estratti di 20 minuti di film e serie della libreria
(5 film + 3 episodi, seme fisso, motori Whisper e Qwen3 in alternanza, solo
traccia audio inglese): selezione, trascrizione con la pipeline reale e
traduttore finto che cattura l'SRT, doppia traduzione NLLB-FT, foglio cieco
(A/B scambiati a caso, mappatura nascosta) e conteggio con regola congelata
(quota ≥60% fra i non pari, p ≤ 0,025, film in maggioranza ≥60%, difetti
visibili ≤3%). Nota: con una traccia audio italiana presente la pipeline
trascrive l'italiano e salta la traduzione, quindi gli estratti contengono solo
l'inglese. 12 test CPU.

### Test nei banchi
I test dei banchi `asr_eval/` e `split_eval/` non erano mai stati pubblicati
(il `.gitignore` del repository ignora `test_*.py`): ora lo sono (76 test in
`split_eval/tests`, 70 in `asr_eval/tests`).

## [1.19.1] — 2026-09-24

Nessuna modifica al comportamento dell'app: due banchi di misura nuovi
(`asr_eval/`, `split_eval/`, con test e README) e i loro primi risultati.

### `asr_eval/` — banco di accuratezza ASR contro i sottotitoli professionali
Whisper large-v3 (profilo di produzione), Canary-Qwen-2.5B (solo inglese) e
Qwen3-ASR su 140 finestre da ~150 s di 16 film (inglese, audio ENG contro
sub ENG professionali), con e senza Demucs. Regole di decisione, normalizzazione
e statistica (bootstrap per film, Wilcoxon esatto) congelate PRIMA dei run
(`decision_rules.py`); sandbox della config di produzione; guardia che rifiuta
di partire con la GPU occupata. 70 test. Risultati (`asr_eval/results/`):
- Gruppo principale (9 film, voce separata), WERc: Qwen3 12,1%, Canary 14,0%,
  Whisper 15,8%. Qwen3 batte Canary di 1,85 punti (IC95% 0,50–3,39,
  Wilcoxon p=0,012, stesso segno nel gruppo dei film più vecchi): verdetto
  «cambio proposto», NON definitivo (manca il set d'oro corretto a mano).
  Whisper contro Canary: pareggio, ma con il doppio di battute perse (8,0% contro 4,2%).
- Demucs: Whisper +2,1 punti, Canary +1,9, Qwen3 +0,2 (nessun effetto significativo).
- Velocità (s per minuto di audio): Whisper 2,0, Canary 2,2, Qwen3 5,5.
- Limiti: il riferimento è un sottotitolo condensato (i valori assoluti sono
  gonfiati, conta la classifica); l'italiano NON è misurato (i sub ITA normali
  dei film doppiati sono la traduzione dell'inglese, non il copione: serve un
  controllo d'ascolto manuale, `work/listen_check.csv`).

### `split_eval/` — frasi spezzate a metà: misura e prototipo di ricomposizione
- **Misura (midcut):** nei blocchi finali del formatter i blocchi che finiscono
  a metà frase sono il 41% con Whisper, il 10-11% con Qwen3 e Canary, il 10%
  nei sottotitoli professionali. Con Whisper la traduzione riceve quindi
  frammenti molto più spesso.
- **Prototipo (`recompose.py`):** unisce le frasi spezzate in unità, traduce
  l'unità intera e ridistribuisce il testo tradotto sui blocchi originali
  (tempi invariati). Esperimento A/B con NLLB fine-tuned su 140 finestre,
  58 con fusioni (195 unità): chrF −0,62 (IC95% −1,28…+0,02, n.s.), COMET
  +0,03 (IC95% 0,02–0,05, 7 film su 7 a favore di B, p=0,016); blocchi >20
  cps 13,3% → 6,9%, >84 caratteri 6,6% → 1,0%; nessun blocco vuoto. Giudice
  GEMBA-MQM (gpt-4o, 480 unità fuse di tutti i film, A e B nella stessa
  chiamata, ordine casuale): B preferito 303 volte, A 161, pari 16; MQM
  pesato medio A 6,65, B 4,51 (più basso = meglio); costo ~2,7 $ (548.700
  token in ingresso, 130.487 in uscita). Verdetto secondo le regole
  congelate: **ARCHIVIA**, perché il criterio chrF (IC95% non interamente
  sopra 0, Wilcoxon p=0,078) non passa; la regola non è stata modificata
  dopo i risultati. Le metriche divergono: chrF confronta con una sola
  traduzione e premia la resa letterale, mentre COMET (7 film su 7), il
  giudice GEMBA e la lettura di esempi favoriscono B (frammenti tipo
  «…come pensi I ricordi», «…scelto per i suoi talenti. per il loro genere»
  diventano frasi complete). NON portato nel codice di produzione: la
  decisione se derogare alla regola spetta all'utente.
- **Prova confermativa (regole v2, dati nuovi).** La regola v1 era difettosa:
  il suo testo dava COMET come metrica di record e chrF come inaffidabile, ma
  il codice richiedeva anche chrF > 0; la memoria di progetto indica la
  preferenza del giudice come metrica principale. La v1 non è stata riscritta:
  la v2 (`decision_rules_split_v2.py`, congelata prima di tradurre) usa come
  endpoint primari la preferenza GEMBA (esatto binomiale, maggioranza in ≥70%
  dei film) e COMET, con chrF solo descrittivo, su dati nuovi (segmenti di
  Qwen3, il motore standard: 200 unità fuse in 61 finestre) e su un campione
  casuale di 250 unità per il giudice. Risultati: GEMBA B 179, A 48, pari 23
  (MQM 2,57 contro 5,10); COMET +0,04 (IC95% 0,02–0,07, 7 film su 7,
  p=0,016); chrF +0,21 (n.s.). Endpoint primari superati e replicati; verdetto
  formale **ARCHIVIA** per tre guardie strutturali sul taglio: blocchi vuoti in
  B 1,94% (soglia 1%), sbilanciamento ai tagli p90 0,236 (soglia 0,20), inglese
  residuo B 28 contro A 27. Il difetto è nell'implementazione della
  ridivisione (8 unità su 200 finite in ripiego), non nella traduzione: la
  ridivisione non cambia le parole, quindi gli endpoint di qualità non
  dipendono da essa. Costo del giudice ~0,9 $. Il selettore delle regole è la
  variabile d'ambiente `SPLIT_RULES_MODULE`.
- Non eseguito: TranslateGemma (`--engine llm`).
- Un bugcheck Opus ha trovato e corretto, prima dell'esecuzione, un difetto
  che rendeva inservibile il traduttore NLLB-FT dopo il serbatoio L3 (asimmetria
  A/B), lo scivolamento degli id COMET/GEMBA e alcune granularità di conteggio.

## [1.19.0] — 2026-09-24

Revisione della qualità a 5 revisori indipendenti (trascrizione, traduzione,
diarizzazione/genere, output SRT/sync/OCR, robustezza) + arbitro, poi due
bugcheck Opus sul codice scritto. Le correzioni sotto sono solo quelle con
evidenza misurata; le idee non dimostrate restano fuori (v. in fondo).

### Trascrizione: struttura e tempi dei sottotitoli
- **`core/aligner.py` — il forced alignment non frammenta più i segmenti.**
  `whisperx.align` divide ogni segmento in frasi (nltk punkt): adottare il
  suo output moltiplicava i segmenti (678 → 1696 su un film reale) e
  produceva blocchi-lampo, mentre il ripristino dei timestamp non scattava
  mai. Ora si allinea UN segmento Whisper alla volta e si copiano soltanto i
  tempi wav2vec2 sulle parole Whisper, con guardia (spostamento massimo
  1,5 s, durata massima max(1,5 s, 2× Whisper), niente nuove sovrapposizioni);
  il testo e il numero dei segmenti restano quelli di Whisper. Verificato su
  6 finestre da 5 minuti di un film (1760 parole): segmenti 426 → 169,
  blocchi < 0,83 s 183 → 16, parole più lunghe di 1,5 s 84 → 6. Il beneficio
  è nei tempi INTERNI delle parole (usati dal diarizer per spezzare ai
  cambi di parlante); inizio/fine dei segmenti restano quelli di Whisper.
  Le parole col trattino (Whisper: " Uh" + "-huh.") non fanno più scartare
  l'intero segmento (5/169 → 0/169 mantenuti con i tempi Whisper).
- **`core/subtitle_formatter.py` — leggibilità (nuovo, `readability`,
  chiave `subtitle_readability_enabled`, default True).** Le frasi
  brevissime consecutive restavano blocchi-lampo perché il blocco seguente
  partiva subito dopo. Ora si uniscono le frasi vicine (gap ≤ 0,5 s) dello
  STESSO speaker quando almeno una è troppo breve (< 1,2 s) o troppo veloce
  (> 17 caratteri/s), entro 2 righe e 6 s, e si allunga la fine del blocco
  fino a 17 cps (max 7 s) senza toccare il blocco seguente. Guardie:
  contesto dialogo (non si esclude un blocco a due voci), una risposta breve
  dopo una domanda non si fonde (il diarizer attribuisce le battute sotto le
  3 parole al parlante precedente), confidenza speaker come media pesata sui
  caratteri (il minimo faceva perdere trattini validi). Su Goodrich, con
  speaker: blocchi 2008 → 1652, < 0,83 s 234 → 68, > 20 cps 311 → 160,
  trattini 220 → 222, nessuna sovrapposizione. Con `readability=False`
  l'output è bit-identico al formatter precedente (verificato).
- **Formattazione anche senza diarizzazione**: se la diarizzazione è
  disattivata, fallisce o manca il token HuggingFace, l'SRT viene comunque
  formattato (CPL, durata minima, leggibilità) invece di restare grezzo
  (prima: 24,5% di blocchi a riga singola oltre 42 caratteri). Se il
  formatter fallisce non si sostituisce mai l'SRT grezzo con uno vuoto.
- `subtitle_cleaner`: non inserisce più lo spazio dopo `, : ;` fra due cifre
  ("10:30" → "10: 30", "3,5" → "3, 5").

### Diarizzazione e correzione del genere
- **`diarization_clustering_threshold` di default 0.85 → 0.0 (default di
  fabbrica 0.7046).** Banco `gender_eval` su 8 episodi (63 punti, Veronica
  Mars) sulla mappa voce → genere dello STEP 6.5: soglia di fabbrica,
  automatico: accuratezza 91,9%, copertura 98,4% (23 parlanti medi);
  automatico a 0.85: 86,8% / 60,3%; `num_speakers=10` esatto: 75,0% / 76,2%;
  0.85 con tetto a 10: 77,8% / 57,1%. I cluster fusi abbassano la
  confidenza sotto soglia e la correzione in 1ª persona non scatta. Sul
  dialogo il confronto Goodrich non aveva mostrato differenze. Il
  commento in `config.py` prevedeva proprio di riconsiderare questo valore
  in caso di sovra-fusione.
- Tooltip del numero di parlanti: > 0 è il numero ESATTO (non un massimo) e
  disattiva la soglia di clustering. La causa era un'incomprensione: il
  valore 10 in una config reale forzava 10 cluster su ogni file.

### Robustezza
- **Traduzione fallita** (`core/pipeline.py`, STEP 6-7): un'eccezione in
  factory/callback/traduzione equivale a "traduzione fallita" (prima: fine
  del job senza salvare nulla e cartella temporanea cancellata). Se il file
  di destinazione (es. `X.en.srt`) esiste già NON viene mai sovrascritto: la
  trascrizione/OCR viene conservata in `~/.transcriberpro/recuperati/` e il
  job risulta fallito. Se non esiste, viene salvato nella lingua originale
  ma il job risulta fallito (niente watermark del motore, niente upload).
- **`Config.save()` atomico**: file temporaneo unico per processo + fsync +
  `os.replace` con retry su `PermissionError` di Windows (un test con 2
  processi e un lettore concorrente aveva prodotto oltre 1.200 letture di
  JSON troncato con la versione a nome fisso). Se `config.json` è
  illeggibile ne resta una copia `config.json.illeggibile-<data>` prima che
  i default lo sovrascrivano.
- **`punctuation_restore_mode='auto'`** (nuovo default): segue il motore di
  trascrizione scelto (Canary e Qwen3: `missing`; faster-whisper non usa il
  ripristino). Le modalità `off|missing|all` restano una forzatura globale.
- `core/llm_subtitle_translator/translator.py`: canale di log del gestore
  batch verso lo schermo e reset del ritmo di riferimento (modifiche del
  12/09 già in uso in produzione, mai sincronizzate prima d'ora).

### Verifiche
- Due bugcheck Opus indipendenti sul codice scritto: trovati e corretti
  (perdita del lavoro con traduzione fallita e `X.en.srt` esistente,
  eccezioni di traduzione non gestite, collisione del file temporaneo di
  `Config.save()`, confidenza speaker minima che faceva perdere trattini,
  ripiego del formatter che poteva scrivere un SRT vuoto o ignorare un
  `save()` fallito).
- Test end-to-end su un estratto reale di 5 minuti (trascrizione,
  allineamento, diarizzazione, formattazione, traduzione, correzione genere:
  exit 0) e test del ramo di traduzione fallita.

### Valutato e NON adottato
- WhisperX come motore (stesso decoder; VAD/diarizzazione di default
  diversi), `initial_prompt`/`hotwords`, parametri anti-allucinazione di
  faster-whisper (ignorati in modalità batched) e Demucs a 44,1 kHz senza
  banco WER: nessuno ha dato un beneficio dimostrato.
- Aperti, non toccati: contesto tra battute consecutive nella traduzione
  (i blocchi tagliati a metà frase vengono tradotti come frammenti),
  banco WER per l'ASR, scelta di STEP 1 (sottotitoli non italiani anche con
  audio già italiano), sovrascrittura del sidecar OCR di `X.<lingua>.srt`.

## [1.18.0] — 2026-09-18

### Valutazione `pyannote/speaker-diarization-community-1` come alternativa a 3.1 — verdetto: NON promuovere
Dalla ricerca aggiornamenti venv: pyannote.audio 4.x introduce una pipeline
di diarizzazione più recente (clustering VBx invece di agglomerativo),
con benchmark pubblici migliori su 10/12 dataset. Valutata con lo stesso
rigore del banco `diar_eval/` già esistente (50 coppie etichettate a mano
su un film reale, Goodrich 2024).

- **Infrastruttura aggiunta, comportamento di produzione INVARIATO**:
  nuova chiave `diarization_model` (default `pyannote/speaker-diarization-
  3.1`, il comportamento storico), `Diarizer` accetta un `model_id`
  opzionale, `diar_eval/diar_bench.py` supporta `--model` per l'A/B.
  Verificato con un run di non-regressione: SRT prodotto bit-identico
  (stesso sha256) al run storico pre-refactoring.
- **`core/diarizer.py::_apply_clustering_overrides`**: community-1 usa
  VBxClustering, che ha `threshold` ma NON `min_cluster_size`. Aggiunta
  introspezione (`pipeline.parameters(instantiated=True)`) che scarta con
  avviso visibile i parametri non supportati dal modello caricato, invece
  di lasciarli sparire in un log che poi mente sull'esito. Un bugcheck
  Opus ha trovato che l'`instantiate()` di pyannote applica le chiavi una
  alla volta e solleva sulla prima sconosciuta: se l'introspezione stessa
  falliva, un override misto restava parzialmente applicato con l'except
  che azzerava comunque i valori "effettivi" nel log — corretto applicando
  ogni chiave separatamente.
- **Guardia esplicita** quando si eredita la soglia 0.85 (tarata su 3.1)
  su un modello diverso: su VBx la stessa chiave inizializza solo il
  clustering agglomerativo preliminare (default del modello 0.6,
  intervallo previsto dagli autori 0.5-0.8) — il numero non porta lo
  stesso significato, va ritarato.
- **Campagna A/B sul banco Goodrich** (C0 soglia di fabbrica 0.6, C1 0.7,
  C2 0.8, C3 0.85): nessun arm di community-1 batte la produzione attuale
  (`balanced_acc` 0.906). Il migliore (C3, 0.875) resta sotto la soglia di
  rumore statistico del banco (~4 punti). Confermato dopo il bugcheck che
  il confronto è onesto (`n_unmatched` — coppie senza parlato rilevato —
  pari a 0 su tutti gli arm confrontati). **Nessuna modifica al default di
  produzione.**
- Bug reale trovato e corretto in `diar_eval/diar_bench.py`: `threshold
  or None` collassava "0 esplicito" e "non specificato" sullo stesso ramo
  — l'unico modo di ottenere il default di fabbrica di un modello diverso
  da quello di produzione era scrivere nella config globale, esattamente
  ciò che la regola dello script vieta. Corretto con una sentinella a tre
  vie (`<0`=da config, `0`=default di fabbrica, `>0`=valore esplicito).

## [1.17.1] — 2026-09-18

### Upgrade `llama-cpp-python` 0.3.4→0.3.34 (ricerca aggiornamenti venv)
Da una ricerca sui venv del progetto per margini di miglioramento simili a
quello di Canary: `llama-cpp-python` (serbatoio L3 traduzione,
`fallback_translate_cli.py`) era 31 versioni patch indietro, con feature
di batching nel changelog aggregato dell'intervallo.

- La nota storica in `requirements.txt` ("solo 0.3.4 ha wheel pre-built
  CUDA per Windows cp311") era superata: esistono wheel CUDA Windows per
  ogni versione fino alla 0.3.35 (verificato con `pip install --dry-run`).
- **0.3.35 (latest) è rotta su questa macchina**: carica i tensori del
  modello su GPU senza errori ma va in crash all'inizializzazione del
  contesto (`OSError: Windows Error 0xc000001d`, istruzione illegale —
  sospetto AVX-512 disabilitato via microcode sui core Alder Lake hybrid
  P-core/E-core, non confermato riga per riga). Bisecting empirico
  0.3.4→0.3.35 caricando il GGUF multi-parte Qwen2.5-14B reale con i
  parametri di produzione: 0.3.16/0.3.26/0.3.31/0.3.33/0.3.34 funzionano
  tutte, solo 0.3.35 rompe. **Fermato a 0.3.34**, un solo patch sotto
  latest.
- Verificato end-to-end sul vero script di produzione
  (`fallback_translate_cli.py`, non solo la libreria isolata): traduzione
  di due frasi con glossario attivo, entrambe risolte correttamente.

## [1.17.0] — 2026-09-18

### Batching sulla trascrizione Canary-Qwen-2.5B (GPU sotto il 70% durante le trascrizioni)
Diagnosi partita da un'osservazione dell'utente: la GPU non superava il 70%
durante le trascrizioni con Canary. Causa: `core/engines/canary_cli.py`
chiamava `model.generate()` un chunk audio alla volta (batch_size=1) in un
for-loop sequenziale, mai sfruttando il supporto nativo al batching
dell'API NeMo SALM. Confermato con ricerca: lo script ufficiale NVIDIA
(`examples/speechlm2/salm_generate.py`) usa `batch_size=64` di default per
questo stesso modello, e il suo benchmark pubblico mostra l'inferenza
"offline" (non-streaming, il nostro caso) come la configurazione con il WER
migliore — nessuna prova che il batching degradi la qualità nell'uso
ufficiale.

- **Upgrade `nemo_toolkit`** in `venv_canary/` da 2.7.3 a 3.0.0 (major,
  repo NVIDIA rinominato in `NVIDIA-NeMo/Speech`). Solo il package NeMo,
  torch/CUDA invariati. Verificato che il flusso storico (batch=1)
  continua a funzionare prima di introdurre il batching.
- **Batching implementato**: `canary_cli.py` raggruppa i chunk in batch
  (`canary_batch_size`, default 8, nuova chiave in `utils/config.py`) e
  decodifica ogni riga del tensore risultato invece di assumere
  `answer_ids[0]`. `canary_engine.py` passa il batch size al subprocess.
- **Bugcheck indipendente** (agente Opus) ha trovato e corretto 3 bug
  reali prima della messa in produzione: (1) un disallineamento silenzioso
  testo↔chunk se `generate()` avesse restituito un numero di righe diverso
  dal batch — ora fa fallire esplicitamente invece di corrompere l'output
  in silenzio; (2) `batch_size` letto fuori dal blocco protetto: un valore
  rovinato a mano in config.json faceva crashare il subprocess prima che
  scrivesse l'esito, lasciando solo un "exit code 1" senza motivo nei log;
  (3) il set di token di stop non includeva il pad (che su questo
  tokenizer coincide con `<|endoftext|>`, usato da Qwen anche come
  fine-turno alternativo) — se il modello lo avesse emesso la riga sarebbe
  proseguita fino a `max_new_tokens` con testo spazzatura in coda. Aggiunto
  anche un ripiego che dimezza il batch se la VRAM non basta.
- **Misurato** (GPU reale, 6 clip di durata diversa): testi identici a
  parola per parola tra batch_size=1 e batch_size=6 in 5/6 clip; nella
  sesta le parole coincidono, cambia solo punteggiatura/maiuscole — nessun
  errore di contenuto osservato. VRAM 5,19→5,56 GB (batch 1→6 su 12 GB
  disponibili): il default 8 è misurato sicuro. Ordine dei testi verificato
  stabile anche con batch disuguali e ordine invertito.

## [1.16.2] — 2026-09-17

### Fix: il padding fisso del placeholder di glossario introduceva nuovi artefatti (bugcheck indipendente)
Il fix v1.16.1 aveva chiuso il bug "Garnet"→"Granato" mascherando anche le
identità sul motore LLM e ripulendo a valle, con regex, lo spazio spurio che
il padding `f" {token} "` introduceva vicino a punteggiatura/virgolette.
Un bugcheck indipendente su quel codice ha trovato che la ripulitura a
valle era essa stessa fonte di bug reali, riproducibili con input concreti:

- `"Mornin' Garnet."` → il regex leggeva l'apostrofo dialettale come
  virgoletta di apertura e incollava il placeholder al testo:
  `"Mornin'<GLOSS0>."`.
- `'"Get out," Garnet said.'` → la virgoletta dritta è ambigua (lì chiude,
  non apre) e veniva trattata sempre come apertura: `'"Get out,"<GLOSS0> said.'`.
- Con un glossario attivo ma nessun termine sulla riga, la ripulitura
  riscriveva anche punteggiatura estranea al glossario (es. un'ellissi
  `". . ."` compattata a `"..."`).
- Annidamento musica/glossario in `_unmask_tolerant`: un placeholder di
  glossario dentro un blocco `♪...♪` (es. `"Garnet!\n♪ Sail on, Ark ♪"`)
  veniva cercato nell'ordine sbagliato e dichiarato irrecuperabile pur
  essendo stato tradotto perfettamente — il blocco finiva nel recupero
  senza mascheramento, riaprendo esattamente il bug che il fix chiudeva.

**Correzione**: invece di aggiungere padding e poi ripulirlo con regex
(che devono indovinare se un apostrofo/virgoletta adiacente apre, chiude o
è una contrazione — casi che a volte richiedono l'opposto l'uno
dell'altro), il padding non viene più inserito affatto sul ramo non-NLLB:
il pattern di ricerca del termine è già ancorato a `\b` su entrambi i
lati, quindi il carattere adiacente al termine nel sorgente non è mai un
carattere di parola — il padding non separava nulla che non fosse già
separato, raddoppiava spazi esistenti o ne inventava dove l'autore non li
aveva. Il padding resta solo su NLLB (comportamento pre-esistente,
invariato — non misurato lì). Corretto anche l'ordine di risoluzione in
`_unmask_tolerant` per l'annidamento musica⊃glossario. Verificato: NLLB
bit-identico al pre-fix, tutti i casi sopra puliti senza elencare
apostrofi/virgolette caso per caso.

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
