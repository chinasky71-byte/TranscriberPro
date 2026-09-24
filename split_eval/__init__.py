"""split_eval - misura e prototipo per le FRASI SPEZZATE a meta' blocco.

Pacchetto di banco: NON importato dalla pipeline di produzione. I moduli
puri (midcut, recompose, srtio, split_metrics) non importano torch ne'
core/* ; i sorgenti di produzione necessari (formatter, cleaner,
postprocess) si caricano per percorso, in sola lettura, da prodmods.

I nomi dei moduli NON collidono con quelli di asr_eval (metrics, stats,
decision_rules, windows, refs, normalize, sandbox, runners): i due banchi
stanno insieme su sys.path.
"""
