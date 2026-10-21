# -*- coding: utf-8 -*-
"""
Dialog "Glossario per show" — Strumenti -> Glossario per show.
File: gui/glossary_dialog.py

Interfaccia per lanciare la costruzione/validazione semi-automatica del
glossario per-show (glossary_engine/build_glossary_candidates.py, subprocess
isolato in venv_glossary/) e approvare a mano i candidati proposti, un
minuto di lavoro invece della riga di comando. NON in SettingsDialog:
questo e' uno strumento con un output (un report da rivedere), non una
preferenza persistente.
"""
import logging
import re
from pathlib import Path
from typing import List, Optional

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


# Librerie Plex (V:\Show\Season N\...): la cartella scelta puo' essere la
# sottocartella stagione, non lo show — il suo nome ("Season 2") non trova
# mai riscontro su TMDB e, peggio, degrada a "Season" dopo _clean_title
# facendo scrivere un tmdb_id SBAGLIATO nel glossario (bug reale). Ancorato
# ^...$ cosi' "Season of the Witch" non viene mai scambiato per una cartella
# stagione.
_SEASON_DIR_RE = re.compile(
    r'^(?:season|stagione|saison|staffel|temporada|series|s)\s*[._-]?\s*\d{1,3}$'
    r'|^(?:specials?|speciali|extras?|bonus|special\s+features|featurettes?)$',
    re.IGNORECASE)

_SXXEXX_RE = re.compile(r'[Ss]\d{1,2}[Ee]\d{1,3}|(?<![A-Za-z0-9])\d{1,2}x\d{1,3}(?![A-Za-z0-9])')

_EP_EXT = {'.mkv', '.mp4', '.avi', '.m4v', '.ts', '.srt', '.ass', '.ssa'}


def _title_from_episode_files(folder: Path, depth: int = 1) -> Optional[str]:
    """Titolo grezzo dal primo file con SxxExx trovato. Scansione LIMITATA
    (cartella scelta + un livello, niente os.walk su share di rete) — le
    cartelle Extras/Special Features si escludono da sole perche' i loro
    file non hanno un pattern SxxExx nel nome."""
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    subdirs = []
    for p in entries:
        if p.is_dir():
            subdirs.append(p)
            continue
        if p.suffix.lower() not in _EP_EXT:
            continue
        m = _SXXEXX_RE.search(p.name)
        if not m:
            continue
        raw = re.sub(r'[._]+', ' ', p.name[:m.start()])
        raw = re.sub(r'\s+', ' ', raw).strip(' -')
        if raw:
            return raw
    if depth > 0:
        for sub in subdirs:
            t = _title_from_episode_files(sub, depth - 1)
            if t:
                return t
    return None


def _name_candidates(folder: str) -> List[str]:
    """Candidati per la ricerca TMDB, in ordine di affidabilita'. Su una
    libreria Plex il nome della cartella show e' curato a mano: batte il
    nome del file (release dotted/lowercase, romanizzazioni anime diverse
    dal titolo TMDB)."""
    p = Path(folder)
    out = []
    if _SEASON_DIR_RE.match(p.name):
        out.append(p.parent.name)  # V:\Show\Season 2 -> "Show"
        out.append(_title_from_episode_files(p))
    else:
        out.append(p.name)  # cartella show gia' pulita, o cartella film
        out.append(_title_from_episode_files(p))
        out.append(p.parent.name)  # ultima spiaggia
    seen, res = set(), []
    for c in out:
        c = (c or '').strip()
        k = c.lower()
        if c and k not in seen and not _SEASON_DIR_RE.match(c):
            seen.add(k)
            res.append(c)
    return res


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
    misurato in revisione, viola la policy no-freeze del progetto).

    Prova i candidati in `_candidates` in ordine, si ferma al primo che
    risolve. Su libreria Plex (V:\\Show\\Season N\\...) la cartella scelta
    puo' essere quella stagione: il nome cartella "Season 2" NON deve mai
    arrivare a search_tv, perche' parse_filename lo degrada a "Season" e
    search_tv restituisce comunque results[0] di qualcosa — un tmdb_id
    sbagliato scritto silenziosamente nel glossario (bug reale)."""
    resolved = pyqtSignal(object, object)  # (dict risultato o None, candidato usato o None)

    def __init__(self, candidates: List[str], parent=None):
        super().__init__(parent)
        self._candidates = [c for c in candidates if c and c.strip()]

    def run(self):
        result = used = None
        try:
            from utils.tmdb_client import get_tmdb_client
            client = get_tmdb_client()
            tried = set()
            for cand in self._candidates:
                if _SEASON_DIR_RE.match(cand.strip()):
                    continue
                # Stessa pulizia usata per le locandine (get_media_info):
                # rimuove punti/underscore, tag release group, risoluzione.
                parsed = client.parse_filename(cand)
                clean = (parsed.get('title') or cand).strip()
                if not clean or clean.lower() in tried:
                    continue
                tried.add(clean.lower())
                r = client.search_tv(clean, year=parsed.get('year'))
                if r and r.get('id'):
                    result, used = r, clean
                    break
        except Exception as e:
            logger.warning(f"Ricerca TMDB fallita: {e}")
        self.resolved.emit(result, used)


class GlossaryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('glossary_dialog_title'))
        self.resize(760, 700)

        self._worker: GlossaryBuilderWorker | None = None
        self._report: dict | None = None
        self._tmdb_id = None
        self._term_cards: list[_TermCard] = []
        self._name_candidates: List[str] = []

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
        self._mark_worker_inactive()
        super().closeEvent(event)

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._mark_worker_inactive()
        super().reject()

    def _mark_worker_inactive(self):
        """Il dialog e' application-modal (exec()), quindi da GUI non si
        puo' avviare la coda di trascrizione mentre e' aperto — ma e' una
        garanzia implicita: questo flag sul parent la rende esplicita, per
        non dipendere in futuro solo dalla modalita' del dialog."""
        parent = self.parent()
        if parent is not None:
            parent._glossary_worker_active = False

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
        if not d:
            return
        self.folder_edit.setText(d)  # show_dir resta la scelta dell'utente, intatta
        self._name_candidates = _name_candidates(d)
        if not self.name_edit.text().strip() and self._name_candidates:
            self.name_edit.setText(self._name_candidates[0])
        if _SEASON_DIR_RE.match(Path(d).name):
            self.tmdb_label.setText(
                f"{tr('glossary_tmdb_not_resolved')} "
                f"({Path(d).parent.name} → {Path(d).name})")

    def _on_name_changed(self, _text):
        self._tmdb_id = None
        self.tmdb_label.setText(tr('glossary_tmdb_not_resolved'))

    def _on_resolve_tmdb(self):
        typed = self.name_edit.text().strip()
        cands = getattr(self, '_name_candidates', []) or []
        # Il testo digitato/pre-riempito ha la precedenza; gli altri
        # candidati (cartella padre, nome file episodio) sono fallback.
        ordered = ([typed] if typed else []) + [
            c for c in cands if c.lower() != typed.lower()]
        if not ordered:
            return
        self.tmdb_label.setText(tr('glossary_tmdb_resolving'))
        self._tmdb_worker = _TmdbResolveWorker(ordered, self)
        self._tmdb_worker.resolved.connect(self._on_tmdb_resolved)
        self._tmdb_worker.start()

    def _on_tmdb_resolved(self, result, used_title):
        if not result or not result.get('id'):
            self.tmdb_label.setText(tr('glossary_tmdb_not_found'))
            self._tmdb_id = None
            return
        self._tmdb_id = result['id']
        title = result.get('title') or used_title or ''
        if title and title.strip().lower() != self.name_edit.text().strip().lower():
            self.name_edit.blockSignals(True)  # _on_name_changed azzererebbe _tmdb_id
            self.name_edit.setText(title)
            self.name_edit.blockSignals(False)
        self.tmdb_label.setText(f"TMDB #{self._tmdb_id} — {title}")

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

        # Fallback se il campo nome e' vuoto: mai il nome della cartella
        # scelta as-is (se e' "Season 2" lo slug collide tra show diversi,
        # vedi nota sotto) — preferisci il primo candidato gia' risolto.
        _fallback = (getattr(self, '_name_candidates', None)
                     or [Path(show_dir).name])[0]
        name = _slugify(self.name_edit.text().strip() or _fallback)
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

        qwen_model_path, qwen_ngl = get_config().resolve_llm_model(
            'gender_correction_model_path', getattr(self, 'llm_model_preference', None))
        if qwen_model_path and qwen_ngl == 0:
            # Scelta automatica senza GPU utilizzabile: il canale Qwen su sola CPU richiederebbe ore, non si accende da solo.
            logger.info(f"Canale Qwen del glossario non attivato (nessuna GPU rilevata): {qwen_model_path}")
            qwen_model_path = None
        elif qwen_model_path:
            logger.info(f"Canale Qwen del glossario: {qwen_model_path} (n_gpu_layers={qwen_ngl})")
        qwen_model_path = qwen_model_path or None

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
            "qwen_n_gpu_layers": qwen_ngl,
            "exclude_episodes": exclude_episodes,
        }
        work_dir = PROJECT_ROOT / 'glossary_engine' / 'glossary_work' / name

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
        parent = self.parent()
        if parent is not None:
            parent._glossary_worker_active = True
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
        self._mark_worker_inactive()

    def _on_finished_ok(self, report_path: str):
        import json
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._mark_worker_inactive()
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
        qwen_err = report.get('qwen_channel_error')
        if qwen_err:
            self.log_view.append(
                tr('glossary_qwen_channel_failed').format(msg=qwen_err))
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
