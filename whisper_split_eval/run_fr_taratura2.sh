#!/bin/bash
# FRANCESE, taratura: run off/on (GPU) sui 3 file di taratura con il codice attuale, poi blocchi + POS spaCy.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
SPY=../gender_eval/.venv_spacy/Scripts/python.exe
$PY run_whisper.py --bench-work work_fr --out-root work_fr_runs --mode off --lang fr --split-langs en,it > work_fr_run_off.log 2>&1 || { echo "FALLITO off"; tail -5 work_fr_run_off.log; exit 1; }
$PY run_whisper.py --bench-work work_fr --out-root work_fr_runs --mode on --lang fr --split-langs en,it,fr > work_fr_run_on.log 2>&1 || { echo "FALLITO on"; tail -5 work_fr_run_on.log; exit 1; }
$PY export_blocks_fr.py taratura 2>&1 | tail -1
$SPY pos_check_fr.py taratura > work_fr_pos_taratura.log 2>&1; tail -6 work_fr_pos_taratura.log
echo "FINITO $(date +%H:%M:%S)"
