# Gender Eval — Fase 0 del redesign Gender Corrector

Harness di misura dell'accuratezza di genere della traduzione EN→IT.
Vedi `PIANO_GENDER_CORRECTOR_REDESIGN.md` (root del progetto) per il contesto.

## Benchmark: MT-GenEval (Amazon Science, EMNLP 2022)

- Fonte: https://github.com/amazon-science/machine-translation-gender-eval (CC-BY-SA-3.0)
- Subset EN→IT in `mt_geneval/data/`: 300 frasi test per genere, in doppia
  variante controfattuale (maschile/femminile) con parole marcate annotate
  `<M>`/`<F>` nei file `annotated/`.
- Copre soprattutto il genere di **entità nel testo** (terza persona).
  Il caso **prima persona/parlante** (non deducibile dal testo) sarà misurato
  con il test-set personale sui film (vedi piano, Fase 0.2).

Nota: **MuST-SHE** (FBK) sarebbe il benchmark ideale per la prima persona
(categorie 1F/1M legate al genere del parlante) ma non è più scaricabile
pubblicamente — la pagina https://mt.fbk.eu/must-she/ è stata rimossa.
Eventualmente richiederlo a FBK via mail. Lo script ufficiale della sua
metrica è conservato in `reference/mustshe_gender_accuracy.py` (Apache-2.0,
da hlt-mt/FBK-fairseq) per replicarne term coverage / gender accuracy quando
avremo dati con coppie di termini annotate.

## Script: `eval_gender_accuracy.py`

Traduce le frasi inglesi del benchmark con **NLLB fine-tuned** (stessi
parametri della pipeline: beam da config, `no_repeat_ngram_size=3`,
`max_length=256`, fp16) e applica la metrica ufficiale MT-GenEval:
una frase è sbagliata se l'ipotesi contiene parole esclusive del riferimento
del genere opposto.

```bash
# Baseline completa (600 frasi, ~25 min su RTX 12GB, ~7GB VRAM)
python gender_eval/eval_gender_accuracy.py

# Smoke test
python gender_eval/eval_gender_accuracy.py --limit 6 --batch-size 6

# Valutare ipotesi esterne (es. output del gender corrector):
python gender_eval/eval_gender_accuracy.py --mode score --tag corrector_v2 \
    --hyp-masculine hm.txt --hyp-feminine hf.txt
```

Output in `results/` (non committato): ipotesi per genere, `results_*.json`,
`failures_*.tsv` con le frasi sbagliate e le parole del genere errato trovate.

Le due percentuali chiave: **accuratezza forme femminili** e **maschili**.
Riferimenti in letteratura per NLLB-200 su questo benchmark: 82–88% globale
(arXiv 2407.15154); il divario F≪M è la firma del bias.

## Smoke test eseguito (2026-07-15)

`--limit 6`: femminile 4/6 (67%), maschile 6/6 (100%) — la metrica segnala
errori reali ("mio cugino" per una cugina; "ucciso" per soggetto femminile).
Catena validata end-to-end. La baseline completa va lanciata nella prossima
sessione.
