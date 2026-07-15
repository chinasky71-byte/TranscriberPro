# Redesign Gender Corrector — Piano esecutivo

> Stato: pianificato (2026-07-15). Branch di lavoro: `gender-corrector-redesign`.
> Nessun codice ancora scritto. Prerequisito: completare la Fase 0 prima di ogni altra fase.

## 1. Diagnosi — perché l'attuale STEP 6.5 fallisce

L'attuale `core/gender_corrector.py` chiede a Qwen2.5-14B Q4 di *scoprire* gli errori di
genere leggendo solo il testo italiano (+ testo inglese e lista cast TMDB). È un compito
mal posto:

1. **Il genere di chi parla non è nel testo.** I sottotitoli non hanno etichette parlante;
   "I'm tired" non dice se il parlante è uomo o donna. Nessun LLM può correggerlo così.
2. La lista cast TMDB (nome→M/F) è quasi inutile: il nome del personaggio raramente
   compare nella riga da correggere.
3. Il pre-filtro regex è troppo largo (`il/la + parola` matcha quasi ogni riga italiana)
   → il LLM elabora tutto il file.
4. Il formato patch `[N] parola → parola` è fragile (parsing, case, match nel testo).

## 2. Fondamenta dalla ricerca (2024-2025)

- **arXiv 2501.05989** (Microsoft, 2025): con il genere del parlante noto, GPT-4
  10-shot + chain-of-thought che riscrive SOLO le parole marcate riferite al parlante
  raggiunge **93-94% accuratezza EN→IT/ES** (+70% assoluto per parlanti donne su
  MuST-SHE). Filtrano solo frasi in prima persona (I/my ≈ 19% del corpus).
  Baseline senza genere: 8-10%.
- **arXiv 2407.15154** (GoE prompting): annotazioni "for X use she/her" nel prompt →
  94-96%; NLLB da solo 82-88%. Più entità con generi diversi nella stessa frase →
  accuratezza -24%.
- **MuST-SHE (FBK, mt.fbk.eu/must-she)**: benchmark EN→IT con forme di genere annotate
  → misurabilità.
- **Genere della voce**: embedding ECAPA-TDNN + classificatore → 97-99% su parlato
  pulito (es. github.com/griko/voice-gender-classification). In pipeline abbiamo già
  pyannote diarization e Demucs vocals.

**Principio del redesign**: da "trova errori alla cieca" a "sappiamo CHI parla e di che
genere è → riscrivi le forme riferite al parlante". Categorie:
- 1ª persona → genere del PARLANTE → risolvibile dall'audio (grosso degli errori).
- 2ª persona → genere dell'interlocutore → inferibile dai turni di dialogo (opzionale).
- 3ª persona → l'inglese di solito disambigua (he/she) → fuori scope iniziale.

## 3. Fasi

### Fase 0 — Harness di valutazione (PRIMA di tutto)
- Scaricare MuST-SHE EN-IT; script di misura gender accuracy F/M sulle forme marcate.
- Mini test-set personale: 3-4 film/episodi con protagonista femminile, ~100 righe con
  ground truth manuale.
- Misurare baseline: NLLB finetuned da solo, e attuale gender corrector
  (atteso ≈0 o peggiorativo).
- Output: script riutilizzabile + numeri di riferimento. Senza questa fase non si
  procede: ogni fase successiva va misurata.

### Fase 1 — Speaker gender map dall'audio (nuovo `core/speaker_gender.py`)
- Diarization pyannote: riusare quella della trascrizione quando disponibile;
  altrimenti pass dedicato (serve anche per il percorso "traduzione di sub embedded"
  dove non c'è trascrizione).
- Per cluster speaker: embedding ECAPA-TDNN mediato su tutti i segmenti →
  classificatore genere → (genere, confidenza).
- Output: mappa tempo→(speaker, genere, confidenza). Ogni riga SRT eredita il genere
  via overlap timestamp.
- Confidenza bassa (bambini, musica, voci borderline) → UNKNOWN → riga non toccata.
  Il "principio di prudenza" passa dal prompt al codice.

### Fase 2 — Selettore righe target (sostituisce le regex attuali)
- Candidata SOLO se: (a) fonte inglese con riferimento 1ª persona (I, I'm, my, we...)
  E (b) italiano con forme potenzialmente marcate legate alla 1ª persona
  (sono/ero/mi sento/sarò + participio/aggettivo).
- Opzione robusta: spaCy `it_core_news_lg` (features Gender=/Person=) per predicati
  copulari in 1ª persona.
- Attese: ~5-15% delle righe candidate → costo LLM ridotto di un ordine di grandezza.

### Fase 3 — Riscrittura vincolata + validatore deterministico
- Prompt stile Microsoft: dato (riga IT, riga EN, GENERE PARLANTE=F/M), riscrivi
  l'INTERA riga cambiando solo le parole marcate riferite al parlante. Output = riga
  completa (niente patch). 10-shot + chain-of-thought.
- Motori intercambiabili:
  - Qwen2.5 locale (il 14B esistente; valutare 7B → meno VRAM, il task vincolato è
    molto più facile del vecchio);
  - Claude/OpenAI già integrati in `core/translator.py` — col pre-filtro parliamo di
    centesimi a film.
- **Validatore deterministico** (anti-allucinazioni): diff parola-per-parola tra riga
  originale e riscritta; accetta SOLO se ogni parola cambiata è una coppia di flessione
  di genere plausibile (-o/-a, -i/-e, il/la, un/una, quello/quella, lui/lei, mio/mia...).
  Qualsiasi altra differenza → scarta l'intera riga. Allucinazioni impossibili per
  costruzione.

### Fase 4 — Seconda persona (opzionale, solo dopo validazione misurata di 1-3)
- Interlocutore = parlante del turno adiacente (dai turni diarization). Soglia di
  confidenza più alta della 1ª persona.

### Fase 5 — Integrazione pipeline + UI
- STEP 6.5 diventa: gender map → selezione → riscrittura → validazione → applica.
  Stesso isolamento subprocess (`core/gender_corrector_cli`).
- Config: motore (locale/cloud), soglia confidenza, toggle 2ª persona.
- Log: N candidate, N riscritte, N scartate dal validatore.

## 4. Alternative considerate e scartate

- **Fine-tuning NLLB "3-mode" con tag genere** (approccio Microsoft completo): risolve
  alla radice ma richiede milioni di frasi riscritte con GPT-4 + training; e il genere
  del parlante serve comunque a runtime. ROI cattivo vs post-edit vincolato.
- **Ritradurre tutto con LLM cloud con contesto**: non risolve la 1ª persona (l'inglese
  non contiene il genere del parlante) e costa molto di più.

## 5. Rischi e mitigazioni

- Audio film sporco (musica/effetti) → Demucs vocals + aggregazione per cluster +
  soglia confidenza.
- Righe di dialogo doppie ("- ... - ...") con timestamp condiviso → gestire con cautela
  o skip.
- Narratore/voice-over/voci atipiche → UNKNOWN → skip.
- MuST-SHE è TED (monologhi): valida la riscrittura, non la diarization → per
  l'end-to-end serve il test-set personale.

## 6. Riferimenti

- https://arxiv.org/abs/2501.05989 — Addressing speaker gender bias in large scale
  speech translation systems (Microsoft, 2025)
- https://arxiv.org/html/2407.15154 — Fine-grained Gender Control in MT with LLMs
- https://mt.fbk.eu/must-she/ — MuST-SHE benchmark (FBK)
- https://arxiv.org/pdf/2006.05754 — Gender in Danger? (MuST-SHE, EN-IT)
- https://github.com/griko/voice-gender-classification — ECAPA-TDNN + SVM
- https://arxiv.org/html/2309.03175v2 — Gender-specific MT with LLMs
