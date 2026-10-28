# P2 — rapporto Windows: schermate Qt vs web (pagina Coda)

Stato: **PARZIALE**. Qt e web catturati e confrontati con gli script di `tpweb/proto`; **nessuna schermata raggiunge l'obiettivo SSIM** (>= 0,985 a 100% e 125%, >= 0,97 a 150%). Lo screenshot a mano con tre file veri (4a) non e' stato fatto (servono nomi di file da concordare). Nessuna modifica a produzione; `config.json`/`history.json` veri non toccati (HOME isolata dallo script).

## Ambiente
- Windows 10.0.26300 (11 Pro), schermo 1920x1080, DPI di sistema 96 (100%); Edge installato 156.0.4314.42 (`--channel msedge`).
- Interprete: venv di produzione (sola lettura) con `PYTHONPATH` sul clone pulito di `webui/main` (`2e49f2a`). `playwright 1.64.1` installato (OK del proprietario) FUORI dal venv di produzione, in `Desktop\p2_pylibs` (`pip install --target`), usando solo il pacchetto (nessun `playwright install`). SSIM = implementazione numpy dello script (scikit-image non serve).

## Qt (7 stati x 3 scale = 21) e web (6 stati x 3 scale = 18)
Qt: tutte ok. Web: tutte ok, **ma lo stato `pipeline` esiste solo in Qt** (il web ne cattura 6), quindi per `pipeline` non c'e' confronto.

## Errori degli script e come sono stati aggirati (codice del repo NON modificato)
1. `p2_qt_capture.py`: `UnicodeDecodeError: 'charmap'` + `TypeError: 'NoneType' object is not subscriptable` in `run_state` (`subprocess.run(text=True)` decodifica con cp1252). Aggirato con `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`. Fix consigliato: `encoding='utf-8', errors='replace'`.
2. `p2_web_capture.py` con `--channel msedge`: `playwright._impl._errors.TargetClosedError: BrowserType.launch: Target page, context or browser has been closed` — Edge esce con «DevTools remote debugging requires a non-default data directory» / «Failed to get path from PathService for key: 112». Causa: lo script isola `HOME`/`USERPROFILE` prima di lanciare il browser, che eredita l'ambiente e non trova il profilo Windows. Aggirato con un `sitecustomize.py` fuori repo (copia in `p2_windows_env/`) che passa a `launch` l'ambiente originale e aggiunge `--headless=new`. Fix consigliato nello script: `env` originale nel `launch` del browser (e `--headless=new` per Edge recente).

## Confronto (`p2_confronto.json`)
| scala | stato | SSIM schermata | diff % | obiettivo | esito |
|---|---|---|---|---|---|
| 1.0 | cronologia | 0.9188 | 1.43 | >= 0.985 | NO |
| 1.0 | filtro_attivi | 0.8633 | 2.26 | >= 0.985 | NO |
| 1.0 | filtro_coda | 0.8661 | 2.13 | >= 0.985 | NO |
| 1.0 | filtro_completati | 0.8632 | 2.52 | >= 0.985 | NO |
| 1.0 | righe | 0.8574 | 2.79 | >= 0.985 | NO |
| 1.0 | vuota | 0.8654 | 2.46 | >= 0.985 | NO |
| 1.25 | cronologia | 0.9257 | 1.40 | >= 0.985 | NO |
| 1.25 | filtro_attivi | 0.8682 | 3.27 | >= 0.985 | NO |
| 1.25 | filtro_coda | 0.8705 | 3.14 | >= 0.985 | NO |
| 1.25 | filtro_completati | 0.8736 | 2.70 | >= 0.985 | NO |
| 1.25 | righe | 0.8710 | 2.86 | >= 0.985 | NO |
| 1.25 | vuota | 0.8733 | 2.69 | >= 0.985 | NO |
| 1.5 | cronologia | 0.9160 | 1.62 | >= 0.97 | NO |
| 1.5 | filtro_attivi | 0.8675 | 3.12 | >= 0.97 | NO |
| 1.5 | filtro_coda | 0.8703 | 2.97 | >= 0.97 | NO |
| 1.5 | filtro_completati | 0.8703 | 2.97 | >= 0.97 | NO |
| 1.5 | righe | 0.8652 | 3.23 | >= 0.97 | NO |
| 1.5 | vuota | 0.8719 | 2.90 | >= 0.97 | NO |

Pannelli (esempio 100%, `righe`): miniTitleBar 0,906, mainTabBar 0,878, rightPanel 0,871, centerPanel 0,830, leftPanel 0,879; il dettaglio per pannello e scala e' nel JSON. `cronologia` (solo barre) e' la piu' vicina (0,92) ma sotto l'obiettivo; centerPanel e rightPanel sono i piu' lontani.

## 4. (a) Screenshot a mano con tre file veri — NON ESEGUITO
Richiede il server web con una coda di tre file reali del disco (solo nomi): da concordare quali, per non portare nel repo pubblico nomi di file personali.
