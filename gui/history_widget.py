# -*- coding: utf-8 -*-
"""
HistoryWidget — Fase 4A Tronco 2

QTableWidget con ricerca, stat tile, persistenza JSON e bottoni azione per
aprire .srt / cartella video direttamente dalla cronologia.
"""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from gui.theme import set_flat
from utils.translations import tr


class HistoryWidget(QWidget):
    HISTORY_FILE = Path.home() / '.transcriberpro' / 'history.json'
    _COLS = ['Nome file', 'Data', 'Lingua', 'Durata', 'Dimensione', 'Azioni']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[dict] = []
        self._build_ui()
        self.load()

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
        self._entries.append(entry)
        self._save()
        self._add_row(entry)
        self._update_stats()

    def load(self):
        """Carica history.json al boot."""
        try:
            if self.HISTORY_FILE.exists():
                with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self._entries = json.load(f)
        except Exception:
            self._entries = []

        self._table.setRowCount(0)
        for entry in self._entries:
            self._add_row(entry)
        self._update_stats()

    def total_count(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _save(self):
        try:
            self.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _add_row(self, entry: dict):
        # Blocca temporaneamente il sort per evitare re-index durante insert
        self._table.setSortingEnabled(False)
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Colonna 0: Nome file
        self._table.setItem(row, 0, QTableWidgetItem(entry.get('name', '')))

        # Colonna 1: Data
        date_iso = entry.get('date_iso', '')
        self._table.setItem(row, 1, QTableWidgetItem(date_iso[:16].replace('T', ' ')))

        # Colonna 2: Lingua  src→dst
        src = entry.get('src_lang', 'auto')
        dst = entry.get('dst_lang', '')
        self._table.setItem(row, 2, QTableWidgetItem(f"{src}→{dst}" if dst else src))

        # Colonna 3: Durata elaborazione
        secs = int(entry.get('duration_seconds', 0))
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        self._table.setItem(
            row, 3,
            QTableWidgetItem(f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s")
        )

        # Colonna 4: Dimensione file sorgente
        self._table.setItem(row, 4, QTableWidgetItem(
            self._fmt_bytes(entry.get('size_bytes', 0))
        ))

        # Colonna 5: Bottoni azione
        self._table.setCellWidget(row, 5, self._make_actions(entry))
        self._table.setRowHeight(row, 38)

        self._table.setSortingEnabled(True)

    def _make_actions(self, entry: dict) -> QWidget:
        container = set_flat(QWidget())
        lay = QHBoxLayout(container)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(5)

        srt = entry.get('srt_path', '')
        folder = str(Path(entry['video_path']).parent) if entry.get('video_path') else ''

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
        for unit in ('B', 'KB', 'MB', 'GB'):
            if n < 1024:
                return f'{n:.0f} {unit}'
            n /= 1024
        return f'{n:.1f} TB'

    def _update_stats(self):
        total = len(self._entries)
        total_bytes = sum(e.get('size_bytes', 0) for e in self._entries)
        total_secs = int(sum(e.get('duration_seconds', 0) for e in self._entries))

        self._tile_total._value_lbl.setText(str(total))  # type: ignore[attr-defined]

        tb = float(total_bytes)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if tb < 1024:
                break
            tb /= 1024
        self._tile_size._value_lbl.setText(f'{tb:.1f} {unit}')  # type: ignore[attr-defined]

        m, s = divmod(total_secs, 60)
        h, m = divmod(m, 60)
        self._tile_time._value_lbl.setText(f'{h}h {m:02d}m')  # type: ignore[attr-defined]

    def _apply_search(self, text: str):
        text = text.strip().lower()
        for row in range(self._table.rowCount()):
            name  = (self._table.item(row, 0) or QTableWidgetItem()).text().lower()
            lang  = (self._table.item(row, 2) or QTableWidgetItem()).text().lower()
            match = not text or text in name or text in lang
            self._table.setRowHidden(row, not match)
