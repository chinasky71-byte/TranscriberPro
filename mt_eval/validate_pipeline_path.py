"""
Il percorso REALE dell'applicazione, esercitato una volta
=========================================================
Tutto il banco di valutazione ha chiamato `core/llm_subtitle_translator/`
direttamente. L'applicazione invece passa da un'altra strada, che nessuna delle
misure ha mai toccato:

    pipeline STEP 6
      -> get_translator(model_type, context)      <- factory, cambiata
      -> translator.translate_file(..., context)  <- firma cambiata
      -> BaseTranslator._generate_srt()
      -> _polish()                                <- post-processing, NUOVO

Ed è proprio lì che vive il guadagno più concreto di tutto il lavoro: la
rifinitura tipografica che porta le righe fuori norma dal 59% al 10% a parole
invariate, e che vale per NLLB, cioè per il motore di produzione.

Questo script prende un SRT inglese vero, lo passa per quella catena esatta con
lo stesso codice che userebbe la pipeline, e verifica sull'uscita le cose che
possono rompersi in silenzio: che i blocchi ci siano tutti, che i tempi non si
siano spostati, che i trattini di dialogo siano sopravvissuti, che la
rifinitura abbia fatto il suo lavoro.

Non sostituisce la prova a schermo: non tocca la GUI, l'estrazione della
traccia audio, la trascrizione. Copre il tratto cambiato.

Uso:
    venv\\Scripts\\python mt_eval\\validate_pipeline_path.py
    venv\\Scripts\\python mt_eval\\validate_pipeline_path.py --engine aya --limit 80
"""

import argparse
import os
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

CPL_MAX = 42
TIME_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")


def leggi_srt(path):
    """Blocchi come (indice, tempi, righe). Parsing minimo di proposito: se
    l'SRT prodotto non si legge con un parser ingenuo, è già un difetto."""
    with open(path, encoding="utf-8-sig") as f:
        grezzo = f.read()
    blocchi = []
    for pezzo in re.split(r"\n\s*\n", grezzo.strip()):
        righe = [r for r in pezzo.split("\n") if r.strip()]
        if len(righe) < 2:
            continue
        m = TIME_RE.search(righe[1]) if len(righe) > 1 else None
        if not m:
            continue
        blocchi.append((righe[0].strip(), (m.group(1), m.group(2)), righe[2:]))
    return blocchi


def esito(ok, testo):
    print(f"  {'PASSA ' if ok else 'FALLISCE'}  {testo}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", default=os.path.join(SCRIPT_DIR, "film",
                                                  "deadpool2_en.srt"))
    ap.add_argument("--engine", default="nllb_finetuned",
                    help="nllb_finetuned | aya | ...")
    ap.add_argument("--limit", type=int, default=120,
                    help="quanti blocchi (0 = tutti); il punto è la catena, "
                         "non la lunghezza")
    ap.add_argument("--context", default=(
        "Deadpool 2. Il mercenario Wade Wilson forma una squadra per "
        "proteggere un ragazzo mutante da un soldato venuto dal futuro."))
    args = ap.parse_args()

    if not os.path.isfile(args.srt):
        sys.exit(f"SRT di partenza assente: {args.srt}")

    # Un ritaglio invece del film intero: la catena è la stessa e la prova
    # dura minuti invece di ore.
    sorgente = args.srt
    if args.limit:
        blocchi = leggi_srt(args.srt)[:args.limit]
        sorgente = os.path.join(SCRIPT_DIR, "_prova_in.srt")
        with open(sorgente, "w", encoding="utf-8") as f:
            for i, (_, (a, b), righe) in enumerate(blocchi, 1):
                f.write(f"{i}\n{a} --> {b}\n" + "\n".join(righe) + "\n\n")

    ingresso = leggi_srt(sorgente)
    uscita_path = os.path.join(SCRIPT_DIR, "_prova_out.srt")
    if os.path.exists(uscita_path):
        os.remove(uscita_path)

    print("=" * 72)
    print(f"  PERCORSO REALE DELLA PIPELINE — motore {args.engine}")
    print(f"  {len(ingresso)} blocchi da {os.path.basename(args.srt)}")
    print("=" * 72)

    # Da qui in poi è esattamente ciò che fa pipeline.py allo STEP 6.
    from core.translator import get_translator

    t0 = time.time()
    traduttore = get_translator(model_type=args.engine, context=args.context)
    traduttore.set_log_callback(lambda m: print(f"    {m}"))
    ok = traduttore.translate_file(
        input_path=sorgente,
        output_path=uscita_path,
        src_lang="en",
        tgt_lang="it",
        context=args.context,
    )
    elapsed = time.time() - t0
    try:
        traduttore.cleanup()
    except Exception as exc:
        print(f"    cleanup: {exc}")

    print(f"\n  translate_file ha restituito {ok} in {elapsed / 60:.1f} min\n")

    if not ok or not os.path.isfile(uscita_path):
        sys.exit("  FALLISCE  translate_file non ha prodotto l'SRT")

    uscita = leggi_srt(uscita_path)
    tutto = []

    tutto.append(esito(len(uscita) == len(ingresso),
                       f"blocchi conservati: {len(uscita)} su {len(ingresso)}"))

    tempi_ok = sum(1 for a, b in zip(ingresso, uscita) if a[1] == b[1])
    tutto.append(esito(tempi_ok == len(ingresso),
                       f"tempi identici all'originale: {tempi_ok}/{len(ingresso)}"))

    vuoti = [b[0] for b in uscita if not " ".join(b[2]).strip()]
    tutto.append(esito(not vuoti, f"nessun blocco vuoto (trovati {len(vuoti)})"))

    # Il post-processing è la ragione principale di questa prova.
    fuori = sum(1 for b in uscita for r in b[2] if len(r) > CPL_MAX)
    righe_tot = sum(len(b[2]) for b in uscita)
    pct = fuori * 100.0 / max(righe_tot, 1)
    tutto.append(esito(pct <= 15,
                       f"righe oltre {CPL_MAX} caratteri: {fuori}/{righe_tot} "
                       f"({pct:.0f}%) — la rifinitura ha lavorato"))

    tre_righe = [b[0] for b in uscita if len(b[2]) > 2]
    tutto.append(esito(not tre_righe,
                       f"mai più di due righe per blocco "
                       f"(violazioni: {len(tre_righe)})"))

    # I trattini di dialogo si perdono facilmente: è già successo.
    dash_in = sum(1 for b in ingresso
                  if sum(1 for r in b[2] if r.lstrip().startswith(("-", "–"))) >= 2)
    dash_out = sum(1 for b in uscita
                   if sum(1 for r in b[2] if r.lstrip().startswith(("-", "–"))) >= 2)
    tutto.append(esito(dash_out >= dash_in * 0.8,
                       f"blocchi di dialogo con i trattini: "
                       f"{dash_out} in uscita contro {dash_in} in ingresso"))

    # Puntini di sospensione: la rifinitura deve usare U+2026 e non tre punti.
    tre_punti = sum(1 for b in uscita for r in b[2] if "..." in r)
    tutto.append(esito(tre_punti == 0,
                       f"nessun '...' non normalizzato (trovati {tre_punti})"))

    identici = sum(1 for a, b in zip(ingresso, uscita)
                   if " ".join(a[2]).strip() == " ".join(b[2]).strip())
    tutto.append(esito(identici < len(ingresso) * 0.15,
                       f"blocchi rimasti in inglese: {identici}/{len(ingresso)}"))

    print()
    print("  Prime battute tradotte:")
    for a, b in list(zip(ingresso, uscita))[:5]:
        print(f"    EN  {' / '.join(a[2])[:66]}")
        print(f"    IT  {' / '.join(b[2])[:66]}")
    print()
    print("=" * 72)
    if all(tutto):
        print("  PERCORSO REALE VALIDATO — tutti i controlli superati")
    else:
        print(f"  {tutto.count(False)} CONTROLLI FALLITI su {len(tutto)}")
    print(f"  Uscita: {uscita_path}")
    print("=" * 72)
    sys.exit(0 if all(tutto) else 1)


if __name__ == "__main__":
    main()
