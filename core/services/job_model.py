# -*- coding: utf-8 -*-
"""
Modello di una riga della coda (nessun Qt; ex gui/services/job_model.py, il vecchio nome e un alias).

La verita' dello stato di una riga resta nel dict in UserRole del QListWidgetItem (e' quello che leggono
delegato, banco visivo e LibraryScannerWidget): JobRecord ne e' una vista tipizzata, con le transizioni
di stato spiegate in un punto solo. `to_item_data()` produce ESATTAMENTE la stessa forma del dict
originale: `kind` compare solo per i job OCR.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class JobStatus:
    QUEUED = 'queued'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'

    ALL = (QUEUED, PROCESSING, COMPLETED, FAILED)


KIND_OCR = 'ocr'


def is_reorderable(status: Optional[str], kind: Optional[str]) -> bool:
    """Solo righe in attesa e destinate al worker (no OCR, no in corso/finite)."""
    return status == JobStatus.QUEUED and kind != KIND_OCR


@dataclass(frozen=True)
class JobRecord:
    path: str
    filename: str
    status: str = JobStatus.QUEUED
    progress: int = 0
    size: str = ''
    kind: Optional[str] = None
    ov: str = ''           # etichetta breve delle eccezioni della riga (solo web UI; la GUI Qt la tiene nel dict della riga)
    ov_lang: str = ''      # lingua di destinazione dell'eccezione: resta sulla riga anche quando il motore prende il file

    # ------------------------------------------------------------------ costruzione
    @classmethod
    def new(cls, path: str, size: str = '') -> 'JobRecord':
        return cls(path=path, filename=Path(path).name, size=size)

    @classmethod
    def new_ocr(cls, path: str, kind_label: str) -> 'JobRecord':
        return cls(path=path, filename=Path(path).name, size=f'OCR · {kind_label}', kind=KIND_OCR)

    @classmethod
    def from_item_data(cls, data: Optional[dict]) -> 'JobRecord':
        d = data or {}
        return cls(path=d.get('path', ''), filename=d.get('filename', ''),
                   status=d.get('status', JobStatus.QUEUED), progress=d.get('progress', 0),
                   size=d.get('size', ''), kind=d.get('kind'), ov=d.get('ov', '') or '', ov_lang=d.get('ov_lang', '') or '')

    def to_item_data(self) -> dict:
        data = {
            'path':     self.path,
            'filename': self.filename,
            'status':   self.status,
            'progress': self.progress,
            'size':     self.size,
        }
        if self.kind is not None:
            data['kind'] = self.kind
        if self.ov:
            data['ov'] = self.ov
        if self.ov_lang:
            data['ov_lang'] = self.ov_lang
        return data

    # ------------------------------------------------------------------ transizioni
    def started(self) -> 'JobRecord':
        return self._with(status=JobStatus.PROCESSING, progress=0)

    def with_progress(self, percent: int) -> 'JobRecord':
        return self._with(progress=percent)

    def completed(self) -> 'JobRecord':
        return self._with(status=JobStatus.COMPLETED, progress=100)

    def failed(self) -> 'JobRecord':
        return self._with(status=JobStatus.FAILED, progress=0)

    def with_ov(self, text: str, lang: str = '') -> 'JobRecord':
        return self._with(ov=text or '', ov_lang=lang or '')

    def with_status(self, status: str, progress: int) -> 'JobRecord':
        return self._with(status=status, progress=int(progress))

    def _with(self, **changes) -> 'JobRecord':
        fields = dict(path=self.path, filename=self.filename, status=self.status,
                      progress=self.progress, size=self.size, kind=self.kind, ov=self.ov, ov_lang=self.ov_lang)
        fields.update(changes)
        return JobRecord(**fields)

    # ------------------------------------------------------------------ interrogazioni
    @property
    def is_ocr(self) -> bool:
        return self.kind == KIND_OCR

    def merge_into(self, data: dict) -> dict:
        """Riporta nel dict esistente SOLO stato e avanzamento (size/kind/path restano quelli della riga)."""
        data['status'] = self.status
        data['progress'] = self.progress
        return data
