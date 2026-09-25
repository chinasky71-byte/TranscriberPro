#!/bin/bash
# Prepara i file della prova v4 UNO PER PROCESSO (memoria): esce se la RAM libera scende sotto 6 GB.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
for id in 02-i-m-not-rappaport-1996 03-paddington-in-peru-2024 04-robert-the-bruce-2019 05-tempest-2025 06-under-the-banner-of-heaven; do
  free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)")
  echo "=== $id | RAM libera ${free} MB | $(date +%H:%M:%S)"
  if [ "${free:-0}" -lt 6000 ]; then echo "RAM insufficiente: mi fermo"; exit 3; fi
  ../venv/Scripts/python.exe prepare_full.py "$id" >> work_full_prepare.log 2>&1 || { echo "FALLITO $id"; exit 1; }
  sleep 20
done
../venv/Scripts/python.exe prepare_full.py >> work_full_prepare.log 2>&1
echo FINITO
ls work_full/win/*/done.json
