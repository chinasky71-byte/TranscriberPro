#!/bin/bash
# FRANCESE, fase 0 (28/09/2026): prepara i 3 file di taratura (uno per processo, RAM libera >= 20 GB) e fa il run raw
# con il modello di produzione per il francese (whisper-large-v3-french via whisper_model_by_language).
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
freeram() { powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"; }
ids=$($PY -c "import json;print(' '.join(i['id'] for i in json.load(open('work_fr/selection_fr.json',encoding='utf-8'))['items'] if i['set']=='taratura'))")
for id in $ids; do
  free=$(freeram)
  for t in $(seq 1 60); do [ "${free:-0}" -ge 20000 ] && break; sleep 30; free=$(freeram); done
  echo "=== prepare $id | RAM libera ${free} MB | $(date +%H:%M:%S)"
  [ "${free:-0}" -lt 20000 ] && { echo "RAM insufficiente: mi fermo"; exit 3; }
  $PY prepare_fr.py "$id" >> work_fr_prepare.log 2>&1 || { echo "FALLITO prepare $id"; exit 1; }
  sleep 20
done
echo "=== run raw | $(date +%H:%M:%S)"
$PY run_whisper.py --bench-work work_fr --out-root work_fr_runs --mode raw --lang fr --split-langs en,it > work_fr_run_raw.log 2>&1 || { echo "FALLITO raw"; tail -5 work_fr_run_raw.log; exit 1; }
tail -6 work_fr_run_raw.log
echo "FINITO $(date +%H:%M:%S)"
