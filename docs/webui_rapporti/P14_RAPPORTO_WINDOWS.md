# P14 — rapporto Windows: Qt vs web (Coda e Impostazioni)

Stato: **FATTO** (numeri raccolti); **criterio non raggiunto**: 0/42 schermate sopra l'obiettivo (SSIM >= 0,985 a 100% e 125%, >= 0,97 a 150%).
Branch di partenza `webui/p14-validazione` (`caaf8aa`). Nessuna modifica a produzione; config e cronologia veri non toccati (HOME isolata dagli script). Nessuna installazione nuova (playwright gia' in una cartella isolata, fuori dal venv di produzione).

## Ambiente
- Windows 10.0.26300 (11 Pro), schermo 1920x1080, DPI di sistema 96; Edge 156.0.4314.42 (`--channel msedge`); Python 3.11.9; interprete del venv esistente in sola lettura + `playwright` 1.64.1 in cartella isolata.
- Il `sitecustomize.py` del giro precedente NON e' stato usato: con le correzioni nel repository gli script girano senza (Qt 42/42 png, web 42/42 png, nessun errore, `p2_calibrate_text.py --channel msedge` ok in 187 s).

## Sintesi
- Coda: SSIM da 0.826 a 0.921; Impostazioni (7 schede): da 0.716 a 0.882.
- Le Impostazioni sono le piu' lontane: `imp_opensubtitles` (0,72-0,77), `imp_translation` (0,73-0,78), `imp_batch` (0,75-0,80) e `imp_ocr` (0,78-0,82); la piu' vicina e' `imp_jobs` (0,86-0,88).
- Pannelli della Coda a 100%: miniTitleBar 0,905, mainTabBar 0,818-0,835 (il piu' basso), leftPanel 0,88-0,91, centerPanel 0,90, rightPanel 0,87 (con `pipeline` 0,79, a 150% 0,72).
- Calibrazione del testo: frazione di pixel diversi 2,3% con il profilo predefinito, 2,288% con crenatura spenta (miglior profilo); gli altri profili (geometricPrecision, optimizeSpeed, glifi a pixel interi, hinting none) non cambiano (2,3%): il residuo e' il rasterizzatore, non un parametro CSS. Dettaglio in `p2_calibrazione_windows.json`.

## Tabella per schermata e scala (`p2_confronto.json`)
| scala | stato | SSIM | diff % | obiettivo | esito |
|---|---|---|---|---|---|
| 1.0 | cronologia | 0.9158 | 1.52 | >= 0.985 | NO |
| 1.0 | filtro_attivi | 0.8806 | 2.43 | >= 0.985 | NO |
| 1.0 | filtro_coda | 0.8833 | 2.30 | >= 0.985 | NO |
| 1.0 | filtro_completati | 0.8838 | 2.28 | >= 0.985 | NO |
| 1.0 | imp_batch | 0.7475 | 5.05 | >= 0.985 | NO |
| 1.0 | imp_general | 0.8330 | 3.89 | >= 0.985 | NO |
| 1.0 | imp_jobs | 0.8606 | 4.44 | >= 0.985 | NO |
| 1.0 | imp_ocr | 0.7780 | 5.50 | >= 0.985 | NO |
| 1.0 | imp_opensubtitles | 0.7157 | 6.39 | >= 0.985 | NO |
| 1.0 | imp_transcription | 0.8132 | 5.51 | >= 0.985 | NO |
| 1.0 | imp_translation | 0.7341 | 7.36 | >= 0.985 | NO |
| 1.0 | pipeline | 0.8541 | 3.38 | >= 0.985 | NO |
| 1.0 | righe | 0.8780 | 2.54 | >= 0.985 | NO |
| 1.0 | vuota | 0.8823 | 2.63 | >= 0.985 | NO |
| 1.25 | cronologia | 0.9215 | 1.48 | >= 0.985 | NO |
| 1.25 | filtro_attivi | 0.8624 | 3.54 | >= 0.985 | NO |
| 1.25 | filtro_coda | 0.8645 | 3.42 | >= 0.985 | NO |
| 1.25 | filtro_completati | 0.8643 | 3.42 | >= 0.985 | NO |
| 1.25 | imp_batch | 0.7867 | 4.60 | >= 0.985 | NO |
| 1.25 | imp_general | 0.8561 | 3.58 | >= 0.985 | NO |
| 1.25 | imp_jobs | 0.8742 | 3.99 | >= 0.985 | NO |
| 1.25 | imp_ocr | 0.8078 | 4.92 | >= 0.985 | NO |
| 1.25 | imp_opensubtitles | 0.7582 | 5.88 | >= 0.985 | NO |
| 1.25 | imp_transcription | 0.8332 | 5.01 | >= 0.985 | NO |
| 1.25 | imp_translation | 0.7683 | 6.93 | >= 0.985 | NO |
| 1.25 | pipeline | 0.8441 | 4.31 | >= 0.985 | NO |
| 1.25 | righe | 0.8611 | 3.62 | >= 0.985 | NO |
| 1.25 | vuota | 0.8673 | 2.97 | >= 0.985 | NO |
| 1.5 | cronologia | 0.9093 | 1.72 | >= 0.97 | NO |
| 1.5 | filtro_attivi | 0.8574 | 3.58 | >= 0.97 | NO |
| 1.5 | filtro_coda | 0.8603 | 3.42 | >= 0.97 | NO |
| 1.5 | filtro_completati | 0.8603 | 3.42 | >= 0.97 | NO |
| 1.5 | imp_batch | 0.8008 | 4.38 | >= 0.97 | NO |
| 1.5 | imp_general | 0.8663 | 3.41 | >= 0.97 | NO |
| 1.5 | imp_jobs | 0.8821 | 3.74 | >= 0.97 | NO |
| 1.5 | imp_ocr | 0.8216 | 4.79 | >= 0.97 | NO |
| 1.5 | imp_opensubtitles | 0.7714 | 5.68 | >= 0.97 | NO |
| 1.5 | imp_transcription | 0.8445 | 4.75 | >= 0.97 | NO |
| 1.5 | imp_translation | 0.7837 | 6.55 | >= 0.97 | NO |
| 1.5 | pipeline | 0.8260 | 4.79 | >= 0.97 | NO |
| 1.5 | righe | 0.8545 | 3.71 | >= 0.97 | NO |
| 1.5 | vuota | 0.8618 | 3.36 | >= 0.97 | NO |
