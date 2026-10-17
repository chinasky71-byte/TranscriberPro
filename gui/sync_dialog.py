# -*- coding: utf-8 -*-
"""
SyncDialog — Dialog per sincronizzazione sottotitoli
File: gui/sync_dialog.py
"""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QTextEdit, QFileDialog,
    QGroupBox, QFormLayout, QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QComboBox,
    QCheckBox, QHeaderView, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor

from gui.progress_log import append_log_line
from gui.styles import load_qss
from gui.sync_worker import SyncWorker
from gui.sync_batch_worker import SyncBatchWorker
from core import sync_pairing as SP
from utils.translations import tr

logger = logging.getLogger(__name__)


class SyncDialog(QDialog):
    """Modal dialog per la sincronizzazione SRT."""

    def __init__(self, video_path: str = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('sync_dialog_title'))
        self.setModal(True)
        self.resize(860, 700)

        self._worker: SyncWorker | None = None
        self._batch_worker: SyncBatchWorker | None = None
        self._pairs: list = []
        self._srt_files: list = []
        self._batch_done = 0
        self._batch_total = 0
        self._loading_table = False
        self._last_output_path: str | None = None
        self._shutting_down: bool = False   # guardia di rientranza, vedi _shutdown()

        self._init_ui()
        self._apply_styles()

        if video_path:
            self.video_input.setText(video_path)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # ── File input ────────────────────────────────────────────────────────
        files_group = QGroupBox(tr('sync_files_group'))
        form = QFormLayout()
        form.setSpacing(8)

        video_row = QHBoxLayout()
        self.video_input = QLineEdit()
        self.video_input.setPlaceholderText(tr('sync_video_ph'))
        self.video_input.setReadOnly(True)
        video_browse = QPushButton(tr('browse'))
        video_browse.setFixedWidth(100)
        video_browse.clicked.connect(self._browse_video)
        video_row.addWidget(self.video_input)
        video_row.addWidget(video_browse)
        form.addRow(tr('sync_video_label'), video_row)

        srt_row = QHBoxLayout()
        self.srt_input = QLineEdit()
        self.srt_input.setPlaceholderText(tr('sync_srt_ph'))
        self.srt_input.setReadOnly(True)
        srt_browse = QPushButton(tr('browse'))
        srt_browse.setFixedWidth(100)
        srt_browse.clicked.connect(self._browse_srt)
        srt_row.addWidget(self.srt_input)
        srt_row.addWidget(srt_browse)
        form.addRow(tr('sync_srt_label'), srt_row)

        files_group.setLayout(form)
        self.tabs = QTabWidget()
        self.tabs.addTab(files_group, tr('sync_tab_single'))
        self.tabs.addTab(self._build_batch_tab(), tr('sync_tab_batch'))
        root.addWidget(self.tabs)

        # ── Progress ──────────────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        root.addWidget(self.progress_bar)

        # ── Log ───────────────────────────────────────────────────────────────
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 9))
        self.log_edit.setMinimumHeight(200)
        root.addWidget(self.log_edit)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.start_btn = QPushButton(tr('sync_start'))
        self.start_btn.setFixedWidth(200)
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton(tr('cancel'))
        self.cancel_btn.setFixedWidth(120)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)

        root.addLayout(btn_row)

    def _apply_styles(self):
        self.setStyleSheet(load_qss('sync_dialog'))

    # ── Browse handlers ───────────────────────────────────────────────────────

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr('sync_browse_video'),
            filter="Video (*.mp4 *.mkv *.avi *.mov *.wmv *.m4v);;All files (*)"
        )
        if path:
            self.video_input.setText(path)

    def _browse_srt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr('sync_browse_srt'),
            filter="SRT files (*.srt);;All files (*)"
        )
        if path:
            self.srt_input.setText(path)

    # ── Start / Cancel ────────────────────────────────────────────────────────

    # ── Coda multi-file ───────────────────────────────────────────────

    def _build_batch_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        self.bv_dir = QLineEdit()
        self.bv_dir.setReadOnly(True)
        b1 = QPushButton(tr('browse'))
        b1.setFixedWidth(100)
        b1.clicked.connect(lambda: self._browse_batch_dir(self.bv_dir))
        r1 = QHBoxLayout()
        r1.addWidget(self.bv_dir)
        r1.addWidget(b1)
        form.addRow(tr('sync_batch_video_dir'), r1)
        self.bs_dir = QLineEdit()
        self.bs_dir.setReadOnly(True)
        b2 = QPushButton(tr('browse'))
        b2.setFixedWidth(100)
        b2.clicked.connect(lambda: self._browse_batch_dir(self.bs_dir))
        r2 = QHBoxLayout()
        r2.addWidget(self.bs_dir)
        r2.addWidget(b2)
        form.addRow(tr('sync_batch_srt_dir'), r2)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.b_recursive = QCheckBox(tr('sync_batch_subdirs'))
        row.addWidget(self.b_recursive)
        row.addStretch()
        self.b_pair_btn = QPushButton(tr('sync_batch_pair'))
        self.b_pair_btn.clicked.connect(self._batch_pair)
        row.addWidget(self.b_pair_btn)
        lay.addLayout(row)
        self.b_table = QTableWidget(0, 5)
        self.b_table.setHorizontalHeaderLabels(['', tr('sync_batch_col_video'), tr('sync_batch_col_srt'),
                                                tr('sync_batch_col_out'), tr('sync_batch_col_state')])
        hh = self.b_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.b_table.setMinimumHeight(180)
        self.b_table.itemChanged.connect(self._on_table_item_changed)
        lay.addWidget(self.b_table)
        self.b_summary = QLabel('')
        lay.addWidget(self.b_summary)
        return w

    def _browse_batch_dir(self, edit: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, tr('sync_batch_browse_dir'), edit.text() or '')
        if d:
            edit.setText(d)

    def _batch_pair(self):
        vd, sd = self.bv_dir.text().strip(), self.bs_dir.text().strip()
        if not vd or not sd:
            QMessageBox.warning(self, tr('warning'), tr('sync_batch_nothing'))
            return
        rec = self.b_recursive.isChecked()
        videos = SP.list_files(vd, SP.VIDEO_EXT, rec)
        self._srt_files = SP.list_files(sd, ('.srt',), rec)
        self._pairs, left = SP.pair_files(videos, self._srt_files)
        self._left_srts = left
        self._populate_table()

    def _srt_label(self, p) -> str:
        base = self.bs_dir.text().strip()
        try:
            return str(Path(p).relative_to(base))
        except Exception:
            return Path(p).name

    def _populate_table(self):
        self._loading_table = True
        try:
            self.b_table.setRowCount(len(self._pairs))
            for r, p in enumerate(self._pairs):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk.setCheckState(Qt.CheckState.Checked if p.include else Qt.CheckState.Unchecked)
                self.b_table.setItem(r, 0, chk)
                it = QTableWidgetItem(Path(p.video).name)
                it.setToolTip(str(p.video))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.b_table.setItem(r, 1, it)
                combo = QComboBox()
                combo.addItem(tr('sync_batch_none'), None)
                sel = 0
                for i, s in enumerate(self._srt_files, start=1):
                    combo.addItem(self._srt_label(s), str(s))
                    if p.srt is not None and Path(s) == Path(p.srt):
                        sel = i
                combo.setCurrentIndex(sel)
                combo.currentIndexChanged.connect(lambda _i, row=r: self._on_srt_changed(row))
                self.b_table.setCellWidget(r, 2, combo)
                for c in (3, 4):
                    x = QTableWidgetItem('')
                    x.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.b_table.setItem(r, c, x)
        finally:
            self._loading_table = False
        self._refresh_rows()

    def _on_srt_changed(self, row: int):
        if self._loading_table or row >= len(self._pairs):
            return
        combo = self.b_table.cellWidget(row, 2)
        val = combo.currentData()
        p = self._pairs[row]
        p.srt = Path(val) if val else None
        p.score = 1.0 if val else 0.0          # scelta manuale dell'utente
        p.note = ''
        p.include = bool(val)
        p.refresh_output()
        self._refresh_rows()

    def _on_table_item_changed(self, item):
        if self._loading_table or item.column() != 0 or item.row() >= len(self._pairs):
            return
        self._pairs[item.row()].include = item.checkState() == Qt.CheckState.Checked
        self._refresh_rows()

    def _refresh_rows(self):
        self._loading_table = True
        try:
            SP.mark_duplicates(self._pairs)
            ready = check = nosrt = 0
            for r, p in enumerate(self._pairs):
                out = self.b_table.item(r, 3)
                st = self.b_table.item(r, 4)
                chk = self.b_table.item(r, 0)
                want = Qt.CheckState.Checked if (p.include and p.srt is not None) else Qt.CheckState.Unchecked
                if chk.checkState() != want:
                    chk.setCheckState(want)
                out.setText(str(p.output) if p.output else '')
                out.setToolTip(out.text())
                if p.srt is None:
                    text, nosrt = tr('sync_batch_state_nosrt'), nosrt + 1
                elif p.duplicate:
                    text = tr('sync_batch_state_dup')
                elif p.note:
                    text, check = tr('sync_batch_state_check'), check + (1 if p.include else 0)
                else:
                    text = tr('sync_batch_state_ready')
                if p.include and p.srt is not None and not p.duplicate:
                    ready += 1
                st.setText(text)
            self.b_summary.setText(tr('sync_batch_summary').format(
                ready=ready, check=check, nosrt=nosrt, left=len(getattr(self, '_left_srts', []))))
        finally:
            self._loading_table = False

    def _set_row_state(self, row: int, text: str):
        it = self.b_table.item(row, 4)
        if it is not None:
            self._loading_table = True
            it.setText(text)
            self._loading_table = False

    def _set_running_ui(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.tabs.setEnabled(not running)

    def _start_batch(self):
        SP.mark_duplicates(self._pairs)
        run = SP.runnable(self._pairs)
        if not run:
            QMessageBox.warning(self, tr('warning'), tr('sync_batch_nothing'))
            return
        if QMessageBox.question(self, tr('sync_batch_start'), tr('sync_batch_confirm').format(n=len(run))) \
                != QMessageBox.StandardButton.Yes:
            return
        self._shutting_down = False
        self.log_edit.clear()
        self.progress_bar.setValue(0)
        self._batch_done, self._batch_total = 0, len(run)
        self._batch_rows = {i: self._pairs.index(p) for i, p in enumerate(run)}
        self._batch_pcts = 0
        for r in range(len(self._pairs)):
            self._set_row_state(r, '' if self._pairs[r] not in run else tr('sync_batch_state_ready'))
        self._batch_worker = SyncBatchWorker(run, parent=self)
        w = self._batch_worker
        w.log_message.connect(self._append_log)
        w.pair_started.connect(lambda i, _v: self._set_row_state(self._batch_rows[i], tr('sync_batch_state_running')))
        w.pair_progress.connect(self._on_batch_pair_progress)
        w.pair_finished.connect(self._on_batch_pair_finished)
        w.all_done.connect(self._on_batch_all_done)
        self._set_running_ui(True)
        self._mark_worker_active(True)
        w.start()

    def _on_batch_pair_progress(self, i: int, pct: int):
        self._set_row_state(self._batch_rows[i], f"{pct}%")
        if self._batch_total:
            self.progress_bar.setValue(int((self._batch_done + pct / 100.0) / self._batch_total * 100))

    def _on_batch_pair_finished(self, i: int, ok: bool, info: str):
        self._batch_done += 1
        self._set_row_state(self._batch_rows[i], tr('sync_batch_state_ok') if ok else tr('sync_batch_state_failed'))
        if self._batch_total:
            self.progress_bar.setValue(int(self._batch_done / self._batch_total * 100))

    def _on_batch_all_done(self, ok: int, fail: int, skipped: int):
        for i, r in self._batch_rows.items():
            it = self.b_table.item(r, 4)
            if it is not None and it.text() in ('', tr('sync_batch_state_ready')):
                self._set_row_state(r, tr('sync_batch_state_skipped'))
        self._set_running_ui(False)
        self._mark_worker_active(False)
        msg = tr('sync_batch_done').format(ok=ok, fail=fail, skipped=skipped)
        self._append_log('\n' + msg)
        QMessageBox.information(self, tr('sync_done_title'), msg)

    def _start(self):
        if self.tabs.currentIndex() == 1:
            self._start_batch()
            return
        video = self.video_input.text().strip()
        srt   = self.srt_input.text().strip()

        if not video:
            QMessageBox.warning(self, tr('warning'), tr('sync_missing_video'))
            return
        if not srt:
            QMessageBox.warning(self, tr('warning'), tr('sync_missing_srt'))
            return

        self._shutting_down = False
        self.log_edit.clear()
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self._worker = SyncWorker(video_path=video, external_srt_path=srt, parent=self)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.log_message.connect(self._append_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.output_ready.connect(self._on_output_ready)
        self._worker.file_completed.connect(self._on_completed)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._mark_worker_active(True)

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._append_log(tr('sync_cancelling'))
            self._worker.cancel()
        if self._batch_worker and self._batch_worker.isRunning():
            self._append_log(tr('sync_cancelling'))
            self._batch_worker.cancel()
        self.cancel_btn.setEnabled(False)

    def _mark_worker_active(self, active: bool):
        """Segnala a main_window che la sincronizzazione sta usando la GPU,
        così la coda principale e lo strumento glossario (stessa GPU) si
        rifiutano di partire in parallelo invece di entrare in contesa VRAM
        silenziosa — stesso pattern di GlossaryDialog._mark_worker_inactive."""
        parent = self.parent()
        if parent is not None:
            parent._sync_worker_active = active

    # ── Worker callbacks ──────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        # Le barre di avanzamento (Demucs, Traduzione...) si riscrivono sul posto come nel log principale.
        append_log_line(self.log_edit, msg)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._mark_worker_active(False)

    def _on_output_ready(self, output_path: str):
        self._last_output_path = output_path

    def _on_completed(self, video_path: str):
        self.progress_bar.setValue(100)
        # Percorso REALE ricevuto dal worker (deriva dall'SRT esterno, non
        # dal video — se sono in cartelle diverse, ricalcolarlo qui dal solo
        # video_path produceva un percorso che non esisteva).
        output = self._last_output_path or (str(Path(video_path).with_suffix('')) + '.synced.it.srt')
        QMessageBox.information(
            self, tr('sync_done_title'),
            tr('sync_done_msg').format(output=output)
        )

    def _on_error(self, msg: str):
        QMessageBox.critical(self, tr('error'), msg)

    # ── Chiusura sicura ───────────────────────────────────────────────────────

    def _cancel_and_wait(self) -> bool:
        """Annulla e attende il worker. Ritorna True solo se è DAVVERO
        terminato entro il timeout — usato per decidere se è sicuro
        azzerare _sync_worker_active. Una singola inferenza Qwen misurata
        fino a ~55s: 3s non bastano quasi mai durante S3, e mai durante S2
        (la traduzione NLLB dell'intero anchor non controlla _cancelled).
        Azzerare il flag comunque farebbe credere alla coda principale/al
        glossario che la GPU sia libera mentre Qwen-14B è ancora residente
        in VRAM — la contesa silenziosa che il flag esiste per evitare."""
        if self._worker and self._worker.isRunning():
            self._cancel()
            return self._worker.wait(30000)
        if self._batch_worker and self._batch_worker.isRunning():
            self._cancel()
            return self._batch_worker.wait(30000)
        return True

    def _shutdown(self) -> None:
        """Punto unico di chiusura: annulla, attende, aggiorna il flag.
        Rientranza guardata perché QDialog::closeEvent chiama a sua volta
        reject(): senza la guardia, chiudere dal pulsante X del titolo
        eseguiva DUE attese da 30s in fila (60s di GUI bloccata) invece di
        una — reject() è sia la strada dell'Esc sia il seguito del
        closeEvent."""
        if self._shutting_down:
            return
        # La guardia NON si riabbassa qui: closeEvent chiama _shutdown() e
        # POI super().closeEvent(), che chiama reject(), che richiama
        # _shutdown() — riabbassarla in un finally la renderebbe inutile.
        # Si riabbassa quando il dialog torna visibile (showEvent) o quando
        # parte una nuova sincronizzazione (_start).
        self._shutting_down = True
        if self._cancel_and_wait():
            self._mark_worker_active(False)
        else:
            self._append_log(
                "⚠️ Il worker non si è fermato in tempo: resta segnalato come "
                "attivo finché non termina davvero (evita contesa GPU con "
                "coda principale/glossario)."
            )

    def showEvent(self, event):
        self._shutting_down = False
        super().showEvent(event)

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)

    def reject(self):
        """Esc chiama QDialog.reject(), che NON passa da closeEvent: senza
        questo override, Esc durante una sincronizzazione lascia il worker
        (e Qwen-14B in VRAM) in esecuzione senza mai chiamare cancel()."""
        self._shutdown()
        super().reject()
