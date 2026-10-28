# -*- coding: utf-8 -*-
"""Impostazioni semplici (fetta 1c): generali, opzioni dei job, batch adattivo, OCR, OpenSubtitles. Usa i servizi senza Qt di G1.
Le chiavi API e le password NON escono mai dal server: la pagina vede solo se sono impostate (`*_set`) e puo' sostituirle."""
import asyncio
from typing import Literal, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.services.adaptive_batch_service import AdaptiveBatchService, AdaptiveBatchValues
from core.services.general_settings_service import GeneralSettingsService, LANGUAGES, ping_scanner
from core.services.job_options_service import JobOptionsService
from core.services.ocr_settings_service import OcrSettingsService
from core.services.opensubtitles_settings_service import IMPLEMENTATIONS, OpenSubtitlesSettingsService
from core.pgs_types import WRITEBACK_MUX, WRITEBACK_SIDECAR, STRATEGY_AUTO, STRATEGY_REVIEW


class GeneralBody(BaseModel):
    language: Optional[Literal['auto', 'it', 'en']] = None
    scanner_url: Optional[str] = None
    scanner_api_key: Optional[str] = None            # sola scrittura
    scanner_path_map: Optional[str] = None


class JobOptionsBody(BaseModel):
    target_language: Optional[str] = Field(None, min_length=1, max_length=8)
    opensubtitles_upload: Optional[bool] = None
    mux_into_video: Optional[bool] = None
    gender_correction: Optional[bool] = None
    shutdown_after: Optional[bool] = None


class AdaptiveBody(BaseModel):
    enabled: Optional[bool] = None
    initial_size: Optional[int] = Field(None, ge=0, le=64)
    min_size: Optional[int] = Field(None, ge=1, le=16)
    max_size: Optional[int] = Field(None, ge=1, le=64)
    warmup_batches: Optional[int] = Field(None, ge=0, le=20)
    high_threshold: Optional[float] = Field(None, ge=0.5, le=1.0)
    low_threshold: Optional[float] = Field(None, ge=0.1, le=0.9)


class OcrBody(BaseModel):
    strategy: Optional[Literal['review', 'auto']] = None
    language: Optional[str] = None
    conf_threshold: Optional[int] = Field(None, ge=0, le=100)
    workers: Optional[int] = Field(None, ge=0, le=32)
    writeback: Optional[Literal['mux', 'sidecar']] = None
    tesseract_path: Optional[str] = None


class OsBody(BaseModel):
    implementation: Optional[Literal['xmlrpc', 'rest']] = None
    upload_enabled: Optional[bool] = None


class OsComBody(BaseModel):
    username: str
    password: str
    api_key: str = ''


class OsOrgBody(BaseModel):
    username: str
    password: str


class PingBody(BaseModel):
    url: Optional[str] = None
    api_key: Optional[str] = None


def add_settings_routes(app: FastAPI, config) -> None:
    gen, job = GeneralSettingsService(config), JobOptionsService(config)
    abs_, ocr, osub = AdaptiveBatchService(config), OcrSettingsService(config), OpenSubtitlesSettingsService(config)

    def general() -> dict:
        return {'language': gen.language(), 'languages': list(LANGUAGES), 'scanner_url': gen.scanner_url(),
                'scanner_api_key_set': bool(gen.scanner_api_key()), 'scanner_path_map': gen.scanner_path_map()}

    def job_options() -> dict:
        o = job.load()
        return {'target_language': o.target_language, 'opensubtitles_upload': o.opensubtitles_upload,
                'mux_into_video': o.mux_into_video, 'gender_correction': o.gender_correction, 'shutdown_after': o.shutdown_after}

    def adaptive() -> dict:
        v = abs_.load()
        return {'enabled': v.enabled, 'initial_size': v.initial_size, 'min_size': v.min_size, 'max_size': v.max_size,
                'warmup_batches': v.warmup_batches, 'high_threshold': v.high_threshold, 'low_threshold': v.low_threshold,
                'status_text': abs_.status_text(v.enabled)}

    def ocr_values() -> dict:
        v = ocr.load((WRITEBACK_MUX, WRITEBACK_SIDECAR))
        return {'strategy': v.strategy, 'language': v.language, 'conf_threshold': v.conf_threshold, 'workers': v.workers,
                'writeback': v.writeback, 'tesseract_path': v.tesseract_path}

    def opensubtitles() -> dict:
        st = osub.status()
        return {'implementation': osub.normalize_implementation(), 'implementations': list(IMPLEMENTATIONS),
                'upload_enabled': osub.upload_enabled(), 'configured': st.configured, 'username': st.username,
                'com_username': osub.credentials_com().get('username', ''), 'org_username': osub.credentials_org().get('username', ''),
                'com_password_set': bool(osub.credentials_com().get('password')),
                'org_password_set': bool(osub.credentials_org().get('password')),
                'com_api_key_set': bool(osub.credentials_com().get('api_key'))}

    sections = {'general': general, 'job_options': job_options, 'adaptive_batch': adaptive, 'ocr': ocr_values,
                'opensubtitles': opensubtitles}

    @app.get('/api/settings')
    async def get_all():
        return {k: fn() for k, fn in sections.items()}

    @app.put('/api/settings/general')
    async def put_general(b: GeneralBody):
        if b.language is not None:
            gen.set_language(b.language)
        if b.scanner_url is not None:
            gen.set_scanner_url(b.scanner_url)
        if b.scanner_api_key is not None:
            gen.set_scanner_api_key(b.scanner_api_key)
        if b.scanner_path_map is not None:
            gen.set_scanner_path_map(b.scanner_path_map)
        return general()

    @app.post('/api/settings/general/ping')
    async def ping(b: PingBody):
        url = b.url if b.url is not None else gen.scanner_url()
        key = b.api_key if b.api_key is not None else gen.scanner_api_key()
        ok, msg = await asyncio.get_running_loop().run_in_executor(None, ping_scanner, url, key)
        return {'ok': ok, 'message': msg}

    @app.put('/api/settings/job_options')
    async def put_job(b: JobOptionsBody):
        if b.target_language is not None:
            job.set_target_language(b.target_language)
        if b.opensubtitles_upload is not None:
            job.set_opensubtitles_upload(b.opensubtitles_upload)
        if b.mux_into_video is not None:
            job.set_mux_into_video(b.mux_into_video)
        if b.gender_correction is not None:
            job.set_gender_correction(b.gender_correction)
        if b.shutdown_after is not None:
            job.set_shutdown_after(b.shutdown_after)
        return job_options()

    @app.put('/api/settings/adaptive_batch')
    async def put_adaptive(b: AdaptiveBody):
        cur = abs_.load()
        merged = {f: (getattr(b, f) if getattr(b, f) is not None else getattr(cur, f)) for f in AdaptiveBatchValues.__dataclass_fields__}
        abs_.save(AdaptiveBatchValues(**merged))
        return adaptive()

    @app.post('/api/settings/adaptive_batch/reset')
    async def reset_adaptive():
        from core.services.adaptive_batch_service import DEFAULTS
        abs_.save(DEFAULTS)
        return adaptive()

    @app.put('/api/settings/ocr')
    async def put_ocr(b: OcrBody):
        if b.strategy is not None:
            ocr.set_strategy(b.strategy == STRATEGY_REVIEW)
        if b.language is not None:
            ocr.set_language(b.language)
        if b.conf_threshold is not None:
            ocr.set_conf_threshold(b.conf_threshold)
        if b.workers is not None:
            ocr.set_workers(b.workers)
        if b.writeback is not None:
            ocr.set_writeback(b.writeback)
        if b.tesseract_path is not None:
            ocr.set_tesseract_path(b.tesseract_path)
        return ocr_values()

    @app.put('/api/settings/opensubtitles')
    async def put_os(b: OsBody):
        if b.implementation is not None:
            osub.set_implementation(b.implementation)
        if b.upload_enabled is not None:
            osub.set_upload_enabled(b.upload_enabled)
        return opensubtitles()

    @app.put('/api/settings/opensubtitles/com')
    async def put_os_com(b: OsComBody):
        if not osub.save_com(b.username, b.password, b.api_key):
            return JSONResponse({'error': 'username e password obbligatori'}, status_code=422)
        return opensubtitles()

    @app.put('/api/settings/opensubtitles/org')
    async def put_os_org(b: OsOrgBody):
        if not osub.save_org(b.username, b.password):
            return JSONResponse({'error': 'username e password obbligatori'}, status_code=422)
        return opensubtitles()

    @app.post('/api/settings/opensubtitles/test')
    async def test_os():
        r = await asyncio.get_running_loop().run_in_executor(None, osub.test_connection)
        return {'kind': r.kind, 'implementation': r.implementation, 'error': r.error}
