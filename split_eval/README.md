# split_eval: misura dei blocchi a metà frase

Rimane solo la misura `midcut` (quota di blocchi che finiscono a metà frase), usata dal banco ASR `asr_eval`:

- `midcut.py`: modulo puro (solo `re`), lo importa `asr_eval/metrics.py` e `asr_eval/asr_bench.py`.
- `prodmods.py`: carica il `SubtitleFormatter` di produzione per percorso, senza torch.
- `tests/test_midcut.py`: test della metrica (`cd split_eval\tests; ..\..\venv\Scripts\python.exe -m unittest test_midcut`).

## Vicolo cieco: ricomposizione delle frasi spezzate (chiuso il 25/09/2026)

L'idea era riunire i blocchi spezzati a metà frase, tradurre la frase intera con NLLB e ridistribuire il testo tradotto sui blocchi originali. Il codice (`core/sentence_recompose.py`, opzione `translation_recompose_sentences`, prototipo e banco in questa cartella) è stato rimosso nella 1.20.1.

Perché è stato chiuso:
- GEMBA e COMET (giudici automatici) davano un vantaggio netto, ma il controllo umano alla cieca su 100 coppie di file reali (8 titoli) non l'ha confermato: ricomposizione 38, base 30, pari 32; quota 55,9% fra i non pari, p unilaterale 0,198. Regola congelata: ARCHIVIA.
- Causa individuata nelle coppie segnalate: in 13 casi su 22 la traduzione ricomposta perde una parte del testo (di solito la coda dell'unità: NLLB riassume o tronca l'input lungo). La guardia esistente scattava solo per uscite enormi e non vedeva un testo troppo corto.
- Il guadagno atteso, anche correggendo le omissioni, è modesto (circa 63% fra i non pari, stima post hoc) e richiederebbe nuovo banco, nuova regola e altri 100 giudizi umani.

I giudizi, la mappatura e il report del controllo alla cieca sono in `results/blind_check_2026-09-25/`.
Un'eventuale ripresa dovrebbe partire da una guardia di copertura (confronto della lunghezza dell'unità tradotta con la somma delle traduzioni per blocco), poi banco e regola nuovi.
