#!/usr/bin/env bash
# Prepara Transcriber Pro su Linux (qualsiasi distribuzione con apt, dnf, pacman o zypper; altrimenti stampa cosa installare).
# NON VERIFICATO SU LINUX REALE: scritto e controllato con `bash -n`, ma mai eseguito su una macchina Linux.
#
#   ./install.sh --check        solo il rapporto dei prerequisiti e il backend che sceglierebbe, nessuna modifica
#   ./install.sh                rileva l'hardware e installa: CUDA su NVIDIA, ROCm su GPU AMD supportate. Nessun altro backend.
#                               Senza --backend decide da solo; se l'hardware non e' supportato si ferma e lo dice (niente fallback silenziosi).
#   ./install.sh --backend=cuda|rocm|auto   forza il backend (auto = rilevamento, il default)
#   ./install.sh --verify-only              riverifica il venv esistente (import di torch/ctranslate2 + GPU) e riscrive
#                               venv/.tp-backend, senza installare nulla: il rimedio quando il timbro manca o e' vecchio
#   ./install.sh --force-backend            accetta un backend diverso dall'hardware rilevato: serve solo al cross-build dei
#                               container (immagine NVIDIA costruita su un host AMD) e per i test; in tutti gli altri casi e' un errore
#   ./install.sh --system-deps  installa anche i pacchetti di sistema con sudo e rilancia da solo lo script (un solo rilancio); se sudo non
#                               puo' chiedere la password (niente terminale) o il comando fallisce, stampa il comando e esce con 2
#                               senza l'opzione, con un terminale interattivo, chiede "Li installo ora con sudo?"
#   opzioni: --yes (nessuna domanda)
#            --with-gui  installa anche requirements-gui.txt (GUI desktop legacy; senza, l'interfaccia e' la WebUI)
#            --with-models  scarica da Hugging Face il Qwen2.5 (glossario/serbatoio) e il NLLB fine-tuned (molti GB)
#            --gguf=auto|q4|iq3|q3|none  TranslateGemma-12B GGUF da Hugging Face (5-7 GB, anonimo, riprendibile, SHA-256) in models/translategemma-12b-gguf/.
#                 auto = per VRAM TOTALE con le stesse soglie del selettore (utils/translator_path_select.py): Q4_K_M per le schede medie, IQ3_M per quelle da ~8 GB,
#                 nulla se la VRAM e' troppo poca o se basta il bf16. Chiede conferma (--yes la salta).
#            --gguf-dir=PATH  cartella di destinazione (default: models/translategemma-12b-gguf, quella che l'app scansiona)
#            --qwen-size=auto|7b|14b  (auto = 14B con GPU da 12 GB o piu', 7B con GPU piu' piccola)
#
# Backend supportati (decisione esplicita, v. ADR-007):
#   cuda  NVIDIA su Linux: requirements.txt (torch +cu126), llama-cpp-python ruota CUDA
#   rocm  AMD con ROCm 7.0 su RDNA3/RDNA4/CDNA: requirements-rocm.txt (torch +rocm7.0), ctranslate2 ROCm dalla release
#         OpenNMT/CTranslate2, whisperx --no-deps, llama-cpp-python ruota Vulkan. Non installa ROCm di sistema: la ruota di torch
#         porta il suo runtime; controlla /dev/kfd, i gruppi render/video e il driver amdgpu e dice cosa fare. Python 3.11 o 3.12.
#   RDNA2 e precedenti, nessuna GPU, Vulkan e CPU non sono supportati: lo script si ferma.
#   Al termine l'installazione viene verificata davvero (import di torch/ctranslate2 e device visibile) e il backend scelto
#   viene scritto in venv/.tp-backend: rilanciare lo script con un backend diverso non sostituisce piu' torch in silenzio.
#
# Non copia ne' scrive mai credenziali. Non va lanciato come root (il venv deve essere dell'utente).
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK=0; VERIFY_ONLY=0; SYSDEPS=0; YES=0; WITHMODELS=0; WITHGUI=0; QWENSIZE=auto; BACKEND="auto"; FORCE_BACKEND=0; LLAMA_IDX=cuda; ROCM=0; GGUF=""; GGUFDIR=""
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --system-deps) SYSDEPS=1 ;;
    --yes) YES=1 ;;
    --with-models) WITHMODELS=1 ;;
    --with-gui) WITHGUI=1 ;;
    --gguf=*) GGUF="${a#--gguf=}" ;;
    --gguf-dir=*) GGUFDIR="${a#--gguf-dir=}" ;;
    --qwen-size=*) QWENSIZE="${a#--qwen-size=}" ;;
    --backend=*) BACKEND="${a#--backend=}" ;;
    --gpu-backend=*) BACKEND="${a#--gpu-backend=}" ;;   # alias storico
    --force-backend) FORCE_BACKEND=1 ;;
    --verify-only) VERIFY_ONLY=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
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

# ----------------------------------------------------------------------------------------------
# Verifica reale: un'installazione non e' riuscita finche' torch/ctranslate2 non vedono davvero la
# GPU. Se il backend e' cuda/rocm e il device non risponde, lo script FALLISCE e non scrive il
# timbro, cosi' non resta in giro un venv che sembra a posto e poi gira su CPU.
# ----------------------------------------------------------------------------------------------
check_backend() {
  "$VPY" - "$BACKEND" <<'PYEOF'
import sys
backend = sys.argv[1]
try:
    import torch
except Exception as exc:                                   # noqa: BLE001
    print(f"KO  import torch fallito: {exc}")
    raise SystemExit(1)
version = torch.__version__
runtime = torch.version.hip or torch.version.cuda or ''
available = bool(torch.cuda.is_available())
devices = torch.cuda.device_count() if available else 0
print(f"  torch {version} | runtime {runtime or '-'} | cuda/hip disponibile: {available} | device: {devices}")
bad = []
if backend == 'rocm':
    if not torch.version.hip:
        bad.append("torch non e' la ruota ROCm (version.hip vuoto)")
    if not available:
        bad.append("torch.cuda.is_available() e' False: ROCm non vede la GPU")
elif backend == 'cuda':
    if not torch.version.cuda:
        bad.append("torch non e' la ruota CUDA (version.cuda vuoto)")
    if not available:
        bad.append("torch.cuda.is_available() e' False: il driver NVIDIA non risponde")
if backend in ('rocm', 'cuda'):
    try:
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        print(f"  ctranslate2 {ctranslate2.__version__} | device GPU: {n}")
        if n < 1:
            bad.append("ctranslate2 non vede alcun device GPU (Whisper girerebbe su CPU)")
    except Exception as exc:                               # noqa: BLE001
        print(f"  [!!]  ctranslate2 non verificabile: {exc}")
for line in bad:
    print(f"KO  {line}")
raise SystemExit(1 if bad else 0)
PYEOF
}
write_stamp() {
  {
    echo "backend=$BACKEND"
    echo "torch=$("$VPY" -c 'import torch;print(torch.__version__)' 2>/dev/null)"
    echo "torchaudio=$("$VPY" -c 'import torchaudio;print(torchaudio.__version__)' 2>/dev/null)"
    # ctranslate2 va importato DOPO torch (le sue librerie HIP dipendono dal runtime di torch)
    echo "ctranslate2=$("$VPY" -c 'import torch, ctranslate2;print(ctranslate2.__version__)' 2>/dev/null)"
    echo "llama_backend=$LLAMA_IDX"
    echo "requirements=$(basename "$REQ")"
    echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$STAMP"
}

verify_and_stamp() {
  echo; echo "== Verifica del backend installato"
  if check_backend; then
    ok "backend $BACKEND verificato: la GPU risponde"
    write_stamp
    ok "backend scritto in $STAMP"
    return 0
  fi
  bad "Installazione NON riuscita: il backend $BACKEND non funziona su questa macchina."
  bad "Controlla i messaggi qui sopra (driver, gruppi render/video, /dev/kfd, indice delle ruote) e rilancia ./install.sh --backend=$BACKEND."
  rm -f "$STAMP"
  return 1
}


case "$GGUF" in ''|auto|q4|iq3|q3|none) ;; *) echo "[KO] --gguf deve essere auto, q4, iq3, q3 o none"; exit 2 ;; esac
case "$BACKEND" in
  auto|cuda|rocm) ;;
  cpu|vulkan) echo "[KO] Backend '$BACKEND' non supportato (ADR-007): restano solo cuda e rocm. Usa --backend=auto|cuda|rocm."; exit 2 ;;
  *) echo "[KO] --backend deve essere auto, cuda o rocm"; exit 2 ;;
esac

# ----------------------------------------------------------------------------------------------
# Scelta del backend. Regola: auto decide dall'hardware e, se l'hardware non e' supportato,
# SI FERMA. Un backend esplicito diverso dall'hardware e' un errore, a meno di --force-backend
# (cross-build dei container e test). Nessun percorso porta a installare torch CUDA su una
# macchina AMD o rocce su una NVIDIA senza che qualcuno l'abbia chiesto (v. ADR-007).
# ----------------------------------------------------------------------------------------------
detected_backend() { python3 "$ROOT/utils/gpu_detect.py" --backend 2>/dev/null | head -1; }
md_amd() { python3 "$ROOT/utils/gpu_detect.py" --amd 2>/dev/null | sed -n "s/^$1=//p"; }
amd_line="$(python3 "$ROOT/utils/gpu_detect.py" --amd 2>/dev/null)"
amd_family="$(printf '%s\n' "$amd_line" | sed -n 's/^amd_family=//p')"
amd_gfx="$(printf '%s\n' "$amd_line" | sed -n 's/^gfx=//p')"
amd_path="$(printf '%s\n' "$amd_line" | sed -n 's/^path=//p')"
# il nome commerciale non e' in --amd: si prende dalla scheda discreta del report JSON
amd_name="$(python3 "$ROOT/utils/gpu_detect.py" --json 2>/dev/null | sed -n 's/.*"name": "\([^"]*\)".*/\1/p' | head -1)"
DETECTED="$(detected_backend)"
KFD="${TP_KFD_PATH:-/dev/kfd}"        # override usato dai test per non dipendere dalla macchina

# rocm utilizzabile solo su famiglie supportate ufficialmente da ROCm 7 e con /dev/kfd accessibile
rocm_ready=1; rocm_why=""
if [ -z "$amd_path" ]; then rocm_ready=0; rocm_why="nessuna GPU AMD rilevata"
elif [ "$amd_path" = "rocm_override" ]; then rocm_ready=0; rocm_why="scheda ${amd_family:-AMD}${amd_gfx:+ ($amd_gfx)}: ROCm non la supporta ufficialmente (serve HSA override)"
elif [ "$amd_path" = "vulkan_cpu" ]; then rocm_ready=0; rocm_why="scheda ${amd_family:-AMD}${amd_gfx:+ ($amd_gfx)}: troppo vecchia per ROCm 7"
elif [ ! -e "$KFD" ]; then rocm_ready=0; rocm_why="/dev/kfd assente: manca il driver amdgpu con supporto compute"
elif [ ! -r "$KFD" ] || [ ! -w "$KFD" ]; then rocm_ready=0; rocm_why="/dev/kfd non accessibile a $(id -un): sudo usermod -aG render,video \$USER poi nuovo login"
fi

case "$BACKEND" in
  auto)
    case "$DETECTED" in
      cuda) BACKEND=cuda ;;
      rocm)
        if [ "$rocm_ready" = "1" ]; then BACKEND=rocm
        else
          bad "GPU AMD rilevata ma ROCm non e' utilizzabile: $rocm_why"
          bad "Backend supportati: cuda e rocm su GPU AMD RDNA3/RDNA4/CDNA (ADR-007). Mi fermo senza toccare il venv."
          exit 2
        fi ;;
      *)  bad "Nessun backend supportato su questo hardware (rilevato: ${DETECTED:-niente})."
          bad "Servono una GPU NVIDIA (cuda) o una AMD RDNA3/RDNA4/CDNA con ROCm (rocm). Mi fermo senza toccare il venv."
          exit 2 ;;
    esac ;;
  cuda)
    if [ "$DETECTED" != "cuda" ] && [ "$FORCE_BACKEND" != "1" ]; then
      bad "--backend=cuda richiesto ma l'hardware rilevato e' '${DETECTED:-niente}'. Se e' un cross-build (container) aggiungi --force-backend."
      exit 2
    fi ;;
  rocm)
    if { [ "$DETECTED" != "rocm" ] || [ "$rocm_ready" != "1" ]; } && [ "$FORCE_BACKEND" != "1" ]; then
      bad "--backend=rocm richiesto ma non utilizzabile qui: ${rocm_why:-rilevato '${DETECTED:-niente}'}."
      bad "Per un cross-build (container) aggiungi --force-backend."
      exit 2
    fi ;;
esac

case "$BACKEND" in
  rocm) ROCM=1; LLAMA_IDX=vulkan ;;   # torch/ctranslate2 su ROCm; llama-cpp-python resta sulla ruota Vulkan (non esiste una ruota ROCm)
  cuda) ROCM=0; LLAMA_IDX=cuda ;;
esac

echo; echo "== Backend"
case "$BACKEND" in
  rocm) ok "rocm  $( [ -n "$amd_name" ] && printf '%s' "$amd_name" )${amd_gfx:+ ($amd_gfx)} — torch 2.10.0+rocm7.0 + ctranslate2 ROCm" ;;
  cuda) ok "cuda  NVIDIA — requirements.txt (torch +cu126)" ;;
esac
[ "$FORCE_BACKEND" = "1" ] && warn "--force-backend: procedo anche se l'hardware rilevato e' '${DETECTED:-niente}' (cross-build/test)"

if [ "$VERIFY_ONLY" = "1" ]; then
  # Riscrive il timbro verificando il venv esistente: nessun pip, nessun pacchetto di sistema.
  VENV="${TP_INSTALL_VENV:-$ROOT/venv}"
  STAMP="$VENV/.tp-backend"
  [ -x "$VENV/bin/python" ] || { bad "Nessun venv in $VENV: niente da verificare (lancia ./install.sh)"; exit 2; }
  VPY="$VENV/bin/python"
  REQ="requirements-rocm.txt"; [ "$BACKEND" = "cuda" ] && REQ="requirements.txt"
  verify_and_stamp || exit 1
  exit 0
fi

MISSING=()

echo; echo "== Prerequisiti"
# Python: 3.11 (provato dall'autore) o 3.12 (provato su Ubuntu 24.04 il 23/10/2026: installazione, selfcheck, test, avvio offscreen, Vulkan/lavapipe; mai su GPU)
PY=""
for c in python3.11 python3.12; do if have "$c"; then PY="$(command -v "$c")"; break; fi; done
if [ -n "$PY" ]; then
  ok "Python: $PY ($("$PY" -c 'import sys;print(sys.version.split()[0])'))"
  "$PY" -c 'import venv, ensurepip' 2>/dev/null || { bad "il modulo venv/ensurepip manca per $PY (pacchetto python3-venv o equivalente)"; MISSING+=("python-venv"); }
else
  bad "Python 3.11 (o 3.12) non trovato"; MISSING+=("python")
fi

if [ "$ROCM" = "1" ]; then
  ok "Backend ROCm: torch/ctranslate2 su GPU, llama-cpp-python sulla ruota Vulkan"
  [ -n "$amd_name$amd_family" ] && ok "GPU AMD: ${amd_name:-AMD}${amd_gfx:+ ($amd_gfx)}${amd_family:+ — famiglia $amd_family}"
  if [ -e "$KFD" ]; then
    if [ -r "$KFD" ] && [ -w "$KFD" ]; then ok "/dev/kfd accessibile"
    else bad "/dev/kfd esiste ma non e' accessibile a $(id -un): sudo usermod -aG render,video \$USER, poi nuovo login"; MISSING+=("kfd-access"); fi
  else bad "/dev/kfd assente: serve il driver amdgpu del kernel con supporto compute (kernel recente o pacchetto amdgpu-dkms di AMD)"; MISSING+=("kfd"); fi
  for g in render video; do
    if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx "$g"; then ok "utente nel gruppo $g"; else warn "utente non nel gruppo $g (sudo usermod -aG $g \$USER, poi nuovo login)"; fi
  done
  if [ -d /sys/module/amdgpu ] || (have lsmod && lsmod 2>/dev/null | grep -q '^amdgpu'); then ok "driver amdgpu caricato"; else warn "driver amdgpu non visibile (lsmod)"; fi
  have rocminfo && ok "rocminfo presente (ROCm di sistema: non obbligatorio, le ruote di torch portano il loro runtime)" || warn "rocminfo assente: non e' un problema, ROCm di sistema non serve"
  if { have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so\.1'; } || [ -e /usr/lib/x86_64-linux-gnu/libvulkan.so.1 ] || [ -e /usr/lib64/libvulkan.so.1 ] || [ -e /usr/lib/libvulkan.so.1 ]; then
    ok "Loader Vulkan (libvulkan.so.1) presente"
  else bad "libvulkan.so.1 non trovata (serve per llama-cpp-python Vulkan)"; MISSING+=("vulkan"); fi
else
  if have nvidia-smi && nvidia-smi >/dev/null 2>&1; then
    ok "GPU NVIDIA: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -1)"
  elif [ "$FORCE_BACKEND" = "1" ]; then
    warn "nvidia-smi non disponibile (--force-backend: cross-build/test, si prosegue)"
  else
    bad "nvidia-smi non disponibile: senza driver NVIDIA il backend cuda non puo' funzionare. Mi fermo."; MISSING+=("nvidia-smi")
  fi
  if { have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so\.1'; } || [ -e /usr/lib/x86_64-linux-gnu/libvulkan.so.1 ]; then
    ok "Loader Vulkan (libvulkan.so.1) presente"
  else warn "libvulkan.so.1 non trovata: serve solo al glossario su Vulkan, non alla trascrizione"
  fi
fi

have ffmpeg && have ffprobe && ok "FFmpeg: $(command -v ffmpeg)" || { bad "ffmpeg/ffprobe non trovati"; MISSING+=("ffmpeg"); }
if have tesseract; then
  langs="$(tesseract --list-langs 2>/dev/null)"
  if echo "$langs" | grep -qx ita && echo "$langs" | grep -qx eng; then ok "Tesseract con ita+eng"; else bad "Tesseract senza ita/eng"; MISSING+=("tesseract-ita-eng"); fi
else bad "Tesseract non trovato"; MISSING+=("tesseract"); fi
have mkvextract && ok "MKVToolNix: $(command -v mkvextract)" || warn "MKVToolNix non trovato (serve solo per i sottotitoli VOBSUB)"
free_gb="$(df -Pk "$ROOT" | awk 'NR==2{printf "%d", $4/1048576}')"
need=15; [ "$ROCM" = "1" ] && need=20
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
      apt) CMDA=(sudo apt-get install -y $PKGS) ;;
      dnf) CMDA=(sudo dnf install -y $PKGS) ;;
      pacman) CMDA=(sudo pacman -S --needed $PKGS) ;;
      zypper) CMDA=(sudo zypper install -y $PKGS) ;;
    esac
    CMD="${CMDA[*]}"
    echo "  Comando per $PM (i nomi dei pacchetti possono variare con la versione della distribuzione):"
    echo "    $CMD"
    # solo i prerequisiti che un pacchetto di sistema puo' risolvere (non disco, accesso a /dev/kfd)
    PKGFIX=0; for m in "${MISSING[@]}"; do case "$m" in disco|kfd|kfd-access) ;; *) PKGFIX=1 ;; esac; done
    if [ "${TP_INSTALL_RETRY:-}" = "1" ] && [ "$CHECK" = "0" ]; then
      # secondo giro dopo l'installazione automatica: nessun terzo tentativo
      bad "Dopo l'installazione dei pacchetti manca ancora: ${MISSING[*]}. Non riprovo: controlla l'errore del gestore pacchetti, installa a mano ed esegui di nuovo ./install.sh."
      exit 2
    fi
    if [ "$CHECK" = "0" ] && [ "$PKGFIX" = "1" ]; then
      GO=0
      if [ "$SYSDEPS" = "1" ]; then ask "Eseguo questo comando con sudo?" && GO=1
      elif [ "$YES" = "1" ] || [ -t 0 ]; then ask "Li installo ora con sudo?" && GO=1; fi
      if [ "$GO" = "1" ]; then
        # senza terminale sudo non puo' chiedere la password: serve una credenziale gia' valida (o NOPASSWD)
        if ! have sudo || { [ ! -t 0 ] && ! sudo -n true 2>/dev/null; }; then
          bad "Non posso usare sudo qui (manca sudo, oppure non c'e' un terminale per la password). Esegui a mano:"
          echo "    $CMD"; echo "  poi rilancia ./install.sh"
          exit 2
        fi
        if [ "$PM" = "apt" ] && [ -z "$(ls -A "${TP_APT_LISTS:-/var/lib/apt/lists}" 2>/dev/null | grep -Ev '^(lock|partial)$')" ]; then
          echo "  elenchi dei pacchetti vuoti (macchina nuova): sudo apt-get update"
          sudo apt-get update || warn "apt-get update ha restituito un errore: provo comunque l'installazione."
        fi
        if "${CMDA[@]}"; then
          echo "  Pacchetti installati: ricontrollo i prerequisiti rilanciando lo script."
          export TP_INSTALL_RETRY=1
          exec "$BASH" "${BASH_SOURCE[0]}" ${1+"$@"}
        fi
        bad "Il gestore pacchetti ha restituito un errore. Correggi i nomi o esegui a mano:"
        echo "    $CMD"; echo "  poi rilancia ./install.sh"
        exit 2
      elif [ "$SYSDEPS" = "1" ]; then
        echo "  Installa a mano il comando qui sopra, poi rilancia ./install.sh"
      fi
    fi
  fi
fi
if [ "$CHECK" = "1" ]; then [ "${#MISSING[@]}" -eq 0 ] && exit 0 || exit 2; fi
[ -z "$PY" ] && { bad "Senza Python 3.11/3.12 non posso continuare (le distribuzioni con solo Python 3.13+ richiedono pyenv, uv o un repository dedicato)."; exit 2; }

echo; echo "== Ambiente Python (venv)"
# TP_INSTALL_VENV sposta il venv su cui si installa: i test di `linux_tests/test_install_retry.py`
# eseguono questo script e senza override installerebbero requirements.txt (torch CPU) nel venv
# di lavoro, distruggendo l'ambiente ROCm/Vulkan. Con la variabile puntano a una directory temporanea.
VENV="${TP_INSTALL_VENV:-$ROOT/venv}"
if [ ! -x "$VENV/bin/python" ]; then
  echo "  creo il venv in $VENV"
  "$PY" -m venv "$VENV" || { bad "Creazione del venv fallita (manca python3-venv?)"; exit 1; }
else ok "venv gia' presente (riuso)"; fi
VPY="$VENV/bin/python"

# Timbro del venv: backend con cui e' stato installato. Rilanciare lo script con un backend diverso non deve
# sostituire torch in silenzio: o e' lo stesso backend, o serve --force-backend (cross-build/test).
unset TP_STAMP_ACTION
STAMP="$VENV/.tp-backend"
if [ -f "$STAMP" ]; then
  _stamp_backend="$(sed -n 's/^backend=//p' "$STAMP" | head -1)"
  if [ -n "$_stamp_backend" ] && [ "$_stamp_backend" != "$BACKEND" ]; then
    if [ "$FORCE_BACKEND" = "1" ]; then
      warn "Il venv in $VENV e' timbrato '$_stamp_backend' e sto installando '$BACKEND' (--force-backend)"
      TP_STAMP_ACTION=rewrite
    else
      bad "Il venv in $VENV e' gia' installato per il backend '$_stamp_backend' (v. $STAMP): non lo sostituisco con '$BACKEND'."
      bad "Se e' davvero quello che vuoi: ./install.sh --backend=$BACKEND --force-backend (o usa un altro venv con TP_INSTALL_VENV)."
      exit 2
    fi
  else
    ok "venv gia' installato per il backend '$_stamp_backend': aggiorno i pacchetti"
  fi
fi

"$VPY" -m pip install --upgrade pip >/dev/null 2>&1

REQ="$ROOT/requirements.txt"
LV="$(sed -n 's/^[[:space:]]*llama[-_]cpp[-_]python==\([0-9.]*\).*/\1/Ip' "$ROOT/requirements.txt" | head -1)"
# llama-cpp-python: ruota CUDA con backend cuda, ruota Vulkan con rocm (una ruota ROCm non esiste). Il marcatore
# venv/llama_backend.txt dice quale ruota c'e': se non combacia si reinstalla, altrimenti pip la riterrebbe valida.
if [ -n "$LV" ]; then
  _have_idx="$(cat "$VENV/llama_backend.txt" 2>/dev/null || echo '')"
  if [ "$_have_idx" != "$LLAMA_IDX" ]; then
    echo "  llama-cpp-python $LV (ruota $LLAMA_IDX${_have_idx:+, ora c'e' $_have_idx})"
    if "$VPY" -m pip install --force-reinstall --no-deps --only-binary=:all: --index-url "https://abetlen.github.io/llama-cpp-python/whl/$LLAMA_IDX" "llama_cpp_python==$LV"; then
      echo "$LLAMA_IDX" > "$VENV/llama_backend.txt"     # letto da utils/llm_model_select.py: solo 'vulkan' cambia la scelta del modello
    else
      rm -f "$VENV/llama_backend.txt"
      bad "Download della ruota $LLAMA_IDX di llama-cpp-python fallito (rete o sito irraggiungibile). Mi fermo: proseguire installerebbe la ruota sbagliata. Controlla la connessione e rilancia ./install.sh"; exit 1
    fi
  else
    ok "llama-cpp-python $LV: ruota $LLAMA_IDX gia' presente"
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
if [ "$WITHGUI" = "1" ]; then
  # GUI desktop (legacy, ADR-002): dipendenze separate, non piu' nel default.
  REQGUI="$ROOT/requirements-gui.txt"
else
  REQGUI=""
fi
echo "  pip install -r $(basename "$REQ")  (puo' richiedere diversi minuti e alcuni GB di download)"
"$VPY" -m pip install -r "$REQ" || { bad "pip install fallito (vedi l'errore sopra; rilancia dopo averlo risolto)"; exit 1; }
if [ -n "$REQGUI" ]; then
  echo "  pip install -r requirements-gui.txt  (GUI desktop opzionale)"
  "$VPY" -m pip install -r "$REQGUI" || warn "GUI non installata: l'interfaccia resta la WebUI (python -m web.main)."
fi
if [ "$ROCM" = "1" ]; then
  # whisperx senza dipendenze (l'app lo usa solo in core/aligner.py; le sue dipendenze sono gia' in requirements-rocm.txt)
  WV="$(sed -n 's/^[[:space:]]*whisperx==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)"
  "$VPY" -m pip install --no-deps "whisperx==$WV" || warn "whisperx $WV non installato: l'allineamento parola per parola non funzionera'."
fi
verify_and_stamp || exit 1

ok "ambiente principale pronto"

if [ "$WITHMODELS" = "1" ]; then
  echo; echo "== Modelli locali (Hugging Face)"
  case "$QWENSIZE" in auto|7b|14b) ;; *) bad "--qwen-size deve essere auto, 7b o 14b"; exit 2 ;; esac
  QS="$QWENSIZE"
  if [ "$QS" = "auto" ]; then
    VR=0
    VR="$(python3 "$ROOT/utils/gpu_detect.py" --vram 2>/dev/null | head -1)"
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
  warn "Il Qwen in models/ lo sceglie l'app da sola in base alla VRAM. I GGUF di TranslateGemma: sezione qui sotto (--gguf)."
fi

# TranslateGemma GGUF: con --with-models vale auto; --gguf=none lo esclude. Mai senza dirlo: mostra file e dimensione e chiede conferma (--yes la salta).
[ -z "$GGUF" ] && { [ "$WITHMODELS" = "1" ] && GGUF=auto || GGUF=none; }
if [ "$GGUF" != "none" ]; then
  echo; echo "== TranslateGemma GGUF (Hugging Face)"
  GARGS=(--gguf "$GGUF")
  [ "$YES" = "1" ] && GARGS+=(--yes)
  [ -n "$GGUFDIR" ] && GARGS+=(--dest "$GGUFDIR")
  "$VPY" "$ROOT/utils/gguf_download.py" "${GARGS[@]}" || warn "Download dei GGUF non completato: rilancia ./install.sh --gguf=$GGUF (riprende da dove si e' fermato)."
fi

echo; echo "== Controllo finale"
SC=("$VPY" "$ROOT/scripts_manutenzione/selfcheck_env.py")
"${SC[@]}"; rc=$?
echo
echo "Avvio: ./run.sh   (le chiavi TMDB/HuggingFace/Claude si impostano a mano; questo script non le scrive)"
exit $rc
