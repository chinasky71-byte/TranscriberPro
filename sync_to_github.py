"""
Sync Transcriber_Pro → TranscriberPro_GitHub
Esclude file sensibili, test, cache, modelli.
"""

import os
import shutil
from pathlib import Path

SRC  = Path(r"C:\Users\fran_\Desktop\Transcriber_Pro")
DST  = Path(r"C:\Users\fran_\Desktop\TranscriberPro_GitHub")

# Pattern nome file da escludere
EXCLUDE_FILES = {
    "README.md",           # GitHub ha il suo
    "requirements_utf8.txt",
    "omdb_api.txt",
    ".gitignore",          # GitHub ha il suo
}

EXCLUDE_SUFFIXES = {".odt", ".docx", ".pyc", ".pyo", ".srt", ".txt"}

EXCLUDE_PREFIXES = ("test_", "fix_", "debug_", "sync_to_github", "speed_fix")

EXCLUDE_NAME_CONTAINS = ("token", "api_key", "password", "secret", "credential", "api key")

# Cartelle da escludere (relative a SRC)
EXCLUDE_DIRS = {
    "venv", "__pycache__", ".claude", "models",
    "NLLB_Tranined", ".git", "memory",
}

copied = []
skipped = []

def should_skip_file(rel: Path) -> bool:
    name = rel.name
    # File esatti
    if name in EXCLUDE_FILES:
        return True
    # Suffisso
    if rel.suffix in EXCLUDE_SUFFIXES:
        return True
    # Prefisso
    if any(name.startswith(p) for p in EXCLUDE_PREFIXES):
        return True
    # Contiene parola sensibile
    if any(kw in name.lower() for kw in EXCLUDE_NAME_CONTAINS):
        return True
    return False

def should_skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS

def sync():
    for root, dirs, files in os.walk(SRC):
        root_path = Path(root)
        rel_root = root_path.relative_to(SRC)

        # Filtra cartelle escluse (in-place, evita discesa)
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]

        for fname in files:
            rel = rel_root / fname
            if should_skip_file(rel):
                skipped.append(str(rel))
                continue

            src_file = SRC / rel
            dst_file = DST / rel

            # Crea directory destinazione se mancante
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            # Copia solo se diverso (dimensione o mtime)
            if dst_file.exists():
                src_stat = src_file.stat()
                dst_stat = dst_file.stat()
                if (src_stat.st_size == dst_stat.st_size and
                        abs(src_stat.st_mtime - dst_stat.st_mtime) < 2):
                    continue  # uguale, salta

            shutil.copy2(src_file, dst_file)
            copied.append(str(rel))
            print(f"  COPIATO: {rel}")

    print(f"\n✅ File copiati: {len(copied)}")
    print(f"   File saltati: {len(skipped)}")

if __name__ == "__main__":
    print(f"Sync: {SRC} → {DST}\n")
    sync()
    print("\nSync completata.")
