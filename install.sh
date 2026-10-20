#!/usr/bin/env bash
# Prepara Transcriber Pro su Linux (qualsiasi distribuzione con apt, dnf, pacman o zypper; altrimenti stampa cosa installare).
# NON VERIFICATO SU LINUX REALE: scritto e controllato con `bash -n`, ma mai eseguito su una macchina Linux.
#
#   ./install.sh --check        solo il rapporto dei prerequisiti, nessuna modifica
#   ./install.sh                crea il venv e installa requirements.txt (chiede conferma per sudo)
#   ./install.sh --system-deps  propone anche l'installazione dei pacchetti di sistema con sudo
#   opzioni: --no-gpu (ruote CPU di torch e llama-cpp-python, ~250 MB invece di ~3 GB) --yes (nessuna domanda)
#
# Non copia ne' scrive mai credenziali. Non va lanciato come root (il venv deve essere dell'utente).
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK=0; SYSDEPS=0; NOGPU=0; YES=0
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --system-deps) SYSDEPS=1 ;;
    --no-gpu) NOGPU=1 ;;
    --yes) YES=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
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

if [ "$NOGPU" = "1" ]; then warn "Modalita' senza GPU (--no-gpu): l'app gira solo su CPU, ~10 volte piu' lenta."
elif have nvidia-smi && nvidia-smi >/dev/null 2>&1; then ok "GPU NVIDIA: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -1)"
else warn "nvidia-smi non disponibile: senza driver NVIDIA usa --no-gpu."; fi

have ffmpeg && have ffprobe && ok "FFmpeg: $(command -v ffmpeg)" || { bad "ffmpeg/ffprobe non trovati"; MISSING+=("ffmpeg"); }
if have tesseract; then
  langs="$(tesseract --list-langs 2>/dev/null)"
  if echo "$langs" | grep -qx ita && echo "$langs" | grep -qx eng; then ok "Tesseract con ita+eng"; else bad "Tesseract senza ita/eng"; MISSING+=("tesseract-ita-eng"); fi
else bad "Tesseract non trovato"; MISSING+=("tesseract"); fi
have mkvextract && ok "MKVToolNix: $(command -v mkvextract)" || warn "MKVToolNix non trovato (serve solo per i sottotitoli VOBSUB)"
free_gb="$(df -Pk "$ROOT" | awk 'NR==2{printf "%d", $4/1048576}')"
need=15; [ "$NOGPU" = "1" ] && need=6
[ "${free_gb:-0}" -ge "$need" ] && ok "Spazio libero: ${free_gb} GB (servono ~${need})" || { bad "Spazio libero ${free_gb} GB, ne servono ~${need}"; MISSING+=("disco"); }

# gestore pacchetti e nomi (ogni distribuzione chiama i pacchetti in modo diverso). I pacchetti Python si aggiungono solo se servono:
# se Python 3.11/3.12 c'e' gia' non si tocca; se manca solo il modulo venv si prende quello della versione trovata.
PM=""; PKGS=""; PYPKG=""; PYVER=""
[ -n "$PY" ] && PYVER="$("$PY" -c 'import sys;print("%d.%d" % sys.version_info[:2])')"
case " ${MISSING[*]:-} " in
  *" python "*) NEED_PY=all ;;
  *" python-venv "*) NEED_PY=venv ;;
  *) NEED_PY="" ;;
esac
if have apt-get; then PM="apt"
  [ "$NEED_PY" = "all" ] && PYPKG="python3 python3-venv"      # versione della distribuzione (deve essere 3.11 o 3.12)
  [ "$NEED_PY" = "venv" ] && PYPKG="python${PYVER}-venv"
  PKGS="$PYPKG ffmpeg mkvtoolnix tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng libxcb-cursor0 libxkbcommon-x11-0 libegl1 libfontconfig1"
elif have dnf; then PM="dnf"
  [ -n "$NEED_PY" ] && PYPKG="python3.11"
  PKGS="$PYPKG ffmpeg-free mkvtoolnix tesseract tesseract-langpack-ita tesseract-langpack-eng xcb-util-cursor libxkbcommon-x11 mesa-libEGL fontconfig"
elif have pacman; then PM="pacman"
  PKGS="ffmpeg mkvtoolnix-cli tesseract tesseract-data-ita tesseract-data-eng xcb-util-cursor libxkbcommon-x11 libglvnd fontconfig"
  [ "$NEED_PY" = "all" ] && warn "Arch: il pacchetto 'python' e' 3.13+, non supportato: serve python 3.11 (AUR 'python311') o 3.12, oppure pyenv/uv."
elif have zypper; then PM="zypper"
  [ -n "$NEED_PY" ] && PYPKG="python311"
  PKGS="$PYPKG ffmpeg mkvtoolnix tesseract-ocr tesseract-ocr-traineddata-italian tesseract-ocr-traineddata-english libxcb-cursor0 libxkbcommon-x11-0 libEGL1 fontconfig"
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
if [ "$NOGPU" = "1" ]; then
  # ruote CPU: llama-cpp-python (stessa versione del pin) e torch/torchaudio, tolte dal file usato da pip
  LV="$(sed -n 's/^[[:space:]]*llama[-_]cpp[-_]python==\([0-9.]*\).*/\1/Ip' "$ROOT/requirements.txt" | head -1)"
  TV="$(sed -n 's/^[[:space:]]*torch==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)"
  AV="$(sed -n 's/^[[:space:]]*torchaudio==\([0-9.]*\).*/\1/p' "$ROOT/requirements.txt" | head -1)"
  if [ -n "$LV" ]; then
    echo "  llama-cpp-python $LV (ruota CPU)"
    "$VPY" -m pip install --force-reinstall --no-deps --only-binary=:all: --index-url https://abetlen.github.io/llama-cpp-python/whl/cpu "llama_cpp_python==$LV" \
      || warn "Ruota CPU di llama-cpp-python non installata: si prosegue con quella di requirements.txt."
  fi
  if [ -n "$TV" ] && [ -n "$AV" ]; then
    echo "  torch $TV / torchaudio $AV (ruote CPU)"
    if "$VPY" -m pip install --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch==$TV" "torchaudio==$AV"; then
      REQ="$(mktemp /tmp/tp_requirements_nogpu.XXXXXX)"; trap 'rm -f "$REQ"' EXIT
      grep -Ev '^[[:space:]]*(torch|torchaudio)==' "$ROOT/requirements.txt" > "$REQ"
    else warn "Ruote CPU di torch non installate: si prosegue con quelle di requirements.txt (+cu126, ~3 GB)."; fi
  fi
fi
echo "  pip install -r requirements.txt  (puo' richiedere diversi minuti e alcuni GB di download)"
"$VPY" -m pip install -r "$REQ" || { bad "pip install fallito (vedi l'errore sopra; rilancia dopo averlo risolto)"; exit 1; }
ok "ambiente principale pronto"

echo; echo "== Controllo finale"
SC=("$VPY" "$ROOT/scripts_manutenzione/selfcheck_env.py"); [ "$NOGPU" = "1" ] && SC+=("--no-gpu")
"${SC[@]}"; rc=$?
echo
echo "Avvio: ./run.sh   (le chiavi TMDB/HuggingFace/Claude si impostano a mano; questo script non le scrive)"
exit $rc
