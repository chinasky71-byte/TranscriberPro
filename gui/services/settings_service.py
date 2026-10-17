# -*- coding: utf-8 -*-
"""
SettingsService: impostazioni lette/scritte dalla finestra principale (senza widget).

  - snapshot prima/dopo il SettingsDialog e righe di log sulle differenze (motore, modello traduzione)
  - etichetta breve del motore di trascrizione, selezione del profilo
  - stato dell'interfaccia persistito: dimensioni splitter, card aperte, ultima cartella usata
"""
from dataclasses import dataclass
from typing import List, Optional

from utils.translations import tr


@dataclass(frozen=True)
class SettingsSnapshot:
    engine_mode: str
    translation_model: str
    upload_enabled: bool


class SettingsService:
    # Etichetta BREVE (tessera Engine e righe di log dopo il dialog). Non e' ENGINE_MODE_LABELS di
    # utils.engine_labels (usata solo dalla riga di avvio: 'Canary-Qwen'): non unificare.
    ENGINE_LABELS = {
        'auto': 'Auto',
        'canary': 'Canary',
        'qwen3': 'Qwen3-ASR',
        'faster-whisper': 'Faster-Whisper',
    }

    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------ dialog Impostazioni
    def engine_mode_label(self, mode: Optional[str] = None) -> str:
        """Etichetta breve della modalita' engine (quella corrente se `mode` e' None)."""
        if mode is None:
            mode = self._config.get_transcription_engine_mode()
        return self.ENGINE_LABELS.get(mode, 'Auto')

    def snapshot(self) -> SettingsSnapshot:
        c = self._config
        return SettingsSnapshot(
            engine_mode=c.get_transcription_engine_mode(),
            translation_model=c.get_translation_model(),
            upload_enabled=c.get('opensubtitles_upload_enabled', True),
        )

    def reload_from_config(self) -> SettingsSnapshot:
        """Rilegge dal config i valori che la finestra mostra (dopo che il dialog li ha cambiati)."""
        c = self._config
        model = c.get_translation_model()
        engine = c.get_transcription_engine_mode()
        upload = c.get('opensubtitles_upload_enabled', True)
        return SettingsSnapshot(engine_mode=engine, translation_model=model, upload_enabled=upload)

    def diff_messages(self, before: SettingsSnapshot, after: SettingsSnapshot) -> List[str]:
        """Righe di log per le impostazioni cambiate, nell'ordine storico: motore, poi modello."""
        out = []
        if after.engine_mode != before.engine_mode:
            out.append(f"⚙️ Motore di trascrizione: {self.engine_mode_label(after.engine_mode)}")
        if after.translation_model != before.translation_model:
            out.append(tr('translation_model_changed').format(model=after.translation_model))
        return out

    # ------------------------------------------------------------------ profilo
    def current_profile(self) -> str:
        return self._config.get_transcription_profile()

    def select_profile(self, profile_key: str) -> str:
        """Salva il profilo scelto e restituisce la riga di log da mostrare."""
        self._config.set_transcription_profile(profile_key)
        return f"⚙️ Profilo selezionato: {tr(f'profile_{profile_key}_name')}"

    # ------------------------------------------------------------------ stato interfaccia
    def main_splitter_sizes(self) -> Optional[list]:
        """Dimensioni salvate delle 3 colonne, None se assenti o non valide."""
        saved = self._config.get('ui_splitter_sizes', None)
        if isinstance(saved, list) and len(saved) == 3 and all(
            isinstance(x, int) and x > 0 for x in saved
        ):
            return saved
        return None

    def save_main_splitter_sizes(self, sizes):
        if all(s > 0 for s in sizes):
            self._config.set('ui_splitter_sizes', list(sizes))

    def center_split_sizes(self) -> Optional[list]:
        saved = self._config.get('ui_center_split', None)
        if isinstance(saved, list) and len(saved) == 2:
            return saved
        return None

    def save_center_split_sizes(self, sizes):
        self._config.set('ui_center_split', sizes)

    def scanner_card_open(self) -> bool:
        return bool(self._config.get('ui_scanner_card_open', False))

    def set_scanner_card_open(self, opened: bool):
        self._config.set('ui_scanner_card_open', opened)

    def last_input_folder(self) -> str:
        return self._config.get('last_input_folder', '')

    def set_last_input_folder(self, folder: str):
        self._config.set('last_input_folder', folder)
