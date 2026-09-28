#!/bin/bash
# FRANCESE, conferma (regola decision_rule_fr.py congelata, sha in decision_rule_fr.sha256): prepara i 9 file di
# conferma (uno per processo, RAM libera >= 20 GB), run raw/off/on, blocchi + POS, verdetto. Non modificare mentre gira.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
PY=../venv/Scripts/python.exe
SPY=../gender_eval/.venv_spacy/Scripts/python.exe
freeram() { powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"; }
retry() { local log=$1; shift
  for t in $(seq 1 120); do "$@" > "$log" 2>&1 && return 0; local rc=$?
    if grep -aq "GPU non libera" "$log"; then echo "   GPU occupata, riprovo fra 60 s ($t)"; sleep 60; continue; fi
    return $rc; done; return 9; }
ids=$($PY -c "import json;print(' '.join(i['id'] for i in json.load(open('work_fr/selection_fr.json',encoding='utf-8'))['items'] if i['set']=='conferma'))")
for id in $ids; do
  free=$(freeram)
  for t in $(seq 1 60); do [ "${free:-0}" -ge 20000 ] && break; sleep 30; free=$(freeram); done
  echo "=== prepare $id | RAM libera ${free} MB | $(date +%H:%M:%S)"
  [ "${free:-0}" -lt 20000 ] && { echo "RAM insufficiente: mi fermo"; exit 3; }
  retry work_fr_prepare_$id.log $PY prepare_fr.py "$id" || { echo "FALLITO prepare $id"; tail -5 work_fr_prepare_$id.log; exit 1; }
  cat work_fr_prepare_$id.log >> work_fr_prepare.log; grep -a "pronto in\|NON valido" work_fr_prepare_$id.log | tail -1
  sleep 20
done
$PY prepare_fr.py >> work_fr_prepare.log 2>&1
for m in raw off; do
  echo "=== run $m | $(date +%H:%M:%S)"
  retry work_fr_run_${m}_conf.log $PY run_whisper.py --bench-work work_fr --out-root work_fr_runs --mode $m --lang fr --split-langs en,it || { echo "FALLITO run $m"; exit 1; }
done
echo "=== run on (en,it,fr) | $(date +%H:%M:%S)"
retry work_fr_run_on_conf.log $PY run_whisper.py --bench-work work_fr --out-root work_fr_runs --mode on --lang fr --split-langs en,it,fr || { echo "FALLITO run on"; exit 1; }
echo "=== analisi | $(date +%H:%M:%S)"
$PY export_blocks_fr.py conferma 2>&1 | tail -1
$SPY pos_check_fr.py conferma > work_fr_pos_conferma.log 2>&1; tail -6 work_fr_pos_conferma.log
$PY analyze_fr.py --set conferma --rule decision_rule_fr 2>&1 | tail -22
echo "FINITO $(date +%H:%M:%S)"
