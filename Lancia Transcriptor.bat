@echo off
TITLE Transcriber Pro Launcher

REM Questo script avvia l'applicazione Transcriber Pro,
REM attivando prima l'ambiente virtuale necessario.

ECHO ===================================================
ECHO         Transcriber Pro Launcher
ECHO ===================================================
ECHO.

REM Imposta il percorso completo della cartella del progetto.
SET "PROJECT_PATH=C:\Users\fran_\Desktop\Transcriber_Pro"

ECHO Cartella di lavoro: %PROJECT_PATH%
cd /d "%PROJECT_PATH%"

REM Controlla se il percorso del progetto esiste.
if not exist "%PROJECT_PATH%\main.py" (
    ECHO ERRORE: Il percorso del progetto non e' corretto o il file 'main.py' non e' stato trovato.
    ECHO Controlla la variabile 'PROJECT_PATH' all'interno di questo script.
    ECHO.
    pause
    exit /b
)

REM Attivazione dell'ambiente virtuale (venv).
SET "VENV_PATH=%PROJECT_PATH%\venv\Scripts\activate.bat"
ECHO.
ECHO Sto attivando l'ambiente virtuale...
if not exist "%VENV_PATH%" (
    ECHO ERRORE: Script di attivazione non trovato in:
    ECHO %VENV_PATH%
    ECHO Assicurati che la cartella dell'ambiente virtuale si chiami 'venv'.
    ECHO.
    pause
    exit /b
)

call "%VENV_PATH%"
ECHO Ambiente virtuale attivato.
ECHO.

REM Esecuzione dello script principale dell'applicazione.
ECHO Avvio di Transcriber Pro...
ECHO (Questa finestra del terminale rimarra' aperta per i log)
ECHO.
python main.py

ECHO.
ECHO ===================================================
ECHO Il programma e' stato chiuso. Premi un tasto per uscire.
ECHO ===================================================
pause
