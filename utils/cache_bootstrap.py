"""
Cache bootstrap - redireziona cache modelli AI nella cartella progetto.

DEVE essere importato PRIMA di torch, transformers, huggingface_hub,
demucs, pyannote, qwen3. Sets HF_HOME, HUGGINGFACE_HUB_CACHE,
TORCH_HOME a sottocartelle di models/.cache/.
(TRANSFORMERS_CACHE non va impostato: deprecato — transformers usa HF_HOME
e impostarlo genera un FutureWarning in ogni processo.)
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# TP_MODELS_DIR lets containers mount the model cache outside the repository.
MODELS_ROOT = (Path(os.environ['TP_MODELS_DIR']).expanduser()
               if os.environ.get('TP_MODELS_DIR') else PROJECT_ROOT / 'models')
CACHE_ROOT = MODELS_ROOT / '.cache'

HF_CACHE = CACHE_ROOT / 'huggingface'
TORCH_CACHE = CACHE_ROOT / 'torch'

(HF_CACHE / 'hub').mkdir(parents=True, exist_ok=True)
(TORCH_CACHE / 'hub' / 'checkpoints').mkdir(parents=True, exist_ok=True)

os.environ.setdefault('HF_HOME', str(HF_CACHE))
os.environ.setdefault('HUGGINGFACE_HUB_CACHE', str(HF_CACHE / 'hub'))
os.environ.setdefault('TORCH_HOME', str(TORCH_CACHE))

HF_HUB_CACHE_DIR = str(HF_CACHE / 'hub')
TORCH_HUB_CACHE_DIR = str(TORCH_CACHE / 'hub' / 'checkpoints')
