#!/usr/bin/env bash
# Avvia Transcriber Pro su Linux (equivalente di "Lancia Transcriptor.bat"). NON VERIFICATO SU LINUX REALE.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1
if [ ! -f main.py ]; then echo "ERRORE: main.py non trovato in $ROOT"; exit 1; fi
if [ ! -x venv/bin/python ]; then echo "ERRORE: venv non trovato. Esegui prima ./install.sh"; exit 1; fi
# Qt: sotto Wayland senza i plugin dedicati l'app parte meglio via XWayland (xcb). Si rispetta un valore gia' impostato dall'utente.
if [ -z "${QT_QPA_PLATFORM:-}" ] && [ -n "${DISPLAY:-}" ]; then export QT_QPA_PLATFORM=xcb; fi
exec venv/bin/python main.py "$@"
