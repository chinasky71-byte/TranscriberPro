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
    QGroupBox, QFormLayout, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor

from gui.sync_worker import SyncWorker
from utils.translations import tr

logger = logging.getLogger(__name__)


class SyncDialog(QDialog):
    """Modal dialog per la sincronizzazione SRT."""

    def __init__(self, video_path: str = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('sync_dialog_title'))
        self.setModal(True)
        self.resize(700, 560)

        self._worker: SyncWorker | None = None

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
        root.addWidget(files_group)

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
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid rgba(255,255,255,0.1);
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLabel {
                color: #cccccc;
            }
            QLineEdit {
                background-color: rgba(45,45,60,200);
                color: #ffffff;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                padding: 4px 8px;
            }
            QTextEdit {
                background-color: rgba(15,15,25,220);
                color: #d0d0d0;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 4px;
            }
            QProgressBar {
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 4px;
                background-color: rgba(30,30,50,200);
                color: #ffffff;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: rgba(0,120,212,200);
                border-radius: 3px;
            }
            QPushButton {
                background-color: rgba(0,120,212,180);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
            }
            QPushButton:hover  { background-color: rgba(0,120,212,230); }
            QPushButton:pressed { background-color: rgba(0,100,180,200); }
            QPushButton:disabled {
                background-color: rgba(60,60,60,150);
                color: rgba(255,255,255,100);
            }
        """)

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

    def _start(self):
        video = self.video_input.text().strip()
        srt   = self.srt_input.text().strip()

        if not video:
            QMessageBox.warning(self, tr('warning'), tr('sync_missing_video'))
            return
        if not srt:
            QMessageBox.warning(self, tr('warning'), tr('sync_missing_srt'))
            return

        self.log_edit.clear()
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self._worker = SyncWorker(video_path=video, external_srt_path=srt, parent=self)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.log_message.connect(self._append_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.file_completed.connect(self._on_completed)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._append_log(tr('sync_cancelling'))
            self._worker.cancel()
        self.cancel_btn.setEnabled(False)

    # ── Worker callbacks ──────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.log_edit.insertPlainText(msg if msg.endswith('\n') else msg + '\n')
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _on_completed(self, video_path: str):
        self.progress_bar.setValue(100)
        output = str(Path(video_path).with_suffix('')) + '.synced.it.srt'
        QMessageBox.information(
            self, tr('sync_done_title'),
            tr('sync_done_msg').format(output=output)
        )

    def _on_error(self, msg: str):
        QMessageBox.critical(self, tr('error'), msg)

    # ── Chiusura sicura ───────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._cancel()
            self._worker.wait(3000)
        super().closeEvent(event)
