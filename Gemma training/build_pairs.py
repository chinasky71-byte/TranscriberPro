"""
Da film a coppie: estrazione, allineamento e pulizia del corpus
===============================================================
Per ogni candidato estrae la traccia inglese e quella italiana, le allinea nel
tempo e scrive le coppie sopravvissute ai controlli.

L'allineamento è quello già scritto e validato per il banco di valutazione
(`mt_eval/build_film_bench.py`): sovrapposizione richiesta in ENTRAMBE le
direzioni e ogni riferimento usabile una volta sola. Senza il vincolo
bidirezionale due battute inglesi finiscono sullo stesso italiano, e la coppia
insegna al modello a tradurre una battuta con il testo di due.

Quando un film ha PIÙ tracce italiane utilizzabili non si indovina quale sia
quella buona: si allineano tutte e vince quella che produce più coppie. È il
caso frequente dei file rimuxati, che portano una traccia originale e una
aggiunta.

Ogni film porta con sé il proprio RAPPORTO di lunghezza italiano/inglese, che
NON è un criterio di scarto ma un'etichetta: intorno a 0,94 è un sottotitolo
adattato per la lettura, sopra 1,05 è quasi sempre una trascrizione del
doppiaggio. Servono entrambi, ma poterli distinguere dopo è utile.

Uso:
    venv\\Scripts\\python corpus\\build_pairs.py --limite 30      (assaggio)
    venv\\Scripts\\python corpus\\build_pairs.py --workers 8      (tutto)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "mt_eval"))

from build_film_bench import align, clean_ocr, strip_cc, ts_to_seconds  # noqa: E402

SOGLIA_INTERRUZIONE = 12   # fallimenti tecnici di fila = rete caduta
TESTO = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

TAG_HTML = re.compile(r"</?[a-z][^>]*>", re.I)
GRAFFE = re.compile(r"\{[^}]*\}")            # direttive di stile ASS
NOTE = re.compile(r"[♪♫]")
SOLO_SEGNI = re.compile(r"^[\W_]+$", re.U)


def parse_srt(path):
    """(inizio, fine, testo) per ogni blocco. Tollerante sul formato."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            grezzo = f.read()
    except Exception:
        return []
    fuori = []
    for pezzo in re.split(r"\n\s*\n", grezzo.strip()):
        righe = [r for r in pezzo.split("\n") if r.strip()]
        if len(righe) < 2:
            continue
        m = re.search(r"([\d:,.]+)\s*-->\s*([\d:,.]+)", pezzo)
        if not m:
            continue
        testo = "\n".join(righe[2:] if righe[0].strip().isdigit() else righe[1:])
        if testo.strip():
            fuori.append((ts_to_seconds(m.group(1)),
                          ts_to_seconds(m.group(2)), testo.strip()))
    return fuori


def ripulisci(testo, sordi=False):
    """Toglie ciò che non è battuta: marcatura, note musicali, descrizioni."""
    testo = TAG_HTML.sub("", testo)
    testo = GRAFFE.sub("", testo)
    if sordi:
        pulito = strip_cc(testo)
        testo = pulito[0] if isinstance(pulito, tuple) else pulito
    testo = NOTE.sub("", testo or "")
    testo = re.sub(r"[ \t]{2,}", " ", testo)
    return testo.strip()


def estrai(video, indice, destinazione, tentativi=3):
    """Estrae una traccia sottotitoli. Ritenta: i dischi sono condivisioni di
    rete e una sessione SMB che cade fa fallire ffmpeg all'istante.

    Il timeout è largo perché la banda è il limite: misurato 106 MB/s su
    gigabit, cioè ~44s per un file da 4,5 GB letto da solo. Con più processi
    la banda si divide e i file grandi sforavano i 300s originali.
    """
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", video,
           "-map", f"0:{indice}", "-c:s", "srt", destinazione]
    for n in range(tentativi):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=1200)
            if r.returncode == 0 and os.path.getsize(destinazione) > 64:
                return True
            # Il file non si vede più: è la rete, non la traccia. Aspetta e
            # ritenta invece di dichiarare il film privo di sottotitoli.
            if not os.path.exists(video):
                time.sleep(5 * (n + 1))
                continue
            return False
        except subprocess.TimeoutExpired:
            time.sleep(5 * (n + 1))
        except Exception:
            time.sleep(5 * (n + 1))
    return False


def scegli_tracce(voce, quante=2):
    """Le tracce testuali candidate, non oltre `quante` per lato."""
    def testuali(elenco):
        return [t for t in elenco
                if (t.get("codec") or "").lower() in TESTO][:quante]
    return testuali(voce.get("eng", [])), testuali(voce.get("ita", []))


def coppie_valide(allineate, minimo_lungo=0):
    """I controlli sulla singola coppia.

    Larghi di proposito: la condensazione è il comportamento desiderato, e una
    soglia stretta scarterebbe proprio le coppie migliori. Qui si cerca il
    guasto grossolano — il blocco non tradotto, quello vuoto, quello che per
    lunghezza non può corrispondere all'altro.
    """
    fuori = []
    for c in allineate:
        en, it = c["source"].strip(), c["reference"].strip()
        if not en or not it:
            continue
        if SOLO_SEGNI.match(en) or SOLO_SEGNI.match(it):
            continue
        if en.lower() == it.lower():
            continue                       # rimasto in inglese
        le = len(en.replace("\n", " "))
        li = len(it.replace("\n", " "))
        if le < 3 or li < 3:
            continue
        rapporto = li / le
        if rapporto < 0.25 or rapporto > 3.0:
            continue                       # non possono essere la stessa cosa
        fuori.append({"en": en, "it": it,
                      "inizio": c["start"], "fine": c["end"]})
    return fuori


def riconcilia(corpus_path, registro_path):
    """Riporta corpus e registro a uno stato coerente prima di ripartire.

    Le coppie di un film si scrivono PRIMA della sua riga di registro: se il
    processo muore fra le due — o va via la corrente — restano coppie che il
    registro non conosce. Alla ripresa quel film risulterebbe da fare e le sue
    coppie verrebbero scritte una seconda volta.

    L'autorita' e' il registro: tutto cio' che non vi compare viene tolto dal
    corpus, e il film torna in coda. Cosi' l'operazione e' idempotente a
    qualunque punto la si interrompa, che e' la sola garanzia che regge su un
    lavoro di venti ore.

    Toglie anche l'ultima riga se e' troncata, il residuo tipico di una
    scrittura interrotta a meta'.
    """
    if not (os.path.isfile(corpus_path) and os.path.isfile(registro_path)):
        return 0, 0

    fatti = set()
    with open(registro_path, encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip()
            if not riga:
                continue
            try:
                fatti.add(json.loads(riga)["relativo"])
            except Exception:
                pass   # riga di registro troncata: il film torna in coda

    tenute, tolte, corrotte = [], 0, 0
    with open(corpus_path, encoding="utf-8") as f:
        for riga in f:
            if not riga.strip():
                continue
            try:
                c = json.loads(riga)
            except Exception:
                corrotte += 1
                continue
            if c.get("film") in fatti:
                tenute.append(riga.rstrip("\n"))
            else:
                tolte += 1

    if tolte or corrotte:
        tmp = corpus_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(tenute) + ("\n" if tenute else ""))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, corpus_path)      # sostituzione atomica
        print(f"Riconciliazione: tolte {tolte} coppie orfane"
              + (f" e {corrotte} righe troncate" if corrotte else "")
              + " da una interruzione precedente.")
    return tolte, corrotte


def scrivi_durevole(handle):
    """flush() svuota i buffer di Python, non quelli del sistema. Senza fsync
    un'interruzione di corrente perde comunque le ultime scritture."""
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except OSError:
        pass


def lavora(voce, tmpdir):
    esito = {"relativo": voce["relativo"], "disco": voce["disco"],
             "coppie": [], "nota": None, "ritentabile": False}
    eng_tracce, ita_tracce = scegli_tracce(voce)
    if not eng_tracce or not ita_tracce:
        esito["nota"] = "tracce testuali assenti"
        return esito

    base = os.path.join(tmpdir, str(abs(hash(voce["relativo"])) % 10 ** 10))
    blocchi_eng = []
    for t in eng_tracce:
        p = f"{base}_en{t['i']}.srt"
        if estrai(voce["percorso"], t["i"], p):
            b = parse_srt(p)
            b = [(a, z, ripulisci(clean_ocr(x), sordi=t.get("sordi")))
                 for a, z, x in b]
            b = [x for x in b if x[2]]
            if len(b) > len(blocchi_eng):
                blocchi_eng = b
            os.unlink(p)
    if len(blocchi_eng) < 100:
        esito["nota"] = f"traccia inglese troppo corta ({len(blocchi_eng)})"
        # Zero blocchi non è un verdetto sul film: il candidato dichiarava una
        # traccia testuale, quindi o la rete è caduta o ffmpeg ha fallito. Va
        # rimesso in coda, non archiviato come lavorato. Distinguere i due casi
        # è ciò che ha salvato 399 film persi da un singolo sganciamento SMB.
        if len(blocchi_eng) == 0:
            esito["ritentabile"] = True
        return esito

    # Più tracce italiane: si allineano tutte e vince quella che rende di più.
    migliore, quale = [], None
    for t in ita_tracce:
        p = f"{base}_it{t['i']}.srt"
        if not estrai(voce["percorso"], t["i"], p):
            continue
        b = parse_srt(p)
        b = [(a, z, ripulisci(x)) for a, z, x in b]
        b = [x for x in b if x[2]]
        os.unlink(p)
        if len(b) < 100:
            continue
        allineate = align(blocchi_eng, b)
        if len(allineate) > len(migliore):
            migliore, quale = allineate, t["i"]

    if not migliore:
        esito["nota"] = "nessun allineamento"
        return esito

    coppie = coppie_valide(migliore)
    resa = len(coppie) / max(len(blocchi_eng), 1)
    # Una resa bassa significa quasi sempre tracce di edizioni diverse: i tempi
    # scorrono e l'allineamento non aggancia. Meglio perdere il film che
    # riempire il corpus di accoppiamenti casuali.
    if resa < 0.35:
        esito["nota"] = f"resa {resa:.0%}, edizioni probabilmente diverse"
        return esito

    car_en = sum(len(c["en"].replace("\n", " ")) for c in coppie)
    car_it = sum(len(c["it"].replace("\n", " ")) for c in coppie)
    esito.update({
        "coppie": coppie,
        "blocchi_eng": len(blocchi_eng),
        "resa": round(resa, 3),
        "traccia_ita": quale,
        # L'etichetta, non un filtro: ~0,94 adattamento per la lettura,
        # sopra 1,05 quasi sempre trascrizione del doppiaggio.
        "rapporto": round(car_it / max(car_en, 1), 3),
    })
    return esito


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidati", default="candidati.jsonl")
    ap.add_argument("--out", default="coppie.jsonl")
    ap.add_argument("--registro", default="film.jsonl")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    percorso = os.path.join(SCRIPT_DIR, args.candidati)
    voci = [json.loads(l) for l in open(percorso, encoding="utf-8") if l.strip()]
    voci = [v for v in voci if v.get("lato_eng") == "testo"]

    reg_path = os.path.join(SCRIPT_DIR, args.registro)
    riconcilia(os.path.join(SCRIPT_DIR, args.out), reg_path)
    fatti = set()
    if os.path.isfile(reg_path):
        with open(reg_path, encoding="utf-8") as f:
            for riga in f:
                if riga.strip():
                    fatti.add(json.loads(riga)["relativo"])
        if fatti:
            print(f"Ripresa: {len(fatti)} film già lavorati\n")
    voci = [v for v in voci if v["relativo"] not in fatti]
    if args.limite:
        voci = voci[:args.limite]

    if not voci:
        print("Niente da fare.")
        return

    print(f"Lavoro {len(voci)} film con {args.workers} processi paralleli...\n")
    out_path = os.path.join(SCRIPT_DIR, args.out)
    lock = threading.Lock()
    t0 = time.time()
    tenuti = scartati = coppie_tot = ritentabili = 0
    consecutivi_ko = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        with open(out_path, "a", encoding="utf-8") as fout, \
                open(reg_path, "a", encoding="utf-8") as freg:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(lavora, v, tmpdir): v for v in voci}
                for n, fut in enumerate(as_completed(futures), 1):
                    v = futures[fut]
                    try:
                        e = fut.result()
                    except Exception as exc:
                        e = {"relativo": v["relativo"], "disco": v["disco"],
                             "coppie": [], "nota": f"{type(exc).__name__}: {exc}"[:120]}
                    with lock:
                        if e["coppie"]:
                            tenuti += 1
                            consecutivi_ko = 0
                            coppie_tot += len(e["coppie"])
                            for c in e["coppie"]:
                                fout.write(json.dumps(
                                    {"film": e["relativo"], **c},
                                    ensure_ascii=False) + "\n")
                        elif e.get("ritentabile"):
                            # Fallimento tecnico, non un verdetto sul film:
                            # non entra nel registro e resta in coda.
                            ritentabili += 1
                            consecutivi_ko += 1
                        else:
                            scartati += 1
                            consecutivi_ko = 0
                        if not e.get("ritentabile"):
                            freg.write(json.dumps(
                                {k: val for k, val in e.items()
                                 if k not in ("coppie", "ritentabile")},
                                ensure_ascii=False) + "\n")
                        scrivi_durevole(fout)
                        scrivi_durevole(freg)
                    # Rete caduta: ogni film successivo fallisce all'istante e
                    # senza freno la coda si svuota senza produrre nulla.
                    if consecutivi_ko >= SOGLIA_INTERRUZIONE:
                        print("\n  INTERROTTO: %d fallimenti tecnici di fila, "
                              "la condivisione di rete sembra caduta. "
                              "I film non lavorati restano in coda."
                              % consecutivi_ko)
                        for f2 in futures:
                            f2.cancel()
                        break
                    if n % 10 == 0 or n == len(voci):
                        el = time.time() - t0
                        print(f"  [{n:>4}/{len(voci)}] {el / 60:.1f} min | "
                              f"tenuti {tenuti} scartati {scartati} "
                              f"da rifare {ritentabili} | "
                              f"{coppie_tot:,} coppie".replace(",", "."))

    print(f"\nFinito in {(time.time() - t0) / 60:.1f} minuti")
    print(f"  film tenuti  : {tenuti}")
    print(f"  film scartati: {scartati}")
    print(f"  da rifare    : {ritentabili}  (restano in coda)")
    print(f"  coppie       : {coppie_tot:,}".replace(",", "."))
    print(f"  Corpus  : {out_path}")
    print(f"  Registro: {reg_path}")


if __name__ == "__main__":
    main()
