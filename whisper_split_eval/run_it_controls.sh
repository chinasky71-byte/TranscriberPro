#!/bin/bash
# Controlli GPU sul motore MODIFICATO (guardia con lista lingue) e run 'off'/'on' di taratura italiana.
# Sequenziale (una sola GPU). Esce al primo errore, non riprova.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
echo "=== C1 regressione inglese: on (lingue di default) su 2 file v5 | $(date +%H:%M:%S)"
$PY run_whisper.py --bench-work work_full5 --out-root work_ctl_en --mode on --lang en --limit 2 > work_ctl_en.log 2>&1 || { echo FALLITO C1; exit 1; }
echo "=== C2 Wristcutters (italiano) on con lingue di default | $(date +%H:%M:%S)"
$PY run_whisper.py --bench-work work_full5 --out-root work_ctl_it --mode on --lang it --split-langs en > work_ctl_it.log 2>&1 || { echo FALLITO C2; exit 1; }
echo "=== T1 taratura italiana: off | $(date +%H:%M:%S)"
$PY run_whisper.py --bench-work work_it --out-root work_it_runs --mode off --lang it > work_it_run_off.log 2>&1 || { echo FALLITO T1; exit 1; }
echo "=== T2 taratura italiana: on (en,it) | $(date +%H:%M:%S)"
$PY run_whisper.py --bench-work work_it --out-root work_it_runs --mode on --lang it --split-langs en,it > work_it_run_on.log 2>&1 || { echo FALLITO T2; exit 1; }
echo "FINITO $(date +%H:%M:%S)"
