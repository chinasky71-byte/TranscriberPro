"""
Passo 5 — CONTEGGIO E VERDETTO (CPU), secondo blind_check/decision_rule.py.

Legge work/giudizi.txt e la mappatura nascosta, conta le preferenze per la
ricomposizione contro la base, i difetti visibili attribuiti a ciascun braccio
e applica la regola congelata. Scrive work/report_cieco.txt/json.

Uso: venv\\Scripts\\python.exe blind_check\\conta.py
"""
import sys

import common as C
import decision_rule as R
import sheet_lib as L


def main():
    mapping = C.read_json(C.WORK / 'NON_APRIRE_mappatura.json')
    gp = C.WORK / 'giudizi.txt'
    if not mapping or not gp.exists():
        sys.exit("mappatura o giudizi.txt mancanti")
    judgments, errs = L.parse_judgments(gp.read_text(encoding='utf-8'))
    unknown = [k for k in judgments if k not in mapping]
    for e in errs:
        print("ATTENZIONE", e)
    if unknown:
        print("ATTENZIONE id sconosciuti ignorati:", unknown)
    todo = [k for k in mapping if k not in judgments]
    if todo:
        print(f"ATTENZIONE {len(todo)} coppie non ancora giudicate (es. {todo[:5]}): il verdetto vale sul giudicato")
    res = L.tally(mapping, judgments, R)
    sel = C.read_json(C.WORK / 'selection.json') or {}
    changed = sel.get('rule_sha256') and sel['rule_sha256'] != C.sha256_file(C.HERE / 'decision_rule.py')
    lines = [f"CONTROLLO ALLA CIECA — regola congelata il {R.FROZEN_ON} ({R.NOTE})"]
    if changed:
        lines.append("!!! decision_rule.py e' CAMBIATO dopo la selezione: verdetto NON VALIDO.")
        res['verdict'] = 'NON_VALIDO'
    lines += [f"giudicate {res['n_judged']} | ricomposizione {res['ricomposta']} | base {res['base']} | pari {res['pari']}",
              f"quota ricomposizione fra i non pari: {res['share']:.3f}  (p unilaterale {res['p']:.4f})",
              f"difetti visibili: ricomposizione {res['defects_ricomposta']} ({res['defect_rate']:.1%} dei giudizi), "
              f"base {res['defects_base']}",
              f"film con la ricomposizione in maggioranza: {res['films_majority']}",
              "per file [ricomposizione, base, pari]:"]
    lines += [f"   {k:45s} {v}" for k, v in sorted(res['per_file'].items())]
    lines.append(f"\nVERDETTO: {res['verdict']}")
    lines += [f"   - {r}" for r in res['reasons']]
    txt = '\n'.join(lines)
    print(txt)
    (C.WORK / 'report_cieco.txt').write_text(txt, encoding='utf-8')
    C.write_json_atomic(C.WORK / 'report_cieco.json', res)
    return 0


if __name__ == '__main__':
    sys.exit(main())
