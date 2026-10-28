# -*- coding: utf-8 -*-
"""Apertura di un file o di una cartella con il programma predefinito del sistema (azione del computer, non della pagina)."""
import os
import subprocess
import sys


def open_path(path: str) -> None:
    if os.name == 'nt':
        os.startfile(path)                                  # noqa: S606  (solo percorsi scelti dal server, vedi routes_history)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])
