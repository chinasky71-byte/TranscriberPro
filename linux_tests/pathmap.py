# -*- coding: utf-8 -*-
"""Percorsi dei test indipendenti dal sistema operativo.

I test scrivono i percorsi come su Windows (`P('V:\\Film\\X.mkv')`). Su Windows `P` restituisce la stringa IDENTICA; su Linux/macOS
la trasforma in `/mnt/v/Film/X.mkv`, cosi' `Path(...).name`, `.parent` e simili si comportano come su Windows.
La trasformazione e' una funzione pura con parametro `windows` (testata anche da Windows).
"""
import re
import sys

_DRIVE = re.compile(r'^([A-Za-z]):[\\/]*(.*)$')


def to_native(p: str, windows: bool) -> str:
    if windows:
        return p
    m = _DRIVE.match(p)
    if not m:
        return p.replace('\\', '/')
    return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace('\\', '/')


def P(p: str) -> str:
    return to_native(p, sys.platform == 'win32')
