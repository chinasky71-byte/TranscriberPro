"""
Scoperta candidati di glossario per uno show — Fase 1, piano "Glossario per-show"
==================================================================================
Un glossario (core/glossary.py) fissa la resa italiana di un termine ricorrente
così NLLB non lo traduce in modo diverso episodio per episodio (misurato su
Knight's & Magic: "Knight Runner" a volte lasciato letterale, una volta reso
"Cavalieri Corridori"). Questo script trova i candidati per QUALUNQUE show
della libreria, riusando gli stessi mattoni di mt_eval/build_film_bench.py.

Logica per episodio:
  1. Traccia IT NOSTRA: un .srt nella cartella dell'episodio con l'header
     "AI generated subtitles" — i sub scaricati non ce l'hanno. Episodi senza
     bozza nostra vengono saltati (nessuna base per misurare l'incoerenza).
  2. Traccia EN: un .srt esterno con "en"/"eng" nel nome se esiste, altrimenti
     la traccia subrip inglese incorporata nel video (stesso file, associato
     per numero di stagione/episodio — i nomi di release spesso NON
     condividono lo stesso "stem" del video, matchare sullo stem è fragile).
  3. parse_srt()/align() (riuso senza modifiche da build_film_bench.py) EN↔IT,
     poi tutti gli episodi dello show confluiscono in un unico banco.
  4. Candidati: sequenze di 1-3 parole capitalizzate consecutive nell'EN,
     frequenza minima configurabile, esclusi le maiuscole di inizio-blocco e
     una stopword-list minima.
  5. Segnale di incoerenza: quante occorrenze del candidato compaiono
     verbatim (case-insensitive) nel blocco IT allineato, quante no. Un
     candidato assente in ALCUNE occorrenze e presente in ALTRE è la prova
     diretta che NLLB lo rende in modo diverso a seconda del contesto.

Uso:
    venv\\Scripts\\python mt_eval\\build_glossary_candidates.py --show-dir "V:\\The Ark" --name the_ark
    venv\\Scripts\\python mt_eval\\build_glossary_candidates.py --show-dir "V:\\PONIES" --name ponies --min-freq 2
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from build_film_bench import parse_srt, align, probe_subtitles, extract_srt  # noqa: E402

OUR_HEADER = "AI generated subtitles"

# Stagione/episodio: "S01E02", "1x02", tollera separatori vari nel nome release.
_SXXEXX_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})|(\d{1,2})x(\d{1,3})')

_STOPWORDS = {
    "The", "A", "An", "I", "You", "He", "She", "It", "We", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "Mr", "Mrs", "Ms", "Dr", "Oh", "Yeah", "Okay", "Ok", "Hey", "Well",
    # "I" resta maiuscolo per grammatica inglese a QUALSIASI posizione nella
    # frase, non solo a inizio — il filtro sentence-start non lo intercetta.
    # Stesso discorso per le interiezioni/contrazioni molto comuni che
    # restano capitalizzate anche a metà dialogo per enfasi.
    "I'm", "I'll", "I've", "I'd", "It's", "It'll", "You're", "You'll",
    "You've", "You'd", "We're", "We'll", "We've", "They're", "They'll",
    "That's", "There's", "Here's", "Let's", "Don't", "Can't", "Won't",
    "Didn't", "Isn't", "Wasn't", "Aren't", "Doesn't", "What's", "Who's",
    "How's", "Why's", "Where's", "Come", "Look", "Wait", "Stop", "Go",
    "Yes", "No", "Sir", "Ma'am",
}
# Sequenze di 1-3 parole capitalizzate consecutive.
_CANDIDATE_RE = re.compile(
    r"\b([A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){0,2})\b")


def episode_key(filename: str):
    m = _SXXEXX_RE.search(filename)
    if not m:
        return None
    if m.group(1):
        return (int(m.group(1)), int(m.group(2)))
    return (int(m.group(3)), int(m.group(4)))


def is_ours(srt_path: str) -> bool:
    try:
        with open(srt_path, encoding="utf-8", errors="replace") as f:
            return OUR_HEADER in f.read(300)
    except Exception:
        return False


def find_episodes(show_dir: str):
    """Un elemento per episodio: {key, video, it_ours, en_external}."""
    by_key = {}
    for root, _dirs, files in os.walk(show_dir):
        for name in files:
            key = episode_key(name)
            if key is None:
                continue
            path = os.path.join(root, name)
            entry = by_key.setdefault(key, {"key": key, "video": None,
                                             "it_ours": None, "en_external": None})
            low = name.lower()
            if low.endswith((".mkv", ".mp4")):
                entry["video"] = path
            elif low.endswith(".srt"):
                if ("en" in low or "eng" in low) and "it" not in low.split(".en")[0][-3:]:
                    entry.setdefault("en_candidates", []).append(path)
                if ".it." in low or low.endswith(".it.srt"):
                    if is_ours(path):
                        entry["it_ours"] = path
    for entry in by_key.values():
        cands = entry.pop("en_candidates", [])
        entry["en_external"] = cands[0] if cands else None
    return sorted(by_key.values(), key=lambda e: e["key"])


def get_english_track_index(video: str):
    """Indice della migliore traccia subrip inglese incorporata, o None."""
    streams = probe_subtitles(video)
    eng = [s for s in streams if s["language"].startswith("en")
           and s["codec_name"] == "subrip"
           and "forced" not in s["title"].lower()]
    if not eng:
        return None
    # Preferisci la traccia SENZA "SDH"/"CC" nel titolo (più pulita).
    plain = [s for s in eng if "sdh" not in s["title"].lower()
             and "cc" not in s["title"].lower()]
    return (plain[0] if plain else eng[0])["index"]


def collect_show_pairs(show_dir: str, work_dir: str, exclude_keys=None,
                        log=print):
    """[(source_text, reference_text, start, end), ...] su tutti gli episodi
    CON bozza nostra, esclusi quelli in `exclude_keys` (episodi gia' usati
    in una run precedente — vedi core/glossary_state.py, evita
    l'auto-alimentazione sugli aggiornamenti).

    Ritorna (pairs, used_episode_keys, counters): used_episode_keys sono le
    chiavi (season, episode) degli episodi EFFETTIVAMENTE inclusi in questa
    run (bozza + allineamento riusciti), da marcare come "usati" solo se
    l'utente conferma il glossario in GUI. `counters` e' un dict con
    skipped_no_draft/skipped_already_used/skipped_no_english — episodi
    scartati senza traccia inglese usabile (es. ffprobe/ffmpeg assenti dal
    PATH del venv_glossary) restavano invisibili prima di questo contatore:
    l'utente vedeva solo "campione insufficiente" senza sapere perche'
    (bug reale misurato in revisione)."""
    exclude_keys = exclude_keys or set()
    episodes = find_episodes(show_dir)
    all_pairs = []
    used_keys = []
    skipped_no_draft = 0
    skipped_already_used = 0
    skipped_no_english = 0
    for ep in episodes:
        if not ep["it_ours"]:
            skipped_no_draft += 1
            continue
        if ep["key"] in exclude_keys:
            skipped_already_used += 1
            continue
        en_path = ep["en_external"]
        if not en_path and ep["video"]:
            idx = get_english_track_index(ep["video"])
            if idx is not None:
                out_path = os.path.join(
                    work_dir, f"en_{ep['key'][0]:02d}x{ep['key'][1]:02d}.srt")
                if extract_srt(ep["video"], idx, out_path):
                    en_path = out_path
        if not en_path:
            skipped_no_english += 1
            log(f"  S{ep['key'][0]:02d}E{ep['key'][1]:02d}: "
                f"nessuna traccia inglese usabile, saltato")
            continue
        en_blocks = parse_srt(en_path)
        it_blocks = parse_srt(ep["it_ours"])
        pairs = align(en_blocks, it_blocks)
        all_pairs.extend(pairs)
        used_keys.append(ep["key"])
        log(f"  S{ep['key'][0]:02d}E{ep['key'][1]:02d}: "
            f"{len(pairs)}/{len(en_blocks)} blocchi allineati")
    if skipped_no_draft:
        log(f"  ({skipped_no_draft} episodi senza bozza nostra, saltati)")
    if skipped_already_used:
        log(f"  ({skipped_already_used} episodi gia' usati in una run precedente, saltati)")
    if skipped_no_english:
        log(f"  ({skipped_no_english} episodi senza traccia inglese usabile, saltati)")
    counters = {"skipped_no_draft": skipped_no_draft,
                "skipped_already_used": skipped_already_used,
                "skipped_no_english": skipped_no_english}
    return all_pairs, used_keys, counters


def _is_sentence_start(prefix: str) -> bool:
    """Vero se ciò che precede il match, sulla stessa riga, è vuoto, un
    trattino di dialogo, o finisce con punteggiatura di fine frase (anche
    seguita da virgolette di chiusura) — non solo l'inizio riga: una riga
    può contenere più frasi ("Come on, baby. Come on.")."""
    prefix = prefix.rstrip()
    if not prefix or prefix in "-–—":
        return True
    return prefix[-1] in '.!?' or (
        len(prefix) >= 2 and prefix[-1] in '"”\'' and prefix[-2] in '.!?')


def _term_present(term: str, src_text: str) -> bool:
    """Vero se `term` compare in `src_text` come parola/frase intera (confine
    di parola su entrambi i lati) — NON una sottostringa: "Ark" non deve
    matchare "dark"/"Mark"/"Arkansas". Usato per selezionare le coppie da
    passare ai canali di valutazione (allineamento/Qwen); un match troppo
    largo qui inquinerebbe i cluster con occorrenze dove il termine non
    c'e' davvero (bug reale misurato in revisione: Qwen puo' rispondere con
    uno span plausibile anche su una coppia dove il termine e' assente,
    perche' la validazione a sottostringa sul lato IT non lo intercetta)."""
    # Lookbehind esclude un apostrofo prima (evita match dentro "l'Arkham"),
    # il lookahead NO: un apostrofo dopo e' quasi sempre il genitivo
    # sassone ("Ark's") — il termine e' comunque presente, va incluso.
    pattern = r"(?<![\w'])" + re.escape(term) + r"(?!\w)"
    return re.search(pattern, src_text, re.IGNORECASE) is not None


def find_candidates(pairs, min_freq: int):
    """{candidato: {'total': n, 'verbatim': n, 'missing': n, 'examples': [...]}}

    Conta solo le occorrenze NON a inizio riga (l'inglese capitalizza ogni
    frase, quindi una parola comune capitalizzata solo a inizio riga —
    "What", "But", "So"...— non è un termine ricorrente da fissare). Per
    ogni riga del blocco, se tutto ciò che precede il match è vuoto o un
    solo trattino di dialogo ("- "), quell'occorrenza viene scartata dal
    conteggio: un vero nome proprio ricorrente compare comunque a
    sufficienza a metà frase per superare la soglia di frequenza.
    """
    stats = {}
    for p in pairs:
        src, ref = p["source"], p["reference"]
        ref_low = ref.lower()
        for line in src.split("\n"):
            for m in _CANDIDATE_RE.finditer(line):
                term = m.group(1)
                if term in _STOPWORDS:
                    continue
                if _is_sentence_start(line[:m.start()]):
                    continue
                entry = stats.setdefault(term, {"total": 0, "verbatim": 0,
                                                 "missing": 0, "examples": []})
                entry["total"] += 1
                present = term.lower() in ref_low
                if present:
                    entry["verbatim"] += 1
                else:
                    entry["missing"] += 1
                if len(entry["examples"]) < 4:
                    entry["examples"].append({"source": src, "reference": ref,
                                              "start": p["start"], "verbatim": present})
    return {t: s for t, s in stats.items() if s["total"] >= min_freq}


def gate_check(episode_count: int, block_count: int,
               min_episodes: int = 6, min_blocks: int = 6000) -> dict:
    """Gate a livello show — vedi memoria piano_glossario_per_show.md e il
    piano di sviluppo di Opus: sotto soglia, "campione insufficiente" e'
    un esito valido da MOSTRARE, non un errore da nascondere. Soglie
    calibrate sul pilota reale: The Ark (13.366 blocchi, 21 episodi) ha
    dato segnale solido, Brilliant Minds (3.645 blocchi) e' stato
    correttamente escluso come campione troppo piccolo."""
    ok = episode_count >= min_episodes and block_count >= min_blocks
    return {"ok": ok, "episodes": episode_count, "blocks": block_count,
            "need_episodes": min_episodes, "need_blocks": min_blocks}


def _channel_verdict(spans, examples, gc, min_occurrences, min_minor_cluster,
                      max_dominant_share):
    clusters = gc.cluster(spans, examples)
    v = gc.verdict(clusters, sum(1 for s in spans if s),
                    min_occurrences, min_minor_cluster, max_dominant_share)
    return clusters, v


def evaluate_term(term: str, term_pairs: list,
                   align_spans_by_term: dict, qwen_results_by_term: dict,
                   min_occurrences: int = 8, min_minor_cluster: int = 2,
                   max_dominant_share: float = 0.85,
                   min_qwen_coverage: float = 0.6) -> dict:
    """Combina i risultati (gia' calcolati) dei due canali per un termine
    in un unico verdetto. `status` e' "auto" SOLO se i due canali
    concordano su divergenza E su resa dominante; qualunque disaccordo,
    canale mancante, o qwen_coverage bassa finisce in "review". Non
    solleva mai: un canale mancante/fallito degrada a "review" col motivo
    esplicito, mai un crash che perde tutto il resto del report."""
    import glossary_cluster as gc

    record = {"term": term, "occurrences": len(term_pairs)}

    examples = [{"en": p["source"], "it": p["reference"], "t": p.get("start")}
                for p in term_pairs]

    # "occurrences" (sopra) e' quante volte il termine compare nel testo
    # sorgente; "extracted" per canale e' quante di quelle occorrenze hanno
    # prodotto uno span verificato — basi DIVERSE (l'allineamento o Qwen
    # possono non estrarre nulla per un'occorrenza). verdict()/min_occurrences
    # si applica alle occorrenze ESTRATTE, non al totale: la card mostra
    # entrambi i numeri esplicitamente per non confonderli (bug reale
    # misurato in revisione: "41 occorrenze" e "73% dominante" sembravano
    # riferirsi alla stessa base ma non era cosi').
    align_clusters, align_v = [], None
    align_spans = align_spans_by_term.get(term)
    if align_spans is not None:
        record["align_extracted"] = sum(1 for s in align_spans if s)
        try:
            align_clusters, align_v = _channel_verdict(
                align_spans, examples, gc, min_occurrences, min_minor_cluster,
                max_dominant_share)
        except Exception as e:
            record["align_error"] = str(e)

    qwen_clusters, qwen_v, qwen_cov = [], None, 0.0
    qwen_results = qwen_results_by_term.get(term)
    if qwen_results is not None:
        try:
            import glossary_qwen_extract as gq
            qwen_cov = gq.coverage(qwen_results)
            spans = gq.to_spans(qwen_results)
            record["qwen_extracted"] = sum(1 for s in spans if s)
            qwen_clusters, qwen_v = _channel_verdict(
                spans, examples, gc, min_occurrences, min_minor_cluster,
                max_dominant_share)
        except Exception as e:
            record["qwen_error"] = str(e)

    # Il report mostra i cluster del canale piu' informativo (allineamento,
    # tipicamente piu' copertura) per la revisione umana.
    shown_clusters = align_clusters or qwen_clusters
    record["clusters"] = [c.to_dict() for c in shown_clusters]
    record["align_verdict"] = ("diverging" if align_v and align_v["diverging"]
                                else "consistent" if align_v else "n/a")
    record["qwen_verdict"] = ("diverging" if qwen_v and qwen_v["diverging"]
                               else "consistent" if qwen_v else "n/a")
    record["qwen_coverage"] = round(qwen_cov, 3)
    dominant = (align_v or qwen_v or {}).get("dominant")
    record["dominant"] = dominant
    record["dominant_share"] = round((align_v or qwen_v or {}).get("dominant_share", 0.0), 3)

    both_ran = align_v is not None and qwen_v is not None
    agree_diverging = both_ran and align_v["diverging"] and qwen_v["diverging"]
    agree_dominant = (both_ran and align_v["dominant"] and qwen_v["dominant"]
                       and gc.normalize(align_v["dominant"]) == gc.normalize(qwen_v["dominant"]))
    if agree_diverging and agree_dominant and qwen_cov >= min_qwen_coverage:
        record["status"] = "auto"
        record["reason"] = "i due canali concordano su divergenza e resa dominante"
    elif align_v is None and qwen_v is None:
        record["status"] = "reject"
        record["reason"] = "nessun canale disponibile"
    else:
        record["status"] = "review"
        reasons = []
        if not both_ran:
            reasons.append("solo un canale disponibile")
        elif not agree_diverging:
            reasons.append("i canali non concordano sulla divergenza")
        elif not agree_dominant:
            reasons.append("i canali non concordano sulla resa dominante")
        if qwen_results is not None and qwen_cov < min_qwen_coverage:
            reasons.append(f"copertura Qwen bassa ({qwen_cov:.0%})")
        record["reason"] = "; ".join(reasons) or "verifica manuale consigliata"
    return record


def build_full_report(show_dir: str, name: str, tmdb_id=None, min_freq: int = 3,
                       min_episodes: int = 6, min_blocks: int = 6000,
                       use_align: bool = True, use_qwen: bool = True,
                       qwen_model_path: str = None, align_device: str = "cpu",
                       qwen_n_gpu_layers: int = -1,
                       exclude_keys=None, max_candidates: int = 25,
                       log=print, progress_cb=None, report_out: str = None) -> dict:
    """Orchestrazione completa: gate show -> shortlist candidati (segnale
    grezzo verbatim/assente, riusato solo per ORDINARE cosa vale la pena
    approfondire) -> per ognuno dei `max_candidates` piu' promettenti,
    valutazione a due canali -> report finale. `progress_cb(phase, done,
    total, msg)` per l'integrazione GUI/subprocess; None = silenzioso.
    Il report viene SEMPRE scritto su disco (anche col gate non superato:
    e' un esito valido, non un errore — chi chiama deve poterlo mostrare),
    su `report_out` se dato, altrimenti nel percorso di default in
    mt_eval/. Il path scritto e' sempre in report["_report_path"]."""
    def _prog(phase, done, total, msg=""):
        if progress_cb:
            progress_cb(phase, done, total, msg)

    def _write_report(report: dict) -> dict:
        out_path = report_out or os.path.join(
            SCRIPT_DIR, f"glossary_report_{name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        report["_report_path"] = out_path
        return report

    work_dir = os.path.join(SCRIPT_DIR, "glossary_work", name)
    os.makedirs(work_dir, exist_ok=True)

    episodes_all = find_episodes(show_dir)
    ep_with_draft = [e for e in episodes_all if e["it_ours"]]
    fresh = [e for e in ep_with_draft if e["key"] not in (exclude_keys or set())]

    _prog("collect", 0, 1, f"{len(ep_with_draft)} episodi con bozza nostra, "
                            f"{len(fresh)} freschi")
    pairs, used_keys, skip_counters = collect_show_pairs(
        show_dir, work_dir, exclude_keys, log=log)
    gate = gate_check(len(used_keys), len(pairs), min_episodes, min_blocks)
    if not gate["ok"]:
        return _write_report({
            "show": name, "tmdb_id": tmdb_id, "gate": gate,
            "episodes_used": used_keys, "blocks": len(pairs),
            "skipped": skip_counters, "candidates": []})

    candidates = find_candidates(pairs, min_freq)
    ranked = sorted(candidates.items(), key=lambda kv: -kv[1]["missing"])[:max_candidates]
    term_pairs_by_term = {
        term: [p for p in pairs if _term_present(term, p["source"])]
        for term, _ in ranked}

    # Passaggio 1: allineamento LaBSE su TUTTI i termini, poi scarico il
    # modello — mai in memoria insieme a Qwen (vedi piano di sviluppo).
    align_spans_by_term = {}
    if use_align:
        try:
            import glossary_align as ga
            ga.load(device=align_device)
            for idx, (term, _stats) in enumerate(ranked):
                _prog("align", idx, len(ranked), term)
                align_spans_by_term[term] = ga.align_spans(
                    term_pairs_by_term[term], term)
            _prog("align", len(ranked), len(ranked), "")
        except Exception as e:
            log(f"  [allineamento] canale saltato: {e}")
        finally:
            try:
                import glossary_align as ga
                ga.unload()
            except Exception:
                pass

    # Passaggio 2: Qwen su TUTTI i termini, dopo aver scaricato LaBSE.
    # Delegato al venv principale via subprocess (GPU) invece che caricato
    # in locale — vedi glossary_qwen_bridge.py per il motivo.
    qwen_results_by_term = {}
    qwen_channel_error = None
    if use_qwen and qwen_model_path:
        try:
            import glossary_qwen_bridge as gqb
            ranked_terms = [term for term, _stats in ranked]
            # Prefissi cumulativi sulle coppie per termine: il subprocess
            # riporta il progresso per-coppia con l'indice di TERMINE
            # costante (term_idx), quindi senza questo conteggio globale la
            # barra della GUI resterebbe ferma per tutta la durata di un
            # singolo termine (minuti) pur ricevendo decine di eventi.
            pair_counts = [len(term_pairs_by_term[t]) for t in ranked_terms]
            prefix = [0]
            for c in pair_counts:
                prefix.append(prefix[-1] + c)
            total_pairs = prefix[-1]

            def _qwen_prog(term_idx, term_total, term, done, total):
                global_done = prefix[term_idx] + done if term_idx < len(prefix) else done
                _prog("qwen", global_done, total_pairs, f"{term} ({done}/{total})")

            qwen_results_by_term = gqb.run_qwen_channel(
                qwen_model_path, term_pairs_by_term, ranked_terms, work_dir,
                n_gpu_layers=qwen_n_gpu_layers, progress_cb=_qwen_prog, log=log)
            _prog("qwen", total_pairs, total_pairs, "")
        except Exception as e:
            qwen_channel_error = str(e)
            log(f"  [Qwen] canale saltato: {e}")

    results = []
    for term, _stats in ranked:
        rec = evaluate_term(term, term_pairs_by_term[term],
                             align_spans_by_term, qwen_results_by_term)
        results.append(rec)

    results.sort(key=lambda r: (r["status"] != "auto", r["status"] != "review",
                                 -r["occurrences"]))
    report = {
        "show": name, "tmdb_id": tmdb_id, "gate": gate,
        "episodes_used": used_keys, "blocks": len(pairs),
        "skipped": skip_counters, "candidates": results,
        "qwen_channel_error": qwen_channel_error,
    }
    return _write_report(report)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-dir", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--min-freq", type=int, default=3)
    args = ap.parse_args()

    work_dir = os.path.join(SCRIPT_DIR, "glossary_work", args.name)
    os.makedirs(work_dir, exist_ok=True)

    print(f"Show: {args.show_dir}\n")
    pairs, _used_keys, _skipped = collect_show_pairs(args.show_dir, work_dir)
    print(f"\nTotale blocchi allineati (tutti gli episodi con bozza nostra): {len(pairs)}")

    candidates = find_candidates(pairs, args.min_freq)
    ranked = sorted(candidates.items(), key=lambda kv: -kv[1]["missing"])

    out_path = os.path.join(SCRIPT_DIR, f"glossary_candidates_{args.name}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for term, s in ranked:
            f.write(json.dumps({"term": term, **s}, ensure_ascii=False) + "\n")

    print(f"\n{len(ranked)} candidati (frequenza >= {args.min_freq}), "
          f"i primi 15 per incoerenza (occorrenze 'assenti'):\n")
    for term, s in ranked[:15]:
        print(f"  {term!r}: {s['total']} tot, {s['verbatim']} verbatim, "
              f"{s['missing']} assenti")
        for ex in s["examples"][:2]:
            flag = "OK " if ex["verbatim"] else "MISS"
            print(f"    [{flag}] EN: {ex['source'][:60]!r}")
            print(f"          IT: {ex['reference'][:60]!r}")

    print(f"\nScritto: {out_path}")


if __name__ == "__main__":
    main()
