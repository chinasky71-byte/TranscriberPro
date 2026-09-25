#!/bin/bash
# Prova v5: prepara ogni file in un processo separato (RAM libera >= 18 GB prima di ciascuno),
# poi run Whisper raw/off/on sui file inglesi e off/on sul controllo italiano, poi analisi.
# Se un passo fallisce o la RAM e' insufficiente ESCE (non si riprova da soli).
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
ids=$($PY -c "import json;print(' '.join(i['id'] for i in json.load(open('work_full5/selection_v5.json',encoding='utf-8'))['items']))")
for id in $ids; do
  free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)")
  echo "=== prepare $id | RAM libera ${free} MB | $(date +%H:%M:%S)"
  # attende (max 4 min) che la RAM torni libera dopo il file precedente, poi controlla la soglia
  for t in 1 2 3 4 5 6 7 8; do
    [ "${free:-0}" -ge 22000 ] && break
    sleep 30
    free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)")
  done
  if [ "${free:-0}" -lt 22000 ]; then echo "RAM insufficiente (${free} MB): mi fermo"; exit 3; fi
  $PY prepare_v5.py "$id" >> work_full5_prepare.log 2>&1 || { echo "FALLITO prepare $id"; exit 1; }
  sleep 20
done
$PY prepare_v5.py >> work_full5_prepare.log 2>&1
for m in raw off on; do
  echo "=== run $m en | $(date +%H:%M:%S)"
  $PY run_whisper.py --bench-work work_full5 --out-root work_full5_runs --mode $m --lang en > work_full5_run_${m}_en.log 2>&1 || { echo "FALLITO run $m en"; exit 1; }
done
for m in off on; do
  echo "=== run $m it (controllo) | $(date +%H:%M:%S)"
  $PY run_whisper.py --bench-work work_full5 --out-root work_full5_runs --mode $m --lang it > work_full5_run_${m}_it.log 2>&1 || { echo "FALLITO run $m it"; exit 1; }
done
echo "=== analisi | $(date +%H:%M:%S)"
$PY analyze_v5.py 2>&1 | tail -30
echo FINITO
