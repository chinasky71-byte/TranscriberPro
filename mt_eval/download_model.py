"""
Scarica un modello del registro MODEL_SPECS nella cache HuggingFace.

Uso:
    venv\\Scripts\\python mt_eval\\download_model.py aya-expanse-8b

I repo Cohere sono gated: serve il token HuggingFace salvato in
~/.transcriberpro/config.json e l'accettazione della licenza sulla pagina del
modello.
"""

import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.llm_subtitle_translator.engine import MODEL_SPECS  # noqa: E402

# Solo i pesi safetensors + i file di config/tokenizer: senza questo filtro si
# scaricherebbero anche i .bin, raddoppiando il transfer.
#
# `*.jinja` NON è opzionale: i modelli TranslateGemma tengono il chat template
# in `chat_template.jinja`, e senza quel file il processor si carica ma non sa
# costruire il prompt.
ALLOW = ["*.safetensors", "*.json", "*.model", "*.txt", "*.md", "*.jinja"]
IGNORE = ["*.bin", "*.pth", "*.h5", "*.msgpack", "original/*"]


def main():
    if len(sys.argv) < 2:
        sys.exit(f"Uso: download_model.py <{'|'.join(MODEL_SPECS)}>")
    key = sys.argv[1]
    if key not in MODEL_SPECS:
        sys.exit(f"Modello sconosciuto: {key}. "
                 f"Disponibili: {', '.join(MODEL_SPECS)}")

    spec = MODEL_SPECS[key]

    token = None
    try:
        from utils.config import get_config
        token = get_config().get_huggingface_token() or None
    except Exception as exc:
        print(f"Token non recuperato dalla config: {exc}")

    if spec.gated and not token:
        sys.exit("Repo gated e nessun token HuggingFace disponibile.")

    from huggingface_hub import snapshot_download

    print(f"Download {spec.label}  ({spec.model_id})")
    if spec.notes:
        print(f"  {spec.notes}")
    print(f"  gated: {spec.gated} | token: {'sì' if token else 'no'}\n")

    t0 = time.time()
    path = snapshot_download(
        repo_id=spec.model_id,
        token=token,
        allow_patterns=ALLOW,
        ignore_patterns=IGNORE,
        max_workers=4,
    )
    print(f"\nCompletato in {(time.time() - t0) / 60:.1f} minuti")
    print(f"Percorso: {path}")


if __name__ == "__main__":
    main()
