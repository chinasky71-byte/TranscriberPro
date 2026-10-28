# P16 — contenuto del pacchetto, misura delle Impostazioni dopo PR #73 e prova funzionale

Stato: **FATTO** (numeri e osservazioni raccolti; il criterio SSIM delle Impostazioni resta non raggiunto: 0/21 schermate sopra l'obiettivo). Branch di partenza `webui/main` (`6e48f0f`, PR #73). Windows 10.0.26300, schermo 1920x1080, DPI 96, Edge 156.0.4314.42. HOME isolata, nessuna elaborazione vera, nessuna installazione nuova.

## 1. Cosa pesa nel pacchetto (build P15: exe 1129 MB; contenuto non compresso 1797 MB, 1816 voci)
Fonte: `build\...\PKG-00.toc` della build di prova, dimensioni dei file sorgente. **Le librerie pesanti sono ancora dentro:**
- **`torch` 964 MB** (di cui `torch\lib\cublasLt64_12.dll` 532 MB, `cusparse64_12.dll` 288 MB, `cublas64_12.dll` 105 MB, `nvJitLink_120_0.dll` 39 MB) + `torch-2.8.0+cu126.dist-info`.
- **`cublasLt64_13.dll` 456 MB e `cublas64_13.dll` 52 MB** nella radice (CUDA 13, portate da qualche altra libreria, non da torch che usa CUDA 12.6).
- **`bitsandbytes` 176 MB** (10 DLL `libbitsandbytes_cuda1xx.dll`, ~16-20 MB ciascuna).
- Minori: `numpy.libs` 21 MB, `PIL` 13 MB (di cui `_avif` 8 MB), `cryptography` 10 MB, `hf_xet` 9,5 MB, `lxml` 7 MB, `numpy` 7 MB, `pydantic_core` 5 MB, `_dynet` 3,6 MB, `Cython` 3 MB.
- Circa 1,5 GB dei 1,8 GB sono CUDA/torch/bitsandbytes: la web UI non li usa direttamente ma `main.py`/`core` li importano (percorso Qt/trascrizione). Da escludere nello spec (se il motore gira come sottoprocesso separato) oppure accettare la dimensione.

Elenco (primi gruppi e 30 file piu' grandi, MB non compressi):
```
voci 1816 totale non compresso MB 1797
--- 30 gruppi (primo livello) piu grandi, MB non compressi
   964.1  torch
   455.7  cublasLt64_13.dll
   176.2  bitsandbytes
    51.6  cublas64_13.dll
    29.3  PYZ-00.pyz
    21.0  numpy.libs
    13.4  PIL
     9.9  cryptography
     9.5  hf_xet
     7.0  lxml
     7.0  numpy
     5.8  python311.dll
     5.4  pydantic_core
     5.2  libcrypto-3.dll
     3.6  _dynet.cp311-win_amd64.pyd
     3.3  Cython
     2.4  _soundfile_data
     1.9  torch-2.8.0+cu126.dist-info
     1.8  core
     1.5  sqlite3.dll
     1.4  base_library.zip
     1.3  utils
     1.2  webview
     1.1  unicodedata.pyd
     1.1  ucrtbase.dll
     0.9  pytz
     0.9  _brotli.cp311-win_amd64.pyd
     0.8  libssl-3.dll
     0.8  assets
     0.7  safetensors
--- 30 file piu grandi
   531.8  BINARY torch\lib\cublasLt64_12.dll
   455.7  BINARY cublasLt64_13.dll
   287.6  BINARY torch\lib\cusparse64_12.dll
   104.9  BINARY torch\lib\cublas64_12.dll
    51.6  BINARY cublas64_13.dll
    39.2  BINARY torch\lib\nvJitLink_120_0.dll
    29.3  PYZ    PYZ-00.pyz
    20.4  BINARY numpy.libs\libscipy_openblas64_-9e3e5a4229c1ca39f10dc82bba9e2b2b.dll
    20.0  BINARY bitsandbytes\libbitsandbytes_cuda129.dll
    19.6  BINARY bitsandbytes\libbitsandbytes_cuda128.dll
    17.1  BINARY bitsandbytes\libbitsandbytes_cuda118.dll
    16.7  BINARY bitsandbytes\libbitsandbytes_cuda123.dll
    16.6  BINARY bitsandbytes\libbitsandbytes_cuda122.dll
    16.6  BINARY bitsandbytes\libbitsandbytes_cuda121.dll
    16.6  BINARY bitsandbytes\libbitsandbytes_cuda120.dll
    16.3  BINARY bitsandbytes\libbitsandbytes_cuda126.dll
    16.3  BINARY bitsandbytes\libbitsandbytes_cuda125.dll
    16.2  BINARY bitsandbytes\libbitsandbytes_cuda124.dll
     9.9  EXTENSION cryptography\hazmat\bindings\_rust.pyd
     9.5  EXTENSION hf_xet\hf_xet.pyd
     7.9  EXTENSION PIL\_avif.cp311-win_amd64.pyd
     5.8  BINARY python311.dll
     5.4  EXTENSION pydantic_core\_pydantic_core.cp311-win_amd64.pyd
     5.2  BINARY libcrypto-3.dll
     4.5  EXTENSION numpy\_core\_multiarray_umath.cp311-win_amd64.pyd
     4.1  EXTENSION lxml\etree.cp311-win_amd64.pyd
     3.6  EXTENSION _dynet.cp311-win_amd64.pyd
     3.4  BINARY bitsandbytes\libbitsandbytes_cuda130.dll
     2.6  EXTENSION PIL\_imaging.cp311-win_amd64.pyd
     2.4  BINARY _soundfile_data\libsndfile_x64.dll
```

## 2. Impostazioni, 7 schede: web vs Qt (riferimenti Qt di L-011)
0/21 sopra l'obiettivo. Miglioramento rispetto a P15 modesto, soprattutto su `imp_jobs` (0,86 -> 0,90 a 100%); le piu' lontane restano `imp_opensubtitles` (0,72-0,78), `imp_translation` (0,75-0,80), `imp_batch` (0,75-0,80) e `imp_ocr` (0,76-0,81).

| scala | scheda | SSIM | prima (P15) | diff % | obiettivo | esito |\n|---|---|---|---|---|---|---|\n| 1.0 | imp_batch | 0.7534 | 0.7473 | 4.88 | >= 0.985 | NO |\n| 1.0 | imp_general | 0.8393 | 0.8330 | 3.68 | >= 0.985 | NO |\n| 1.0 | imp_jobs | 0.9020 | 0.8602 | 3.36 | >= 0.985 | NO |\n| 1.0 | imp_ocr | 0.7634 | 0.7780 | 5.41 | >= 0.985 | NO |\n| 1.0 | imp_opensubtitles | 0.7215 | 0.7156 | 6.19 | >= 0.985 | NO |\n| 1.0 | imp_transcription | 0.8337 | 0.8130 | 5.00 | >= 0.985 | NO |\n| 1.0 | imp_translation | 0.7494 | 0.7341 | 6.92 | >= 0.985 | NO |\n| 1.25 | imp_batch | 0.7881 | 0.7865 | 4.54 | >= 0.985 | NO |\n| 1.25 | imp_general | 0.8627 | 0.8561 | 3.46 | >= 0.985 | NO |\n| 1.25 | imp_jobs | 0.9111 | 0.8738 | 3.17 | >= 0.985 | NO |\n| 1.25 | imp_ocr | 0.7984 | 0.8078 | 4.92 | >= 0.985 | NO |\n| 1.25 | imp_opensubtitles | 0.7606 | 0.7581 | 5.82 | >= 0.985 | NO |\n| 1.25 | imp_transcription | 0.8523 | 0.8330 | 4.64 | >= 0.985 | NO |\n| 1.25 | imp_translation | 0.7831 | 0.7683 | 6.66 | >= 0.985 | NO |\n| 1.5 | imp_batch | 0.8041 | 0.8006 | 4.31 | >= 0.97 | NO |\n| 1.5 | imp_general | 0.8696 | 0.8663 | 3.27 | >= 0.97 | NO |\n| 1.5 | imp_jobs | 0.9142 | 0.8818 | 2.96 | >= 0.97 | NO |\n| 1.5 | imp_ocr | 0.8106 | 0.8216 | 4.76 | >= 0.97 | NO |\n| 1.5 | imp_opensubtitles | 0.7763 | 0.7713 | 5.57 | >= 0.97 | NO |\n| 1.5 | imp_transcription | 0.8599 | 0.8444 | 4.40 | >= 0.97 | NO |\n| 1.5 | imp_translation | 0.7970 | 0.7837 | 6.27 | >= 0.97 | NO |

## 3. Prova funzionale a mano nel guscio (HOME isolata, finto Library Scanner locale)
Screenshot (solo finestre dell'app) in `tpweb/proto/results/p16_screens/`.
- **Impostazioni:** si aprono; la lingua si cambia (Auto/Italiano/English) e il valore e' **salvato subito** (non c'e' un pulsante Salva nella scheda Generali: `config.json` della home isolata ha `language: en` subito dopo la scelta); riaperte, mostrano English; riavviando l'app l'interfaccia e' in inglese. Le 7 schede si aprono senza testo tagliato.
- **Strumenti > Glossario per show:** il dialogo si apre; mostra l'avviso «venv_glossary non trovato: crea il venv dedicato…» (atteso in questa cartella di prova, non ho provato l'analisi).
- **Sincronizzazione sottotitoli:** il dialogo si apre con le schede «File singolo» e «Coda (cartelle)»; «Sfoglia…» apre il dialogo nativo di Windows (con la HOME isolata mostra prima «Percorso non disponibile» per `<home>\Desktop`), Esc lo chiude senza effetti. Non ho avviato sincronizzazioni.
- **Library Scanner (finto server locale):** tabella con 3 file, contatore 3, «Importa tutti i filtrati» -> 3 file in coda con segno di spunta nelle righe. Non ho provato OCR/Superpower/ASS in questo giro (gia' coperti in G4).
- Chiusura con coda non al lavoro (anche con 3 file in coda): X chiude senza conferma, nessun processo residuo, `tpweb.lock` rimosso.

### Anomalie viste (nessuna corretta)
1. **Finestra troppo alta per lo schermo 1920x1080:** la finestra nativa da 1400x900 viene posizionata (dopo averla portata in primo piano) a un'origine che la fa sporgere sotto il bordo inferiore dello schermo (es. origine 234,234: l'ultima riga con «Avvia/Ferma» finisce dietro la barra delle applicazioni); in altre aperture era a 26, 130, 156 o 182 px e rientrava. Vedi `finestra_fuori_schermo.png`. Da verificare come sceglie la posizione iniziale `tpweb/shell.py` (centrare e limitare all'area di lavoro).
2. **Primo clic sull'ingranaggio dopo aver chiuso Impostazioni a volte non riapre il dialogo** (mostra solo il tooltip «Impostazioni»; il secondo clic lo apre).
3. **Segnaposto troncati** nella scheda «File singolo» di Sincronizza SRT («Seleziona file .srt da sincronizz…»).
4. **Library Scanner a pannello chiuso/aperto:** con il pannello aperto la tabella mostra ~2,5 righe (scorre); funziona ma e' stretta nello spazio disponibile.
5. Dopo «Percorso non disponibile» nei dialoghi nativi: dovuto alla HOME isolata, da verificare con la HOME vera (non provabile qui).
