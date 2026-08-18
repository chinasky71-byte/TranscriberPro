"""
Censimento dei media su disco: chi può entrare nel corpus di addestramento
==========================================================================
Interroga ogni file video con ffprobe e registra ciò che serve a decidere se
la coppia di sottotitoli (inglese, italiano) che contiene sia materiale onesto
per addestrare il traduttore.

Le due regole che decidono:

  1. DOPPIA TRACCIA AUDIO ita+eng — certifica che il file è un'edizione
     italiana retail, quindi che i suoi sottotitoli italiani vengono dal
     distributore e non dal nostro software. È il filtro primario perché su un
     film con audio italiano non avremmo mai avuto motivo di TRADURRE i
     sottotitoli: al massimo di fare OCR su una traccia bitmap.
  2. ASSENZA dall'elenco OCR del Library Scanner — copre proprio quel caso
     residuo: un film retail con sottotitoli italiani bitmap che abbiamo
     passato per Tesseract, e il cui testo quindi è nostro.

Due strade scartate dopo averci ragionato, che vale la pena non ritentare:
  - distinguere per POSIZIONE (traccia dentro il contenitore contro sidecar):
    FileFlows rimuxa i sidecar dentro l'mkv, quindi "embedded" non certifica
    niente;
  - riconoscere la FIRMA di FileFlows: quel software fa anche sola ricodifica
    video, quindi la sua firma compare anche su file dai sottotitoli intatti.

Questo script si limita a REGISTRARE. Non filtra e non scarta: la selezione
arriva dopo, quando i numeri sono sul tavolo.

Uso:
    venv\\Scripts\\python corpus\\scan_media.py
    venv\\Scripts\\python corpus\\scan_media.py --dischi W,Y --workers 12
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_EXT = (".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts")

# Un episodio si riconosce dal nome o da una cartella di stagione. Serve solo
# a etichettare: ogni episodio conta come unità a sé, quindi non cambia il
# trattamento, solo il conteggio.
EPISODIO = re.compile(
    r"(?:^|[^a-z0-9])s\d{1,2}[\s._-]?e\d{1,3}(?:[^a-z0-9]|$)"
    r"|(?:^|[^a-z0-9])\d{1,2}x\d{2}(?:[^a-z0-9]|$)", re.I)
STAGIONE = re.compile(
    r"(?:^|[\\/])(?:season|stagione)[\s._-]*\d+(?:[\\/]|$)", re.I)


def elenca(radice):
    """Tutti i file video sotto una radice, col percorso relativo."""
    trovati = []
    for cartella, _dirs, files in os.walk(radice):
        for nome in files:
            if nome.lower().endswith(VIDEO_EXT):
                pieno = os.path.join(cartella, nome)
                trovati.append((pieno, os.path.relpath(pieno, radice)))
    return trovati


def sidecar_vicini(percorso_video):
    """I .srt accanto al video.

    Non servono al corpus: servono a sapere quanti file abbiamo già lavorato,
    e quindi quanto il filtro stia davvero escludendo.
    """
    cartella = os.path.dirname(percorso_video)
    radice = os.path.splitext(os.path.basename(percorso_video))[0].lower()
    try:
        return sorted(n for n in os.listdir(cartella)
                      if n.lower().endswith(".srt")
                      and n.lower().startswith(radice[:24]))
    except Exception:
        return []


def interroga(percorso):
    """ffprobe su un file. Restituisce (dati, errore)."""
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "stream=index,codec_type,codec_name:"
           "stream_tags=language,title:"
           "stream_disposition=forced,hearing_impaired,default:"
           "format=duration:format_tags=encoder",
           "-of", "json", percorso]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return None, (r.stderr or "ffprobe fallito").strip()[:160]
        return json.loads(r.stdout or "{}"), None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"[:160]


def scheda(percorso, relativo, disco):
    dati, errore = interroga(percorso)
    riga = {
        "disco": disco,
        "relativo": relativo.replace("\\", "/"),
        "percorso": percorso,
        "tipo": ("episodio"
                 if EPISODIO.search(os.path.basename(percorso))
                 or STAGIONE.search(relativo) else "film"),
        "audio": [],
        "sub": [],
        "sidecar": sidecar_vicini(percorso),
    }
    if errore:
        riga["errore"] = errore
        return riga

    fmt = dati.get("format", {}) or {}
    try:
        riga["durata"] = float(fmt.get("duration") or 0) or None
    except (TypeError, ValueError):
        riga["durata"] = None
    riga["encoder"] = (fmt.get("tags") or {}).get("encoder")

    for s in dati.get("streams", []):
        tipo = s.get("codec_type")
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        voce = {
            "i": s.get("index"),
            "lang": (tags.get("language") or "und").lower(),
            "codec": s.get("codec_name"),
            "titolo": tags.get("title"),
        }
        if tipo == "audio":
            riga["audio"].append(voce)
        elif tipo == "subtitle":
            voce["forced"] = bool(disp.get("forced"))
            voce["sordi"] = bool(disp.get("hearing_impaired"))
            voce["default"] = bool(disp.get("default"))
            riga["sub"].append(voce)
    return riga


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dischi", default="W,X,Y")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(SCRIPT_DIR, "media.jsonl"))
    args = ap.parse_args()

    dischi = [d.strip().upper() for d in args.dischi.split(",") if d.strip()]

    # Riprende invece di ricominciare: quasi quattromila interrogazioni via
    # SMB non si rifanno per un'interruzione.
    fatti = set()
    if os.path.isfile(args.out):
        with open(args.out, encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if riga:
                    try:
                        fatti.add(json.loads(riga)["percorso"])
                    except Exception:
                        pass
        if fatti:
            print(f"Ripresa: {len(fatti)} file già censiti\n")

    lavoro = []
    for d in dischi:
        radice = d + ":" + os.sep
        if not os.path.isdir(radice):
            print(f"  {radice} non accessibile, salto")
            continue
        trovati = elenca(radice)
        nuovi = [(p, r, d) for p, r in trovati if p not in fatti]
        print(f"  {radice} {len(trovati):>5} file video, "
              f"{len(nuovi):>5} da fare")
        lavoro += nuovi

    if not lavoro:
        print("\nNiente da fare.")
        return

    print(f"\nInterrogo {len(lavoro)} file con {args.workers} processi "
          f"paralleli...\n")
    lock = threading.Lock()
    t0 = time.time()
    with open(args.out, "a", encoding="utf-8") as fout:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(scheda, p, r, d): p for p, r, d in lavoro}
            for n, fut in enumerate(as_completed(futures), 1):
                try:
                    riga = fut.result()
                except Exception as exc:
                    riga = {"percorso": futures[fut],
                            "errore": f"{type(exc).__name__}: {exc}"[:160]}
                with lock:
                    fout.write(json.dumps(riga, ensure_ascii=False) + "\n")
                    fout.flush()
                if n % 200 == 0 or n == len(lavoro):
                    el = time.time() - t0
                    print(f"  [{n:>5}/{len(lavoro)}] {el / 60:.1f} min | "
                          f"~{el / n * (len(lavoro) - n) / 60:.1f} min "
                          f"rimanenti")

    print(f"\nCensimento in {(time.time() - t0) / 60:.1f} minuti")
    print(f"Archivio: {args.out}")


if __name__ == "__main__":
    main()
