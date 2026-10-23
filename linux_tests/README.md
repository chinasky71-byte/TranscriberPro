# linux_tests

Test portabili (nessuna GPU, nessun modello, nessun Qt): `python -m pytest linux_tests -q` dalla radice del progetto, dopo `pip install -r linux_tests/requirements.txt` (bastano queste 4 dipendenze: nessun torch, nessun Qt).

Copie dei test di `ui_bench/tests` (che non e' nel repo); se ne cambi uno, aggiorna anche l'originale del proprietario o segnalalo nel PR.
