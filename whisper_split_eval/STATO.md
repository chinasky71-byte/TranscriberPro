# Stato prova confermativa v2 (25/09/2026) — COMPLETATA

Tutti i passi eseguiti (da whisper_split_eval\, PYTHONIOENCODING=utf-8, ..\venv\Scripts\python.exe):
1. decision_rule_v2.py congelata prima delle misure (sha256 9b95d2ab... in decision_rule_v2.sha256, invariata al verdetto).
2. `fresh_bench.py copy` + `plan`: 91 finestre nuove, 13 film (seme 20260925, margine 10 s dalle 140 usate).
3. `fresh_bench.py prepare`: 89 finestre, 12 film (return-to-silent-hill escluso: sincronia debole).
4. `run_whisper.py --bench-work work_fresh --out-root work_fresh_runs --mode raw|off|on` (89 ciascuno).
5. `analyze_v2.py` -> work_fresh_runs\verdict_v2.json: **NON VINCENTE** (falliscono solo i 3 criteri f; a-e OK).
