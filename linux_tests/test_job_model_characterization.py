# -*- coding: utf-8 -*-
"""JobRecord (modello di una riga della coda): forma del dict e transizioni di stato, fissate PRIMA di aggiungere il campo `ov`.
Lo stesso file passa identico sul codice vecchio (gui.services.job_model) e sul nuovo (core.services.job_model)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from core.services.job_model import JobRecord, JobStatus, KIND_OCR, is_reorderable
except ImportError:                                  # codice vecchio: il modulo stava in gui/services
    from gui.services.job_model import JobRecord, JobStatus, KIND_OCR, is_reorderable


def test_forma_del_dict_della_riga():
    r = JobRecord.new('/v/Film.mkv', '1 GB')
    assert r.to_item_data() == {'path': '/v/Film.mkv', 'filename': 'Film.mkv', 'status': 'queued', 'progress': 0, 'size': '1 GB'}
    o = JobRecord.new_ocr('/v/Film.mkv', 'PGS')
    assert o.to_item_data() == {'path': '/v/Film.mkv', 'filename': 'Film.mkv', 'status': 'queued', 'progress': 0, 'size': 'OCR · PGS', 'kind': 'ocr'}
    assert o.is_ocr and not r.is_ocr


def test_transizioni():
    r = JobRecord.new('/a.mkv')
    assert (r.started().status, r.started().progress) == ('processing', 0)
    assert r.started().with_progress(40).progress == 40
    assert (r.completed().status, r.completed().progress) == ('completed', 100)
    assert (r.started().with_progress(40).failed().status, r.failed().progress) == ('failed', 0)
    w = r.with_status('processing', '55')
    assert (w.status, w.progress) == ('processing', 55)
    assert r.started().with_progress(7).path == '/a.mkv' and JobRecord.new_ocr('/a.mkv', 'x').started().kind == KIND_OCR


def test_da_dict_e_ritorno_e_merge():
    d = {'path': '/a.mkv', 'filename': 'a.mkv', 'status': 'processing', 'progress': 30, 'size': '2 GB', 'extra': 'x'}
    r = JobRecord.from_item_data(d)
    assert r.to_item_data() == {k: v for k, v in d.items() if k != 'extra'}
    assert JobRecord.from_item_data(None).path == '' and JobRecord.from_item_data({}).status == 'queued'
    merged = r.completed().merge_into(dict(d))
    assert merged['status'] == 'completed' and merged['progress'] == 100 and merged['size'] == '2 GB' and merged['extra'] == 'x'


def test_riordinabile_solo_in_attesa_e_non_ocr():
    assert is_reorderable('queued', None) and not is_reorderable('queued', 'ocr')
    assert not is_reorderable('processing', None) and not is_reorderable('completed', None) and not is_reorderable(None, None)
    assert JobStatus.ALL == ('queued', 'processing', 'completed', 'failed')
