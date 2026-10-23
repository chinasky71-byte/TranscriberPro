#!/usr/bin/env bash
# Prepara Transcriber Pro su Linux (qualsiasi distribuzione con apt, dnf, pacman o zypper; altrimenti stampa cosa installare).
# NON VERIFICATO SU LINUX REALE: scritto e controllato con `bash -n`, ma mai eseguito su una macchina Linux.
#
#   ./install.sh --check        solo il rapporto dei prerequisiti, nessuna modifica
#   ./install.sh                crea il venv e installa requirements.txt (chiede conferma per sudo)
#   ./install.sh --system-deps  propone anche l'installazione dei pacchetti di sistema con sudo
#   opzioni: --no-gpu (ruote CPU di torch e llama-cpp-python, ~250 MB invece di ~3 GB) --yes (nessuna domanda)
#            --with-models  scarica da Hugging Face il Qwen2.5 (glossario/serbatoio) e il NLLB fine-tuned (molti GB)
#            --qwen-size=auto|7b|14b  (auto = 14B con GPU da 12 GB o piu', 7B con GPU piu' piccola o --no-gpu)
#            --gpu-backend=auto|cuda|vulkan|rocm|cpu  (senza l'opzione: comportamento di sempre = ruota CUDA di llama-cpp-python)
#                 cuda   come senza opzione        cpu     come --no-gpu
#                 vulkan torch su CPU + llama-cpp-python Vulkan (glossario su GPU AMD/Intel, serve il driver Vulkan; la
#                        trascrizione e la traduzione restano su CPU)
#                 auto   sceglie con `utils/gpu_detect.py --backend` (cuda, vulkan o cpu; se rileva solo ROCm usa vulkan)
#                 rocm   Linux + GPU AMD con ROCm 7.0: torch/torchaudio +rocm7.0 (requirements-rocm.txt), ctranslate2 ROCm (release
#                        OpenNMT/CTranslate2), whisperx --no-deps, llama-cpp-python Vulkan. NON PROVATO SU HARDWARE AMD. Non installa ROCm
#                        di sistema: controlla /dev/kfd, gruppi render/video e driver amdgpu e dice cosa fare. Python 3.11 o 3.12.
#
# Non copia ne' scrive mai credenziali. Non va lanciato come root (il venv deve essere dell'utente).
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK=0; SYSDEPS=0; NOGPU=0; YES=0; WITHMODELS=0; QWENSIZE=auto; GPUBACKEND=""; LLAMA_IDX=cpu; ROCM=0
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --system-deps) SYSDEPS=1 ;;
    --no-gpu) NOGPU=1 ;;
    --yes) YES=1 ;;
    --with-models) WITHMODELS=1 ;;
    --qwen-size=*) QWENSIZE="${a#--qwen-size=}" ;;
    --gpu-backend=*) GPUBACKEND="${a#--gpu-backend=}" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Opzione sconosciuta: $a"; exit 2 ;;
  esac
done

if [ "$(id -u)" = "0" ]; then echo "[KO] Non lanciare come root: il venv deve essere dell'utente (sudo viene chiesto solo per i pacchetti)."; exit 2; fi
[ "$(uname -s)" = "Linux" ] || { echo "[KO] Questo script e' per Linux."; exit 2; }
[ "$(uname -m)" = "x86_64" ] || echo "[!!] Architettura $(uname -m): le ruote di torch/ctranslate2 pinnate sono per x86_64."

ok()   { printf '  [OK]  %s\n' "$*"; }
warn() { printf '  [!!]  %s\n' "$*"; }
bad()  { printf '  [KO]  %s\n' "$*"; }
ask()  { [ "$YES" = "1" ] && return 0; read -r -p "$1 [s/N] " r; case "$r" in s|S|si|SI|y|Y|yes) return 0 ;; *) return 1 ;; esac; }
have() { command -v "$1" >/dev/null 2>&1; }

# --gpu-backend: senza l'opzione non cambia nulla. 'cpu' = --no-gpu; 'vulkan' = ruote CPU di torch + llama Vulkan (NOGPU=1 e LLAMA_IDX=vulkan).
case "$GPUBACKEND" in ''|auto|cuda|vulkan|rocm|cpu) ;; *) echo "[KO] --gpu-backend deve essere auto, cuda, vulkan, rocm o cpu"; exit 2 ;; esac
if [ "$GPUBACKEND" = "auto" ]; then
  if [ "$NOGPU" = "1" ]; then GPUBACKEND=cpu
  else
    GPUBACKEND="$(python3 "$ROOT/utils/gpu_detect.py" --backend 2>/dev/null | head -1)"
    case "$GPUBACKEND" in cuda|rocm|vulkan|cpu) ;; *) GPUBACKEND=cpu ;; esac
    echo "  gpu_detect: backend consigliato = $GPUBACKEND"
    [ "$GPUBACKEND" = "rocm" ] && { echo "  [!!]  Rilevato ROCm: 'auto' non lo sceglie perche' non e' ancora provato su hardware; uso vulkan (glossario su GPU, il resto su CPU). Per ROCm: --gpu-backend=rocm"; GPUBACKEND=vulkan; }
  fi
fi
if [ -n "$GPUBACKEND" ] && [ "$NOGPU" = "1" ] && [ "$GPUBACKEND" != "cpu" ]; then echo "[KO] --no-gpu equivale a --gpu-backend=cpu: non si combina con --gpu-backend=$GPUBACKEND"; exit 2; fi
case "$GPUBACKEND" in
  cpu) NOGPU=1 ;;
  vulkan) NOGPU=1; LLAMA_IDX=vulkan ;;
  rocm) ROCM=1; LLAMA_IDX=vulkan ;;     # torch/ctranslate2 su ROCm; llama resta Vulkan (ruota ROCm di llama non prevista)
esac

MISSING=()

echo; echo "== Prerequisiti"
# Python: 3.11 (provato dall'autore) o 3.12 (ruote disponibili per tutti i pin, ma non verificato a runtime)
PY=""
for c in python3.11 python3.12; do if have "$c"; then PY="$(command -v "$c")"; break; fi; done
if [ -n "$PY" ]; then
  ok "Python: $PY ($("$PY" -c 'import sys;print(sys.version.split()[0])'))"
  "$PY" -c 'import venv, ensurepip' 2>/dev/null || { bad "il modulo venv/ensurepip manca per $PY (pacchetto python3-venv o equivalente)"; MISSING+=("python-venv"); }
else
  bad "Python 3.11 (o 3.12) non trovato"; MISSING+=("python")
fi

if [ "$ROCM" = "1" ]; then
  warn "Backend ROCm (NON PROVATO su hardware AMD): torch/ctranslate2 su GPU con ROCm 7.0, llama-cpp-python su Vulkan."
  if [ -e /dev/kfd ]; then
    if [ -r /dev/kfd ] && [ -w /dev/kfd ]; then ok "/dev/kfd accessibile"
    else bad "/dev/kfd esiste ma non e' accessibile a $(id -un): aggiungi l'utente ai gruppi render e video (sudo usermod -aG render,video \$USER) e rifai il login"; MISSING+=("kfd-access"); fi
  else bad "/dev/kfd assente: serve il driver amdgpu del kernel con supporto compute (kernel recente o pacchetto amdgpu-dkms di AMD)"; MISSING+=("kfd"); fi
  for g in render video; do
    if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx "$g"; then ok "utente nel gruppo $g"; else warn "utente non nel gruppo $g (sudo usermod -aG $g \$USER, poi nuovo login)"; fi
  done
  if [ -d /sys/module/amdgpu ] || (have lsmod && lsmod 2>/dev/null | grep -q '^amdgpu'); then ok "driver amdgpu caricato"; else warn "driver amdgpu non visibile (lsmod)"; fi
  have rocminfo && ok "rocminfo presente (ROCm di sistema: non obbligatorio, le ruote di torch portano il loro runtime)" || warn "rocminfo assente: non e' un problema, ROCm di sistema non serve"
  if { have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so\.1'; } || [ -e /usr/lib/x86_64-linux-gnu/libvulkan.so.1 ] || [ -e /usr/lib64/libvulkan.so.1 ] || [ -e /usr/lib/libvulkan.so.1 ]; then
    ok "Loader Vulkan (libvulkan.so.1) presente"
  else bad "libvulkan.so.1 non trovata (serve per llama-cpp-python Vulkan)"; MISSING+=("vulkan"); fi
elif [ "$LLAMA_IDX" = "vulkan" ]; then
  warn "Backend Vulkan: llama-cpp-python usera' la GPU (solo il glossario); trascrizione e traduzione girano su CPU, ~10 volte piu' lente."
  if { have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so\.1'; } || [ -e /usr/lib/x86_64-linux-gnu/libvulkan.so.1 ] || [ -e /usr/lib64/libvulkan.so.1 ] || [ -e /usr/lib/libvulkan.so.1 ]; then
    ok "Loader Vulkan (libvulkan.so.1) presente"
  else bad "libvulkan.so.1 non trovata (pacchetto del loader Vulkan e driver Mesa)"; MISSING+=("vulkan"); fi
elif [ "$NOGPU" = "1" ]; then warn "Modalita' senza GPU (--no-gpu): l'app gira solo su CPU, ~10 volte piu' lenta."
elif have nvidia-smi && nvidia-smi >/dev/null 2>&1; then ok "GPU NVIDIA: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -1)"
else warn "nvidia-smi non disponibile: senza driver NVIDIA usa --no-gpu."; fi

have ffmpeg && have ffprobe && ok "FFmpeg: $(command -v ffmpeg)" || { bad "ffmpeg/ffprobe non trovati"; MISSING+=("ffmpeg"); }
if have tesseract; then
  langs="$(tesseract --list-langs 2>/dev/null)"
  if echo "$langs" | grep -qx ita && echo "$langs" | grep -qx eng; then ok "Tesseract con ita+eng"; else bad "Tesseract senza ita/eng"; MISSING+=("tesseract-ita-eng"); fi
else bad "Tesseract non trovato"; MISSING+=("tesseract"); fi
have mkvextract && ok "MKVToolNix: $(command -v mkvextract)" || warn "MKVToolNix non trovato (serve solo per i sottotitoli VOBSUB)"
free_gb="$(df -Pk "$ROOT" | awk 'NR==2{printf "%d", $4/1048576}')"
need=15; [ "$NOGPU" = "1" ] && need=6; [ "$ROCM" = "1" ] && need=20
[ "${free_gb:-0}" -ge "$need" ] && ok "Spazio libero: ${free_gb} GB (servono ~${need})" || { bad "Spazio libero ${free_gb} GB, ne servono ~${need}"; MISSING+=("disco"); }

# gestore pacchetti e nomi (ogni distribuzione chiama i pacchetti in modo diverso). I pacchetti Python si aggiungono solo se servono:
# se Python 3.11/3.12 c'e' gia' non si tocca; se manca solo il modulo venv si prende quello della versione trovata.
PM=""; PKGS=""; PYPKG=""; PYVER=""; VKPKG=""
[ -n "$PY" ] && PYVER="$("$PY" -c 'import sys;print("%d.%d" % sys.version_info[:2])')"
case " ${MISSING[*]:-} " in
  *" python "*) NEED_PY=all ;;
  *" python-venv "*) NEED_PY=venv ;;
  *) NEED_PY="" ;;
esac
case " ${MISSING[*]:-} " in *" vulkan "*) VKFLAG=1 ;; *) VKFLAG=0 ;; esac
if have apt-get; then PM="apt"
  [ "$VKFLAG" = "1" ] && VKPKG="libvulkan1 mesa-vulkan-drivers"
  [ "$NEED_PY" = "all" ] && PYPKG="python3 python3-venv"      # versione della distribuzione (deve essere 3.11 o 3.12)
  [ "$NEED_PY" = "venv" ] && PYPKG="python${PYVER}-venv"
  PKGS="$PYPKG ffmpeg mkvtoolnix tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng libxcb-cursor0 libxkbcommon-x11-0 libegl1 libfontconfig1 $VKPKG"
elif have dnf; then PM="dnf"
  [ "$VKFLAG" = "1" ] && VKPKG="vulkan-loader mesa-vulkan-drivers"
  [ -n "$NEED_PY" ] && PYPKG="python3.11"
  PKGS="$PYPKG ffmpeg-free mkvtoolnix tesseract tesseract-langpack-ita tesseract-langpack-eng xcb-util-cursor libxkbcommon-x11 mesa-libEGL fontconfig $VKPKG"
elif have pacman; then PM="pacman"
  [ "$VKFLAG" = "1" ] && VKPKG="vulkan-icd-loader vulkan-radeon vulkan-intel"
  PKGS="ffmpeg mkvtoolnix-cli tesseract tesseract-data-ita tesseract-data-eng xcb-util-cursor libxkbcommon-x11 libglvnd fontconfig $VKPKG"
  [ "$NEED_PY" = "all" ] && warn "Arch: il pacchetto 'python' e' 3.13+, non supportato: serve python 3.11 (AUR 'python311') o 3.12, oppure pyenv/uv."
elif have zypper; then PM="zypper"
  [ "$VKFLAG" = "1" ] && VKPKG="libvulkan1 libvulkan_radeon libvulkan_intel"
  [ -n "$NEED_PY" ] && PYPKG="python311"
  PKGS="$PYPKG ffmpeg mkvtoolnix tesseract-ocr tesseract-ocr-traineddata-italian tesseract-ocr-traineddata-english libxcb-cursor0 libxkbcommon-x11-0 libEGL1 fontconfig $VKPKG"
fi

if [ "${#MISSING[@]}" -gt 0 ]; then
  echo; echo "== Programmi mancanti: ${MISSING[*]}"
  if [ -z "$PM" ]; then
    warn "Gestore pacchetti non riconosciuto. Installa a mano: Python 3.11 (con venv), ffmpeg, mkvtoolnix, tesseract con i dati ita ed eng,"
    warn "e le librerie Qt: xcb-cursor, xkbcommon-x11, EGL, fontconfig."
  else
    case "$PM" in
      apt) CMD="sudo apt-get install -y $PKGS" ;;
      dnf) CMD="sudo dnf install -y $PKGS" ;;
      pacman) CMD="sudo pacman -S --needed $PKGS" ;;
      zypper) CMD="sudo zypper install -y $PKGS" ;;
    esac
    echo "  Comando per $PM (i nomi dei pacchetti possono variare con la versione della distribuzione):"
    echo "    $CMD"
    if [ "$SYSDEPS" = "1" ] && [ "$CHECK" = "0" ]; then
      if ask "Eseguo questo comando con sudo?"; then $CMD || warn "Il gestore pacchetti ha restituito un errore: correggi i nomi o installa a mano."; fi
      echo "  Rilancia ./install.sh per ricontrollare i prerequisiti."
    fi
  fi
fi
if [ "$CHECK" = "1" ]; then [ "${#MISSING[@]}" -eq 0 ] && exit 0 || exit 2; fi
[ -z "$PY" ] && { bad "Senza Python 3.11/3.12 non posso continuare (le distribuzioni con solo Python 3.13+ richiedono pyenv, uv o un repository dedicato)."; exit 2; }

echo; echo "== Ambiente Python (venv)"
VENV="$ROOT/venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "  creo il venv in $VENV"
  "$PY" -m venv "$VENV" || { bad "Creazione del venv fallita (manca python3-venv?)"; exit 1; }
else ok "venv gia' presente (riuso)"; fi
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip >/dev/null 2>&1

REQ="$ROOT/requirements.txt"
if [ "$NOGPU" = "0" ] && [ "$ROCM" = "0" ] && [ -f "$VENV/llama_backend.txt" ]; then
  # venv riusato che aveva la ruota CPU/Vulkan di llama (installata da una esecuzione precedente con --no-gpu / --gpu-backend):
  # pip la riterrebbe valida (stessa versione), quindi si rimette la ruota CUDA dei requisiti. Senza marcatore non si tocca nulla.
  LV="$(sed -n 's/^[[:space:]]*llama[-_]cpp[-_]python==\([0-9.]*\).*/\1/Ip' "$ROOT/requirements.txt" | head -1)"
  if [ -n "$LV" ]; then
    echo "  llama-cpp-python $LV: ripristino la ruota CUDA (il venv aveva la ruota $(cat "$VENV/llama_backend.txt"))"
    if "$VPY" -m pip install --force-reinstall --no-deps --only-binary=:all: --index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 "llama_cpp_python==$LV"; then
      rm -f "$VENV/llama_backend.txt"
    else warn "Ruota CUDA di llama-cpp-python non reinstallata: il venv conserva quella di prima."; fi
  fi
fi
if [ "$NOGPU" = "1" ] || [ "$ROCM" = "1" ]; then
  # ruote CPU: llama-cpp-python (stessa versione del pin) e torch/torchaudio, tolte dal file usato da pip
  LV="$(sed -n 's/^[[:space:]]*llama[-_]cpp[-_]python==\([0-9.]*\).*/\1/Ip' "$ROOT/requirements.txt" | head -1)"
  TV="$(sed -n 's/^[[:space:]]*torch==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)"
  AV="$(sed -n 's/^[[:space:]]*torchaudio==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)"
  if [ -n "$LV" ]; then
    echo "  llama-cpp-python $LV (ruota $LLAMA_IDX)"
    if "$VPY" -m pip install --force-reinstall --no-deps --only-binary=:all: --index-url "https://abetlen.github.io/llama-cpp-python/whl/$LLAMA_IDX" "llama_cpp_python==$LV"; then
      echo "$LLAMA_IDX" > "$VENV/llama_backend.txt"     # letto da utils/llm_model_select.py: solo 'vulkan' cambia la scelta del modello
    else
      rm -f "$VENV/llama_backend.txt"
      warn "Ruota $LLAMA_IDX di llama-cpp-python non installata: si prosegue con quella di requirements.txt."
    fi
  fi
  if [ "$NOGPU" = "1" ] && [ -n "$TV" ] && [ -n "$AV" ]; then
    echo "  torch $TV / torchaudio $AV (ruote CPU)"
    if "$VPY" -m pip install --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch==$TV" "torchaudio==$AV"; then
      REQ="$(mktemp /tmp/tp_requirements_nogpu.XXXXXX)"; trap 'rm -f "$REQ"' EXIT
      grep -Ev '^[[:space:]]*(torch|torchaudio)==' "$ROOT/requirements.txt" > "$REQ"
    else warn "Ruote CPU di torch non installate: si prosegue con quelle di requirements.txt (+cu126, ~3 GB)."; fi
  fi
fi
if [ "$ROCM" = "1" ]; then
  # ctranslate2 ROCm: non e' su PyPI, sta nella release di OpenNMT/CTranslate2 (rocm-python-wheels-Linux.zip). Va installato PRIMA, cosi' pip
  # considera soddisfatta la dipendenza di faster-whisper e non scarica la ruota CUDA di PyPI.
  PYTAG="cp$("$VPY" -c 'import sys;print("%d%d" % sys.version_info[:2])')"
  CT2DIR="$(mktemp -d /tmp/tp_ct2rocm.XXXXXX)"; trap 'rm -rf "$CT2DIR"' EXIT
  echo "  ctranslate2 ROCm (release piu' recente di OpenNMT/CTranslate2, ruota $PYTAG)"
  if curl -fsSL --retry 3 -o "$CT2DIR/w.zip" "https://github.com/OpenNMT/CTranslate2/releases/latest/download/rocm-python-wheels-Linux.zip" \
     && "$VPY" - "$CT2DIR" "$PYTAG" <<'PYEOF'
import sys, zipfile, glob, os
d, tag = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(d + '/w.zip')
names = [n for n in z.namelist() if n.endswith('.whl') and ('-%s-%s-' % (tag, tag)) in os.path.basename(n) and 'manylinux' in n]
if not names: sys.exit('nessuna ruota ctranslate2 ROCm per ' + tag)
open(d + '/path.txt', 'w').write(z.extract(names[0], d))
PYEOF
  then
    "$VPY" -m pip install --no-deps "$(cat "$CT2DIR/path.txt")" || { bad "installazione ctranslate2 ROCm fallita"; exit 1; }
  else bad "ctranslate2 ROCm non scaricata/estratta: Whisper non usera' la GPU AMD. Scarica a mano rocm-python-wheels-Linux.zip da github.com/OpenNMT/CTranslate2/releases"; exit 1; fi
  REQ="$ROOT/requirements-rocm.txt"
fi
echo "  pip install -r $(basename "$REQ")  (puo' richiedere diversi minuti e alcuni GB di download)"
"$VPY" -m pip install -r "$REQ" || { bad "pip install fallito (vedi l'errore sopra; rilancia dopo averlo risolto)"; exit 1; }
if [ "$ROCM" = "1" ]; then
  # whisperx senza dipendenze (l'app lo usa solo in core/aligner.py; le sue dipendenze sono gia' in requirements-rocm.txt)
  WV="$(sed -n 's/^[[:space:]]*whisperx==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)"
  "$VPY" -m pip install --no-deps "whisperx==$WV" || warn "whisperx $WV non installato: l'allineamento parola per parola non funzionera'."
fi
ok "ambiente principale pronto"

if [ "$WITHMODELS" = "1" ]; then
  echo; echo "== Modelli locali (Hugging Face)"
  case "$QWENSIZE" in auto|7b|14b) ;; *) bad "--qwen-size deve essere auto, 7b o 14b"; exit 2 ;; esac
  QS="$QWENSIZE"
  if [ "$QS" = "auto" ]; then
    VR=0
    if [ "$NOGPU" = "0" ] && have nvidia-smi; then VR="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1)"; fi
    case "$VR" in ''|*[!0-9]*) VR=0 ;; esac
    if [ "$VR" -ge 12000 ]; then QS=14b; else QS=7b; fi
  fi
  if [ "$QS" = "7b" ]; then echo "  Qwen2.5-7B-Instruct Q4_K_M (2 file, ~4,7 GB: ripiego per GPU sotto i 12 GB) -> models/"
  else echo "  Qwen2.5-14B-Instruct Q4_K_M (3 file, ~9 GB) -> models/"; fi
  echo "  NLLB-200 3.3B fine-tuned EN->IT (Chinasky71/nllb-200-3.3b-it-subtitles, molti GB) -> NLLB_Tranined/"
  if ask "Scarico questi modelli?"; then
    "$VPY" - "$ROOT" "$QS" <<'PYEOF' || warn "Download modelli non completato: rilancia ./install.sh --with-models (riprende da dove si e' fermato)."
import sys
from huggingface_hub import hf_hub_download, snapshot_download
root, size = sys.argv[1], sys.argv[2]
if size == '7b':
    repo, name, n = 'Qwen/Qwen2.5-7B-Instruct-GGUF', 'qwen2.5-7b-instruct-q4_k_m-0000%d-of-00002.gguf', 2
else:
    repo, name, n = 'Qwen/Qwen2.5-14B-Instruct-GGUF', 'qwen2.5-14b-instruct-q4_k_m-0000%d-of-00003.gguf', 3
for i in range(1, n + 1):
    f = name % i
    print('scarico', f, flush=True)
    hf_hub_download(repo, f, local_dir=root + '/models')
print('scarico NLLB fine-tuned', flush=True)
snapshot_download('Chinasky71/nllb-200-3.3b-it-subtitles', local_dir=root + '/NLLB_Tranined')
print('modelli scaricati')
PYEOF
  fi
  warn "TranslateGemma fine-tuned (models/translategemma-...): non e' su un hub, va copiato a mano. Il Qwen in models/ lo sceglie l'app da sola in base alla VRAM."
fi

echo; echo "== Controllo finale"
SC=("$VPY" "$ROOT/scripts_manutenzione/selfcheck_env.py"); [ "$NOGPU" = "1" ] && SC+=("--no-gpu")
"${SC[@]}"; rc=$?
echo
echo "Avvio: ./run.sh   (le chiavi TMDB/HuggingFace/Claude si impostano a mano; questo script non le scrive)"
exit $rc
