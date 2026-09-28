#!/bin/bash
# TEDESCO, taratura: run off/on (GPU) sui 3 file di taratura con il codice attuale, poi blocchi + POS spaCy.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
SPY=../gender_eval/.venv_spacy/Scripts/python.exe
$PY run_whisper.py --bench-work work_de --out-root work_de_runs --mode off --lang de --split-langs en,it > work_de_run_off.log 2>&1 || { echo "FALLITO off"; tail -5 work_de_run_off.log; exit 1; }
$PY run_whisper.py --bench-work work_de --out-root work_de_runs --mode on --lang de --split-langs en,it,fr,de > work_de_run_on.log 2>&1 || { echo "FALLITO on"; tail -5 work_de_run_on.log; exit 1; }
$PY export_blocks_de.py taratura 2>&1 | tail -1
$SPY pos_check_de.py taratura > work_de_pos_taratura.log 2>&1; tail -6 work_de_pos_taratura.log
echo "FINITO $(date +%H:%M:%S)"
