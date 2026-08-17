# -*- coding: utf-8 -*-
"""
Env Check CLI — operazioni ML delle Impostazioni in subprocess isolato.
File: core/env_check_cli.py

Il processo GUI non deve MAI importare torch/pyannote/transformers
(freeze del thread GUI + ~2GB di RAM permanenti). Le due operazioni
"pesanti" del dialog Impostazioni girano qui, in un processo separato
che muore alla fine restituendo tutto all'OS:

    python -m core.env_check_cli diarization-test
    python -m core.env_check_cli llm-download

Stdout: righe di progresso leggibili, riemesse dalla GUI nella label.
Exit code: 0 = ok, 1 = errore, 2 = argomenti invalidi.
Il token HuggingFace viene letto dalla config (come nel resto dell'app).
"""
import sys
import traceback


def _emit(msg: str) -> None:
    print(msg, flush=True)


def diarization_test() -> int:
    """Replica il test pyannote che girava nel thread GUI (translation_model_dialog)."""
    from utils.config import get_config
    token = get_config().get_huggingface_token()
    if not token:
        _emit("❌ Token non configurato. Salvalo prima.")
        return 1

    try:
        import os
        import tempfile
        import warnings

        import numpy as np
        import soundfile as sf
        import torch

        warnings.filterwarnings("ignore", message="torchcodec is not installed")

        _emit("⏳ Caricamento pipeline pyannote (prima volta: download ~1 GB)...")
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=token)
        if torch.cuda.is_available():
            pipeline = pipeline.to(torch.device("cuda"))

        _emit("⏳ Test su audio sintetico...")
        # Audio sintetico: 4 secondi, 2 "parlanti" (toni diversi)
        sr = 16000
        t = np.linspace(0, 4.0, sr * 4, dtype=np.float32)
        audio = np.concatenate([
            0.3 * np.sin(2 * np.pi * 200 * t[:sr * 2]),
            0.3 * np.sin(2 * np.pi * 600 * t[sr * 2:]),
        ])
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name
        sf.write(tmp_path, audio, sr)
        try:
            import torchaudio
            waveform, sample_rate = torchaudio.load(tmp_path)
            output = pipeline({'waveform': waveform, 'sample_rate': sample_rate})
            annotation = getattr(output, 'speaker_diarization', output)
            turns = list(annotation.itertracks(yield_label=True))
        finally:
            os.unlink(tmp_path)

        _emit(f"✅ Modello OK! Trovati {len(turns)} turni sul test audio.")
        _emit("Puoi abilitare la diarization.")
        return 0

    except Exception as e:
        err = str(e)
        if "403" in err or "gated" in err.lower() or "restricted" in err.lower():
            _emit("❌ Accesso negato (403).")
            _emit("Accetta i termini su:")
            _emit("  huggingface.co/pyannote/speaker-diarization-3.1")
            _emit("  huggingface.co/pyannote/segmentation-3.0")
        elif "401" in err or "token" in err.lower():
            _emit("❌ Token non valido o scaduto. "
                  "Controllalo su huggingface.co/settings/tokens")
        else:
            _emit(f"❌ Errore: {err}")
        traceback.print_exc(file=sys.stderr)
        return 1


def llm_download() -> int:
    """Scarica/carica il modello LLM di traduzione in uso.

    Gira in sottoprocesso apposta: la cache su disco resta, mentre la memoria
    occupata dal caricamento muore col processo invece di restare appesa alla
    GUI. Quale modello venga scaricato lo decide `llm_translator_model`.
    """
    from utils.config import get_config

    chiave = get_config().get('llm_translator_model') or 'translategemma-12b'
    _emit(f"Avvio caricamento modello {chiave}...")
    if not get_config().is_huggingface_token_set():
        _emit("Token HuggingFace non rilevato. Tentativo anonimo...")
    _emit("Download in corso (può richiedere alcuni minuti)...")

    try:
        from core.translator import get_translator
        translator = get_translator(model_type='llm')
        if translator is not None:
            _emit("Modello caricato in memoria.")
            return 0
        _emit("❌ Caricamento fallito")
        return 1
    except Exception as e:
        err = str(e)
        if "GatedRepo" in err or "401" in err:
            err = "Errore autenticazione. Token HuggingFace non valido."
        _emit(f"❌ Errore: {err}")
        traceback.print_exc(file=sys.stderr)
        return 1


def main(argv: list) -> int:
    # 'aya-download' resta accettato: se una GUI vecchia resta aperta durante
    # l'aggiornamento, il pulsante continua a funzionare.
    if len(argv) < 2 or argv[1] not in ('diarization-test', 'llm-download',
                                        'aya-download'):
        _emit("Uso: python -m core.env_check_cli diarization-test|llm-download")
        return 2
    if argv[1] == 'diarization-test':
        return diarization_test()
    return llm_download()


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    from pathlib import Path
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    # Niente flash di finestre console dalle librerie (stesso di pipeline_cli)
    from core.pipeline_cli import _suppress_subprocess_windows
    _suppress_subprocess_windows()

    sys.exit(main(sys.argv))
