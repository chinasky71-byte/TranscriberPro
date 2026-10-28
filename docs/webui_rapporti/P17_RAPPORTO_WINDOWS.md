# P17 — verifica finale su Windows (pacchetto, guscio, Library Scanner, suite di test)

Stato: **PARZIALE** (tutto eseguito; la suite NON e' tutta verde: vedi §4-5). Branch di partenza `webui/main` (`a973596`, PR #74). Windows 10.0.26300 (11 Pro), schermo 1920x1080 (area di lavoro 1920x1032), DPI 96, Edge 156.0.4314.42, Python 3.11.9. HOME isolata, nessuna elaborazione vera, installazioni solo in cartelle isolate (`pip install --target`, gia' presenti dai giri precedenti; pytest dal Python di sistema tramite `ui_bench/tests/run.py`).

## 1. Pacchetto
`pyinstaller TranscriberProWeb.spec`: exit 0 in **68 s** (prima 196 s). **`TranscriberProWeb.exe` = 70 MB** (prima 1129 MB, all'inizio 3,0 GB). Si avvia: finestra «Transcriber Pro» dopo **2,7 s** dall'avvio del processo (prima 18 s), pagina Coda visibile, Responding, solo l'avviso TMDB atteso. Aggiungi file (dialogo nativo) -> in coda; chiusura con coda al lavoro (X -> «Si»): processo terminato in **2,2 s**, `tpweb.lock` rimosso, nessun residuo, nessuna cartella `_MEI` rimasta in TEMP. Nulla di grosso da elencare.

## 2. Guscio: finestra nello schermo
Finestra 1400x900 posizionata a (260,50)-(1660,950): **sta tutta nello schermo (area di lavoro 1032 px), sopra la barra delle applicazioni, centrata** (screenshot in locale). Chiusura con coda al lavoro: X -> «Fermare e uscire?» -> «Si» -> uscita in 2,2 s, lock rimosso (vedi §1).

## 3. Library Scanner (finto server locale)
Con il pannello aperto la tabella mostra **tutte e 3 le righe** del finto server (prima ~2,5) e ha spazio per circa 7-8 righe nella stessa finestra 1400x900 senza scorrere.

## 4. Suite di test locale
`python ui_bench/tests/run.py -c linux_tests/pytest.ini --rootdir linux_tests -p no:cacheprovider -v --ignore=linux_tests/test_translation_success_gate.py` (processo unico, 202 s): **14 falliti, 1351 passati, 131 saltati**. Log: `p17_pytest_windows.txt`.

| Rosso | Tipo | Motivo |
|---|---|---|
| test_amd_family::test_override_applicato_solo_ai_sottoprocessi, ::test_smoke_report_famiglia_percorso_override[gfx1031...], test_amd_rocm_f6::test_smoke_run_py_classifies_results | (a) ambiente | i 3 test AMD/ROCm (script POSIX/ambiente), gia' noti e identici a master da G1-G4 |
| test_core_jobs_unit x3 (runner_contratto, motore_senza_qt, motore_eccezione...), test_queue_gui_characterization::test_contratto_del_sottoprocesso, test_queue_runner_characterization::test_contratto_del_sottoprocesso | (a) ambiente | contratto del sottoprocesso/runner con comandi POSIX, gia' noti e identici a master |
| test_tpweb_packaging::test_script_di_avvio_senza_percorsi_personali | (a) Windows | `run_web.sh` non ha il bit di esecuzione: `os.stat().st_mode & 0o111` e' sempre 0 su NTFS |
| test_tpweb_services::test_cronologia_apri_solo_percorsi_della_cronologia | (a) Windows | atteso `/v`, ottenuto `\v` (separatore dei percorsi) |
| test_tpweb_sync::test_singola_ok_progresso_log_e_uscita | (a) Windows | atteso `/out/Film.it.synced.it.srt`, ottenuto `\out\Film.it.synced.it.srt` (separatori) |
| test_tpweb_tools::test_chiusura_del_server_annulla_il_run_e_non_lascia_processi | (a) con riserva | il test usa `os.kill(pid, 0)` e `/proc` (POSIX): su Windows `os.kill(pid,0)` termina il processo se esiste e non solleva, quindi `DID NOT RAISE` significa che il figlio del glossario era ANCORA VIVO subito dopo `srv.stop()`. Il test non e' valido su Windows, ma segnala un possibile ritardo di chiusura da verificare con un test Windows (psutil) |
| **test_tpweb_lifecycle::test_avvio_vero_secondo_server_rifiutato_e_uscita_ordinata[argv2]** e **::test_config_con_ui_web_avvia_la_web** | **(b) difetto vero su Windows** | `python main.py --ui=web` (o con `ui: web` nel config, senza `--ui web` nella riga di comando) esce con codice 3 e «la coda e' gia' in uso da la GUI: chiudila prima di avviare la web UI». Riprodotto a mano: con `--ui web` parte, con `--ui=web` no. Causa (`tpweb/lifecycle.py::conflicts`): cerca processi con `main.py` e `Transcriber` nella riga di comando e senza la stringa `--ui web`; su Windows il venv avvia `python.exe` come launcher PADRE del vero interprete (stessa riga di comando), quindi il padre della web UI stessa (e `--ui=web` non contiene `--ui web`) viene scambiato per una GUI Qt. Chi imposta `ui: web` nel config (senza flag) non riesce ad avviare la web UI. Non corretto |

## 5. Giudizio finale
**«Tutti i test previsti sono verdi»: NO.**
- Rossi di tipo (b): 2 (`test_avvio_vero_secondo_server_rifiutato_e_uscita_ordinata[argv2]`, `test_config_con_ui_web_avvia_la_web`) — stessa causa, vedi tabella.
- Da chiarire: `test_chiusura_del_server_annulla_il_run_e_non_lascia_processi` (il figlio del glossario risulta vivo dopo lo stop).
- Gli altri 11 rossi sono ambientali/Windows (percorsi, bit di esecuzione, POSIX) o gia' noti.
- Anomalie ancora aperte: nessuna delle quattro di P16 e' stata riprodotta in questo giro tranne «Percorso non disponibile» con HOME isolata (non provabile con la HOME vera). Il primo clic sull'ingranaggio e i segnaposto troncati non sono stati rivisti.
