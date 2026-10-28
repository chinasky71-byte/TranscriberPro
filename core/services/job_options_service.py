# -*- coding: utf-8 -*-
"""
JobOptionsService: opzioni per-job (lingua target, upload OpenSubtitles, mux, gender, spegnimento).

Ogni setter scrive in config E SU DISCO in modo SINCRONO (config.set(..., save=True)): il child
pipeline_cli rilegge il config dal disco all'avvio di ogni file, quindi il valore deve essere
persistito al momento del cambio, non a fine sessione.
"""
from dataclasses import dataclass


# Lingue sottotitoli supportate (i nomi si traducono con le chiavi lang_name_<codice>)
SUBTITLE_LANGUAGE_CODES = ("ita", "eng", "fra", "spa", "deu", "por", "rus", "jpn", "zho", "ara", "kor", "nld", "pol", "tur")


def engine_short(config) -> str:
    """Motore di traduzione predefinito, in breve ('TG', 'NLLB-FT', ...)."""
    try:
        m = config.get_translation_model()
    except Exception:
        return '?'
    return {'llm': 'TG', 'nllb_finetuned': 'NLLB-FT', 'nllb': 'NLLB'}.get(m, str(m).upper())


def ocr_review_label(config) -> str:
    """Revisione OCR predefinita: 'mirata' o 'automatica' (config 'ocr_strategy')."""
    from utils.translations import tr
    return tr('job_ocr_mode_auto') if config.get('ocr_strategy', 'review') == 'auto' else tr('job_ocr_mode_targeted')


def defaults_summary(config) -> str:
    """Riga di riepilogo dei predefiniti sotto Avvia: 'ITA · ↗ OS · ⧉ mux · ⚧ · TG' (senza lo spegnimento, che ha la sua casella)."""
    c = config
    text = JobOptionsService.summary_text(c.get_target_language(), c.get('opensubtitles_upload_enabled', True),
                                          c.get('mux_subtitle_into_video', False), c.get('gender_correction_enabled', False), False)
    return f"{text} · {engine_short(c)}"


@dataclass(frozen=True)
class JobOptions:
    target_language: str
    opensubtitles_upload: bool
    mux_into_video: bool
    gender_correction: bool
    shutdown_after: bool


class JobOptionsService:
    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------ lettura
    def target_language(self) -> str:
        return self._config.get_target_language()

    def load(self) -> JobOptions:
        c = self._config
        return JobOptions(
            target_language=c.get_target_language(),
            opensubtitles_upload=c.get('opensubtitles_upload_enabled', True),
            mux_into_video=c.get('mux_subtitle_into_video', False),
            gender_correction=c.get('gender_correction_enabled', False),
            shutdown_after=c.get('shutdown_after_processing', False),
        )

    def card_open(self) -> bool:
        return bool(self._config.get('ui_job_card_open', False))

    # ------------------------------------------------------------------ scrittura (sincrona su disco)
    def set_target_language(self, code):
        if code:
            self._config.set_target_language(code)

    def set_opensubtitles_upload(self, enabled: bool):
        self._config.set('opensubtitles_upload_enabled', enabled, save=True)

    def set_mux_into_video(self, enabled: bool):
        self._config.set('mux_subtitle_into_video', enabled, save=True)

    def set_gender_correction(self, enabled: bool):
        self._config.set('gender_correction_enabled', enabled, save=True)

    def set_shutdown_after(self, enabled: bool):
        self._config.set('shutdown_after_processing', enabled, save=True)

    def set_card_open(self, opened: bool):
        try:
            self._config.set('ui_job_card_open', opened)
        except Exception:
            pass

    # ------------------------------------------------------------------ riepilogo
    @staticmethod
    def summary_text(target_code, upload_os: bool, mux: bool, gender: bool, shutdown: bool) -> str:
        """Riepilogo compatto nell'header della card: "ITA · ↗ OS · ⧉ mux · ⚧ · ⏻"."""
        parts = []
        code = target_code or ""
        parts.append(code.upper() if code else "—")
        if upload_os:
            parts.append("↗ OS")
        if mux:
            parts.append("⧉ mux")
        if gender:
            parts.append("⚧")
        if shutdown:
            parts.append("⏻")
        return " · ".join(parts)
