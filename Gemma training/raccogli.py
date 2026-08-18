"""Supervisore della raccolta: riavvia build_pairs finche' la coda non e' vuota.

Serve perche' la raccolta dura ore e i dischi sono condivisioni di rete. Una
sessione SMB che cade fa fallire ogni estrazione all'istante: `build_pairs` se
ne accorge e si ferma (SOGLIA_INTERRUZIONE), ma da solo non riparte. Questo
supervisore aspetta che la rete torni e riprende dal punto esatto — il registro
e la riconciliazione all'avvio garantiscono che nessun film venga rifatto.

Uso:
    python raccogli.py                 # fino a esaurire il bacino
    python raccogli.py --max-ore 8     # si ferma dopo otto ore

Interrompibile in qualunque momento: al riavvio riprende da dove era.
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ATTESA_BASE = 60        # secondi prima di riprovare dopo una caduta
ATTESA_MAX = 900        # tetto all'attesa progressiva


def dischi_pronti(lettere=("W:", "Y:", "V:")):
    return all(os.path.isdir(d + os.sep) for d in lettere)


def conta(nome):
    p = os.path.join(SCRIPT_DIR, nome)
    if not os.path.isfile(p):
        return 0
    with open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for r in f if r.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3,
                    help="la banda di rete e' gia' satura a 1: oltre 3 "
                         "aggiunge solo rischio di timeout")
    ap.add_argument("--blocco", type=int, default=120,
                    help="film per invocazione: piu' corta e' la singola "
                         "esecuzione, meno lavoro c'e' da riconciliare")
    ap.add_argument("--max-ore", type=float, default=0)
    ap.add_argument("--log", default="raccolta.log")
    args = ap.parse_args()

    log_path = os.path.join(SCRIPT_DIR, args.log)
    t0 = time.time()
    giro = 0
    attesa = ATTESA_BASE

    def scrivi(msg):
        riga = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(riga, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(riga + "\n")

    scrivi(f"Avvio raccolta | {conta('coppie.jsonl'):,} coppie, "
           f"{conta('film.jsonl')} opere gia' fatte".replace(",", "."))

    while True:
        if args.max_ore and (time.time() - t0) / 3600 >= args.max_ore:
            scrivi(f"Raggiunto il tetto di {args.max_ore} ore. Mi fermo.")
            break

        if not dischi_pronti():
            scrivi(f"Dischi di rete non raggiungibili: attendo {attesa}s")
            time.sleep(attesa)
            attesa = min(attesa * 2, ATTESA_MAX)
            continue

        giro += 1
        prima_c, prima_f = conta("coppie.jsonl"), conta("film.jsonl")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "build_pairs.py"),
             "--limite", str(args.blocco), "--workers", str(args.workers)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=SCRIPT_DIR)
        uscita = (r.stdout or "") + (r.stderr or "")
        dopo_c, dopo_f = conta("coppie.jsonl"), conta("film.jsonl")

        scrivi(f"giro {giro}: +{dopo_c - prima_c:,} coppie, "
               f"+{dopo_f - prima_f} opere | totale {dopo_c:,} coppie "
               f"da {dopo_f} opere".replace(",", "."))

        if "Niente da fare" in uscita:
            scrivi("Bacino esaurito. Raccolta completa.")
            break

        if r.returncode != 0:
            scrivi(f"Uscita anomala ({r.returncode}): attendo {attesa}s")
            scrivi("  " + uscita.strip().splitlines()[-1][:200]
                   if uscita.strip() else "  nessun messaggio")
            time.sleep(attesa)
            attesa = min(attesa * 2, ATTESA_MAX)
            continue

        if "INTERROTTO" in uscita:
            scrivi(f"Rete caduta durante il giro: attendo {attesa}s")
            time.sleep(attesa)
            attesa = min(attesa * 2, ATTESA_MAX)
            continue

        # Un giro che non produce nulla e non segnala nulla: non insistere a
        # vuoto, ma nemmeno arrendersi — puo' essere un blocco di film tutti
        # legittimamente scartati.
        if dopo_f == prima_f:
            scrivi(f"Nessuna opera lavorata: attendo {attesa}s")
            time.sleep(attesa)
            attesa = min(attesa * 2, ATTESA_MAX)
            continue

        attesa = ATTESA_BASE   # giro sano: si riazzera l'attesa

    scrivi(f"Fine dopo {(time.time() - t0) / 3600:.1f} ore | "
           f"{conta('coppie.jsonl'):,} coppie da {conta('film.jsonl')} opere"
           .replace(",", "."))


if __name__ == "__main__":
    main()
