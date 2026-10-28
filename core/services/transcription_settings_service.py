# -*- coding: utf-8 -*-
"""Impostazioni di trascrizione (motore, stile dei dialoghi, profili), senza Qt.

Trasposizione fedele della logica di gui/profile_dialog.py: voci e salvataggio del motore di trascrizione, stile dei dialoghi
professionale e schede dei profili (testi, badge, avvisi). Il dialogo resta la vista. I parametri dei profili sono in
utils/transcription_profiles.py."""
from dataclasses import dataclass
from typing import List, Optional

from utils.transcription_profiles import ProfileConfig, TranscriptionProfile
from utils.translations import tr

# Come `gui.profile_dialog.SHOW_PROFILE_CARDS` (decisione 02/10/2026: profili fissi su 'maximum', schede nascoste); `test_tpweb_settings_models`
# verifica che i due valori coincidano.
SHOW_PROFILE_CARDS = False

# (valore in config, chiave tr() dell'etichetta) nell'ordine della tendina
ENGINE_CHOICES = (('auto', 'engine_auto'), ('canary', 'engine_canary'), ('qwen3', 'engine_qwen3'),
                  ('faster-whisper', 'engine_whisper'))


def engine_choices() -> List[tuple]:
    """[(etichetta tradotta, valore)] nell'ordine della tendina."""
    return [(tr(key), value) for value, key in ENGINE_CHOICES]


def format_speed(speed_factor: float) -> str:
    """Speed factor in percentuale leggibile."""
    if speed_factor > 1.0:
        return f"+{int((speed_factor - 1) * 100)}%"
    elif speed_factor < 1.0:
        return f"{int((speed_factor - 1) * 100)}%"
    else:
        return "100%"


@dataclass(frozen=True)
class ProfileCard:
    value: str
    name_html: str
    description: str
    params: str
    time: str
    recommended_badge: Optional[str]     # testo del badge, None se non raccomandato
    warning: Optional[str]               # testo dell'avviso (con icona), None se assente


@dataclass(frozen=True)
class ProfileSpec:
    """Come `ProfileCard`, ma con le CHIAVI dei testi al posto dei testi: la web UI li traduce nella lingua della pagina."""
    value: str
    name_key: str
    desc_key: str
    params: str                     # emoji e numeri: uguale in ogni lingua
    time: str
    recommended: bool
    warning_key: Optional[str]


def profile_specs() -> List[ProfileSpec]:
    specs = []
    for profile in TranscriptionProfile:
        config = ProfileConfig.get_profile_config(profile)
        specs.append(ProfileSpec(
            value=profile.value, name_key=f'profile_{profile.value}_name', desc_key=f'profile_{profile.value}_desc',
            params=(f"⚙️ Whisper · W:{config['num_workers']} | "
                    f"🎯 B:{config['beam_size']} | "
                    f"⚡ {format_speed(config['speed_factor'])} | "
                    f"✨ {config['quality_percent']:.0f}%"),
            time=f"⏱️ ~{config['time_1h_audio_min']}min/h", recommended=profile == TranscriptionProfile.BALANCED,
            warning_key=f'profile_{profile.value}_warning' if 'warning' in config else None))
    return specs


def profile_cards() -> List[ProfileCard]:
    cards = []
    for profile in TranscriptionProfile:
        config = ProfileConfig.get_profile_config(profile)
        cards.append(ProfileCard(
            value=profile.value,
            name_html=f"<b>{tr(f'profile_{profile.value}_name')}</b>",
            description=tr(f'profile_{profile.value}_desc'),
            params=(f"⚙️ Whisper · W:{config['num_workers']} | "
                    f"🎯 B:{config['beam_size']} | "
                    f"⚡ {format_speed(config['speed_factor'])} | "
                    f"✨ {config['quality_percent']:.0f}%"),
            time=f"⏱️ ~{config['time_1h_audio_min']}min/h",
            recommended_badge=tr('recommended') if profile == TranscriptionProfile.BALANCED else None,
            warning=f"⚠️ {tr(f'profile_{profile.value}_warning')}" if 'warning' in config else None,
        ))
    return cards


class TranscriptionSettingsService:
    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------------------------------------------------- motore
    def engine_mode(self) -> str:
        """Modalita' corrente; un valore non valido nel config viene riscritto 'auto' (da Config)."""
        return self._config.get_transcription_engine_mode()

    def set_engine_mode(self, mode) -> None:
        self._config.set_transcription_engine_mode(mode or 'auto')

    # --------------------------------------------------------------------------------------------------- stile dei dialoghi
    def dialogue_style(self) -> bool:
        return bool(self._config.get('dialogue_style_enabled', True))

    def set_dialogue_style(self, enabled: bool) -> None:
        self._config.set('dialogue_style_enabled', bool(enabled))

    # ---------------------------------------------------------------------------------------------------------------- profili
    def current_profile(self) -> str:
        return self._config.get_transcription_profile()

    def select_profile(self, value: str, persist: bool) -> None:
        """In modalita' embed (SettingsDialog) la scelta si salva subito; standalone solo su accept() (a cura di chi chiama)."""
        if persist:
            self._config.set_transcription_profile(value)
