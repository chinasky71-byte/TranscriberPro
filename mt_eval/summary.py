"""
Tutti i numeri della valutazione motori in un posto solo
========================================================
Legge i file prodotti dal banco (giudizi GEMBA, traduzioni, punteggi
CometKiwi) e stampa le tabelle finali. Esiste perché i numeri del recap devono
venire dai file, non da appunti: ogni volta che una misura si rifà, questo
script è l'unico posto da rieseguire.

Uso:
    venv\\Scripts\\python mt_eval\\summary.py
    venv\\Scripts\\python mt_eval\\summary.py --json   (per il recap HTML)
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
W = {"minor": 1, "major": 5, "critical": 10}
CPL_MAX, CPS_MAX = 42, 17.0

STRONG_IT = re.compile(
    r"cazz|merd|stronz|fanculo|porc[oa]|troi|figa|coglion|puttan|inculat|"
    r"bastard|vaffa|fott|incazz|minchi", re.I)
PROF_EN = re.compile(
    r"\b(fuck\w*|shit\w*|bullshit|asshole|bitch\w*|bastard|cunt|dick|prick|"
    r"motherfuck\w*|goddamn)\b", re.I)


def load(name):
    p = os.path.join(SCRIPT_DIR, name)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def mqm(rows, side):
    if not rows:
        return None
    return sum(W.get(e.get("severity"), 1)
               for r in rows for e in r[f"errors_{side}"]) / len(rows)


def pref(rows, who):
    if not rows:
        return None
    return sum(1 for r in rows if r["preferred"] == who) * 100.0 / len(rows)


def style(items, texts):
    """Le quattro scelte di mestiere misurabili su un file di sottotitoli."""
    n = len(items)
    chars = cpl = cps = 0
    hit = src_prof = 0
    used = 0
    for it in items:
        t = (texts or {}).get(it["id"], "")
        if not t.strip():
            continue
        used += 1
        flat = t.replace("\n", " ")
        chars += len(flat)
        if any(len(l) > CPL_MAX for l in t.split("\n")):
            cpl += 1
        if "start" in it and "end" in it:
            dur = max(0.001, float(it["end"]) - float(it["start"]))
            if len(flat) / dur > CPS_MAX:
                cps += 1
        if PROF_EN.search(it["source"]):
            src_prof += 1
            if STRONG_IT.search(t):
                hit += 1
    src = sum(len(i["source"].replace("\n", " ")) for i in items) / n
    return {
        "chars": chars / max(used, 1),
        "ratio": (chars / max(used, 1)) / max(src, 1),
        "cpl_pct": cpl * 100.0 / n,
        "cps_pct": cps * 100.0 / n,
        "prof_hit": hit, "prof_src": src_prof,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    out = {}

    # -- banco sintetico: classifica per categoria -------------------------
    tg = {r["id"]: r for r in (load("gemba_nllb_vs_tgemma.jsonl") or [])}
    ay = {r["id"]: r for r in (load("gemba_nllb_vs_aya.jsonl") or [])}
    hy = {r["id"]: r for r in (load("gemba_nllb_vs_hunyuan.jsonl") or [])}
    cats = {}
    for i, r in tg.items():
        cats.setdefault(r["category"], []).append(i)
    synth = []
    for c, ids in sorted(cats.items()):
        rt = [tg[i] for i in ids]
        ra = [ay[i] for i in ids if i in ay]
        rh = [hy[i] for i in ids if i in hy]
        row = {"categoria": c, "n": len(ids),
               "nllb": mqm(rt, "a"), "aya": mqm(ra, "b"),
               "tgemma": mqm(rt, "b"), "hunyuan": mqm(rh, "b")}
        row["vincitore"] = min(("nllb", "aya", "tgemma", "hunyuan"),
                               key=lambda k: row[k] if row[k] is not None
                               else 99)
        synth.append(row)
    allids = list(tg)
    if allids:
        rt = [tg[i] for i in allids]
        ra = [ay[i] for i in allids if i in ay]
        rh = [hy[i] for i in allids if i in hy]
        out["sintetico_totale"] = {
            "n": len(allids), "nllb": mqm(rt, "a"), "aya": mqm(ra, "b"),
            "tgemma": mqm(rt, "b"), "hunyuan": mqm(rh, "b")}
    out["sintetico"] = synth

    # -- giudizio sui film -------------------------------------------------
    giudizi = []
    for f, sfida in (("gemba_fnllb_vs_ftg.jsonl", "NLLB vs TranslateGemma"),
                     ("gemba_fnllb_vs_faya.jsonl", "NLLB vs Aya")):
        rows = load(f)
        if not rows:
            continue
        giudizi.append({
            "sfida": sfida, "n": len(rows),
            "mqm_a": mqm(rows, "a"), "mqm_b": mqm(rows, "b"),
            "pref_a": pref(rows, "a"), "pref_b": pref(rows, "b"),
            "pari": pref(rows, "tie")})
    out["film_giudizio"] = giudizi

    # -- stile sui due film ------------------------------------------------
    qe = {}
    for name in os.listdir(SCRIPT_DIR):
        if name.startswith("qek_") and name.endswith(".jsonl"):
            rows = load(name)
            if rows:
                key = name[4:-6]
                qe[key] = sum(d["qe"] for d in rows) / len(rows)

    films = []
    for film, setname, pfx in (
            ("Deadpool 2", "filmset_deadpool2_sample.jsonl", "film"),
            ("A Man Called Otto", "filmset_otto_sample.jsonl", "otto")):
        items = load(setname)
        if not items:
            continue
        righe = []
        for key, label in (("pro", "traduttore professionista"),
                           ("nllb", "NLLB fine-tuned"),
                           ("aya", "Aya Expanse 8B"),
                           ("tg", "TranslateGemma 12B"),
                           ("tgr", "TranslateGemma + regole")):
            if key == "pro":
                texts = {i["id"]: i["reference"] for i in items}
            else:
                rows = load(f"tr_{pfx}_{key}.jsonl")
                if not rows:
                    continue
                texts = {d["id"]: d["text"] for d in rows}
            row = style(items, texts)
            row["motore"] = label
            row["qe"] = qe.get(f"{pfx}_{key}")
            righe.append(row)
        films.append({"film": film, "n": len(items),
                      "src_chars": sum(len(i["source"].replace("\n", " "))
                                       for i in items) / len(items),
                      "righe": righe})
    out["film_stile"] = films

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    print("=" * 78)
    print("  BANCO SINTETICO — MQM pesato per categoria (più basso = meglio)")
    print("=" * 78)
    print(f"  {'categoria':<16}{'n':>4}{'NLLB':>8}{'Aya':>8}{'TGemma':>9}"
          f"{'Hunyuan':>9}   vincitore")
    print("  " + "-" * 68)
    for r in synth:
        print(f"  {r['categoria']:<16}{r['n']:>4}{r['nllb']:>8.2f}"
              f"{r['aya']:>8.2f}{r['tgemma']:>9.2f}{r['hunyuan']:>9.2f}"
              f"   {r['vincitore']}")
    t = out.get("sintetico_totale")
    if t:
        print("  " + "-" * 68)
        print(f"  {'TOTALE':<16}{t['n']:>4}{t['nllb']:>8.2f}{t['aya']:>8.2f}"
              f"{t['tgemma']:>9.2f}{t['hunyuan']:>9.2f}")

    print()
    print("=" * 78)
    print("  FILM REALI — giudizio GEMBA (A = NLLB fine-tuned)")
    print("=" * 78)
    for g in giudizi:
        print(f"  {g['sfida']:<26} n={g['n']:<5} MQM {g['mqm_a']:.2f} vs "
              f"{g['mqm_b']:.2f} | preferenza {g['pref_a']:.0f}% vs "
              f"{g['pref_b']:.0f}% (pari {g['pari']:.0f}%)")

    for f in films:
        print()
        print("=" * 78)
        print(f"  {f['film']} — {f['n']} blocchi, "
              f"{f['src_chars']:.1f} caratteri inglesi per blocco")
        print("=" * 78)
        print(f"  {'':<26}{'car':>7}{'x EN':>8}{'>42car':>9}{'>17CPS':>9}"
              f"{'turpiloquio':>13}{'CometKiwi':>11}")
        print("  " + "-" * 74)
        for r in f["righe"]:
            q = f"{r['qe']:.4f}" if r["qe"] is not None else "—"
            turp = f"{r['prof_hit']}/{r['prof_src']}"
            print(f"  {r['motore']:<26}{r['chars']:7.1f}{r['ratio']:8.2f}"
                  f"{r['cpl_pct']:8.0f}%{r['cps_pct']:8.0f}%"
                  f"{turp:>13}{q:>11}")
    print("=" * 78)


if __name__ == "__main__":
    main()
