# -*- coding: utf-8 -*-
"""Impostazioni del motore di traduzione, delle credenziali e della diarizzazione, senza Qt.

Trasposizione fedele della logica di gui/translation_model_dialog.py: scelta del modello (con i controlli di prerequisiti), percorsi del
modello NLLB fine-tuned e dell'LLM con la loro validazione, chiavi API e token con validazione, parametri NLLB, diarizzazione, genere,
forza-audio. Il download del modello e il test di pyannote usano core/jobs/env_cli.py. Il dialogo resta la vista (dialoghi, stati, colori)."""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

MODEL_IDS = ('nllb', 'nllb_finetuned', 'llm', 'claude', 'opensubtitles', 'openai')
EMBED_MODEL_IDS = frozenset(MODEL_IDS)

DISPLAY_NAMES = {
    'nllb': 'NLLB-200',
    'nllb_finetuned': 'NLLB-200 Fine-Tuned (Plex)',
    'llm': 'TranslateGemma_finetuned',
    'claude': 'Claude API',
    'opensubtitles': 'OpenSubtitles AI',
    'openai': 'OpenAI GPT',
}

OPENAI_MODELS = ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo']
DEFAULT_DIARIZATION_MODEL = 'pyannote/speaker-diarization-3.1'


@dataclass(frozen=True)
class SelectionCheck:
    """Prerequisito mancante per il modello scelto: la vista chiede conferma con le chiavi tr() date."""
    title_key: str
    message_key: str
    warn_key: Optional[str]      # avviso mostrato prima di salvare comunque (None = nessuno)
    stay_on_yes: bool            # True: "Si'" = resta nel dialogo; False: "No" = resta nel dialogo


@dataclass(frozen=True)
class FolderCheck:
    kind: str                    # 'ok' | 'empty' | 'missing' | 'invalid'


@dataclass(frozen=True)
class KeyResult:
    kind: str                    # 'ok' | 'empty' | 'invalid'
    error: str = ''


class TranslationModelService:
    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------------------------------------------ modello scelto
    def current_model(self) -> str:
        return self._config.get_translation_model()

    def select_embedded(self, name: str) -> bool:
        """Salva subito la scelta (modalita' embed). False se `name` non e' un modello noto."""
        if name in EMBED_MODEL_IDS:
            self._config.set_translation_model(name)
            return True
        return False

    def selection_check(self, model: str) -> Optional[SelectionCheck]:
        c = self._config
        if model == 'claude' and not c.is_claude_api_key_set():
            return SelectionCheck('tmd_api_key_missing_title', 'tmd_claude_key_missing_ask', 'tmd_claude_needs_key', True)
        if model == 'nllb_finetuned' and not c.is_nllb_finetuned_configured():
            return SelectionCheck('tmd_model_not_configured_title', 'tmd_ft_path_missing_ask', 'tmd_ft_needs_path', True)
        if model == 'opensubtitles' and not c.is_opensubtitles_rest_configured():
            return SelectionCheck('tmd_creds_missing_title', 'tmd_os_creds_missing_ask', None, False)
        if model == 'openai' and not c.is_openai_api_key_set():
            return SelectionCheck('tmd_api_key_missing_title', 'tmd_openai_key_missing_ask', 'tmd_openai_needs_key', True)
        return None

    def commit_selection(self, model: str) -> str:
        """Salva il modello scelto e ritorna il nome da mostrare."""
        self._config.set_translation_model(model)
        return DISPLAY_NAMES.get(model, model.upper())

    # --------------------------------------------------------------------------------------------------------------- percorsi
    @staticmethod
    def check_folder(path: str) -> FolderCheck:
        """Cartella di un modello: deve esistere e contenere config.json."""
        p = Path(path)
        if not p.exists():
            return FolderCheck('missing')
        if not (p / 'config.json').exists():
            return FolderCheck('invalid')
        return FolderCheck('ok')

    def nllb_ft_path(self) -> str:
        return self._config.get_nllb_finetuned_model_path()

    def nllb_ft_configured(self) -> bool:
        return self._config.is_nllb_finetuned_configured()

    def save_nllb_ft_path(self, text: str) -> Tuple[FolderCheck, str]:
        """(esito, percorso ripulito). Vuoto/inesistente/senza config.json: non salva."""
        path = text.strip()
        if not path:
            return FolderCheck('empty'), path
        chk = self.check_folder(path)
        if chk.kind == 'ok':
            self._config.set_nllb_finetuned_model_path(path)
        return chk, path

    def llm_path(self) -> str:
        return self._config.get_llm_translator_model_path()

    def save_llm_path(self, text: str) -> Tuple[FolderCheck, str]:
        """Come sopra, ma il percorso vuoto e' valido (= predefinito) e si salva."""
        path = text.strip()
        if path:
            chk = self.check_folder(path)
            if chk.kind != 'ok':
                return chk, path
        self._config.set_llm_translator_model_path(path)
        return FolderCheck('ok'), path

    # ------------------------------------------------------------------------------------------------------------ parametri NLLB
    def nllb_beams(self) -> int:
        return self._config.get_nllb_num_beams()

    def set_nllb_beams(self, value: int) -> None:
        self._config.set_nllb_num_beams(value)

    # ---------------------------------------------------------------------------------------------------------- chiavi e token
    def hf_token(self) -> str:
        return self._config.get_huggingface_token()

    def hf_token_set(self) -> bool:
        return self._config.is_huggingface_token_set()

    def save_hf_token(self, text: str) -> Tuple[KeyResult, str]:
        token = text.strip()
        if not token:
            return KeyResult('empty'), token
        ok, error = self._config.validate_huggingface_token(token)
        if not ok:
            return KeyResult('invalid', error), token
        self._config.set_huggingface_token(token)
        return KeyResult('ok'), token

    def claude_key(self) -> str:
        return self._config.get_claude_api_key()

    def claude_key_set(self) -> bool:
        return self._config.is_claude_api_key_set()

    def save_claude_key(self, text: str) -> KeyResult:
        key = text.strip()
        if not key:
            return KeyResult('empty')
        ok, error = self._config.validate_claude_api_key(key)
        if not ok:
            return KeyResult('invalid', error)
        self._config.set_claude_api_key(key)
        return KeyResult('ok')

    def openai_key(self) -> str:
        return self._config.get_openai_api_key()

    def openai_model(self) -> str:
        return self._config.get_openai_model()

    def openai_key_set(self) -> bool:
        return self._config.is_openai_api_key_set()

    def save_openai(self, text: str, model: str) -> KeyResult:
        key = text.strip()
        ok, error = self._config.validate_openai_api_key(key)
        if not ok:
            return KeyResult('invalid', error)
        self._config.set_openai_api_key(key)
        self._config.set_openai_model(model)
        return KeyResult('ok')

    def opensubtitles_rest_configured(self) -> bool:
        return self._config.is_opensubtitles_rest_configured()

    # ------------------------------------------------------------------------------------------- diarizzazione, genere, audio
    def diarization_urls(self) -> str:
        """URL dei repo HF da accettare per il modello di diarizzazione configurato."""
        model = self._config.get('diarization_model', DEFAULT_DIARIZATION_MODEL)
        urls = f"  • huggingface.co/{model}"
        if model == DEFAULT_DIARIZATION_MODEL:
            urls += "\n  • huggingface.co/pyannote/segmentation-3.0"
        return urls

    def flag(self, key: str, default: bool):
        return self._config.get(key, default)

    def set_flag(self, key: str, value) -> None:
        self._config.set(key, value)

    def gender_prerequisites(self, project_root: Path) -> List[str]:
        """Chiavi tr() dei prerequisiti mancanti del genere v2 (venv NLP e token HF); lista vuota = tutto ok."""
        from utils.platform_compat import venv_python
        cands = [self._config.get('gender_selector_python', ''),
                 venv_python(project_root / 'venv_nlp'),
                 venv_python(project_root / 'gender_eval' / '.venv_spacy')]
        nlp_ok = any(p and Path(p).exists() for p in cands)
        hf_ok = bool(self._config.get('huggingface_token', ''))
        missing = []
        if not nlp_ok:
            missing.append('tmd_gender_missing_nlp')
        if not hf_ok:
            missing.append('tmd_gender_missing_hf')
        return missing
