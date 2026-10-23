# -*- coding: utf-8 -*-
"""Aiuto per la fase B (traduzione dei log della pipeline): elenca i punti di emissione dei log e li converte in
tr('chiave') SENZA cambiare il testo italiano.

  list  <file.py> [--print]            elenca (id, modello IT con {segnaposto}) i letterali passati a _log/_emit/log/...
  apply <file.py> <en.py> [--prefix p] riscrive i punti elencati in <en.py> (dict {id: "modello EN"}) e aggiunge le
                                       chiavi a utils/translations.py (EN e IT). Il valore IT e' il testo originale.
  extra: --also id,id   (list) include anche letterali fuori dalle chiamate di log (es. `msg = f"..."`)

L'id e' "riga:colonna" del letterale nel file CORRENTE. Le righe CRLF/LF sono conservate (si lavora sui byte).
Solo scrittura sul file indicato e su utils/translations.py.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSL = ROOT / 'utils' / 'translations.py'
LOG_NAMES = {'_log', '_emit', 'log', 'log_callback', '_log_callback', 'emit_log', '_progress_log'}


def _call_name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')


def _is_logger(call):
    f = call.func
    if isinstance(f, ast.Attribute):
        v = f.value
        base = v.id if isinstance(v, ast.Name) else (v.attr if isinstance(v, ast.Attribute) else '')
        return base in ('logger', 'logging', '_logger', 'log_')
    return False


class Site:
    pass


def _name_for(expr, used, src_of):
    if isinstance(expr, ast.Name):
        base = expr.id
    elif isinstance(expr, ast.Attribute):
        base = expr.attr
    elif isinstance(expr, ast.Call):
        f = expr.func
        base = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', 'v')
    elif isinstance(expr, ast.Subscript):
        b = expr.value
        base = (b.attr if isinstance(b, ast.Attribute) else getattr(b, 'id', 'v')) + '_item'
    else:
        base = 'v'
    base = re.sub(r'\W', '_', base).strip('_').lstrip('_') or 'v'
    if base[0].isdigit():
        base = 'v' + base
    return base


def build_site(node, src_bytes, line_off):
    """Modello IT di un letterale (Constant o JoinedStr) e le espressioni dei segnaposto. None se non gestibile."""
    s = Site()
    s.node = node
    s.start = line_off[node.lineno - 1] + node.col_offset
    s.end = line_off[node.end_lineno - 1] + node.end_col_offset
    s.id = f"{node.lineno}:{node.col_offset}"
    s.exprs = {}       # nome -> codice sorgente dell'espressione
    s.manual = None
    if isinstance(node, ast.Constant):
        s.it = node.value.replace('{', '{{').replace('}', '}}')
        s.braces = ('{' in node.value or '}' in node.value)
        return s
    s.braces = False
    parts = []
    by_src = {}
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(v.value.replace('{', '{{').replace('}', '}}'))
            continue
        fv = v
        code = src_bytes[line_off[fv.value.lineno - 1] + fv.value.col_offset:
                         line_off[fv.value.end_lineno - 1] + fv.value.end_col_offset].decode('utf-8')
        if fv.format_spec is not None and any(isinstance(x, ast.FormattedValue) for x in fv.format_spec.values):
            s.manual = 'specifica di formato annidata'
            return s
        if code in by_src:
            name = by_src[code]
        else:
            name = _name_for(fv.value, s.exprs, code)
            base, n = name, 2
            while name in s.exprs:
                name = f"{base}_{n}"
                n += 1
            s.exprs[name] = code
            by_src[code] = name
        conv = {-1: '', 115: '!s', 114: '!r', 97: '!a'}[fv.conversion]
        spec = ''
        if fv.format_spec is not None:
            spec = ':' + ''.join(x.value for x in fv.format_spec.values)
        parts.append('{' + name + conv + spec + '}')
    s.it = ''.join(parts)
    return s


def collect(path, use_print=False, also=()):
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8-sig')
    tree = ast.parse(text)
    src_bytes = text.encode('utf-8')
    line_off, pos = [], 0
    for ln in src_bytes.split(b'\n'):
        line_off.append(pos)
        pos += len(ln) + 1
    sites = []
    seen = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and not _is_logger(n):
            name = _call_name(n)
            if name in LOG_NAMES or (use_print and name == 'print'):
                for a in n.args[:1]:
                    if isinstance(a, (ast.Constant, ast.JoinedStr)) and (not isinstance(a, ast.Constant) or isinstance(a.value, str)):
                        s = build_site(a, src_bytes, line_off)
                        s.call = name
                        if s.id not in seen:
                            seen.add(s.id)
                            sites.append(s)
    if also:
        for n in ast.walk(tree):
            if isinstance(n, (ast.Constant, ast.JoinedStr)) and hasattr(n, 'lineno'):
                i = f"{n.lineno}:{n.col_offset}"
                if i in also and i not in seen and (isinstance(n, ast.JoinedStr) or isinstance(n.value, str)):
                    s = build_site(n, src_bytes, line_off)
                    s.call = 'extra'
                    seen.add(i)
                    sites.append(s)
    sites.sort(key=lambda s: s.start)
    return text, src_bytes, sites


def slug(en, prefix):
    words = re.findall(r'[A-Za-z0-9]+', re.sub(r'\{[^}]*\}', ' ', en).lower())
    return prefix + '_' + '_'.join(words[:5] or ['msg'])


def table_block(items):
    out = []
    for k, v in items:
        out.append(f"            {k!r}: {v!r},")
    return '\n'.join(out) + '\n'


def cmd_list(path, use_print, also):
    text, _, sites = collect(path, use_print, also)
    for s in sites:
        flag = '' if not s.manual else f'  [MANUALE: {s.manual}]'
        ph = ','.join(f"{k}={v}" for k, v in s.exprs.items())
        print(f"{s.id}\t{s.call}\t{s.it!r}\t{ph}{flag}")


def cmd_apply(path, en_file, prefix, use_print):
    en_map = eval(Path(en_file).read_text(encoding='utf-8'), {})
    also = set(i for i in en_map)
    text, src_bytes, sites = collect(path, use_print, also)
    tr_src = TRANSL.read_text(encoding='utf-8')
    ns = {}
    exec(compile(ast.parse(tr_src), 'tr', 'exec'), {'__name__': 'x', 'os': __import__('os')}, ns)
    existing_it = ns['Translations'].TEXTS['it']
    existing_en = ns['Translations'].TEXTS['en']
    it_by_text = {}
    for k, v in existing_it.items():
        it_by_text.setdefault(v, k)
    new_it, new_en, manifest = [], [], {}
    repl = []
    byid = {s.id: s for s in sites}
    missing = [i for i in en_map if i not in byid]
    if missing:
        sys.exit(f"id non trovati: {missing}")
    for i, en in en_map.items():
        s = byid[i]
        if s.manual:
            sys.exit(f"{i}: {s.manual}")
        if isinstance(en, tuple):          # (testo EN, {nome automatico: nome scelto})
            en, ren = en
            for old_n, new_n in ren.items():
                s.it = re.sub(r'\{' + old_n + r'(?=[}!:])', '{' + new_n, s.it)
                s.exprs = {(new_n if k == old_n else k): v for k, v in s.exprs.items()}
        names_it = sorted(re.findall(r'\{(\w+)[^}]*\}', re.sub(r'\{\{|\}\}', '', s.it)))
        names_en = sorted(re.findall(r'\{(\w+)[^}]*\}', re.sub(r'\{\{|\}\}', '', en)))
        if names_it != names_en:
            sys.exit(f"{i}: segnaposto diversi IT={names_it} EN={names_en}")
        # stessa riga IT gia' presente (con lo stesso EN) -> stessa chiave
        key = None
        if s.it in it_by_text and existing_en.get(it_by_text[s.it]) == en:
            key = it_by_text[s.it]
        else:
            key = slug(en, prefix)
            base, n = key, 2
            while key in existing_it or key in dict(new_it):
                if existing_it.get(key) == s.it and existing_en.get(key) == en or dict(new_it).get(key) == s.it and dict(new_en).get(key) == en:
                    break
                key = f"{base}_{n}"
                n += 1
            if key not in existing_it and key not in dict(new_it):
                new_it.append((key, s.it))
                new_en.append((key, en))
        manifest[key] = s.it
        call = f"tr({key!r})"
        if s.exprs or s.braces:
            call += '.format(' + ', '.join(f"{k}={v}" for k, v in s.exprs.items()) + ')'
        repl.append((s.start, s.end, call))
    out = bytearray(src_bytes)
    for a, b, call in sorted(repl, reverse=True):
        out[a:b] = call.encode('utf-8')
    # import tr
    new_text = bytes(out).decode('utf-8')
    if not re.search(r'^\s*from utils\.translations import[^\n]*\btr\b', new_text, re.M):
        lines = new_text.split('\n')
        idx = 0
        for st in ast.parse(new_text).body:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                idx = st.end_lineno
            elif isinstance(st, (ast.FunctionDef, ast.ClassDef)):
                break
        lines.insert(idx, 'from utils.translations import tr')
        new_text = '\n'.join(lines)
    # BOM e fine riga originali
    raw = Path(path).read_bytes()
    nl_crlf = b'\r\n' in raw
    if nl_crlf:
        new_text = new_text.replace('\r\n', '\n').replace('\n', '\r\n')
    prefix_bytes = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    Path(path).write_bytes(prefix_bytes + new_text.encode('utf-8'))
    # translations.py
    en_blk = table_block(new_en)
    it_blk = table_block(new_it)
    head = f"\n            # ── log pipeline: {Path(path).name} ──\n"
    j = tr_src.index("        'it': {")
    j = tr_src.rfind("        },", 0, j)
    tr_src = tr_src[:j] + head + en_blk + tr_src[j:]
    k = tr_src.rindex("        },\n    }")
    tr_src = tr_src[:k] + head + it_blk + tr_src[k:]
    TRANSL.write_text(tr_src, encoding='utf-8', newline='')
    # manifest dell'identita' dell'italiano
    mf = ROOT / 'linux_tests' / 'i18n_it_originals.json'
    cur = json.loads(mf.read_text(encoding='utf-8')) if mf.exists() else {}
    cur.update(manifest)
    mf.write_text(json.dumps(cur, ensure_ascii=False, indent=0, sort_keys=True) + '\n', encoding='utf-8')
    print(f"{len(repl)} punti riscritti, {len(new_it)} chiavi nuove")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = sys.argv[1:]
    use_print = '--print' in a
    a = [x for x in a if x != '--print']
    also = set()
    if '--also' in a:
        i = a.index('--also')
        also = set(a[i + 1].split(','))
        del a[i:i + 2]
    if a[0] == 'list':
        cmd_list(a[1], use_print, also)
    elif a[0] == 'apply':
        prefix = 'pl'
        if '--prefix' in a:
            i = a.index('--prefix')
            prefix = a[i + 1]
        cmd_apply(a[1], a[2], prefix, use_print)
