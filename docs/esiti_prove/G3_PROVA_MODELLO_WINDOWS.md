# G3 (parte 2: dialogo del modello di traduzione): prova su Windows (sessione locale)

Branch da provare: **`refactor/g3-prova2`** = master (1.34.39) + la PR #46 (modello di traduzione) + le PR #44 e #45 della parte 1. Se la parte 1 è già stata provata, qui conta solo il dialogo del modello. Suite Linux: 893 test (PR #46 da sola) / più sul branch unito. Non unire nulla a master: l'esito va riferito al proprietario.

Dove sta cosa nella GUI: **Impostazioni → scheda «Traduzione»** (`TranslationModelDialog`, embedded): scelta del modello (NLLB-200, NLLB fine-tuned, TranslateGemma_finetuned, Claude API, OpenSubtitles AI, OpenAI GPT), percorsi, chiavi API, token HuggingFace, scarico del modello LLM, diarizzazione (+ test pyannote), correzione del genere, forza trascrizione da audio. Esiste anche in versione standalone (`save_selection` con le domande di conferma).

## 0. Preparazione e sicurezza
1. Clone di `refactor/g3-prova2` (o aggiorna il clone G3) + worktree di master per i confronti. Interprete: venv di produzione solo come eseguibile; nessuna scrittura in produzione.
2. **Isola i dati**: `$env:USERPROFILE = "C:\tp_prova_home_g3b"; $env:HOME = $env:USERPROFILE` (nuova, vuota). Tutte le chiavi e i token usati sono **FINTI** (es. `sk-ant-` + 40 caratteri a caso, `sk-proj-` + 40, `hf_` + 30): non inserire MAI chiavi vere, non scriverle nel rapporto.
3. **Nessun download reale di modelli**: i punti sul download LLM e sul test pyannote si provano con token finti e l'esito atteso è un ERRORE (token rifiutato/rete) o l'avviso «token mancante»; se parte un download vero di GB, interrompi subito e riferiscilo. Per vedere il percorso di successo lo copre il test automatico (CLI finto).

## 1. Automatica
`python -m pytest linux_tests -q` in un solo processo, home isolata, nessuna esclusione; riporta passati/falliti/saltati e confronta con master (attesi solo gli 8 ambientali noti; nessun crash 0xC0000409). Test di G3 parte 2: `test_translation_model_characterization.py`, `test_translation_model_service.py`.

## 2. Manuale, GUI vera (confronto con master punto per punto)
1. Impostazioni → Traduzione: stesse sezioni, stessi testi, stessi colori degli stati («Configurato» in verde, «Non configurato» in arancione), nello stesso ordine. Screenshot affiancato a master.
2. **Selezione del modello** (embed): cliccando ogni radio la scelta si salva subito; riavvia: la scelta resta. Nessun dialogo di conferma in modalità embed.
3. **NLLB fine-tuned**: percorso vuoto → avviso; percorso inesistente → avviso; cartella senza `config.json` → avviso «cartella non valida»; cartella con `config.json` (creane una finta) → «Percorso salvato» e stato «Configurato». Pulsante «Sfoglia…» apre il selettore sulla cartella corrente o sulla home.
4. **LLM**: stessi controlli del percorso (vuoto = predefinito, salva senza controlli). Token HF: vuoto → avviso; formato errato → avviso con il messaggio; valido (finto `hf_...`) → «Credenziali salvate».
5. **Claude API**: vuota/errata (`sk-sbagliata`) → avvisi; chiave finta valida nel formato → salvata, stato «Configurato», e dopo il riavvio il campo è riempito. **OpenAI**: idem con `sk-proj-...` e scelta del modello (gpt-4o-mini / gpt-4o / gpt-4-turbo) salvata.
6. **OpenSubtitles AI**: lo stato segue le credenziali .com salvate nella scheda OpenSubtitles (nome utente, password, API key) — prova a entrambi gli stati.
7. **Parametri NLLB**: spin dei beams (1-20) salvato al volo.
8. **Diarizzazione**: token HF (stessa convalida; salvandolo si aggiorna anche il campo del traduttore LLM e viceversa dopo il riavvio), testo con gli URL dei repo (3.1 → due URL; altro modello → uno), «Test download» senza token → avviso rosso; con token finto → si avvia il test (righe di avanzamento, poi esito rosso con le ultime 4 righe); forced alignment, diarizzazione e numero parlanti (0 = Auto, max 10) salvati.
9. **Genere**: stato dei prerequisiti (venv NLP e token HF) come master; casella e «2ª persona» salvate; la casella «Correzione del genere» cambiata nella scheda «Opzioni job» si riflette qui (e viceversa).
10. **Forza trascrizione da audio**: casella salvata.
11. **Download LLM**: senza token → avviso «salva prima il token»; con token finto → barra indeterminata, poi esito d'errore; mentre è in corso un secondo clic non fa nulla. Nessun processo python/transformers/torch lanciato dalla GUI (Task Manager: solo il sottoprocesso `core.env_check_cli`, che poi termina).
12. **Standalone** (se raggiungibile dalla GUI, es. dal menu): scegli Claude/OpenAI/NLLB-FT senza prerequisiti → compaiono le domande di conferma con gli stessi testi e lo stesso comportamento di master (Sì = resta, No = avviso e salva), OpenSubtitles al contrario (No = resta).

## 3. Riferire
Per ogni punto: OK / differenza (testo o schermata) rispetto a master; allega pytest. Non correggere il codice. Nel rapporto NON riportare chiavi né token (anche finti).
