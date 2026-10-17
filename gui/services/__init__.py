# -*- coding: utf-8 -*-
"""
Servizi di logica della finestra principale (separati dalla vista).

REGOLA: nessun modulo di questo pacchetto importa PyQt6.QtWidgets. Sono ammessi
PyQt6.QtCore (QObject, segnali) e QPixmap, cosi' i servizi si provano senza
costruire widget.
"""
