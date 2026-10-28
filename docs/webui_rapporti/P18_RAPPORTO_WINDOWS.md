# P18 — riprova su Windows dopo la correzione di `lifecycle` (PR #75)

Stato: **FATTO**. Branch di partenza `webui/main` (`64500d6`). Windows 10.0.26300 (11 Pro), Python 3.11.9. HOME isolata, nessuna installazione nuova (cartelle isolate gia' presenti; pytest dal Python di sistema via `ui_bench/tests/run.py`).

## 1. Suite completa (processo unico)
`python ui_bench/tests/run.py -c linux_tests/pytest.ini --rootdir linux_tests -p no:cacheprovider -v --ignore=linux_tests/test_translation_success_gate.py`: **11 falliti, 1357 passati, 131 saltati** (199 s). Log: `p18_pytest_windows.txt`. (P17: 14 falliti, 1351 passati.)
- `test_tpweb_lifecycle.py` e `test_tpweb_tools.py`: **tutti verdi** (i 2 rossi (b) e il test del glossario di P17 ora passano; il figlio del glossario non resta vivo dopo `srv.stop()`).
- Gli 11 rossi restanti sono tutti ambientali/Windows, gia' elencati in C-016: `test_amd_family` x2, `test_amd_rocm_f6`, `test_core_jobs_unit` x3, `test_queue_gui_characterization::test_contratto_del_sottoprocesso`, `test_queue_runner_characterization::test_contratto_del_sottoprocesso`, `test_tpweb_packaging::test_script_di_avvio_senza_percorsi_personali` (bit di esecuzione), `test_tpweb_services::test_cronologia_apri_solo_percorsi_della_cronologia` (`\v` vs `/v`), `test_tpweb_sync::test_singola_ok_progresso_log_e_uscita` (separatori).
- **Nota:** la PRIMA esecuzione della suite si e' interrotta a ~90% con un crash nativo del processo (`0xC0000409`, nel file `test_translation_model_characterization.py`, dialogo Qt): non riprodotto ne' rilanciando quel file da solo (46 passati) ne' rifacendo la suite intera (completa, 1357 passati). Intermittente, come il crash gia' visto in G2; da tenere d'occhio. Rilanciati anche da soli `test_translation_model_service`, `test_translator_path_select`, `test_vram_settle`: verdi (`test_install_retry`: nessun test raccolto).

## 2. Prove a mano (HOME isolata)
| Prova | Esito |
|---|---|
| `python main.py --ui=web --no-browser` | parte (stampa l'indirizzo); un secondo avvio e' RIFIUTATO (exit 3, «un altro server e' gia' in esecuzione») |
| `ui: web` nel config, `python main.py --no-browser` senza flag | parte (stampa l'indirizzo); un secondo avvio e' RIFIUTATO (exit 3) ma con il messaggio «la coda e' gia' in uso da la GUI» invece di «un altro server e' gia' in esecuzione»: il primo server, senza `--ui web` nella riga di comando, e' ancora scambiato per una GUI Qt dal secondo avvio (messaggio fuorviante; il rifiuto c'e'). |
| GUI Qt vera aperta (`python main.py --ui qt`, finestra in primo piano verificata con screenshot) poi web UI | RIFIUTATA in tutte e tre le forme (`main.py --ui web`, `main.py --ui=web`, `python -m tpweb`): exit 3, «la coda e' gia' in uso da la GUI». La GUI resta viva. |

## 3. Giudizio finale
**«Tutti i test previsti sono verdi» = SI**, considerando previsti tutti tranne gli 11 ambientali/Windows elencati sopra. Residuo non bloccante: il messaggio del secondo avvio con `ui: web` senza flag (rifiutato ma con la causa sbagliata) e il crash nativo intermittente `0xC0000409` visto una volta in una corsa intera.
