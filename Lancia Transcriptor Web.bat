@echo off
TITLE Transcriber Pro (interfaccia web)

REM Avvia Transcriber Pro con l'interfaccia web: una finestra propria (se pywebview e' installato) oppure il browser.
REM Il server resta su questo computer (127.0.0.1) e si chiude con il pulsante "Esci" o chiudendo la finestra.

SET "PROJECT_PATH=%~dp0"
IF "%PROJECT_PATH:~-1%"=="\" SET "PROJECT_PATH=%PROJECT_PATH:~0,-1%"
cd /d "%PROJECT_PATH%"

if not exist "%PROJECT_PATH%\main.py" (
    ECHO ERRORE: 'main.py' non trovato in %PROJECT_PATH%.
    pause
    exit /b 1
)
if not exist "%PROJECT_PATH%\venv\Scripts\activate.bat" (
    ECHO ERRORE: ambiente virtuale 'venv' non trovato. Esegui prima install.bat.
    pause
    exit /b 1
)

call "%PROJECT_PATH%\venv\Scripts\activate.bat"
ECHO Avvio di Transcriber Pro (web)...
python main.py --ui web %*
SET "RC=%ERRORLEVEL%"
IF NOT "%RC%"=="0" (
    ECHO.
    ECHO Il programma e' terminato con codice %RC%. Se dice che un altro server o la GUI sono gia' in uso, chiudili e riprova.
    pause
)
