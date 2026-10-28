# -*- coding: utf-8 -*-
"""Impostazioni di trascrizione e di traduzione (fase 3). Usano i servizi senza Qt di G3: `TranscriptionSettingsService` e
`TranslationModelService`; il download del modello LLM e il test di pyannote girano in un sottoprocesso (`EnvCliRunner`) e le righe
arrivano alla pagina come eventi. Chiavi API e token non escono mai dal server: la pagina vede solo se sono impostati."""
import importlib.util
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.jobs.env_cli import EnvCliListener, EnvCliRunner
from core.services.transcription_settings_service import ENGINE_CHOICES, SHOW_PROFILE_CARDS, TranscriptionSettingsService, profile_specs
from core.services.translation_model_service import MODEL_IDS, OPENAI_MODELS, TranslationModelService
from tpweb.events import EventBus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FLAGS = {          # chiave del config -> (tipo, minimo, massimo, predefinito): le sole che la pagina puo' scrivere
    'enable_forced_alignment': ('bool', None, None, False),
    'enable_diarization': ('bool', None, None, False),
    'diarization_num_speakers': ('int', 0, 10, 0),
    'gender_correction_enabled': ('bool', None, None, False),
    'gender_correction_second_person': ('bool', None, None, True),
    'force_audio_transcription': ('bool', None, None, False),
}


def translator_available() -> bool:
    """Come la GUI: la scheda Traduzione si apre solo se `torch` e `transformers` sono installati (senza importarli)."""
    return importlib.util.find_spec('transformers') is not None and importlib.util.find_spec('torch') is not None


class EnvJobs:
    """Un lavoro alla volta per tipo (`llm-download`, `diarization-test`): righe di stato come eventi del bus."""

    def __init__(self, bus: EventBus, runner_cls=None):
        self.bus, self.runner_cls = bus, runner_cls or EnvCliRunner
        self._lock = threading.Lock()
        self.state: Dict[str, dict] = {}

    def snapshot(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self.state.items()}

    def start(self, command: str) -> bool:
        with self._lock:
            if self.state.get(command, {}).get('running'):
                return False
            self.state[command] = {'running': True, 'last_line': '', 'exit_code': None}
        bus, jobs = self.bus, self

        class L(EnvCliListener):
            def on_line(self, line):
                with jobs._lock:
                    jobs.state[command]['last_line'] = line
                bus.publish('env_line', {'job': command, 'line': line})

            def on_finished(self, exit_code):
                with jobs._lock:
                    jobs.state[command].update(running=False, exit_code=exit_code)
                bus.publish('env_done', {'job': command, 'exit_code': exit_code, 'last_line': jobs.state[command]['last_line']})
        runner = self.runner_cls(command, L())
        threading.Thread(target=runner.run, name=f'tpweb-env-{command}', daemon=True).start()
        return True


class EngineBody(BaseModel):
    engine_mode: Optional[str] = None
    dialogue_style: Optional[bool] = None
    profile: Optional[str] = None


class ModelBody(BaseModel):
    name: str


class PathBody(BaseModel):
    path: str = ''


class BeamsBody(BaseModel):
    value: int = Field(ge=1, le=20)


class SecretBody(BaseModel):
    value: str = ''


class OpenAiBody(BaseModel):
    key: str = ''
    model: str = OPENAI_MODELS[0]


class FlagBody(BaseModel):
    key: str
    value: object


def add_model_routes(app: FastAPI, config, bus: EventBus, env_jobs: Optional[EnvJobs] = None,
                     translator_ok: Optional[Callable[[], bool]] = None) -> None:
    translator_ok = translator_ok or translator_available
    ts, tm = TranscriptionSettingsService(config), TranslationModelService(config)
    jobs = env_jobs or EnvJobs(bus)
    app.state.env_jobs = jobs

    # ------------------------------------------------------------------------------------------------------------- trascrizione
    def transcription_state() -> dict:
        return {'engine_mode': ts.engine_mode(), 'engines': [{'value': v, 'key': k} for v, k in ENGINE_CHOICES],
                'dialogue_style': ts.dialogue_style(), 'profile': ts.current_profile(), 'show_cards': SHOW_PROFILE_CARDS,
                'cards': [{'value': c.value, 'name_key': c.name_key, 'desc_key': c.desc_key, 'params': c.params, 'time': c.time,
                           'recommended': c.recommended, 'warning_key': c.warning_key} for c in profile_specs()]}

    @app.get('/api/settings/transcription')
    async def get_transcription():
        return transcription_state()

    @app.put('/api/settings/transcription')
    async def put_transcription(b: EngineBody):
        if b.engine_mode is not None:
            if b.engine_mode not in {v for v, _ in ENGINE_CHOICES}:
                return JSONResponse({'error': 'motore non valido'}, status_code=422)
            ts.set_engine_mode(b.engine_mode)
        if b.dialogue_style is not None:
            ts.set_dialogue_style(b.dialogue_style)
        if b.profile is not None:
            if b.profile not in {c.value for c in profile_specs()}:
                return JSONResponse({'error': 'profilo non valido'}, status_code=422)
            ts.select_profile(b.profile, persist=True)
        return transcription_state()

    # --------------------------------------------------------------------------------------------------------------- traduzione
    def translation_state() -> dict:
        model = tm.current_model()
        return {'translator_available': translator_ok(), 'model': 'llm' if model == 'aya' else model, 'models': list(MODEL_IDS),
                'nllb_ft': {'path': tm.nllb_ft_path(), 'configured': tm.nllb_ft_configured()}, 'llm_path': tm.llm_path(),
                'nllb_beams': tm.nllb_beams(), 'hf_token_set': tm.hf_token_set(), 'claude_key_set': tm.claude_key_set(),
                'openai_key_set': tm.openai_key_set(), 'openai_model': tm.openai_model(), 'openai_models': list(OPENAI_MODELS),
                'os_rest_configured': tm.opensubtitles_rest_configured(), 'diarization_urls': tm.diarization_urls(),
                'flags': {k: tm.flag(k, spec[3]) for k, spec in FLAGS.items()},
                'gender_missing': tm.gender_prerequisites(PROJECT_ROOT), 'jobs': jobs.snapshot()}

    @app.get('/api/settings/translation')
    async def get_translation():
        return translation_state()

    @app.put('/api/settings/translation/model')
    async def put_model(b: ModelBody):
        if not tm.select_embedded(b.name):                 # in modalita' embed la scelta si salva subito, senza conferme
            return JSONResponse({'error': 'modello sconosciuto'}, status_code=422)
        return translation_state()

    @app.put('/api/settings/translation/nllb_ft_path')
    async def put_nllb_ft(b: PathBody):
        chk, path = tm.save_nllb_ft_path(b.path)
        return {'kind': chk.kind, 'path': path, 'state': translation_state()}

    @app.put('/api/settings/translation/llm_path')
    async def put_llm(b: PathBody):
        chk, path = tm.save_llm_path(b.path)
        return {'kind': chk.kind, 'path': path, 'state': translation_state()}

    @app.put('/api/settings/translation/nllb_beams')
    async def put_beams(b: BeamsBody):
        tm.set_nllb_beams(b.value)
        return translation_state()

    @app.put('/api/settings/translation/hf_token')
    async def put_hf(b: SecretBody):
        res, _ = tm.save_hf_token(b.value)
        return {'kind': res.kind, 'error': res.error, 'state': translation_state()}

    @app.put('/api/settings/translation/claude_key')
    async def put_claude(b: SecretBody):
        res = tm.save_claude_key(b.value)
        return {'kind': res.kind, 'error': res.error, 'state': translation_state()}

    @app.put('/api/settings/translation/openai')
    async def put_openai(b: OpenAiBody):
        if b.model not in OPENAI_MODELS:
            return JSONResponse({'error': 'modello non valido'}, status_code=422)
        res = tm.save_openai(b.key, b.model)
        return {'kind': res.kind, 'error': res.error, 'state': translation_state()}

    @app.put('/api/settings/translation/flag')
    async def put_flag(b: FlagBody):
        spec = FLAGS.get(b.key)
        if spec is None:
            return JSONResponse({'error': 'impostazione non ammessa'}, status_code=422)
        kind, lo, hi, _ = spec
        if kind == 'bool' and isinstance(b.value, bool):
            tm.set_flag(b.key, b.value)
        elif kind == 'int' and isinstance(b.value, int) and not isinstance(b.value, bool) and lo <= b.value <= hi:
            tm.set_flag(b.key, b.value)
        else:
            return JSONResponse({'error': 'valore non valido'}, status_code=422)
        return translation_state()

    @app.post('/api/settings/translation/llm_download')
    async def llm_download():
        if not tm.hf_token_set():                          # come la GUI: serve prima il token (la pagina mostra l'avviso)
            return JSONResponse({'kind': 'token_missing'}, status_code=409)
        return JSONResponse({'kind': 'started' if jobs.start('llm-download') else 'running'})

    @app.post('/api/settings/translation/diarization_test')
    async def diarization_test():
        if not tm.hf_token():
            return JSONResponse({'kind': 'token_missing'}, status_code=409)
        return JSONResponse({'kind': 'started' if jobs.start('diarization-test') else 'running'})
