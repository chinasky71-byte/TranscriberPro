# Corpus per l'addestramento di TranslateGemma — stato

> Documento di ripresa. Se la macchina si è spenta o la chat è ripartita,
> leggi questo file: dice dove siamo, come riprendere e perché le cose sono
> fatte così.

## Come si riprende, in una riga

Doppio clic su **`RIPRENDI.cmd`**. Riprende dal punto esatto: nessun film
viene rilavorato, nessuna coppia duplicata. Si può interrompere in qualunque
momento, anche togliendo la corrente.

Per fermarla dopo un certo tempo: `RIPRENDI.cmd --max-ore 8`.

## Obiettivo

Costruire il corpus di coppie EN→IT con cui addestrare TranslateGemma-12B a
battere NLLB-200-3.3B fine-tuned, che oggi resta il motore di produzione.

Il divario da colmare è **lessicale**, non di forma: TranslateGemma fa il
doppio delle *mistranslation* di NLLB (72 contro 33 su Deadpool 2), zero
problemi di omissione. Sono rese deboli di espressioni idiomatiche —
«bring him down» → «gestirlo» invece di «sconfiggerlo». NLLB le azzecca
perché è fine-tunato su 2,6 milioni di coppie di sottotitoli.

## Quante coppie servono, e perché

Misurato sul corpus stesso (copertura dei verbi frasali che i due film
d'esame useranno):

| coppie | copertura ≥3 occorrenze | ≥10 occorrenze |
|---|---|---|
| 50.000 | 40,0% | 18,3% |
| 100.000 | 52,0% | 29,5% |
| 189.000 | 60,5% | 41,7% |

La curva sale ancora di 10-12 punti a ogni raddoppio: **non è satura**.
Per questo l'obiettivo è l'intero bacino (~3 milioni), non le 200.000
inizialmente ipotizzate — un ventesimo delle munizioni di NLLB.

Decisione presa sull'asimmetria di costo: raccogliere molto e addestrare su
un sottoinsieme è gratis (basta troncare); scoprire dopo che i dati erano
pochi costa un'altra raccolta completa.

**Quello che questa misura non dice**: la copertura è necessaria ma non
sufficiente. Il secondo vincolo è la capacità del LoRA. Quale dei due morda
per primo si scopre solo con un pilota di scaling a tre dimensioni
(50k / 200k / 800k) misurato sul banco, da fare PRIMA dell'addestramento
lungo.

## Da dove vengono le coppie

Censite 7.009 unità su W:, X:, Y:, V:. Due filtri, decisi con l'utente:

1. **doppia traccia audio ita+eng** → è un'edizione italiana retail, i
   sottotitoli italiani vengono dal distributore
2. **assente dall'elenco del Library Scanner** → non l'abbiamo mai lavorato
   noi (copre anche i file passati dal nostro OCR)

Regola SDH **asimmetrica**: sull'inglese si ammette (le descrizioni sonore si
tolgono, serve solo come sorgente), sull'italiano no (è il testo che
insegniamo a scrivere). Senza questa distinzione si perdevano 195 film.

Esclusi per parentela col banco d'esame: Deadpool 2, A Man Called Otto e
**Deadpool (2016)** — stesso personaggio e con ogni probabilità lo stesso
adattatore del film d'esame.

Le trascrizioni del doppiaggio sono **tenute** (decisione dell'utente): sono
italiano professionale col lessico giusto, e la lunghezza la governa già il
budget al momento della traduzione. Il rapporto IT/EN resta come etichetta,
non come criterio di scarto.

## Perché la ripresa è affidabile

La notte del 2026-08-17 si sono persi 399 film: la condivisione di rete è
caduta a metà run e da quel momento ogni ffmpeg falliva all'istante, ma il
registro li marcava comunque come "lavorati". Correzioni:

- **il fallimento tecnico non entra nel registro** — resta in coda; solo lo
  scarto di merito (resa bassa, edizioni diverse) viene archiviato
- **freno automatico**: dopo 12 fallimenti tecnici di fila la run si ferma
  invece di svuotare la coda a vuoto
- **riconciliazione all'avvio**: le coppie senza riga di registro vengono
  tolte e il film torna in coda, così l'operazione è idempotente a qualunque
  punto la si interrompa. Verificata con interruzione simulata a metà
  scrittura, righe troncate comprese
- **`os.fsync`** dopo ogni film: `flush()` da solo non protegge da una caduta
  di corrente
- **`raccogli.py`** riavvia da solo dopo una caduta di rete, con attesa
  progressiva fino a 15 minuti

Misurato: la banda è satura a **106 MB/s con un solo processo**, quindi tre
worker sono l'ottimo — oltre si aggiunge solo rischio di timeout.

## I file

| file | cosa fa |
|---|---|
| `RIPRENDI.cmd` | **lo script da lanciare**: riprende la raccolta |
| `raccogli.py` | supervisore: riavvia dopo le cadute di rete |
| `build_pairs.py` | estrae e allinea le coppie da un film |
| `make_dataset.py` | dal corpus al dataset: dedup, split, formato |
| `train_qlora.py` | addestramento QLoRA (non ancora eseguito) |
| `token_stats.py` | statistiche di lunghezza in token |
| `scan_media.py` / `select_candidates.py` | censimento e filtri (già eseguiti) |
| `coppie.jsonl` | **il corpus**: una coppia per riga |
| `film.jsonl` | registro delle opere lavorate (autorità sulla ripresa) |
| `candidati.jsonl` | la coda: opere ammesse dai filtri |
| `raccolta.log` | diario dei giri del supervisore |

## Il prompt di addestramento

**Non si scrive a mano.** `make_dataset.py` chiama
`SubtitleLLMEngine.mt_messages()`, lo stesso codice che gira in produzione,
così la forma su cui si addestra e quella su cui si interroga non possono
divergere.

Era già successo: la clausola sul turpiloquio, che in produzione viene
aggiunta solo alle battute volgari, nel dataset non compariva mai — si
sarebbe addestrato senza e interrogato con, proprio sulla categoria dove
quella clausola era stata misurata come necessaria (da 4/33 a 25/33).

## Split

Per **opera**, non per blocco: gli errori di allineamento sono correlati
dentro un film, e con uno split casuale finirebbero sia in addestramento sia
in test. Per le serie l'unità è la **serie intera**, non l'episodio.

Stratificato per famiglia (adattato per la lettura ~0,94 contro trascrizione
del doppiaggio >1,05) e per tipo.

Deadpool 2 e A Man Called Otto restano fuori da tutto: sono l'esame finale,
con sottotitolo professionale, giudizi GEMBA e output di tutti i motori già
misurati.

## Cosa resta da fare

1. **La raccolta** (in corso: `RIPRENDI.cmd`)
2. `make_dataset.py` per produrre train/valid/test
3. **Pilota di scaling** QLoRA a tre dimensioni, misurato sul banco — prima
   dell'addestramento lungo
4. Misura di token/s e s/passo sulla 3060 **a macchina scarica**, per
   estrapolare onestamente il costo su A100
