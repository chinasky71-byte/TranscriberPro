# P15 — rapporto Windows: Qt vs web dopo l'allineamento geometrico, guscio e pacchetto

Stato: **PARZIALE** (numeri e prove raccolti; criterio SSIM ancora non raggiunto). Branch di partenza `webui/main` (`5d5514f`, PR #72). Windows 10.0.26300 (11 Pro), schermo 1920x1080, DPI 96, Edge 156.0.4314.42, Python 3.11.9. HOME isolata; nessuna elaborazione vera; nessuna installazione nuova (cartelle isolate gia' create).

## 1. Aspetto: web vs Qt (riferimenti Qt di L-011)
0/42 schermate sopra l'obiettivo (SSIM >= 0,985 a 100% e 125%, >= 0,97 a 150%).
- Coda a 100%: 0.921-0.938 (prima 0,826-0,921); a 125%: 0.859-0.926; a 150%: 0.840-0.916. A 100% i pannelli sono ora 0,93-0,94 (leftPanel/centerPanel/rightPanel), miniTitleBar 0,954; mainTabBar resta il piu' basso (0,84-0,86); `pipeline` rightPanel 0,89 (150%: 0,74).
- Impostazioni (7 schede): a 100% 0.716-0.860; a 125% 0.758-0.874; a 150% 0.771-0.882: praticamente invariate rispetto a P14 (opensubtitles/translation/batch/ocr le piu' lontane).
- Il miglioramento e' netto solo a 100% sulla Coda; a 125% e 150% la Coda e' invariata (0,83-0,92).

## 2. Guscio nativo (punti 1, 2, 4 di C-012)
- Avvio: finestra presente ~1 s dopo l'avvio del processo, pagina Coda visibile.
- Dialoghi: «Apri» nativo, file in coda. Con HOME isolata compare ancora il messaggio «Percorso non disponibile» (`<home>\Desktop` inesistente) prima del dialogo; il dialogo si apre sull'ultima cartella usata da Windows. Con la HOME vera NON l'ho verificato (non posso toccare `~\.transcriberpro`): il codice (`tpweb/shell.py`, `create_file_dialog` senza `directory`) lascia la scelta della cartella iniziale a Windows.
- Chiusura a coda libera: processo terminato, lock rimosso.
- **Chiusura con coda al lavoro (corretta rispetto a P14):** X -> conferma «Fermare e uscire?» -> «Si»: l'app termina dopo **1,9 s** (misurato sul PID) e `tpweb.lock` sparisce; nessun processo residuo, nessun intervento dell'uscita forzata.

## 3. Pacchetto (`pyinstaller TranscriberProWeb.spec`)
Build in cartella di prova: exit 0 in 196 s (prima 724 s). **`TranscriberProWeb.exe` = 1129 MB** (prima ~3,0 GB). **Si avvia e mostra la pagina Coda**: finestra «Transcriber Pro» dopo **18,1 s** dall'avvio (estrazione del file unico), Responding, nessun errore nello stderr oltre l'avviso TMDB atteso; chiusura a coda libera in 2,6 s, lock rimosso. Nessun modulo mancante registrato. La cartella temporanea `_MEI` e' stata rimossa a fine prova. L'exe (1,1 GB) e' ancora grande: vale la pena controllare cosa porta dentro.

## Tabella per schermata e scala (`p2_confronto.json`)
| scala | stato | SSIM | prima (P14) | diff % | obiettivo | esito |
|---|---|---|---|---|---|---|
| 1.0 | cronologia | 0.9237 | 0.9158 | 1.36 | >= 0.985 | NO |
| 1.0 | filtro_attivi | 0.9355 | 0.8806 | 2.07 | >= 0.985 | NO |
| 1.0 | filtro_coda | 0.9380 | 0.8833 | 1.94 | >= 0.985 | NO |
| 1.0 | filtro_completati | 0.9384 | 0.8838 | 1.93 | >= 0.985 | NO |
| 1.0 | imp_batch | 0.7473 | 0.7475 | 5.05 | >= 0.985 | NO |
| 1.0 | imp_general | 0.8330 | 0.8330 | 3.89 | >= 0.985 | NO |
| 1.0 | imp_jobs | 0.8602 | 0.8606 | 4.46 | >= 0.985 | NO |
| 1.0 | imp_ocr | 0.7780 | 0.7780 | 5.50 | >= 0.985 | NO |
| 1.0 | imp_opensubtitles | 0.7156 | 0.7157 | 6.39 | >= 0.985 | NO |
| 1.0 | imp_transcription | 0.8130 | 0.8132 | 5.53 | >= 0.985 | NO |
| 1.0 | imp_translation | 0.7341 | 0.7341 | 7.36 | >= 0.985 | NO |
| 1.0 | pipeline | 0.9215 | 0.8541 | 2.69 | >= 0.985 | NO |
| 1.0 | righe | 0.9329 | 0.8780 | 2.18 | >= 0.985 | NO |
| 1.0 | vuota | 0.9372 | 0.8823 | 2.28 | >= 0.985 | NO |
| 1.25 | cronologia | 0.9260 | 0.9215 | 1.50 | >= 0.985 | NO |
| 1.25 | filtro_attivi | 0.8832 | 0.8624 | 2.60 | >= 0.985 | NO |
| 1.25 | filtro_coda | 0.8845 | 0.8645 | 2.51 | >= 0.985 | NO |
| 1.25 | filtro_completati | 0.8845 | 0.8643 | 2.51 | >= 0.985 | NO |
| 1.25 | imp_batch | 0.7865 | 0.7867 | 4.60 | >= 0.985 | NO |
| 1.25 | imp_general | 0.8561 | 0.8561 | 3.58 | >= 0.985 | NO |
| 1.25 | imp_jobs | 0.8738 | 0.8742 | 4.02 | >= 0.985 | NO |
| 1.25 | imp_ocr | 0.8078 | 0.8078 | 4.92 | >= 0.985 | NO |
| 1.25 | imp_opensubtitles | 0.7581 | 0.7582 | 5.88 | >= 0.985 | NO |
| 1.25 | imp_transcription | 0.8330 | 0.8332 | 5.03 | >= 0.985 | NO |
| 1.25 | imp_translation | 0.7683 | 0.7683 | 6.93 | >= 0.985 | NO |
| 1.25 | pipeline | 0.8587 | 0.8441 | 3.51 | >= 0.985 | NO |
| 1.25 | righe | 0.8819 | 0.8611 | 2.67 | >= 0.985 | NO |
| 1.25 | vuota | 0.8834 | 0.8673 | 2.87 | >= 0.985 | NO |
| 1.5 | cronologia | 0.9156 | 0.9093 | 1.80 | >= 0.97 | NO |
| 1.5 | filtro_attivi | 0.8675 | 0.8574 | 3.25 | >= 0.97 | NO |
| 1.5 | filtro_coda | 0.8705 | 0.8603 | 3.09 | >= 0.97 | NO |
| 1.5 | filtro_completati | 0.8704 | 0.8603 | 3.09 | >= 0.97 | NO |
| 1.5 | imp_batch | 0.8006 | 0.8008 | 4.38 | >= 0.97 | NO |
| 1.5 | imp_general | 0.8663 | 0.8663 | 3.41 | >= 0.97 | NO |
| 1.5 | imp_jobs | 0.8818 | 0.8821 | 3.76 | >= 0.97 | NO |
| 1.5 | imp_ocr | 0.8216 | 0.8216 | 4.79 | >= 0.97 | NO |
| 1.5 | imp_opensubtitles | 0.7713 | 0.7714 | 5.68 | >= 0.97 | NO |
| 1.5 | imp_transcription | 0.8444 | 0.8445 | 4.76 | >= 0.97 | NO |
| 1.5 | imp_translation | 0.7837 | 0.7837 | 6.55 | >= 0.97 | NO |
| 1.5 | pipeline | 0.8404 | 0.8260 | 4.19 | >= 0.97 | NO |
| 1.5 | righe | 0.8651 | 0.8545 | 3.36 | >= 0.97 | NO |
| 1.5 | vuota | 0.8694 | 0.8618 | 3.56 | >= 0.97 | NO |
