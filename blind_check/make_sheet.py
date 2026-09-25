"""
Passo 4 — FOGLIO CIECO (CPU).

Legge work/src, work/tr (base e ricomposta) e costruisce le coppie da giudicare:
solo le unita' ricomposte in cui le due traduzioni differiscono, al massimo
MAX_PAIRS_PER_FILE per file e N_PAIRS_TARGET in totale (seme fisso), con A/B
scambiati a caso. Scrive:
  work/foglio/lotto_NN.txt         da leggere e giudicare (25 coppie per lotto)
  work/giudizi.txt                 modello da compilare (una riga per coppia)
  work/NON_APRIRE_mappatura.json   A/B -> base/ricomposta: non guardarlo prima di aver finito

Uso: venv\\Scripts\\python.exe blind_check\\make_sheet.py
"""
import random
import sys

import common as C
import decision_rule as R
import sheet_lib as L

LOT = 25


def main():
    sel = C.read_json(C.WORK / 'selection.json')
    if not sel:
        sys.exit("selection.json mancante")
    rerender = '--rerender' in sys.argv
    map_path = C.WORK / 'NON_APRIRE_mappatura.json'
    if map_path.exists() and not rerender:
        sys.exit("il foglio esiste gia' (NON_APRIRE_mappatura.json): non si rigenera dopo aver iniziato a giudicare. "
                 "Per rifare SOLO l'impaginazione dei lotti (stesse coppie, stessi id, stessa mappatura): --rerender.")
    SR = L.load_recompose()
    pairs_by_file = {}
    for it in sel['items']:
        d = C.WORK / 'tr' / it['id']
        src = C.WORK / 'src' / f"{it['id']}.src.srt"
        if not (d / 'res.json').exists() or not src.exists():
            print(f"salto {it['id']}: doppia traduzione non completata")
            continue
        rng = random.Random(f"{R.SEED}:{it['id']}:pairs")
        ps = L.build_pairs(SR, src, d / 'base.srt', d / 'ricomposta.srt', it, rng, R.MAX_PAIRS_PER_FILE)
        pairs_by_file[it['id']] = ps
        print(f"{it['id']:45s} coppie diverse disponibili (max {R.MAX_PAIRS_PER_FILE}): {len(ps)}")
    pairs, mapping = L.assemble(pairs_by_file, R.SEED, R.N_PAIRS_TARGET)
    if not pairs:
        sys.exit("nessuna coppia da giudicare")
    if rerender:
        old = C.read_json(map_path)
        if old != mapping:
            sys.exit("--rerender: la mappatura ricalcolata NON coincide con quella salvata: nessun file modificato")
        print("mappatura identica a quella salvata: riscrivo solo i lotti (giudizi.txt e mappatura intatti)")
    (C.WORK / 'foglio').mkdir(parents=True, exist_ok=True)
    lots = [pairs[i:i + LOT] for i in range(0, len(pairs), LOT)]
    for n, lot in enumerate(lots, start=1):
        (C.WORK / 'foglio' / f"lotto_{n:02d}.txt").write_text(L.render_lot(lot, n, len(lots)), encoding='utf-8')
    if not rerender:
        (C.WORK / 'giudizi.txt').write_text(
            "# una riga per coppia: ID|A|  ID|B|  ID|P|   (+ lettere a/b minuscole dopo la seconda barra per un difetto visibile)\n"
            + '\n'.join(f"{p['id']}||" for p in pairs) + '\n', encoding='utf-8')
        C.write_json_atomic(map_path, mapping)
    print(f"\n{len(pairs)} coppie in {len(lots)} lotti: {C.WORK / 'foglio'}\n"
          f"compila {C.WORK / 'giudizi.txt'}; poi lancia conta.py (NON aprire la mappatura prima)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
