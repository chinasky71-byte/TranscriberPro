#!/bin/bash
# Prova ITALIANA: (1) codice finale su taratura + regressione inglese/italiano, (2) preparazione dei file di conferma
# (uno per processo, Demucs a chunk, pulizia RAM di produzione), (3) run raw/off/on, (4) analisi con la regola congelata.
# Sequenziale. Riprova (max ~2 h) se la GPU e' occupata; esce al primo errore vero. Non modificare mentre gira.
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
export ASR_EVAL_ALLOW_GUI=1      # app aperta ma inattiva: la guardia del banco lo ammette (vedi asr_eval/runners.py)
PY=../venv/Scripts/python.exe
SPY=../gender_eval/.venv_spacy/Scripts/python.exe

retry() {   # retry <log> <comando...>
  local log=$1; shift
  for t in $(seq 1 120); do
    "$@" > "$log" 2>&1 && return 0
    local rc=$?
    if grep -aq "GPU non libera" "$log"; then echo "   GPU occupata, riprovo fra 60 s ($t)"; sleep 60; continue; fi
    return $rc
  done
  return 9
}
freeram() { powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"; }

echo "=== S1 taratura: on con il codice finale | $(date +%H:%M:%S)"
retry work_it_run_on_final.log $PY run_whisper.py --bench-work work_it --out-root work_it_runs --mode on --lang it --split-langs en,it --force || { echo FALLITO S1; exit 1; }
echo "=== S2 regressione inglese (2 file v5) | $(date +%H:%M:%S)"
retry work_ctl_final_en.log $PY run_whisper.py --bench-work work_full5 --out-root work_ctl_final_en --mode on --lang en --limit 2 || { echo FALLITO S2; exit 1; }
echo "=== S3 Wristcutters con lingue di default | $(date +%H:%M:%S)"
retry work_ctl_final_it.log $PY run_whisper.py --bench-work work_full5 --out-root work_ctl_final_it --mode on --lang it --split-langs en || { echo FALLITO S3; exit 1; }
$PY regression_check.py || { echo FALLITO regression_check; exit 1; }
$PY export_blocks_it.py taratura > /dev/null 2>&1 && $SPY pos_check_it.py taratura > work_it_pos_taratura.log 2>&1

ids=$($PY -c "import json;print(' '.join(i['id'] for i in json.load(open('work_it/selection_it.json',encoding='utf-8'))['items'] if i['set']=='conferma'))")
for id in $ids; do
  free=$(freeram)
  for t in 1 2 3 4 5 6 7 8; do
    [ "${free:-0}" -ge 16000 ] && break
    sleep 30; free=$(freeram)
  done
  echo "=== prepare $id | RAM libera ${free} MB | $(date +%H:%M:%S)"
  if [ "${free:-0}" -lt 16000 ]; then echo "RAM insufficiente (${free} MB): mi fermo"; exit 3; fi
  retry work_it_prepare_$id.log $PY prepare_it.py "$id" || { echo "FALLITO prepare $id"; exit 1; }
  cat work_it_prepare_$id.log >> work_it_prepare.log
  sleep 20
done
$PY prepare_it.py >> work_it_prepare.log 2>&1

for m in raw off; do
  echo "=== run $m it | $(date +%H:%M:%S)"
  retry work_it_run_${m}_conf.log $PY run_whisper.py --bench-work work_it --out-root work_it_runs --mode $m --lang it || { echo "FALLITO run $m"; exit 1; }
done
echo "=== run on it (en,it) | $(date +%H:%M:%S)"
retry work_it_run_on_conf.log $PY run_whisper.py --bench-work work_it --out-root work_it_runs --mode on --lang it --split-langs en,it || { echo "FALLITO run on"; exit 1; }

echo "=== analisi | $(date +%H:%M:%S)"
$PY export_blocks_it.py conferma 2>&1 | tail -2
$SPY pos_check_it.py conferma > work_it_pos_conferma.log 2>&1; tail -6 work_it_pos_conferma.log
$PY analyze_it.py --set conferma --rule decision_rule_it 2>&1 | tail -25
echo "--- taratura (per riferimento)"
$PY analyze_it.py --set taratura --rule decision_rule_it 2>&1 | tail -22
echo "FINITO $(date +%H:%M:%S)"
