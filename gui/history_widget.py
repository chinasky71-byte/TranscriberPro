# -*- coding: utf-8 -*-
"""
HistoryWidget — Fase 4A Tronco 2

QTableWidget con ricerca, stat tile, persistenza JSON e bottoni azione per
aprire .srt / cartella video direttamente dalla cronologia.

La LOGICA (caricamento/salvataggio di history.json, statistiche, testi delle celle, ricerca) sta in
core/services/history_service.py (senza Qt, condivisa con la web UI): qui resta solo la vista.
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from core.services.history_service import (HistoryRow, HistoryService, actions_of, format_bytes, matches,
                                           row_of)
from gui.theme import set_flat
from utils.translations import tr


class HistoryWidget(QWidget):
    HISTORY_FILE = Path.home() / '.transcriberpro' / 'history.json'
    _COLS = ['Nome file', 'Data', 'Lingua', 'Durata', 'Dimensione', 'Azioni']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._svc = HistoryService(self.HISTORY_FILE)
        self._build_ui()
        self.load()

    @property
    def _entries(self) -> list:
        """Compatibilita': la lista delle voci e' quella del servizio."""
        return self._svc.entries

    # ------------------------------------------------------------------
    # Costruzione UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 15)
        layout.setSpacing(10)

        layout.addWidget(self._create_stat_bar())

        self._search = QLineEdit()
        self._search.setObjectName("historySearch")
        self._search.setPlaceholderText(tr('hist_search_ph'))
        self._search.textChanged.connect(self._apply_search)
        layout.addWidget(self._search)

        self._table = QTableWidget(0, len(self._COLS))
        self._table.setObjectName("historyTable")
        self._table.setHorizontalHeaderLabels(self._COLS)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 200)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._table)

    def _create_stat_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(10)

        self._tile_total = self._make_tile("File elaborati", "0")
        self._tile_size  = self._make_tile("Spazio totale", "0 GB")
        self._tile_time  = self._make_tile("Tempo totale", "0h 00m")

        lay.addWidget(self._tile_total)
        lay.addWidget(self._tile_size)
        lay.addWidget(self._tile_time)
        lay.addStretch()
        return bar

    def _make_tile(self, label: str, value: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("historyStatTile")
        lay = QVBoxLayout(tile)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)

        val_lbl = QLabel(value)
        val_lbl.setObjectName("historyStatValue")
        lbl_lbl = QLabel(label)
        lbl_lbl.setObjectName("historyStatLabel")

        lay.addWidget(val_lbl)
        lay.addWidget(lbl_lbl)

        tile._value_lbl = val_lbl  # type: ignore[attr-defined]
        return tile

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def append_entry(self, entry: dict):
        """Aggiunge voce, persiste e aggiorna tabella + stat."""
        self._svc.path = Path(self.HISTORY_FILE)
        self._svc.append(entry)
        self._add_row(entry)
        self._update_stats()

    def load(self):
        """Carica history.json al boot."""
        self._svc.path = Path(self.HISTORY_FILE)
        self._svc.load()

        self._table.setRowCount(0)
        for entry in self._entries:
            self._add_row(entry)
        self._update_stats()

    def total_count(self) -> int:
        return self._svc.total_count()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _save(self):
        self._svc.path = Path(self.HISTORY_FILE)
        self._svc.save()

    def _add_row(self, entry: dict):
        # Blocca temporaneamente il sort per evitare re-index durante insert
        self._table.setSortingEnabled(False)
        row = self._table.rowCount()
        self._table.insertRow(row)

        cells = row_of(entry).as_tuple()          # nome, data, lingua, durata, dimensione (testi: core/services/history_service.py)
        for col, text in enumerate(cells):
            self._table.setItem(row, col, QTableWidgetItem(text))

        # Colonna 5: Bottoni azione
        self._table.setCellWidget(row, 5, self._make_actions(entry))
        self._table.setRowHeight(row, 38)

        self._table.setSortingEnabled(True)

    def _make_actions(self, entry: dict) -> QWidget:
        container = set_flat(QWidget())
        lay = QHBoxLayout(container)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(5)

        srt, folder = actions_of(entry)

        btn_srt = QPushButton(tr('hist_open_srt'))
        btn_srt.setObjectName("historyActionBtn")
        btn_srt.setEnabled(bool(srt))
        btn_srt.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(srt)
        ))

        btn_dir = QPushButton(tr('hist_folder'))
        btn_dir.setObjectName("historyActionBtn")
        btn_dir.setEnabled(bool(folder))
        btn_dir.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(folder)
        ))

        lay.addWidget(btn_srt)
        lay.addWidget(btn_dir)
        lay.addStretch()
        return container

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        return format_bytes(n)

    def _update_stats(self):
        st = self._svc.stats()
        self._tile_total._value_lbl.setText(str(st.total))  # type: ignore[attr-defined]
        self._tile_size._value_lbl.setText(st.size_text)  # type: ignore[attr-defined]
        self._tile_time._value_lbl.setText(st.time_text)  # type: ignore[attr-defined]

    def _apply_search(self, text: str):
        for row in range(self._table.rowCount()):
            name = (self._table.item(row, 0) or QTableWidgetItem()).text()
            lang = (self._table.item(row, 2) or QTableWidgetItem()).text()
            self._table.setRowHidden(row, not matches(text, HistoryRow(name, '', lang, '', '')))
