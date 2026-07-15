# -*- coding: utf-8 -*-
"""
Costruisce ground-truth di genere (1ª persona) dai film con doppia traccia
sottotitoli testo (ita + eng), sfruttando la traduzione professionale italiana
come riferimento corretto — nessuna annotazione manuale delle forme.

Pipeline:
  1. Rileva gli indici delle tracce ita/eng subrip (ffprobe) ed estrae i due SRT.
  2. Allinea per SOVRAPPOSIZIONE TEMPORALE (molti-a-molti): a ogni cue italiana
     associa la concatenazione delle cue inglesi che si sovrappongono nel tempo.
  3. Marca le righe italiane con forma di GENERE in PRIMA PERSONA (euristica),
     che sono il ground-truth d'interesse (il traduttore ha già risolto il genere
     del parlante dall'ascolto).
  4. Emette un TSV rivedibile: start, ita_ref, eng_source, marker, femminile?

L'output NON è ancora la metrica: è il materiale da (a) spot-checkare a campione
e (b) passare a NLLB per misurare quante di queste forme il modello sbaglia.

Uso:
    python gender_eval/build_film_groundtruth.py --video "V:/Veronica Mars/Season 1/....mkv"
    python gender_eval/build_film_groundtruth.py --video "..." --out veronica_s01e01.tsv
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "film_groundtruth"


# ---------------------------------------------------------------------------
# Estrazione tracce
# ---------------------------------------------------------------------------

def ffprobe_sub_streams(video: str):
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 's',
         '-show_entries', 'stream=index,codec_name:stream_tags=language,title',
         '-of', 'json', video],
        capture_output=True, text=True, encoding='utf-8', timeout=120)
    return json.loads(out.stdout or '{}').get('streams', [])


def pick_track(streams, lang_prefix):
    """Sceglie la miglior traccia subrip per lingua: preferisce 'regular'/full,
    evita 'forced' (che ha poche righe)."""
    cands = [s for s in streams
             if s.get('codec_name') == 'subrip'
             and (s.get('tags') or {}).get('language', '').lower().startswith(lang_prefix)]
    if not cands:
        return None
    def score(s):
        title = ((s.get('tags') or {}).get('title') or '').lower()
        sc = 0
        if 'forced' in title:
            sc -= 10
        if 'sdh' in title or 'non udenti' in title or 'cc' in title:
            sc -= 1   # SDH ok ma leggermente meno pulito
        if 'regular' in title or 'full' in title:
            sc += 2
        return sc
    cands.sort(key=score, reverse=True)
    return cands[0]['index']


def extract_srt(video: str, index: int, dest: Path):
    subprocess.run(
        ['ffmpeg', '-y', '-v', 'error', '-i', video, '-map', f'0:{index}', str(dest)],
        check=True, timeout=300)


# ---------------------------------------------------------------------------
# Parsing SRT
# ---------------------------------------------------------------------------

_TS = re.compile(
    r'(\d+)\s*\n(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)\s*\n'
    r'((?:.*\n?)+?)(?=\n\d+\s*\n|\Z)', re.MULTILINE)

_TAGS = re.compile(r'<[^>]+>')            # <i> </i> <font>
_SPEAKER = re.compile(r'^\s*[-–—]?\s*\[[^\]]+\]\s*', re.MULTILINE)  # [Veronica]
_PAREN = re.compile(r'\([^)]*\)')          # (ride)
_MUSIC = re.compile(r'[♪♫#]+')
_LEAD_DASH = re.compile(r'^\s*[-–—]\s*', re.MULTILINE)


def clean_text(t: str) -> str:
    t = _TAGS.sub('', t)
    t = _SPEAKER.sub('', t)
    t = _PAREN.sub('', t)
    t = _MUSIC.sub('', t)
    t = _LEAD_DASH.sub('', t)
    t = t.replace('\n', ' ').replace('’', "'")
    return re.sub(r'\s+', ' ', t).strip()


def _is_dialog_cue(raw: str) -> bool:
    """True se la cue contiene un dialogo a due parlanti ("- ... - ...").

    Una cue con due (o più) righe che iniziano col trattino, o con una
    risposta introdotta da trattino su riga successiva, ha DUE parlanti:
    non è attribuibile a un singolo speaker → va esclusa dal ground-truth.
    """
    lines = [l.strip() for l in raw.strip().split('\n') if l.strip()]
    dash_lines = sum(1 for l in lines if re.match(r'^[-–—]', l))
    if dash_lines >= 2:
        return True
    if dash_lines == 1 and len(lines) >= 2 and not re.match(r'^[-–—]', lines[0]):
        return True
    return False


def parse_srt(path: Path, detect_dialog: bool = False):
    content = path.read_text(encoding='utf-8', errors='replace')
    cues = []
    for m in _TS.finditer(content):
        s = (int(m.group(2))*3600 + int(m.group(3))*60 + int(m.group(4)))*1000 + int(m.group(5))
        e = (int(m.group(6))*3600 + int(m.group(7))*60 + int(m.group(8)))*1000 + int(m.group(9))
        raw = m.group(10)
        txt = clean_text(raw)
        if txt:
            if detect_dialog:
                cues.append((s, e, txt, _is_dialog_cue(raw)))
            else:
                cues.append((s, e, txt))
    return cues


# ---------------------------------------------------------------------------
# Allineamento per sovrapposizione temporale
# ---------------------------------------------------------------------------

def align(ita_cues, eng_cues):
    """Per ogni cue italiana (s, e, txt, is_dialog) ritorna
    (start_ms, end_ms, ita_text, eng_text_concatenato, is_dialog)."""
    pairs = []
    j0 = 0
    for (s, e, it, dlg) in ita_cues:
        overlap = []
        for k in range(j0, len(eng_cues)):
            es, ee, et = eng_cues[k]
            if ee < s:              # cue eng interamente prima: avanza la base
                j0 = k + 1
                continue
            if es > e:              # cue eng interamente dopo: stop
                break
            if max(s, es) < min(e, ee):   # sovrapposizione reale
                overlap.append(et)
        eng = ' '.join(dict.fromkeys(overlap))   # dedup preservando ordine
        pairs.append((s, e, it, eng, dlg))
    return pairs


# ---------------------------------------------------------------------------
# Filtro spaCy (preferito): forma di GENERE in PRIMA PERSONA nell'italiano
# ---------------------------------------------------------------------------

_NLP = None
_SPACY_TRIED = False


def _get_nlp():
    global _NLP, _SPACY_TRIED
    if not _SPACY_TRIED:
        _SPACY_TRIED = True
        try:
            import spacy
            _NLP = spacy.load('it_core_news_lg')
        except Exception as e:
            print(f"[spaCy non disponibile: {str(e)[:60]}] uso euristica regex", flush=True)
            _NLP = None
    return _NLP


# Forme flesse di "avere": il lemmatizer spaCy fallisce su forme
# capitalizzate ("Avrei"→"Avrei") e clitiche ("averlo"→"avere lo")
_AVERE_FORMS = {
    'ho', 'hai', 'ha', 'abbiamo', 'avete', 'hanno',
    'avevo', 'avevi', 'aveva', 'avevamo', 'avevate', 'avevano',
    'ebbi', 'avesti', 'ebbe', 'avemmo', 'aveste', 'ebbero',
    'avrò', 'avrai', 'avrà', 'avremo', 'avrete', 'avranno',
    'avrei', 'avresti', 'avrebbe', 'avremmo', 'avreste', 'avrebbero',
    'abbia', 'abbiate', 'abbiano', 'avessi', 'avesse', 'avessimo',
    'avessero', 'avendo', 'aver', 'avere',
}


def _is_avere(tok) -> bool:
    """True se il token è una forma di 'avere' (anche clitica/capitalizzata)."""
    lem = tok.lemma_.lower()
    if lem == 'avere' or lem.startswith('avere '):
        return True
    txt = tok.text.lower()
    return txt in _AVERE_FORMS or txt.startswith('aver')


def firstperson_gender_spacy(ita: str):
    """
    Candidato 1ª persona con genere se la frase contiene un predicato
    (participio Part o aggettivo ADJ) singolare marcato al genere, e un
    contesto di 1ª persona singolare. Ritorna (span, 'F'|'M'|None) o (None,None).

    Regole di 1ª persona (in ordine di robustezza):
      - un verbo/ausiliare FINITO con Person=1  (es. "ero", "sarei", "sento");
      - il verbo "sono" con un predicato SINGOLARE marcato → è "io sono"
        (la 3ª plurale richiederebbe accordo plurale);
      - un "io" esplicito.
    Esclude implicitamente 2ª/3ª persona (nessun aggancio 1ª persona) e i casi
    plurali (predicato Number=Sing richiesto → "sono stati" cade).
    """
    nlp = _get_nlp()
    if nlp is None:
        return firstperson_gender_regex(ita)
    doc = nlp(ita)

    for g in doc:
        # candidato: participio o aggettivo SINGOLARE marcato al genere
        if g.morph.get('Number') != ['Sing']:
            continue
        if g.morph.get('Gender') not in (['Fem'], ['Masc']):
            continue
        if not (g.pos_ == 'ADJ' or g.morph.get('VerbForm') == ['Part']):
            continue
        # anti-FP: la desinenza deve combaciare col genere (esclude mis-tag
        # tipo "potresti" e forme invariabili non misurabili)
        low = g.text.lower()
        if g.morph.get('Gender') == ['Fem'] and not low.endswith('a'):
            continue
        if g.morph.get('Gender') == ['Masc'] and not low.endswith('o'):
            continue
        # anti-FP: "stesso/stessa" concorda col nome, mai col parlante
        if g.lemma_.lower() == 'stesso':
            continue
        # anti-FP: mis-tag lessicali ricorrenti (interiezioni/particelle)
        if low in ('ciao', 'vero', 'so', 'ecco', 'bene', 'no'):
            continue
        # anti-FP: modificatore/argomento NOMINALE ("una CATTIVA compagnia",
        # "il mio orso VINTO"): concorda col nome, non col parlante
        if g.dep_ in ('amod', 'nummod', 'det', 'appos', 'nmod', 'obl',
                      'obj', 'iobj', 'nsubj', 'fixed', 'flat', 'compound'):
            continue
        # anti-FP: participio retto da AVERE in QUALSIASI forma — finita
        # ("Avrò dimenticato"), infinita ("potrei aver detto"), con clitico
        # ("ricordo di averlo fatto", lemma spaCy "avere lo"), o come
        # fratello aux del participio modale ("Avrei voluto", lemma non
        # normalizzato). Il participio con avere è invariabile (o concorda
        # col clitico oggetto), mai col parlante.
        if g.morph.get('VerbForm') == ['Part']:
            linked = [c for c in g.children if c.dep_.startswith('aux')
                      or c.dep_ == 'cop']
            if g.pos_ == 'AUX' or g.dep_.startswith('aux'):
                # participio modale ("voluto" in "Avrei voluto"): gli aux
                # coordinati sono FRATELLI sotto lo stesso head
                linked += [c for c in g.head.children
                           if c is not g and c.dep_.startswith('aux')]
            if any(_is_avere(c) for c in linked):
                continue
        # anti-FP: locuzioni avverbiali ("di nascosto", "all'improvviso"):
        # token retto/preceduto direttamente da preposizione
        if g.i > 0 and doc[g.i - 1].pos_ == 'ADP':
            continue

        # verbi FINITI legati SINTATTICAMENTE a g (l'ausiliare/copula che
        # regge g, non un verbo di un'altra proposizione nella stessa cue).
        # dep_ 'conj' escluso: un verbo COORDINATO ("...fantastica e lo
        # apprezzo") appartiene a un'altra proposizione.
        fins = [c for c in g.children
                if c.pos_ in ('AUX', 'VERB') and c.morph.get('VerbForm') == ['Fin']
                and c.dep_ != 'conj']
        h = g.head
        if h is not g and g.dep_ != 'conj':
            if h.pos_ in ('AUX', 'VERB') and h.morph.get('VerbForm') == ['Fin']:
                fins.append(h)
            for c in h.children:
                if c.pos_ == 'AUX' and c.morph.get('VerbForm') == ['Fin']:
                    fins.append(c)
        if not fins:
            continue

        # Nei tempi composti con AVERE il participio è INVARIABILE (maschile
        # di default, "ho detto/mangiato") → NON concorda col parlante.
        # Solo i participi con ESSERE concordano ("sono andata", "ero stanca").
        if g.morph.get('VerbForm') == ['Part']:
            aux_lemmas = {f.lemma_.lower() for f in fins if f.pos_ == 'AUX'}
            if 'avere' in aux_lemmas:
                continue

        persons = set()
        has_sono = False
        for f in fins:
            persons.update(f.morph.get('Person'))
            if f.text.lower() == 'sono':
                has_sono = True
        # soggetto esplicito "io"/"tu" tra i figli del verbo reggente
        # (e del predicato stesso: "fossi stato tu" aggancia "tu" a g)
        subj_toks = [c for f in fins for c in f.children] + list(g.children)
        has_io = any(c.text.lower() == 'io' for c in subj_toks)
        has_tu = any(c.text.lower() == 'tu' for c in subj_toks)
        if has_tu and not has_io:
            continue

        # decisione: 1ª persona se il verbo reggente è P1, o è "io ...",
        # o è "sono" con predicato singolare (→ io sono, non loro sono).
        # Escludi se il reggente è chiaramente 2ª/3ª persona.
        if '2' in persons or ('3' in persons and not has_sono and not has_io):
            continue
        if not ('1' in persons or has_io or has_sono):
            continue

        gender = 'F' if g.morph.get('Gender') == ['Fem'] else 'M'
        return g.text, gender

    return None, None


# ---------------------------------------------------------------------------
# Euristica regex (fallback se spaCy non c'è)
# ---------------------------------------------------------------------------

# Marcatori di soggetto 1ª persona singolare vicino a un participio/aggettivo genere.
_P1 = r'(?:io\s+)?(?:sono|ero|sarò|sarei|fui|mi\s+sento|mi\s+sentivo|mi\s+sentii|' \
      r'mi\s+sono|mi\s+ero|resto|rimango|rimasi|mi\s+sentirei)'
# participi/aggettivi con desinenza di genere (m -o/-i, f -a/-e) — catturiamo la desinenza
_GENDERED = r'([a-zàèéìòù]+?(?:at|ut|it|os|iv|ant|ent))([oaie])\b'

# forme frequenti irregolari/aggettivi comuni marcati al genere
_COMMON_F = re.compile(
    r'\b(stanca|sicura|pronta|sola|contenta|felice|convinta|delusa|stufa|'
    r'nata|cresciuta|rimasta|andata|stata|venuta|morta|viva|certa|'
    r'preoccupata|spaventata|arrabbiata|innamorata|sorpresa|seduta|'
    r'costretta|obbligata|abituata|grata|pentita|persa|sposata)\b', re.I)
_COMMON_M = re.compile(
    r'\b(stanco|sicuro|pronto|solo|contento|convinto|deluso|stufo|'
    r'nato|cresciuto|rimasto|andato|stato|venuto|morto|vivo|certo|'
    r'preoccupato|spaventato|arrabbiato|innamorato|sorpreso|seduto|'
    r'costretto|obbligato|abituato|grato|pentito|perso|sposato)\b', re.I)

_P1_RE = re.compile(_P1 + r'\s+(?:\w+\s+){0,2}?' + _GENDERED, re.I)


def firstperson_gender_regex(ita: str):
    """Ritorna (marker_trovato, genere 'F'|'M'|None) se la riga contiene una
    forma di genere plausibilmente in 1ª persona, altrimenti (None, None)."""
    m = _P1_RE.search(ita)
    if m:
        ending = m.group(2).lower()
        g = 'F' if ending == 'a' else ('M' if ending == 'o' else None)
        return m.group(0), g
    # marcatori di 1ª persona + aggettivo comune marcato
    if re.search(_P1, ita, re.I):
        mf = _COMMON_F.search(ita)
        if mf:
            return mf.group(0), 'F'
        mm = _COMMON_M.search(ita)
        if mm:
            return mm.group(0), 'M'
    return None, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', required=True)
    ap.add_argument('--out', default=None, help='nome TSV (default: dal filename)')
    ap.add_argument('--ita-index', type=int, default=None)
    ap.add_argument('--eng-index', type=int, default=None)
    args = ap.parse_args()

    video = args.video
    if not Path(video).exists():
        sys.exit(f"File non trovato: {video}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(video).stem
    out_tsv = OUT_DIR / (args.out or f"{stem}.tsv")

    streams = ffprobe_sub_streams(video)
    ita_idx = args.ita_index if args.ita_index is not None else pick_track(streams, 'ita')
    eng_idx = args.eng_index if args.eng_index is not None else pick_track(streams, 'eng')
    if ita_idx is None or eng_idx is None:
        sys.exit(f"Tracce testo mancanti (ita={ita_idx}, eng={eng_idx}). Stream: "
                 + json.dumps([(s['index'], s.get('codec_name'),
                                (s.get('tags') or {}).get('language')) for s in streams]))
    print(f"Tracce: ita=0:{ita_idx}, eng=0:{eng_idx}")

    tmp = OUT_DIR / "_tmp"
    tmp.mkdir(exist_ok=True)
    ita_srt, eng_srt = tmp / f"{stem}.ita.srt", tmp / f"{stem}.eng.srt"
    extract_srt(video, ita_idx, ita_srt)
    extract_srt(video, eng_idx, eng_srt)

    ita_cues = parse_srt(ita_srt, detect_dialog=True)
    eng_cues = parse_srt(eng_srt)
    print(f"Cue: ita={len(ita_cues)}, eng={len(eng_cues)}")

    pairs = align(ita_cues, eng_cues)
    aligned_ok = sum(1 for p in pairs if p[3])
    print(f"Cue italiane con sorgente inglese allineata: {aligned_ok}/{len(pairs)}")

    def ms2ts(ms):
        h, r = divmod(ms, 3600000); m, r = divmod(r, 60000); s, msx = divmod(r, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{msx:03d}"

    n_cand = 0
    n_dialog_skip = 0
    with open(out_tsv, 'w', encoding='utf-8') as f:
        f.write("start\tend\tgender\tmarker\tita_reference\teng_source\n")
        for (start, end, it, en, dlg) in pairs:
            marker, g = firstperson_gender_spacy(it)
            if marker and en:            # candidato 1ª persona con sorgente
                if dlg:
                    # cue di dialogo a due parlanti: non attribuibile → skip
                    n_dialog_skip += 1
                    continue
                n_cand += 1
                f.write(f"{ms2ts(start)}\t{ms2ts(end)}\t{g or '?'}\t{marker}\t{it}\t{en}\n")

    print(f"\nCandidati 1ª persona con genere e sorgente EN: {n_cand}")
    print(f"TSV: {out_tsv}")
    # anteprima
    print("\n--- Anteprima primi candidati ---")
    lines = out_tsv.read_text(encoding='utf-8').splitlines()[1:11]
    for ln in lines:
        cols = ln.split('\t')
        if len(cols) >= 5:
            print(f"  [{cols[0]}] ({cols[2]}) {cols[4]}")
            print(f"        EN: {cols[5][:90]}")


if __name__ == '__main__':
    main()
