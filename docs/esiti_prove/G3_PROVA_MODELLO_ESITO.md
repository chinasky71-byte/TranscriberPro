# G3 parte 2 (dialogo del modello di traduzione): esito della prova su Windows (27/10/2026)

Branch provato: `refactor/g3-prova2` (HEAD `6cf8d09`), confrontato con un worktree di master 1.34.39 (`97c6173`). Nessun codice modificato, nessuna unione, produzione e `development` non toccati, niente cancellato. Nel rapporto non ci sono chiavi ne' token (nemmeno finti).

## Ambiente e metodo
- Windows 11, RTX 3060 (non usata). Interprete: venv di produzione solo come eseguibile (cartella di lavoro e `PYTHONPATH` sul clone).
- Dove ho lavorato: clone `Desktop\Transcriber_Pro_G3` (portato su `refactor/g3-prova2`) e worktree di master `Desktop\Transcriber_Pro_G3_master`. Dati isolati in `C:\tp_prova_home_g3b` (nuova; una sottocartella per albero e per prova, 379 KB in totale). Chiavi e token tutti FINTI (`sk-ant-`, `sk-proj-`, `hf_`), generati dallo script.
- **Metodo:** punto 1 con la **GUI vera** (finestra Impostazioni → Traduzione aperta a schermo, 7 schermate scorrendo la scheda, G3 e master a confronto pixel per pixel). Punti 2-12 con il **dialogo vero** (`TranslationModelDialog`, embed e standalone) pilotato da script Python con Qt offscreen e `QMessageBox` registrato (titolo e testo), lo stesso script su G3 e su master, in sequenza, con home separata per albero; il riavvio e' simulato con un processo nuovo.
- **Download di modelli: nessuno.** Ho forzato `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1` nelle prove con token finto; le home di prova restano sotto 400 KB.

## 1. pytest (un solo processo, home isolata, nessuna esclusione)
| Albero | Passati | Falliti | Saltati |
|---|---|---|---|
| master `97c6173` | 815 | 8 | 28 |
| `refactor/g3-prova2` | 919 | 8 | 28 |

Gli 8 falliti sono gli stessi ambientali noti su entrambi (`test_amd_family` x2, `test_amd_rocm_f6`, `test_core_jobs_unit` x3, `test_queue_gui/runner_characterization::test_contratto_del_sottoprocesso`). Nessun crash `0xC0000409` (73 s e 68 s).

## 2. Punti della checklist
| # | Punto | Esito | Dettaglio (G3 identico a master) |
|---|---|---|---|
| 1 | Sezioni, testi, colori | **OK** | Schermate della scheda a 7 posizioni di scorrimento: **0 pixel diversi** tra G3 e master (stessi testi, stati arancione/verde, ordine). |
| 2 | Selezione del modello (embed) | **OK** | Ogni radio salva subito (nllb, nllb_finetuned, llm, claude, opensubtitles, openai); nessun messaggio in embed; la scelta resta dopo il riavvio (openai). |
| 3 | NLLB fine-tuned | **OK** | Vuoto: «Percorso vuoto»; inesistente: «Cartella non trovata»; senza `config.json`: «Cartella non valida»; con `config.json`: «Salvato» e stato «Modello configurato e pronto» (verde). Pulsante «Sfoglia…»: non provato (selettore nativo). |
| 4 | LLM e token HF | **OK** | Percorso: vuoto = salva senza controlli; inesistente: avviso; valido: «Salvato». Token: vuoto «Token vuoto»; `abc`: «Token non valido: deve iniziare con 'hf_'»; finto valido: «Credenziali salvate». |
| 5 | Claude e OpenAI | **OK** | Claude: vuota/`sk-sbagliata` avvisi, chiave finta «Credenziali salvate», stato «Credenziali configurate» (verde), campo riempito dopo il riavvio. OpenAI: «API key vuota»/«troppo corta», finta salvata; modelli gpt-4o-mini / gpt-4o / gpt-4-turbo; il modello scelto (gpt-4-turbo) resta dopo il riavvio (si salva insieme alla chiave). |
| 6 | OpenSubtitles AI | **OK** | Senza credenziali .com: «Credenziali non configurate (vai in Impostazioni > OpenSubtitles)» arancione; con nome/password/API key finti: «Credenziali configurate» verde. |
| 7 | Parametri NLLB | **OK** | Spin beams 1-20, valore 9 salvato; dopo il riavvio 7 (predefinito) nelle prove senza modifica. |
| 8 | Diarizzazione | **OK** | Token: vuoto/`abc`/finto come sopra; URL dei repo per il modello 3.1 (due repo: speaker-diarization-3.1, segmentation-3.0); parlanti 0-10 (0 = «auto»); forced alignment/diarizzazione/parlanti salvati e riletti dopo il riavvio. «Test download» senza token: «Token non configurato. Salvalo prima.» (rosso); con token finto: si avvia il test nel sottoprocesso (6,3 s) ed esito rosso con le ultime righe e «Errore: ... cannot find the requested files» (offline). |
| 9 | Genere | **OK** | Prerequisiti «venv NLP (spaCy) non trovato — token HuggingFace mancante» in rosso, come master; casella e «2ª persona» salvate; dopo una modifica del config (come dalla scheda «Opzioni job») `refresh_from_config` aggiorna la casella. Il verso «Opzioni job -> questa scheda» e' coperto solo da `refresh_from_config`, non dalla GUI. |
| 10 | Forza trascrizione da audio | **OK** | Casella salvata e riletta dopo il riavvio. |
| 11 | Download LLM | **OK** | Senza token: «Token mancante: salva prima il token HuggingFace». Con token (percorso LLM valido impostato): barra indeterminata, parte `core.env_check_cli` (python.exe + conhost), il secondo clic non lancia un secondo processo, termina in 5,4 s con «[OK] Download completato!» (nessun download: modello gia' indicato, offline), 0 processi residui. Esito d'errore del download non provato (il CLI non ha fallito). |
| 12 | Standalone (`save_selection`) | **OK** | Claude e OpenAI senza chiave: domanda «... non configurata. Vuoi configurarla ora?»: Sì = resta nel dialogo; No = avviso «... non funzionerà senza API key» + «Modello aggiornato» e chiusura. NLLB-FT/OpenSubtitles/LLM con i prerequisiti gia' presenti: nessuna domanda, modello aggiornato. Le domande per NLLB-FT e OpenSubtitles senza prerequisiti non sono state provate. |

## 3. Differenze rispetto a master
**Nessuna.** Il confronto automatico delle uscite (messaggi, stati e colori, valori riletti) tra G3 e master ha prodotto una sola differenza: la durata del test pyannote (6,3 s contro 6,5 s).

## 4. Download inattesi
Nessuno.

## 5. Non provato
Interazione con mouse e tastiera sugli altri punti (2-12) nella finestra reale; «Sfoglia…»; esito d'errore del download LLM; domande standalone per NLLB-FT e OpenSubtitles senza prerequisiti; il verso «Opzioni job -> scheda Traduzione» fatto dalla GUI.
