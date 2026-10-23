# -*- coding: utf-8 -*-
"""
Controllo dell'ambiente Python di Transcriber Pro (usato da install.ps1 a fine installazione).

Verifica, con il python del venv principale:
  - le librerie principali si importano (nell'ordine dell'app: onnxruntime PRIMA di PyQt6, torch prima di ctranslate2);
  - CUDA e' visibile da torch e da ctranslate2 (bundled: non serve il CUDA Toolkit di sistema);
  - i binari esterni sono nel PATH (ffmpeg, ffprobe, tesseract con ita/eng, mkvextract).

Uso:  venv\\Scripts\\python.exe scripts_manutenzione\\selfcheck_env.py [--json] [--no-gpu]
Exit code: 0 = tutto il necessario funziona, 1 = manca qualcosa di necessario (i "facoltativi" non contano).
Non carica modelli. torch crea il proprio contesto CUDA (qualche centinaio di MB di VRAM per pochi secondi) per leggere
le proprieta' della GPU; con --no-gpu non tocca la GPU. llama_cpp si prova in un processo NUOVO, senza torch ne' PyQt6
gia' caricati, per scoprire i problemi di DLL che l'import di torch nasconderebbe.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
results = []   # (categoria, nome, esito True/False/None, dettaglio, necessario)


def add(cat, name, ok, detail='', required=True):
    results.append((cat, name, ok, detail, required))


def try_import(name, required=True, attr=None):
    try:
        mod = __import__(name, fromlist=['_'])
        ver = getattr(mod, attr or '__version__', '')
        add('python', name, True, str(ver), required)
        return mod
    except Exception as e:
        add('python', name, False, f'{type(e).__name__}: {e}'[:160], required)
        return None


def run_tool(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
        return r.returncode, (r.stdout or r.stderr or '').strip()
    except Exception as e:
        return -1, str(e)


def check_llama():
    """llama_cpp in un processo pulito: usa utils/cuda_dll_path come l'app (torch\\lib nel PATH, torch NON importato)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from utils.cuda_dll_path import ensure_torch_lib_on_path\n"
            "ensure_torch_lib_on_path()\n"
            "import llama_cpp; print(llama_cpp.__version__, 'torch importato:', 'torch' in sys.modules)" % root)
    rc, out = run_tool([sys.executable, '-c', code])
    add('python', 'llama_cpp (processo pulito)', rc == 0, out.splitlines()[-1] if out else '', False)


def main():
    want_json = '--json' in sys.argv
    check_gpu = '--no-gpu' not in sys.argv

    is_win = os.name == 'nt'
    if is_win:
        add('sistema', 'Python', sys.version_info[:2] == (3, 11), platform.python_version() + ' (serve 3.11)')
        add('sistema', 'Windows', True, platform.platform(), True)
    else:   # Linux/macOS: 3.11 provato dall'autore; 3.12 provato il 23/10/2026 su Ubuntu 24.04 (installazione, selfcheck, test, avvio offscreen; no GPU)
        add('sistema', 'Python', sys.version_info[:2] in ((3, 11), (3, 12)), platform.python_version() + ' (serve 3.11 o 3.12)')
        add('sistema', platform.system(), True, platform.platform(), True)

    # ordine dell'app (main.py): onnxruntime prima di PyQt6
    ort = try_import('onnxruntime')
    if ort is not None:
        add('python', 'onnxruntime provider', True, ','.join(ort.get_available_providers()), False)
    try_import('PyQt6.QtCore', attr='PYQT_VERSION_STR')
    torch = try_import('torch')
    if torch is not None and check_gpu:
        ok = bool(torch.cuda.is_available())
        detail = ''
        if ok:
            p = torch.cuda.get_device_properties(0)
            detail = f'{p.name}, {p.total_memory / 1e9:.1f} GB, CUDA runtime {torch.version.cuda}'
        add('gpu', 'torch.cuda', ok, detail or 'CUDA non disponibile (driver NVIDIA aggiornato? torch +cu126?)')
    ct2 = try_import('ctranslate2')
    if ct2 is not None and check_gpu:
        try:
            n = ct2.get_cuda_device_count()
            add('gpu', 'ctranslate2 CUDA', n > 0, f'{n} dispositivo/i')
        except Exception as e:
            add('gpu', 'ctranslate2 CUDA', False, f'{type(e).__name__}: {e}'[:160])
    try:
        import pkg_resources  # noqa: F401
        add('python', 'pkg_resources', True, 'presente (ctranslate2 4.6.0 lo importa su Windows)')
    except Exception as e:
        add('python', 'pkg_resources', False, f'MANCA: {e}. Reinstallare setuptools==70.3.0')
    for n in ('faster_whisper', 'whisperx', 'demucs', 'transformers', 'sentencepiece', 'huggingface_hub', 'peft',
              'accelerate', 'librosa', 'soundfile', 'torchaudio', 'cv2', 'pytesseract', 'psutil', 'requests', 'numpy',
              'PIL'):
        try_import(n)
    for n in ('pyannote.audio', 'qwen_asr', 'anthropic', 'openai', 'imdb', 'bitsandbytes'):
        try_import(n, required=(n in ('pyannote.audio',)))
    check_llama()
    if torch is not None:
        try:
            import torchaudio
            add('python', 'torchaudio/torch versione', torchaudio.__version__.split('+')[0] == torch.__version__.split('+')[0],
                f'torch {torch.__version__} / torchaudio {torchaudio.__version__}')
        except Exception:
            pass

    # binari esterni: si controlla quello che l'APP vede davvero (PATH, percorso nelle Impostazioni, shim di scoop)
    cfg = {}
    try:
        with open(os.path.join(os.path.expanduser('~'), '.transcriberpro', 'config.json'), encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        pass
    scoop = os.path.expanduser(r'~\scoop\shims') if is_win else ''
    for exe, req, hint, extra in (
            ('ffmpeg', True, 'winget install Gyan.FFmpeg' if is_win else 'installa ffmpeg dal gestore pacchetti', []),
            ('ffprobe', True, 'incluso in FFmpeg', []),
            ('tesseract', True, 'winget install UB-Mannheim.TesseractOCR' if is_win else 'installa tesseract-ocr dal gestore pacchetti',
             [cfg.get('ocr_tesseract_path') or '', os.path.join(scoop, 'tesseract.exe') if scoop else '']),
            ('mkvextract', False, ('winget install MoritzBunkus.MKVToolNix' if is_win else 'installa mkvtoolnix dal gestore pacchetti') + ' (solo per i VOBSUB)',
             [os.path.join(scoop, 'mkvextract.exe') if scoop else ''])):
        path = shutil.which(exe)
        if not path:
            for cand in extra:
                if cand and os.path.exists(cand):
                    path = cand
                    break
        if not path:
            try:    # stessa ricerca dell'app: PATH, poi cartelle standard di installazione
                root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if root not in sys.path:
                    sys.path.insert(0, root)
                from utils.platform_compat import find_tool
                path = find_tool(exe)
            except Exception:
                pass
        detail = path or f'non trovato ({hint})'
        add('esterni', exe, bool(path), detail, req)
        if exe == 'tesseract' and path:
            rc, out = run_tool([path, '--list-langs'])
            langs = set(out.split()) if rc == 0 else set()
            add('esterni', 'tesseract ita+eng', {'ita', 'eng'} <= langs,
                'ok' if {'ita', 'eng'} <= langs else 'mancano ita.traineddata / eng.traineddata (tessdata_best)', True)
    if is_win:
        add('esterni', 'Visual C++ Redistributable', os.path.exists(os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32', 'msvcp140.dll')),
            'MSVCP140.dll (winget install Microsoft.VCRedist.2015+.x64)', True)

    # stampa
    if want_json:
        print(json.dumps([dict(zip(('cat', 'name', 'ok', 'detail', 'required'), r)) for r in results], ensure_ascii=False))
    else:
        cur = None
        order = {'sistema': 0, 'python': 1, 'gpu': 2, 'esterni': 3}
        for cat, name, ok, detail, req in sorted(results, key=lambda r: order.get(r[0], 9)):
            if cat != cur:
                print(f'\n[{cat}]')
                cur = cat
            mark = 'OK ' if ok else ('-- ' if not req else 'KO ')
            print(f'  {mark} {name:28s} {detail}')
    bad = [r for r in results if not r[2] and r[4]]
    if not want_json:
        print('\n' + ('RISULTATO: tutto il necessario funziona.' if not bad else
                      f'RISULTATO: {len(bad)} elemento/i necessario/i mancante/i: ' + ', '.join(r[1] for r in bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
