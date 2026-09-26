@echo off
rem Avvia install.ps1 con la politica di esecuzione solo per questo processo. Argomenti: gli stessi di install.ps1
rem (esempio: install.bat -CheckOnly  /  install.bat -InstallSystemDeps -WithNlp  /  install.bat -All -Yes)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
