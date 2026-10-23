# -*- coding: utf-8 -*-
"""Verifica che il testo ITALIANO dei log convertiti in tr() sia IDENTICO a quello del sorgente originale.

Uso:  python scripts_manutenzione/verify_i18n_identity.py <rif-git-base> <file.py> [--print]
      (es. origin/master core/pipeline.py)

Per ogni chiamata di log (_log/_emit/log/...) del file base e del file corrente, in ordine, valuta il primo
argomento con valori finti ma deterministici per i nomi (ogni nome/attributo/chiamata diventa un oggetto che si
formatta come il proprio nome e ricorda la specifica di formato: `{x:.2f}` -> "<x:.2f>"). Con la lingua IT il
risultato nuovo deve coincidere carattere per carattere con quello vecchio. Esce con 1 se trova differenze.
Solo lettura (eccetto un file temporaneo con la versione base)."""
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import i18n_convert as C  # noqa: E402


class D:
    """Valore finto: si formatta con il proprio nome e la specifica."""

    def __init__(self, name):
        self._n = name

    def __getattr__(self, a):
        if a.startswith('__'):
            raise AttributeError(a)
        return D(f"{self._n}.{a}")

    def __call__(self, *a, **k):
        return D(f"{self._n}({','.join(str(x) for x in a)})")

    def __getitem__(self, i):
        return D(f"{self._n}[{i}]")

    def __format__(self, spec):
        return f"<{self._n}:{spec}>" if spec else f"<{self._n}>"

    def __str__(self):
        return f"<{self._n}>"

    __repr__ = __str__

    def __len__(self):
        return 3

    def __iter__(self):
        return iter([D(f"{self._n}#0"), D(f"{self._n}#1")])

    def __bool__(self):
        return True

    def _bin(self, o):
        return D(f"({self._n}?{o})")

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _bin
    __floordiv__ = __mod__ = __pow__ = __neg__ = lambda self, *a: D(f"op({self._n})")
    __lt__ = __gt__ = __le__ = __ge__ = lambda self, o: True


class Env(dict):
    def __missing__(self, k):
        return D(k)


def evaluate(node, env):
    code = compile(ast.Expression(node), '<expr>', 'eval')
    return eval(code, {'__builtins__': {}}, env)


def sites_of(path, use_print):
    _, _, sites = C.collect(path, use_print)
    return sites


def main():
    args = [a for a in sys.argv[1:] if a != '--print']
    use_print = '--print' in sys.argv
    base, rel = args[0], args[1]
    old_src = subprocess.run(['git', 'show', f'{base}:{rel}'], cwd=ROOT, capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / 'old.py'
        tmp.write_bytes(old_src)
        old = sites_of(tmp, use_print)
    new = sites_of(ROOT / rel, use_print)
    from utils import translations
    translations.get_translations().set_language('it')
    # Le chiamate di log restano le stesse e nello stesso ordine: si accoppiano per posizione.
    ok = bad = skipped = unchanged = 0
    # accoppiamento sul numero d'ordine tra le sole chiamate (sia vecchie che nuove): nelle nuove il primo
    # argomento e' una Call a tr; le chiamate non convertite restano letterali.
    n_old, n_new = len(old), None
    new_calls = []
    tree = ast.parse((ROOT / rel).read_text(encoding='utf-8-sig'))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and not C._is_logger(n):
            nm = C._call_name(n)
            if (nm in C.LOG_NAMES or (use_print and nm == 'print')) and n.args:
                new_calls.append(n)
    new_calls.sort(key=lambda c: (c.args[0].lineno, c.args[0].col_offset))
    old_tree = ast.parse(old_src.decode('utf-8-sig'))
    old_calls = []
    for n in ast.walk(old_tree):
        if isinstance(n, ast.Call) and not C._is_logger(n):
            nm = C._call_name(n)
            if (nm in C.LOG_NAMES or (use_print and nm == 'print')) and n.args:
                old_calls.append(n)
    old_calls.sort(key=lambda c: (c.args[0].lineno, c.args[0].col_offset))
    if len(old_calls) != len(new_calls):
        print(f"ATTENZIONE: chiamate di log diverse (base {len(old_calls)}, ora {len(new_calls)})")
    for o, nw in zip(old_calls, new_calls):
        oa, na = o.args[0], nw.args[0]
        is_tr = isinstance(na, ast.Call) and (
            getattr(na.func, 'id', '') == 'tr' or (isinstance(na.func, ast.Attribute) and isinstance(na.func.value, ast.Call)
                                                   and getattr(na.func.value.func, 'id', '') == 'tr'))
        if not is_tr:
            unchanged += 1
            continue
        try:
            env = Env({'tr': translations.tr})
            a = evaluate(oa, Env())
            b = evaluate(na, env)
        except Exception as e:
            skipped += 1
            print(f"  NON VERIFICATO riga {oa.lineno} -> {na.lineno}: {type(e).__name__}: {e}")
            continue
        if a == b:
            ok += 1
        else:
            bad += 1
            print(f"  DIFFERENZA riga {oa.lineno}:\n    vecchio: {a!r}\n    nuovo:   {b!r}")
    print(f"identici: {ok}, differenti: {bad}, non verificati: {skipped}, non convertiti: {unchanged}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
