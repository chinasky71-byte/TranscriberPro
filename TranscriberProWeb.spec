# -*- mode: python ; coding: utf-8 -*-
# Pacchetto PyInstaller della web UI (cartella `tpweb/`): avvia `main.py --ui web`. NON ancora costruito ne' provato: il giro vero
# (build + avvio su Windows) e' un compito della sessione locale. `test_tpweb_packaging.py` controlla che i file elencati esistano.
#   pyinstaller TranscriberProWeb.spec
from PyInstaller.utils.hooks import collect_submodules

# Moduli che uvicorn/starlette/anyio caricano per nome (PyInstaller non li vede): il guscio nativo e' opzionale, quindi `webview` solo se c'e'.
hidden = (collect_submodules('uvicorn') + collect_submodules('anyio') + collect_submodules('starlette') + collect_submodules('fastapi')
          + ['h11', 'httptools', 'websockets', 'pydantic', 'multipart', 'tpweb.__main__'])
try:
    hidden += collect_submodules('webview')
except Exception:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('tpweb/static', 'tpweb/static'), ('assets', 'assets'), ('core', 'core'), ('utils', 'utils')],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas',
              # P14 (Windows): l'exe pesava ~3 GB perche' seguiva gli import pesanti del venv, e pyi_rth_pkgres falliva con
              # `No module named 'pkg_resources.extern'`. La web UI non li usa nel proprio processo: l'elaborazione gira nel sottoprocesso.
              'pkg_resources', 'setuptools', 'torch', 'torchaudio', 'torchvision', 'tensorflow', 'transformers', 'faster_whisper',
              'ctranslate2', 'onnxruntime', 'bitsandbytes', 'accelerate', 'peft', 'triton', 'scipy', 'numba', 'llvmlite', 'sklearn', 'cv2', 'PySide6', 'PyQt5', 'PyQt6', 'tkinter'],
    noarchive=False,
    optimize=0,
)
# P16 (Windows): `excludes` non bastava, le DLL CUDA/torch/bitsandbytes (~1,5 GB) entravano dai loro hook. Filtro sul percorso di destinazione.
HEAVY = ('torch', 'nvidia', 'bitsandbytes', 'libbitsandbytes', 'cublas', 'cusparse', 'cudnn', 'cufft', 'curand', 'cusolver', 'nvjitlink', 'nvrtc',
         'nvtoolsext', 'cudart', 'triton', 'onnxruntime')


def drop_heavy(toc):
    return [t for t in toc if not any(h in str(t[0]).lower().replace('\\', '/').split('/')[0] or h in str(t[0]).lower().replace('\\', '/').rsplit('/', 1)[-1] for h in HEAVY)]


a.binaries = drop_heavy(a.binaries)
a.datas = drop_heavy(a.datas)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TranscriberProWeb',
    icon='transcriptor.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
