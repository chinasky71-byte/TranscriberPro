# -*- coding: utf-8 -*-
"""
Corrispondenza tra i percorsi che il Library Scanner restituisce (`windows_path`: `\\\\server\\film\\...` o `V:\\...`) e i percorsi
locali di questo computer (cartelle condivise montate, ad es. `/mnt/film`). Serve soprattutto su Linux/macOS, dove il percorso del
server non esiste; su Windows la mappa e' vuota (impostazione predefinita) e ogni funzione restituisce il percorso invariato.

La mappa e' un testo, una regola per riga:  `<prefisso del server>=<prefisso locale>`  (righe vuote e `#...` ignorate), ad es.
    \\\\192.168.1.12\\film=/mnt/film
    V:\\=/mnt/v
Vince il prefisso piu' lungo. Il confronto del lato server ignora maiuscole/minuscole e il tipo di barra; il resto del percorso
si conserva cosi' com'e'. Solo libreria standard.
"""
from typing import List, Tuple

Rule = Tuple[str, str]


def parse_map(text) -> List[Rule]:
    """Testo -> lista (prefisso_server, prefisso_locale), dal prefisso piu' lungo al piu' corto. Righe non valide ignorate."""
    rules: List[Rule] = []
    for line in (text or '').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        srv, loc = (x.strip() for x in s.split('=', 1))
        if srv and loc and _norm(srv) and _norm(loc):   # un lato che si riduce a '/' farebbe corrispondere ogni percorso
            rules.append((srv, loc))
    rules.sort(key=lambda r: len(_norm(r[0])), reverse=True)
    return rules


def _norm(p: str) -> str:
    return p.replace('\\', '/').rstrip('/')


def _swap(path: str, src: str, dst: str, case_insensitive: bool) -> str:
    """Se `path` comincia con il prefisso `src` (confini di cartella), lo sostituisce con `dst`; altrimenti None."""
    n, s = _norm(path), _norm(src)
    a, b = (n.lower(), s.lower()) if case_insensitive else (n, s)
    if a == b or a.startswith(b + '/'):
        rest = n[len(s):]
        sep = '\\' if (('\\' in dst and '/' not in dst) or dst[:2] == '\\\\' or (len(dst) == 2 and dst[1] == ':')) else '/'
        if sep == '\\':
            rest = rest.replace('/', '\\')
        return dst.rstrip('\\/') + rest
    return None


def to_local(path: str, rules: List[Rule]) -> str:
    """Percorso del server -> percorso locale. Senza regola corrispondente restituisce `path` invariato."""
    if not path or not rules:
        return path
    for srv, loc in rules:
        out = _swap(path, srv, loc, case_insensitive=True)
        if out is not None:
            return out
    return path


def to_server(path: str, rules: List[Rule]) -> str:
    """Percorso locale -> percorso del server (per le chiamate all'API). Senza regola corrispondente restituisce `path` invariato."""
    if not path or not rules:
        return path
    for srv, loc in sorted(rules, key=lambda r: len(_norm(r[1])), reverse=True):
        out = _swap(path, loc, srv, case_insensitive=not loc.startswith('/'))
        if out is not None:
            return out
    return path
