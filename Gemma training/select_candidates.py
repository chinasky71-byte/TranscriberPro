"""
Dal censimento ai candidati: chi entra nel corpus e con quale lato inglese
==========================================================================
Legge `media.jsonl` (prodotto da scan_media.py) e `scanner_db.json` (l'estratto
del Library Scanner) e applica i due filtri concordati, riportando quanto costa
ciascuno. Lo scopo non è solo produrre l'elenco: è mostrare dove si perdono i
file, perché un filtro che scarta il 90% va discusso prima di accettarlo.

I filtri, in ordine di applicazione:

  1. una traccia audio ITALIANA e una INGLESE — il file è un'edizione italiana
     retail, quindi i sottotitoli italiani sono del distributore;
  2. NON nell'elenco OCR del Library Scanner — copre il caso residuo del film
     retail con sottotitoli bitmap che abbiamo passato per Tesseract;
  3. una traccia sottotitoli italiana utilizzabile — non `forced` (copre solo
     il parlato straniero) e non per non udenti;
  4. una traccia sottotitoli inglese, che è la sorgente della coppia.

Il lato inglese può essere testuale (`subrip`, `ass`, `mov_text`) oppure bitmap
(`pgs`, `dvd_subtitle`): i bitmap servono l'OCR per essere usati, quindi il
conteggio li tiene separati — sono candidati di seconda ondata, non scarti.

Uso:
    venv\\Scripts\\python corpus\\select_candidates.py
    venv\\Scripts\\python corpus\\select_candidates.py --out candidati.jsonl
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Film tenuti fuori dall'addestramento perche sono il metro di valutazione.
BANCO = ("deadpool 2", "a man called otto", "non cos")

ITA = {"ita", "it", "italian", "italiano"}
ENG = {"eng", "en", "english"}
TESTO = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
BITMAP = {"hdmv_pgs_subtitle", "pgssub", "pgs", "dvd_subtitle", "dvdsub",
          "xsub"}


def carica(nome):
    p = os.path.join(SCRIPT_DIR, nome)
    if not os.path.isfile(p):
        sys.exit(f"Manca {p}")
    if nome.endswith(".jsonl"):
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def lingue_audio(riga):
    return {a.get("lang", "und") for a in riga.get("audio", [])}


def tracce_utili(riga, lingue, ammetti_sordi=False):
    """Sottotitoli di quelle lingue che valgono come materiale.

    Le `forced` si scartano sempre: coprono solo il parlato straniero, quindi
    una frazione del film.

    Sulle tracce per non udenti la regola è ASIMMETRICA, ed è una correzione
    fatta guardando i dati. Sul lato INGLESE si ammettono: le descrizioni
    sonore e le etichette di parlante si tolgono con `strip_cc`, e l'inglese
    serve solo come sorgente da tradurre. Sul lato ITALIANO no: quello è il
    testo che insegniamo a scrivere, e non vogliamo insegnare "[PORTA CHE
    SBATTE]" né "MARCO:".

    Senza questa asimmetria si perdevano film interi la cui unica traccia
    inglese è SDH — A Man Called Otto è esattamente questo caso.
    """
    fuori = []
    for s in riga.get("sub", []):
        if s.get("lang") not in lingue:
            continue
        if s.get("forced"):
            continue
        titolo = (s.get("titolo") or "").lower()
        if "forced" in titolo or "forzat" in titolo:
            continue
        sordi = bool(s.get("sordi")) or "sdh" in titolo or "udenti" in titolo
        if sordi and not ammetti_sordi:
            continue
        s = dict(s, sordi=sordi)
        fuori.append(s)
    # Se ci sono entrambe, le pulite vengono prima: chi sceglie prende quella.
    fuori.sort(key=lambda t: bool(t.get("sordi")))
    return fuori


def classifica(tracce):
    """(ha_testo, ha_bitmap) fra le tracce passate."""
    codec = {(t.get("codec") or "").lower() for t in tracce}
    return bool(codec & TESTO), bool(codec & BITMAP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", default="media.jsonl")
    ap.add_argument("--db", default="scanner_db.json")
    ap.add_argument("--out", default="candidati.jsonl")
    args = ap.parse_args()

    media = carica(args.media)
    db = {x["rel"]: x for x in carica(args.db)}
    ocr_nostri = {r for r, x in db.items() if x.get("ocr") == "done"}

    tot = len(media)
    passo = []          # (etichetta, quanti restano)

    vivi = [m for m in media if "errore" not in m]
    passo.append(("censiti senza errori", len(vivi)))

    doppio = [m for m in vivi
              if lingue_audio(m) & ITA and lingue_audio(m) & ENG]
    passo.append(("con audio ITA + ENG", len(doppio)))

    puliti = [m for m in doppio if m["relativo"] not in ocr_nostri]
    passo.append(("non passati dal nostro OCR", len(puliti)))

    # I film del banco NON entrano: addestrare su ciò con cui si misura
    # renderebbe la misura priva di significato.
    riservati = [m for m in puliti
                 if any(k in m["relativo"].lower() for k in BANCO)]
    puliti = [m for m in puliti if m not in riservati]
    passo.append(("meno i film riservati al banco", len(puliti)))

    con_ita = []
    for m in puliti:
        t = tracce_utili(m, ITA)
        if t:
            m["_ita"] = t
            con_ita.append(m)
    passo.append(("con sottotitoli ITA utilizzabili", len(con_ita)))

    finali, solo_bitmap = [], []
    for m in con_ita:
        t_eng = tracce_utili(m, ENG, ammetti_sordi=True)
        if not t_eng:
            continue
        m["_eng"] = t_eng
        ita_testo, ita_bmp = classifica(m["_ita"])
        eng_testo, eng_bmp = classifica(t_eng)
        if not ita_testo:
            continue                      # l'italiano bitmap andrebbe OCR-ato
        m["_lato_eng"] = "testo" if eng_testo else "bitmap"
        (finali if eng_testo else solo_bitmap).append(m)
    passo.append(("con ENG testuale (pronti)", len(finali)))
    passo.append(("con ENG solo bitmap (serve OCR)", len(solo_bitmap)))

    print("=" * 74)
    print(f"  DAL CENSIMENTO AI CANDIDATI — {tot} file esaminati")
    print("=" * 74)
    precedente = tot
    for etichetta, quanti in passo[:-1]:
        perso = precedente - quanti
        print(f"  {etichetta:<36}{quanti:>6}   (-{perso})")
        precedente = quanti
    print(f"  {passo[-1][0]:<36}{passo[-1][1]:>6}   (in piu, seconda ondata)")
    print("=" * 74)

    per_disco = {}
    per_tipo = {}
    for m in finali:
        per_disco[m["disco"]] = per_disco.get(m["disco"], 0) + 1
        per_tipo[m["tipo"]] = per_tipo.get(m["tipo"], 0) + 1
    print(f"  pronti per disco : {per_disco}")
    print(f"  pronti per tipo  : {per_tipo}")

    ore = sum(m.get("durata") or 0 for m in finali) / 3600
    print(f"  durata complessiva dei pronti: {ore:.0f} ore")
    print(f"  stima coppie (a ~900 battute per ora di film): "
          f"{int(ore * 900):,}".replace(",", "."))

    out = os.path.join(SCRIPT_DIR, args.out)
    with open(out, "w", encoding="utf-8") as f:
        for m in finali + solo_bitmap:
            f.write(json.dumps({
                "disco": m["disco"],
                "relativo": m["relativo"],
                "percorso": m["percorso"],
                "tipo": m["tipo"],
                "durata": m.get("durata"),
                "lato_eng": m["_lato_eng"],
                "ita": m["_ita"],
                "eng": m["_eng"],
            }, ensure_ascii=False) + "\n")
    print(f"\n  Elenco: {out}")


if __name__ == "__main__":
    main()
