#!/usr/bin/env bash
# Avvia l'interfaccia web di Transcriber Pro su Linux (stampa l'indirizzo; con pywebview installato apre la finestra nativa).
# Opzioni utili: --no-browser (solo l'indirizzo), --shell off|on|auto. NON VERIFICATO SU LINUX REALE (la coda reale richiede il venv completo).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1
if [ ! -f main.py ]; then echo "ERRORE: main.py non trovato in $ROOT"; exit 1; fi
if [ ! -x venv/bin/python ]; then echo "ERRORE: venv non trovato. Esegui prima ./install.sh"; exit 1; fi
exec venv/bin/python main.py --ui web "$@"
