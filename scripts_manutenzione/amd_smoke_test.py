# -*- coding: utf-8 -*-
"""
Test di fumo per macchine con GPU AMD (Linux, ROCm o Vulkan). NON PROVATO SU HARDWARE AMD.

Raccoglie in un solo file di testo, da rimandare agli sviluppatori:
  - il rapporto di utils/gpu_detect.py (--json);
  - famiglia della scheda (RDNA1..4, CDNA), percorso scelto (ROCm / ROCm con override RDNA2 / Vulkan+CPU) e se
    HSA_OVERRIDE_GFX_VERSION e' stata applicata alle prove (solo ai sottoprocessi, mai se l'hai gia' impostata tu);
  - versioni di torch/HIP e un piccolo calcolo su GPU;
  - ctranslate2: versione e compute types per 'cuda' (su ROCm la ruota ctranslate2 usa questo nome);
  - llama_cpp (ruota Vulkan): carica un GGUF piccolo e genera 5 token (solo con --gguf PERCORSO);
  - facoltativo (--whisper): trascrizione di ~10 secondi di silenzio/tono con Whisper 'tiny' (scarica ~75 MB).

Uso:  venv/bin/python scripts_manutenzione/amd_smoke_test.py [--gguf modello.gguf] [--whisper] [--out amd_smoke_report.txt]
Ogni componente mancante o in errore finisce nel rapporto come SKIP/FAIL senza fermare gli altri. Ogni prova rischiosa
(torch su GPU, ctranslate2, llama_cpp, Whisper) gira in un processo separato con timeout: un crash nativo (std::abort,
segfault) viene registrato invece di chiudere lo script. Il rapporto non contiene nome utente, nome host ne' percorsi
della home (sostituiti da ~).
Exit code: 0 sempre se il rapporto e' stato scritto.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TIMEOUT_S = 180

_TORCH = r'''
import json, time
import torch
r = {"torch": torch.__version__, "hip": getattr(torch.version, "hip", None), "cuda_build": torch.version.cuda,
     "cuda_available": bool(torch.cuda.is_available())}
if r["cuda_available"]:
    r["device"] = torch.cuda.get_device_name(0)
    t = time.time()
    a = torch.randn(1024, 1024, device="cuda"); b = torch.randn(1024, 1024, device="cuda")
    c = (a @ b).sum().item(); torch.cuda.synchronize()
    r["matmul_ok"] = c == c
    r["matmul_s"] = round(time.time() - t, 3)
print(json.dumps(r))
'''

_CT2 = r'''
import json
import torch  # prima di ctranslate2, come nell'app
import ctranslate2 as ct2
r = {"ctranslate2": ct2.__version__, "cuda_devices": ct2.get_cuda_device_count()}
try:
    r["compute_types_cuda"] = sorted(ct2.get_supported_compute_types("cuda"))
except Exception as e:
    r["compute_types_cuda"] = "%s: %s" % (type(e).__name__, str(e)[:120])
print(json.dumps(r))
'''

_LLAMA = r'''
import json, sys
import llama_cpp
r = {"llama_cpp": llama_cpp.__version__, "gpu_offload": bool(llama_cpp.llama_supports_gpu_offload())}
if len(sys.argv) > 1:
    m = llama_cpp.Llama(model_path=sys.argv[1], n_gpu_layers=-1, n_ctx=256, verbose=False)
    out = m("Ciao", max_tokens=5)
    r["generated"] = out["choices"][0]["text"][:40]
print(json.dumps(r))
'''

_WHISPER = r'''
import json, time, wave, struct, math, tempfile, os
import torch  # prima di ctranslate2
from faster_whisper import WhisperModel
p = os.path.join(tempfile.mkdtemp(), "t.wav")
with wave.open(p, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * i / 16000))) for i in range(16000 * 10)))
t = time.time()
m = WhisperModel("tiny", device="cuda", compute_type="float16")
segs, info = m.transcribe(p)
n = len(list(segs))
print(json.dumps({"whisper_tiny_cuda": "ok", "segments": n, "seconds": round(time.time() - t, 2)}))
'''


def anonymize(text):
    home = os.path.expanduser('~')
    if home and home != '/':
        text = text.replace(home, '~')
    for v in (os.environ.get('USER'), os.environ.get('LOGNAME'), platform.node()):
        if v and len(v) > 2:
            text = re.sub(r'\b' + re.escape(v) + r'\b', '<anon>', text)
    return text


CHILD_ENV = None        # ambiente dei sottoprocessi di prova (con l'eventuale override AMD); None = quello corrente


def run_py(code, args=(), timeout=TIMEOUT_S):
    """Esegue `code` in un processo nuovo. Ritorna (esito 'OK'|'FAIL'|'SKIP', testo)."""
    try:
        p = subprocess.run([sys.executable, '-c', code, *args], capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir(),
                           env=CHILD_ENV)
    except subprocess.TimeoutExpired:
        return 'FAIL', 'timeout dopo %d s' % timeout
    except Exception as e:
        return 'FAIL', '%s: %s' % (type(e).__name__, e)
    out = (p.stdout or '').strip().splitlines()
    last = out[-1] if out else ''
    if p.returncode == 0 and last.startswith('{'):
        return 'OK', last
    err = (p.stderr or '').strip().splitlines()
    if 'ModuleNotFoundError' in (p.stderr or '') or 'ImportError' in (p.stderr or ''):
        return 'SKIP', (err[-1] if err else 'modulo mancante')[:300]
    sig = ' (segnale %d: crash nativo)' % -p.returncode if p.returncode < 0 else ''
    return 'FAIL', ('codice %d%s; %s' % (p.returncode, sig, err[-1] if err else ''))[:400]


def gpu_detect_section():
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'utils', 'gpu_detect.py'), '--json'], capture_output=True, text=True, timeout=60)
        try:
            return 'OK', json.dumps(json.loads(p.stdout), indent=2)
        except Exception:
            return 'FAIL', (p.stdout + p.stderr)[:1500]
    except Exception as e:
        return 'FAIL', '%s: %s' % (type(e).__name__, e)


def amd_family_section():
    """Famiglia, percorso scelto e override. Imposta CHILD_ENV (override solo per i sottoprocessi di prova, come fa l'app)."""
    global CHILD_ENV
    try:
        from utils import gpu_detect as gd
        rep = gd.detect_gpus(force=True)
        plan = gd.amd_runtime_plan(rep)
        env = os.environ.copy()
        gd.apply_subprocess_env(env)
        before, after = os.environ.get(gd.HSA_OVERRIDE_VAR), env.get(gd.HSA_OVERRIDE_VAR)
        CHILD_ENV = env
        applied = bool(after) and after != before
        if applied:
            ovr = 'APPLICATO (%s=%s, solo ai sottoprocessi di prova)' % (gd.HSA_OVERRIDE_VAR, after)
        elif before:
            ovr = 'NON applicato: %s=%s gia\' impostata dall\'utente, non toccata' % (gd.HSA_OVERRIDE_VAR, before)
        else:
            ovr = 'non applicato (non serve per questa scheda)'
        lines = ['gfx: %s' % (plan['gfx'] or 'sconosciuto'), 'famiglia: %s' % (plan['amd_family'] or 'nessuna GPU AMD'),
                 'supporto ROCm: %s' % (plan['rocm_support'] or 'n/d'), 'percorso scelto: %s' % (plan['path'] or 'nessuno'),
                 'override HSA: %s' % ovr, 'nota: %s' % plan['message']]
        if plan.get('override_source'):
            lines.append('fonte override: %s' % plan['override_source'])
        return 'OK', '\n'.join(lines)
    except Exception as e:
        return 'FAIL', '%s: %s' % (type(e).__name__, e)


def system_section():
    lines = ['python: %s' % sys.version.split()[0], 'sistema: %s %s' % (platform.system(), platform.release()), 'macchina: %s' % platform.machine()]
    for dev in ('/dev/kfd', '/dev/dri'):
        lines.append('%s: %s' % (dev, 'presente' if os.path.exists(dev) else 'assente'))
    lines.append('kfd leggibile/scrivibile: %s' % (os.access('/dev/kfd', os.R_OK | os.W_OK) if os.path.exists('/dev/kfd') else 'n/d'))
    try:
        import grp
        names = {grp.getgrgid(g).gr_name for g in os.getgroups()}
        lines.append('gruppi render/video: %s' % (', '.join(sorted(names & {'render', 'video'})) or 'nessuno'))
    except Exception:
        pass
    for k in ('HSA_OVERRIDE_GFX_VERSION', 'HIP_VISIBLE_DEVICES', 'ROCR_VISIBLE_DEVICES', 'GGML_VK_VISIBLE_DEVICES', 'TP_GPU_FORCE_BACKEND'):
        if os.environ.get(k):
            lines.append('%s=%s' % (k, os.environ[k]))
    return 'OK', '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--gguf', help='GGUF piccolo per la prova di llama_cpp (5 token)')
    ap.add_argument('--whisper', action='store_true', help="prova anche Whisper 'tiny' su 10 s (scarica ~75 MB)")
    ap.add_argument('--out', default='amd_smoke_report.txt')
    a = ap.parse_args(argv)

    sections = [('Sistema', system_section()), ('gpu_detect --json', gpu_detect_section()),
                ('Famiglia AMD e percorso', amd_family_section()),
                ('torch / HIP', run_py(_TORCH)), ('ctranslate2', run_py(_CT2)),
                ('llama_cpp (Vulkan)', run_py(_LLAMA, [a.gguf] if a.gguf else []))]
    if not a.gguf:
        sections[-1] = (sections[-1][0], (sections[-1][1][0], sections[-1][1][1] + '\n(nessun --gguf: non provato il caricamento di un modello)'))
    if a.whisper:
        sections.append(('Whisper tiny su GPU (dentro un processo senza PyQt6)', run_py(_WHISPER, timeout=600)))
    else:
        sections.append(('Whisper tiny', ('SKIP', 'non richiesto (--whisper)')))

    out = ['Transcriber Pro - amd_smoke_report', time.strftime('%Y-%m-%d %H:%M:%S'), '']
    for title, (status, text) in sections:
        out += ['== %s: %s' % (title, status), text, '']
    out.append('RIASSUNTO: ' + ', '.join('%s=%s' % (t, s) for t, (s, _) in sections))
    out.append("Nota: la prova decisiva e' Whisper (ctranslate2 ROCm) dentro l'app PyQt6: avviare ./run.sh e trascrivere 1 minuto.")
    report = anonymize('\n'.join(out) + '\n')
    path = a.out if os.path.isabs(a.out) else os.path.join(os.getcwd(), a.out)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(report)
    print(report)
    print('Rapporto scritto in', path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
