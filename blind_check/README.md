# blind_check: controllo alla cieca della ricomposizione delle frasi

Confronta, su file reali della libreria, la traduzione normale (`base`) con quella con
`translation_recompose_sentences` accesa (`ricomposta`), senza sapere quale sia quale.
La regola di decisione e' congelata in `decision_rule.py` (25/09/2026).

Ordine (da `Transcriber_Pro`, con `set PYTHONIOENCODING=utf-8`, mai con la coda di Transcriber Pro attiva):

1. `venv\Scripts\python.exe blind_check\select_files.py` — sceglie 5 film (Y:, W:) e 3 episodi (V:) con audio
   inglese e ritaglia 20 minuti da ciascuno in `work\excerpts` (solo rete/CPU). Il campione si congela in
   `work\selection.json`.
2. `venv\Scripts\python.exe blind_check\run_phase1.py` — pipeline reale (GPU) su ogni estratto con il motore assegnato
   (whisper / qwen3 in alternanza); cattura l'SRT inglese che andrebbe al traduttore in `work\src`.
3. `venv\Scripts\python.exe blind_check\run_phase2.py` — traduce lo stesso SRT due volte con NLLB-FT (GPU):
   `work\tr\<id>\base.srt` e `ricomposta.srt`.
4. `venv\Scripts\python.exe blind_check\make_sheet.py` — crea `work\foglio\lotto_NN.txt` (25 coppie a lotto, A/B
   scambiati a caso), `work\giudizi.txt` da compilare e la mappatura nascosta `work\NON_APRIRE_mappatura.json`.
5. L'utente legge i lotti e compila `work\giudizi.txt` (una riga per coppia: `P012|A|`, `P012|B|`, `P012|P|`;
   lettere `a`/`b` dopo la seconda barra per un difetto visibile, es. `P012|B|a`).
6. `venv\Scripts\python.exe blind_check\conta.py` — conteggio, difetti e verdetto (PROMUOVI / ARCHIVIA /
   INSUFFICIENTE) secondo la regola congelata.

Test (CPU): `cd blind_check\tests` poi `..\..\venv\Scripts\python.exe -m unittest test_blind`.
`work\` e' escluso da git (contiene audio e sottotitoli dei film).
