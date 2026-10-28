# Rapporti delle prove su Windows della web UI / Windows test reports of the web UI

Rapporti scritti dalla sessione locale (Windows) durante la costruzione della web UI (`tpweb/`), con la finestra Qt vera come riferimento. Sono il registro delle misure e delle anomalie trovate; le correzioni sono nel codice e in `CHANGELOG.md`. Le immagini e i JSON di misura restano nei branch `webui/*-results` (o sono stati scartati): qui ci sono solo i testi. / Reports written by the local (Windows) session while the web UI was built, using the real Qt window as the reference. They are the record of the measurements and anomalies found; the fixes are in the code and in `CHANGELOG.md`. Images and measurement JSON stay in the `webui/*-results` branches (or were dropped): only the texts are here.

| Rapporto | Contenuto |
|---|---|
| [P2_RAPPORTO_WINDOWS.md](P2_RAPPORTO_WINDOWS.md) | Prime schermate Qt (7 stati x 3 scale) e primo bug dello script di cattura |
| [P14_RAPPORTO_WINDOWS.md](P14_RAPPORTO_WINDOWS.md) | Qt contro web: Coda e 7 schede delle Impostazioni, calibrazione del testo (SSIM, 0/42 sopra l'obiettivo) |
| [P14_GUSCIO_WINDOWS.md](P14_GUSCIO_WINDOWS.md) | Guscio pywebview: avvio, dialoghi nativi, chiusura con coda al lavoro (difetto trovato), pacchetto PyInstaller da 3 GB che non partiva |
| [P15_RAPPORTO_WINDOWS.md](P15_RAPPORTO_WINDOWS.md) | Dopo l'allineamento geometrico: Coda a 100% migliorata, chiusura corretta (1,9 s), pacchetto da 1,1 GB funzionante |
| [P16_PACCHETTO.md](P16_PACCHETTO.md) | Cosa pesava nel pacchetto (torch, CUDA, bitsandbytes), Impostazioni dopo la PR #73, prova funzionale a mano e anomalie |
| [P17_RAPPORTO_WINDOWS.md](P17_RAPPORTO_WINDOWS.md) | Verifica finale: exe da 70 MB, finestra nello schermo, tabella del Library Scanner, suite (14 rossi, 2 di tipo b in `lifecycle`) |
| [P18_RAPPORTO_WINDOWS.md](P18_RAPPORTO_WINDOWS.md) | Riprova dopo la correzione di `lifecycle`: 11 rossi tutti ambientali, via libera all'unione in `master` |
