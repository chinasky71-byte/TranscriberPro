"""
Genera la pagina di confronto affiancato tra i motori di traduzione.

L'idea portante: il testo tradotto è reso in monospace con una guida verticale
a 42 caratteri. Il limite di riga dei sottotitoli è un conteggio di caratteri,
quindi il monospace è l'unica resa onesta del vincolo — e lo sforamento si vede
a occhio invece di essere un numero da leggere.

Uso:
    venv\\Scripts\\python mt_eval\\build_compare.py
    venv\\Scripts\\python mt_eval\\build_compare.py --out confronto.html
"""

import argparse
import html
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EVALSET = os.path.join(SCRIPT_DIR, "evalset.jsonl")

CPL_MAX = 42
CPS_MAX = 17.0
MIN_DUR = 1.0

# Volgarità italiane di forza piena. Serve a misurare se un motore attenua il
# turpiloquio dell'originale, cosa che la guida di stile vieta esplicitamente.
STRONG_RE = re.compile(
    r"cazz|merd|stronz|fanculo|porc|troi|figa|coglion|puttan|inculat|"
    r"sbatt|schifez|bastard|vaffa|fott", re.I)

# Ordine e nomi dei sistemi. Chi manca viene semplicemente saltato.
# La reference è una colonna come le altre, non un dato nascosto: senza un
# termine di paragone umano davanti agli occhi, ogni giudizio su "quanto è
# naturale" resta senza scala.
SYSTEMS = [
    ("tr_nllb_finetuned.jsonl", "NLLB fine-tuned", "motore in produzione"),
    ("tr_aya_v2.jsonl", "Aya Expanse 8B", "chat model, prompt di adattamento"),
    ("tr_hunyuan.jsonl", "Hunyuan-MT-7B", "modello MT specializzato"),
]

REFERENCE_LABEL = "Traduzione umana"
REFERENCE_SUB = "reference professionale"


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def measure(text, duration):
    lines = [l for l in text.split("\n") if l.strip()]
    longest = max((len(l) for l in lines), default=0)
    visible = len(text.replace("\n", " "))
    cps = visible / duration if duration > 0 else 0.0
    return {
        "lines": lines,
        "longest": longest,
        "over_cpl": longest > CPL_MAX,
        "cps": cps,
        "over_cps": cps > CPS_MAX,
        "chars": visible,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(SCRIPT_DIR, "confronto.html"))
    args = ap.parse_args()

    items = {d["id"]: d for d in load_jsonl(EVALSET)}
    order = sorted(items)

    systems = []
    for filename, label, subtitle in SYSTEMS:
        path = os.path.join(SCRIPT_DIR, filename)
        if not os.path.isfile(path):
            print(f"  assente, salto: {filename}")
            continue
        data = {d["id"]: d["text"] for d in load_jsonl(path)}
        systems.append({"label": label, "subtitle": subtitle, "data": data})
        print(f"  caricato: {label} ({len(data)} blocchi)")

    if not systems:
        sys.exit("Nessun file di traduzione trovato.")

    systems.append({
        "label": REFERENCE_LABEL,
        "subtitle": REFERENCE_SUB,
        "data": {i: items[i]["reference"] for i in order},
        "is_ref": True,
    })
    print(f"  caricato: {REFERENCE_LABEL} (termine di paragone)")

    durations = {
        i: max(MIN_DUR, len(items[i]["source"].replace("\n", " ")) / CPS_MAX)
        for i in order
    }

    # Statistiche per sistema.
    #
    # Nota su una metrica ASSENTE: il rispetto dei 17 caratteri al secondo non
    # è riportato. Le durate qui sono sintetiche, derivate dalla lunghezza del
    # testo inglese, e con quelle durate qualunque resa italiana più lunga
    # dell'originale risulta fuori norma — inclusa la traduzione umana, che
    # "sfora" nel 66% dei blocchi. Il CPS va misurato solo su timing reali.
    # Il limite di 42 caratteri per riga non dipende dalla durata ed è valido.
    profanity_ids = [i for i in order if items[i]["category"] == "parolacce"]

    for sysd in systems:
        n = len(order) or 1
        m = [measure(sysd["data"].get(i, ""), durations[i]) for i in order]
        kept = sum(1 for i in profanity_ids
                   if STRONG_RE.search(sysd["data"].get(i, "")))
        sysd["stats"] = {
            "over_cpl": sum(1 for x in m if x["over_cpl"]) * 100.0 / n,
            "avg_chars": sum(x["chars"] for x in m) / n,
            "profanity": kept,
            "profanity_total": len(profanity_ids),
        }

    src_avg = sum(len(items[i]["source"].replace("\n", " "))
                  for i in order) / (len(order) or 1)

    categories = sorted({items[i]["category"] for i in order})

    # ---------------------------------------------------------------- HTML
    parts = []
    add = parts.append

    add(f"""<title>Righello dei Sottotitoli</title>
<style>
:root {{
  --ground:  #F2F4F7;
  --surface: #FFFFFF;
  --sunken:  #E8EBF0;
  --ink:     #171A20;
  --ink-mid: #565D6B;
  --ink-dim: #7C8494;
  --rule:    #D6DBE3;
  --accent:  #A8741A;
  --accent-soft: #F0E3C8;
  --ok:      #2E6F52;
  --warn:    #A8621F;
  --bad:     #A63D3D;
  --mono: ui-monospace, "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace;
  --sans: system-ui, "Segoe UI", Roboto, sans-serif;
  --serif: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
}}
:root:not([data-theme="light"]) {{
  color-scheme: light dark;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground:  #101317;
    --surface: #191D23;
    --sunken:  #0B0D11;
    --ink:     #E4E7ED;
    --ink-mid: #A6ADBA;
    --ink-dim: #767E8C;
    --rule:    #2C323B;
    --accent:  #E0B052;
    --accent-soft: #3A2F17;
    --ok:      #5FBF8F;
    --warn:    #D9954E;
    --bad:     #E07272;
  }}
}}
:root[data-theme="dark"] {{
  --ground:  #101317;
  --surface: #191D23;
  --sunken:  #0B0D11;
  --ink:     #E4E7ED;
  --ink-mid: #A6ADBA;
  --ink-dim: #767E8C;
  --rule:    #2C323B;
  --accent:  #E0B052;
  --accent-soft: #3A2F17;
  --ok:      #5FBF8F;
  --warn:    #D9954E;
  --bad:     #E07272;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 15px;
  line-height: 1.5;
}}
.wrap {{ max-width: 1400px; margin: 0 auto; padding: 40px 24px 80px; }}

header {{ margin-bottom: 36px; }}
h1 {{
  font-family: var(--serif);
  font-size: clamp(28px, 4vw, 42px);
  font-weight: 600;
  letter-spacing: -0.015em;
  margin: 0 0 10px;
  text-wrap: balance;
}}
.lede {{
  color: var(--ink-mid);
  max-width: 62ch;
  margin: 0;
}}
.lede code {{ font-family: var(--mono); font-size: 0.9em; }}

/* Riepilogo ------------------------------------------------------------ */
.summary {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin: 32px 0 12px;
}}
.card {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 4px;
  padding: 18px 20px;
}}
.card h3 {{
  margin: 0 0 2px;
  font-size: 15px;
  font-weight: 600;
  font-family: var(--sans);
}}
.card .sub {{
  color: var(--ink-dim);
  font-size: 12.5px;
  margin-bottom: 14px;
}}
.metric {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 5px 0;
  border-top: 1px solid var(--rule);
  font-size: 13px;
}}
.metric span:first-child {{ color: var(--ink-mid); }}
.metric b {{
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 14px;
}}

/* Barra di conformità: la quota che sfora, resa come lunghezza */
.bar {{
  height: 4px;
  background: var(--sunken);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 3px;
}}
.bar i {{ display: block; height: 100%; }}

/* Filtri --------------------------------------------------------------- */
.controls {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 28px 0 20px;
  padding-top: 20px;
  border-top: 1px solid var(--rule);
}}
.controls .label {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-dim);
  margin-right: 4px;
}}
button.chip {{
  font: inherit;
  font-size: 12.5px;
  background: var(--surface);
  color: var(--ink-mid);
  border: 1px solid var(--rule);
  border-radius: 3px;
  padding: 5px 11px;
  cursor: pointer;
}}
button.chip:hover {{ border-color: var(--accent); color: var(--ink); }}
button.chip[aria-pressed="true"] {{
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--ink);
  font-weight: 600;
}}
button.chip:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}

/* Blocchi -------------------------------------------------------------- */
.block {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 4px;
  margin-bottom: 14px;
  overflow: hidden;
}}
.block-head {{
  display: flex;
  gap: 12px;
  align-items: baseline;
  padding: 11px 16px;
  background: var(--sunken);
  border-bottom: 1px solid var(--rule);
  flex-wrap: wrap;
}}
.idx {{
  font-family: var(--mono);
  font-size: 12px;
  color: var(--ink-dim);
  font-variant-numeric: tabular-nums;
}}
.cat {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent);
  font-weight: 600;
}}
.src {{
  font-family: var(--mono);
  font-size: 13px;
  color: var(--ink-mid);
  white-space: pre-wrap;
  flex: 1 1 100%;
  margin-top: 4px;
}}
.cols {{
  display: grid;
  grid-template-columns: repeat({len(systems)}, 1fr);
}}
.col {{ padding: 14px 16px; border-right: 1px solid var(--rule); min-width: 0; }}
.col:last-child {{ border-right: none; }}
.col h4 {{
  margin: 0 0 9px;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-dim);
  font-weight: 600;
}}

/* Il righello: 42 caratteri esatti in monospace ------------------------ */
.ruler {{ position: relative; overflow-x: auto; }}
.ruler::before {{
  content: "";
  position: absolute;
  top: 0; bottom: 0;
  left: calc(42ch + 1px);
  width: 1px;
  background: var(--accent);
  opacity: 0.5;
}}
.line {{
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre;
  min-width: max-content;
}}
.line .over {{
  background: color-mix(in srgb, var(--bad) 18%, transparent);
  text-decoration: underline wavy var(--bad) 1px;
  text-underline-offset: 3px;
}}
.empty {{ color: var(--bad); font-style: italic; font-family: var(--sans); }}

.tags {{ display: flex; gap: 6px; margin-top: 9px; flex-wrap: wrap; }}
.tag {{
  font-family: var(--mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  padding: 1px 6px;
  border-radius: 2px;
  border: 1px solid var(--rule);
  color: var(--ink-dim);
}}
.tag.bad {{ color: var(--bad); border-color: var(--bad); }}
.tag.ok {{ color: var(--ok); border-color: var(--ok); }}

footer {{
  margin-top: 40px;
  padding-top: 18px;
  border-top: 1px solid var(--rule);
  color: var(--ink-dim);
  font-size: 12.5px;
}}
@media (max-width: 860px) {{
  .cols {{ grid-template-columns: 1fr; }}
  .col {{ border-right: none; border-bottom: 1px solid var(--rule); }}
}}
</style>
""")

    add('<div class="wrap"><header>')
    add("<h1>Righello dei sottotitoli</h1>")
    add(f'<p class="lede">Confronto fra {len(systems) - 1} motori di '
        f'traduzione EN&rarr;IT, con la traduzione umana come quarta colonna, '
        f'su {len(order)} blocchi stratificati per categoria. '
        f'La linea verticale marca i <strong>42 caratteri</strong>: il testo è '
        f'in monospace perché il limite è un conteggio di caratteri, quindi '
        f'ciò che supera la linea è esattamente ciò che sfora.</p>')
    add("</header>")

    # Riepilogo
    add('<div class="summary">')
    for sysd in systems:
        s = sysd["stats"]
        cpl_color = "var(--bad)" if s["over_cpl"] > 25 else (
            "var(--warn)" if s["over_cpl"] > 10 else "var(--ok)")
        prof_pct = (s["profanity"] * 100.0 / s["profanity_total"]
                    if s["profanity_total"] else 0)
        prof_color = "var(--bad)" if prof_pct < 40 else (
            "var(--warn)" if prof_pct < 70 else "var(--ok)")
        add(f'''<div class="card">
  <h3>{html.escape(sysd["label"])}</h3>
  <div class="sub">{html.escape(sysd["subtitle"])}</div>
  <div class="metric"><span>righe oltre 42 caratteri</span>
    <b>{s["over_cpl"]:.0f}%</b></div>
  <div class="bar"><i style="width:{min(100, s['over_cpl']):.0f}%;
    background:{cpl_color}"></i></div>
  <div class="metric"><span>turpiloquio mantenuto</span>
    <b>{s["profanity"]}/{s["profanity_total"]}</b></div>
  <div class="bar"><i style="width:{prof_pct:.0f}%;
    background:{prof_color}"></i></div>
  <div class="metric"><span>caratteri medi</span>
    <b>{s["avg_chars"]:.0f}</b></div>
</div>''')
    add(f'''<div class="card">
  <h3>Originale inglese</h3>
  <div class="sub">termine di paragone</div>
  <div class="metric"><span>caratteri medi</span>
    <b>{src_avg:.0f}</b></div>
  <div class="metric"><span>blocchi</span><b>{len(order)}</b></div>
  <div class="metric"><span>categorie</span><b>{len(categories)}</b></div>
</div>''')
    add("</div>")

    # Filtri
    add('<div class="controls"><span class="label">Categoria</span>')
    add('<button class="chip" data-cat="all" aria-pressed="true">tutte</button>')
    for cat in categories:
        add(f'<button class="chip" data-cat="{html.escape(cat)}" '
            f'aria-pressed="false">{html.escape(cat)}</button>')
    add('<span class="label" style="margin-left:12px">Mostra</span>')
    add('<button class="chip" id="only-over" aria-pressed="false">'
        'solo chi sfora i 42</button>')
    add("</div>")

    # Blocchi
    add('<div id="list">')
    for i in order:
        item = items[i]
        any_over = any(
            measure(s["data"].get(i, ""), durations[i])["over_cpl"]
            for s in systems
        )
        add(f'<article class="block" data-cat="{html.escape(item["category"])}" '
            f'data-over="{"1" if any_over else "0"}">')
        add('<div class="block-head">')
        add(f'<span class="idx">#{i:03d}</span>')
        add(f'<span class="cat">{html.escape(item["category"])}</span>')
        add(f'<span class="idx">{durations[i]:.1f}s</span>')
        add(f'<div class="src">{html.escape(item["source"])}</div>')
        add("</div>")
        add('<div class="cols">')
        for sysd in systems:
            text = sysd["data"].get(i, "")
            m = measure(text, durations[i])
            add('<div class="col">')
            add(f'<h4>{html.escape(sysd["label"])}</h4>')
            if not m["lines"]:
                add('<div class="empty">— nessun output —</div>')
            else:
                add('<div class="ruler">')
                for line in m["lines"]:
                    if len(line) > CPL_MAX:
                        head = html.escape(line[:CPL_MAX])
                        tail = html.escape(line[CPL_MAX:])
                        add(f'<div class="line">{head}'
                            f'<span class="over">{tail}</span></div>')
                    else:
                        add(f'<div class="line">{html.escape(line)}</div>')
                add("</div>")
            cpl_cls = "bad" if m["over_cpl"] else "ok"
            add(f'<div class="tags">'
                f'<span class="tag {cpl_cls}">{m["longest"]} car/riga</span>'
                f'<span class="tag">{m["chars"]} car</span>'
                f'</div>')
            add("</div>")
        add("</div></article>")
    add("</div>")

    add('<footer><p>Limite di riferimento: 42 caratteri per riga, guida di '
        'stile italiana Netflix. La conformità al reading speed (17 caratteri '
        'al secondo) <strong>non</strong> è riportata: le durate di questo set '
        'sono sintetiche, e con durate derivate dal testo inglese qualunque '
        "resa italiana più lunga dell'originale risulta fuori norma — "
        'compresa la traduzione umana, che le supererebbe nel 66% dei blocchi. '
        'Va misurata solo su tempi reali.</p></footer>')
    add("</div>")

    add("""
<script>
(function () {
  var list = document.getElementById('list');
  var blocks = Array.prototype.slice.call(list.children);
  var cat = 'all';
  var onlyOver = false;

  function apply() {
    blocks.forEach(function (b) {
      var okCat = cat === 'all' || b.dataset.cat === cat;
      var okOver = !onlyOver || b.dataset.over === '1';
      b.style.display = (okCat && okOver) ? '' : 'none';
    });
  }

  document.querySelectorAll('.chip[data-cat]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.chip[data-cat]').forEach(function (o) {
        o.setAttribute('aria-pressed', String(o === btn));
      });
      cat = btn.dataset.cat;
      apply();
    });
  });

  var over = document.getElementById('only-over');
  over.addEventListener('click', function () {
    onlyOver = !onlyOver;
    over.setAttribute('aria-pressed', String(onlyOver));
    apply();
  });
})();
</script>""")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"\nPagina scritta: {args.out}")


if __name__ == "__main__":
    main()
