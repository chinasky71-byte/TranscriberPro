#!/bin/bash
# Prepara i file italiani indicati (uno per processo, RAM libera >= 22 GB prima di ciascuno) e poi, se richiesto, fa il run raw.
# Uso: bash run_it_prepare.sh <id1> <id2> ...
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
for id in "$@"; do
  free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)")
  for t in 1 2 3 4 5 6 7 8; do
    [ "${free:-0}" -ge 22000 ] && break
    sleep 30
    free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)")
  done
  echo "=== prepare $id | RAM libera ${free} MB | $(date +%H:%M:%S)"
  if [ "${free:-0}" -lt 22000 ]; then echo "RAM insufficiente (${free} MB): mi fermo"; exit 3; fi
  $PY prepare_it.py "$id" >> work_it_prepare.log 2>&1 || { echo "FALLITO prepare $id"; exit 1; }
  sleep 20
done
echo "FINITO prepare"
