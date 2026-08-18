@echo off
REM ===================================================================
REM  Riprende la raccolta del corpus per l'addestramento di TranslateGemma.
REM
REM  Si puo' lanciare in qualunque momento, anche dopo uno spegnimento
REM  improvviso: riprende dal punto esatto in cui si era interrotta.
REM  Nessun film viene rilavorato, nessuna coppia viene duplicata.
REM
REM  Per fermarla: chiudere questa finestra o premere Ctrl+C.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo   Raccolta corpus TranslateGemma
echo   ------------------------------
echo   Cartella: %CD%
echo.

if not exist "%~dp0..\venv\Scripts\python.exe" (
    echo   ERRORE: non trovo il venv del progetto.
    echo   Atteso in: %~dp0..\venv\Scripts\python.exe
    pause
    exit /b 1
)

"%~dp0..\venv\Scripts\python.exe" raccogli.py %*

echo.
echo   Raccolta terminata. Il riepilogo e' in raccolta.log
pause
