# -*- coding: utf-8 -*-
"""
Dialog "Glossario per show" — Strumenti -> Glossario per show.
File: gui/glossary_dialog.py

Interfaccia per lanciare la costruzione/validazione semi-automatica del
glossario per-show (mt_eval/build_glossary_candidates.py, subprocess
isolato in venv_glossary/) e approvare a mano i candidati proposti, un
minuto di lavoro invece della riga di comando. NON in SettingsDialog:
questo e' uno strumento con un output (un report da rivedere), non una
preferenza persistente.
"""
import logging
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QScrollArea, QWidget, QCheckBox, QProgressBar, QTextEdit,
    QMessageBox, QFrame,
)

from gui.collapsible_card import CollapsibleCard
from gui.glossary_worker import GlossaryBuilderWorker, venv_glossary_available
from utils.translations import tr
from utils.config import get_config

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "show"


class _TermCard(CollapsibleCard):
    """Una card per candidato: checkbox approvazione + cluster/esempi."""

    def __init__(self, record: dict, parent=None):
        title = f"{record['term']}  →  {record.get('dominant') or '?'}"
        super().__init__(title, parent)
        self.record = record
        self.setSummary(self._summary_text(record))

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        approve_row = QHBoxLayout()
        self.approve_cb = QCheckBox(tr('glossary_approve_term'))
        self.approve_cb.setChecked(record.get('status') == 'auto')
        approve_row.addWidget(self.approve_cb)
        approve_row.addWidget(QLabel(tr('glossary_rendering_label')))
        self.rendering_edit = QLineEdit(record.get('dominant') or '')
        approve_row.addWidget(self.rendering_edit, 1)
        lay.addLayout(approve_row)

        info = QLabel(
            f"{tr('glossary_occurrences')}: {record.get('occurrences', 0)} · "
            f"{tr('glossary_align_channel')}: {record.get('align_verdict', 'n/a')} "
            f"({record.get('align_extracted', 0)} estratte) · "
            f"{tr('glossary_qwen_channel')}: {record.get('qwen_verdict', 'n/a')} "
            f"({record.get('qwen_extracted', 0)} estratte, "
            f"{record.get('qwen_coverage', 0):.0%} coverage) · {record.get('reason', '')}")
        info.setWordWrap(True)
        info.setObjectName("glossaryTermReason")
        lay.addWidget(info)

        for cluster in record.get('clusters', [])[:6]:
            c_label = QLabel(f"「{cluster['text']}」 × {cluster['n']}")
            c_label.setObjectName("glossaryClusterLabel")
            lay.addWidget(c_label)
            for ex in cluster.get('examples', [])[:2]:
                ex_label = QLabel(f"   EN: {ex.get('en', '')[:70]}\n   IT: {ex.get('it', '')[:70]}")
                ex_label.setWordWrap(True)
                ex_label.setObjectName("glossaryExampleLabel")
                lay.addWidget(ex_label)

        self.setBody(body)
        self.setExpanded(record.get('status') != 'auto')

    @staticmethod
    def _summary_text(record: dict) -> str:
        status = record.get('status', 'review')
        icon = {'auto': '✓', 'review': '?', 'reject': '✕'}.get(status, '?')
        return f"{icon} {status}"


class _TmdbResolveWorker(QThread):
    """search_tv() prova piu' varianti del titolo (timeout 10s ciascuna)
    piu' i fallback IMDb/OMDb — decine di secondi nel caso peggiore.
    Chiamarlo direttamente sul thread GUI congela la finestra (bug reale
    misurato in revisione, viola la policy no-freeze del progetto)."""
    resolved = pyqtSignal(object)  # dict risultato o None

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title

    def run(self):
        try:
            from utils.tmdb_client import get_tmdb_client
            result = get_tmdb_client().search_tv(self._title)
        except Exception as e:
            logger.warning(f"Ricerca TMDB fallita: {e}")
            result = None
        self.resolved.emit(result)


class GlossaryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('glossary_dialog_title'))
        self.resize(760, 700)

        self._worker: GlossaryBuilderWorker | None = None
        self._report: dict | None = None
        self._tmdb_id = None
        self._term_cards: list[_TermCard] = []

        self._build_ui()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """Chiudere il dialog (X, Esc, Alt+F4) mentre un run e' in corso
        NON deve lasciare il subprocess orfano: senza questo, il worker e
        il processo venv_glossary continuano a girare anche a dialog
        chiuso, e riaprendo lo strumento nascerebbe un secondo worker che
        scrive lo stesso args.json/report.json del primo (bug reale
        misurato in revisione)."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().reject()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)

        if not venv_glossary_available():
            warn = QLabel(tr('glossary_venv_missing'))
            warn.setWordWrap(True)
            warn.setObjectName("glossaryWarning")
            root.addWidget(warn)

        form = QHBoxLayout()
        form.addWidget(QLabel(tr('glossary_show_folder')))
        self.folder_edit = QLineEdit()
        form.addWidget(self.folder_edit, 1)
        browse_btn = QPushButton(tr('glossary_browse'))
        browse_btn.clicked.connect(self._on_browse)
        form.addWidget(browse_btn)
        root.addLayout(form)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr('glossary_show_name')))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self.name_edit, 1)
        resolve_btn = QPushButton(tr('glossary_resolve_tmdb'))
        resolve_btn.clicked.connect(self._on_resolve_tmdb)
        name_row.addWidget(resolve_btn)
        root.addLayout(name_row)

        self.tmdb_label = QLabel(tr('glossary_tmdb_not_resolved'))
        self.tmdb_label.setObjectName("glossaryTmdbLabel")
        root.addWidget(self.tmdb_label)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton(tr('glossary_run'))
        self.run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self.run_btn)
        self.cancel_btn = QPushButton(tr('glossary_cancel'))
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        run_row.addWidget(self.cancel_btn)
        run_row.addStretch()
        root.addLayout(run_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        root.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(90)
        root.addWidget(self.log_view)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        retro_warning = QLabel(tr('glossary_retroactive_warning'))
        retro_warning.setWordWrap(True)
        retro_warning.setObjectName("glossaryWarning")
        root.addWidget(retro_warning)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.addStretch()
        self.scroll.setWidget(self.cards_container)
        root.addWidget(self.scroll, 1)

        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = QPushButton(tr('glossary_save'))
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self.save_btn)
        root.addLayout(save_row)

    # ------------------------------------------------------------------
    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, tr('glossary_show_folder'))
        if d:
            self.folder_edit.setText(d)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(d).name)

    def _on_name_changed(self, _text):
        self._tmdb_id = None
        self.tmdb_label.setText(tr('glossary_tmdb_not_resolved'))

    def _on_resolve_tmdb(self):
        title = self.name_edit.text().strip()
        if not title:
            return
        self.tmdb_label.setText(tr('glossary_tmdb_resolving'))
        self._tmdb_worker = _TmdbResolveWorker(title, self)
        self._tmdb_worker.resolved.connect(
            lambda result: self._on_tmdb_resolved(result, title))
        self._tmdb_worker.start()

    def _on_tmdb_resolved(self, result, title):
        if not result or not result.get('id'):
            self.tmdb_label.setText(tr('glossary_tmdb_not_found'))
            self._tmdb_id = None
            return
        self._tmdb_id = result['id']
        self.tmdb_label.setText(
            f"TMDB #{self._tmdb_id} — {result.get('title', title)}")

    # ------------------------------------------------------------------
    def _on_run(self):
        show_dir = self.folder_edit.text().strip()
        if not show_dir or not Path(show_dir).is_dir():
            QMessageBox.warning(self, tr('glossary_dialog_title'),
                                 tr('glossary_error_no_folder'))
            return
        if self._tmdb_id is None:
            resp = QMessageBox.question(
                self, tr('glossary_dialog_title'),
                tr('glossary_confirm_no_tmdb'))
            if resp != QMessageBox.StandardButton.Yes:
                return

        name = _slugify(self.name_edit.text() or Path(show_dir).name)
        if self._tmdb_id is not None:
            # Il solo slug del nome puo' collidere tra show diversi (stesso
            # titolo comune, o traslitterazioni che si normalizzano uguali)
            # sovrascrivendo report/work_dir a vicenda — il TMDB id, quando
            # c'e', li rende univoci (bug reale segnalato in revisione).
            name = f"{name}_{self._tmdb_id}"

        exclude_episodes = []
        if self._tmdb_id is not None:
            try:
                from core.glossary_state import load_used
                exclude_episodes = [list(k) for k in load_used(self._tmdb_id)]
            except Exception as e:
                logger.warning(f"Lettura used_episodes fallita: {e}")

        qwen_model_path = get_config().get('gender_correction_model_path', '') or None

        args_payload = {
            "show_dir": show_dir,
            "name": name,
            "tmdb_id": self._tmdb_id,
            "min_freq": 3,
            "min_episodes": 6,
            "min_blocks": 6000,
            "use_align": True,
            "use_qwen": bool(qwen_model_path),
            "qwen_model_path": qwen_model_path,
            "align_device": "cpu",
            "exclude_episodes": exclude_episodes,
        }
        work_dir = PROJECT_ROOT / 'mt_eval' / 'glossary_work' / name

        self._clear_cards()
        self.save_btn.setEnabled(False)
        self.log_view.clear()
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(tr('glossary_status_running'))
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self._worker = GlossaryBuilderWorker(args_payload, work_dir, self)
        self._worker.gate.connect(self._on_gate)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.cancel()
        self.cancel_btn.setEnabled(False)

    def _on_gate(self, gate: dict):
        if not gate.get('ok', True):
            self.status_label.setText(
                tr('glossary_gate_insufficient').format(
                    blocks=gate.get('blocks', 0), need=gate.get('need_blocks', 0)))

    def _on_progress(self, phase, done, total, msg):
        if total:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
        self.status_label.setText(f"[{phase}] {msg} ({done}/{total})" if total else phase)

    def _on_log_line(self, msg):
        self.log_view.append(msg)

    def _on_failed(self, msg):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status_label.setText(tr('glossary_status_failed').format(msg=msg))
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _on_finished_ok(self, report_path: str):
        import json
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        try:
            report = json.loads(Path(report_path).read_text(encoding='utf-8'))
        except Exception as e:
            self._on_failed(f"Report illeggibile: {e}")
            return
        self._report = report

        gate = report.get('gate', {})
        if not gate.get('ok', True):
            self.status_label.setText(
                tr('glossary_gate_insufficient').format(
                    blocks=gate.get('blocks', 0), need=gate.get('need_blocks', 0)))
            return

        candidates = report.get('candidates', [])
        self.status_label.setText(
            tr('glossary_status_done').format(n=len(candidates)))
        self._clear_cards()
        for rec in candidates:
            card = _TermCard(rec)
            self._term_cards.append(card)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.save_btn.setEnabled(bool(candidates))

    def _clear_cards(self):
        for card in self._term_cards:
            card.setParent(None)
            card.deleteLater()
        self._term_cards = []

    # ------------------------------------------------------------------
    def _on_save(self):
        if not self._report:
            return
        tmdb_id = self._report.get('tmdb_id') or self._tmdb_id
        if tmdb_id is None:
            QMessageBox.warning(self, tr('glossary_dialog_title'),
                                 tr('glossary_error_no_tmdb_save'))
            return

        new_terms = {}
        for card in self._term_cards:
            if card.approve_cb.isChecked():
                term = card.record['term']
                rendering = card.rendering_edit.text().strip()
                if rendering:
                    new_terms[term] = rendering

        if not new_terms:
            QMessageBox.information(self, tr('glossary_dialog_title'),
                                     tr('glossary_no_terms_approved'))
            return

        try:
            from core.glossary import merge_glossary
            from core.glossary_state import mark_used
            path = merge_glossary(tmdb_id, new_terms)
            episodes_used = [tuple(k) for k in self._report.get('episodes_used', [])]
            if episodes_used:
                mark_used(tmdb_id, episodes_used)
        except Exception as e:
            QMessageBox.critical(self, tr('glossary_dialog_title'),
                                  tr('glossary_save_error').format(error=str(e)))
            return

        QMessageBox.information(
            self, tr('glossary_dialog_title'),
            tr('glossary_save_success').format(n=len(new_terms), path=str(path)))
