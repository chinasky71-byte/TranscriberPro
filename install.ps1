<#
.SYNOPSIS
  Prepara l'ambiente di Transcriber Pro su un PC Windows dove non e' ancora installato.

.DESCRIPTION
  1. Controlla i prerequisiti (Python 3.11, driver NVIDIA, FFmpeg, Tesseract ita+eng, MKVToolNix, spazio su disco).
  2. Facoltativo: installa con winget i programmi mancanti (chiede conferma per ciascuno) e scarica da solo
     ita.traineddata/eng.traineddata di Tesseract (tessdata_best) se mancano.
  3. Crea il venv principale e installa requirements.txt (torch +cu126 e llama-cpp-python dagli indici speciali).
  4. Facoltativo: venv secondari (-WithNlp, -WithCanary, -WithGlossary) e modelli locali (-WithModels).
  5. Alla fine esegue scripts_manutenzione\selfcheck_env.py.

  Non copia ne' scrive mai credenziali: stampa quali file/chiavi vanno create a mano.
  E' idempotente: si puo' rilanciare, salta quello che c'e' gia'.

.PARAMETER CheckOnly            Solo il rapporto dei prerequisiti, nessuna modifica. Exit code 0 = ok, 2 = manca qualcosa di necessario.
.PARAMETER InstallSystemDeps    Propone l'installazione con winget dei programmi mancanti.
.PARAMETER WithNlp              Crea anche venv_nlp (spaCy + it_core_news_lg, correzione del genere).
.PARAMETER WithCanary           Crea anche venv_canary (NeMo / Canary-Qwen, solo inglese, ~10 GB).
.PARAMETER WithGlossary         Crea anche venv_glossary (glossario per-show, torch CPU).
.PARAMETER WithModels           Scarica da HuggingFace NLLB fine-tuned e Qwen2.5-14B GGUF (decine di GB).
.PARAMETER All                  Equivale a -WithNlp -WithCanary -WithGlossary -WithModels -InstallSystemDeps.
.PARAMETER Yes                  Non chiede conferme (assume si').
.PARAMETER SkipVerify           Salta il controllo finale.
.PARAMETER Gguf                 TranslateGemma-12B GGUF da Hugging Face (5-7 GB, anonimo, riprendibile, SHA-256) in models\translategemma-12b-gguf\.
                          auto = per VRAM TOTALE con le stesse soglie del selettore (utils/translator_path_select.py): Q4_K_M per le schede medie, IQ3_M per quelle da ~8 GB,
                          nulla se la VRAM e' troppo poca, se basta il bf16 (cuda/rocm) o senza GPU; su Vulkan, dove il bf16 non esiste, si scarica anche con molta VRAM; q3 solo se la chiedi; none = niente. Senza il parametro: auto se c'e' -WithModels, altrimenti nulla.
                          Chiede conferma (-Yes la salta). Scarica i file e basta: non cambia nessuna impostazione dell'app.
.PARAMETER GgufDir              Cartella di destinazione dei GGUF (default: models\translategemma-12b-gguf, quella che l'app scansiona).
.PARAMETER QwenSize             Con -WithModels: Qwen2.5 da scaricare. auto = 14B con GPU da 12 GB o piu', 7B con GPU piu' piccola o senza GPU.
.PARAMETER GpuBackend         Senza il parametro: comportamento di sempre (ruota CUDA di llama-cpp-python). cuda = come senza; cpu = come -NoGpu;
                          vulkan = torch su CPU + llama-cpp-python Vulkan (glossario su GPU AMD/Intel; trascrizione e traduzione su CPU);
                          auto = sceglie con utils\gpu_detect.py --backend (cuda, vulkan o cpu); rocm = non disponibile su Windows (fase F8).
.PARAMETER NoGpu                 PC senza GPU NVIDIA: il driver non e' richiesto e il controllo finale salta i test CUDA (l'app gira ~10 volte piu' lenta).
.PARAMETER VenvRoot             Cartella dove creare i venv (default: la cartella del progetto). Serve per prove.
.PARAMETER PythonExe            Percorso di un python.exe 3.11 (default: cerca "py -3.11" o "python").

.EXAMPLE
  .\install.ps1 -CheckOnly
  .\install.ps1 -InstallSystemDeps -WithNlp
  .\install.ps1 -All -Yes
#>
[CmdletBinding(PositionalBinding=$false)]
param(
    [switch]$CheckOnly,
    [switch]$InstallSystemDeps,
    [switch]$WithNlp,
    [switch]$WithCanary,
    [switch]$WithGlossary,
    [switch]$WithModels,
    [switch]$All,
    [switch]$Yes,
    [switch]$SkipVerify,
    [switch]$NoGpu,
    [ValidateSet('', 'auto', 'cuda', 'vulkan', 'rocm', 'cpu')][string]$GpuBackend = '',
    [ValidateSet('', 'auto', 'q4', 'iq3', 'q3', 'none')][string]$Gguf = '',
    [string]$GgufDir = '',
    [ValidateSet('auto', '7b', '14b')][string]$QwenSize = 'auto',
    [string]$VenvRoot = '',
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Continue'   # i comandi nativi scrivono su stderr: si controlla $LASTEXITCODE esplicitamente
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $VenvRoot) { $VenvRoot = $Root }
if ($All) { $WithNlp = $true; $WithCanary = $true; $WithGlossary = $true; $WithModels = $true; $InstallSystemDeps = $true }
if (-not $CheckOnly) { try { Start-Transcript -Path (Join-Path $Root 'install_log.txt') -Force | Out-Null } catch { } }
function Fail($msg) { Write-Host "  [KO]  $msg" -ForegroundColor Red; try { Stop-Transcript | Out-Null } catch { }; exit 1 }

$script:Missing = New-Object System.Collections.ArrayList     # necessari mancanti
$script:Optional = New-Object System.Collections.ArrayList    # facoltativi mancanti

function Write-Head($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Write-Ok($t)   { Write-Host "  [OK]  $t" -ForegroundColor Green }
function Write-Warn($t) { Write-Host "  [!!]  $t" -ForegroundColor Yellow }
function Write-Bad($t)  { Write-Host "  [KO]  $t" -ForegroundColor Red }
function Confirm-Step($question) {
    if ($Yes) { return $true }
    $a = Read-Host "$question [s/N]"
    return ($a -match '^(s|si|y|yes)$')
}
function Find-Exe($name, $extra) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in $extra) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}
function Add-Problem($name, $required, $hint, $wingetId) {
    $o = [pscustomobject]@{ Name = $name; Hint = $hint; Winget = $wingetId }
    if ($required) { [void]$script:Missing.Add($o) } else { [void]$script:Optional.Add($o) }
}

# ------------------------------------------------------------------ prerequisiti
Write-Head 'Prerequisiti'
if (-not [Environment]::Is64BitOperatingSystem -or $env:OS -ne 'Windows_NT') {
    Write-Bad 'Serve Windows a 64 bit.'; Add-Problem 'Windows 64 bit' $true 'Transcriber Pro e'' solo per Windows 10/11 x64' $null
} else { Write-Ok 'Windows 64 bit' }

# Python 3.11 a 64 bit
function Test-Py311($exe) {
    try {
        $r = (& $exe -c "import sys,struct;print(int(sys.version_info[:2]==(3,11) and struct.calcsize('P')==8))" 2>$null)
        return ($LASTEXITCODE -eq 0 -and $r -and $r.Trim() -eq '1')
    } catch { return $false }
}
$Py = $null
if ($PythonExe) {
    if ((Test-Path $PythonExe) -and (Test-Py311 $PythonExe)) { $Py = $PythonExe }
    else { Write-Bad "-PythonExe ($PythonExe) non e' un Python 3.11 a 64 bit funzionante." }
} else {
    $pyl = Get-Command py -ErrorAction SilentlyContinue
    if ($pyl) {
        try { $p = (& py -3.11 -c "import sys;print(sys.executable)" 2>$null); if ($LASTEXITCODE -eq 0 -and $p -and (Test-Py311 $p.Trim())) { $Py = $p.Trim() } } catch { }
    }
    if (-not $Py) {
        $pp = Get-Command python -ErrorAction SilentlyContinue
        if ($pp -and (Test-Py311 $pp.Source)) { $Py = $pp.Source }
    }
}
if ($Py) { Write-Ok "Python 3.11: $Py" } else {
    Write-Bad 'Python 3.11 non trovato (serve ESATTAMENTE la 3.11: le ruote di torch/ctranslate2 sono per cp311).'
    Add-Problem 'Python 3.11' $true 'winget install Python.Python.3.11' 'Python.Python.3.11'
}

# -GpuBackend: senza il parametro non cambia nulla. 'cpu' = -NoGpu; 'vulkan' = ruote CPU di torch + llama Vulkan ($NoGpu e $LlamaIdx).
$LlamaIdx = 'cpu'
if ($GpuBackend -eq 'auto') {
    if ($NoGpu) { $GpuBackend = 'cpu' }
    elseif ($Py) {
        $gb = ''
        try { $gb = ((& $Py (Join-Path $Root 'utils\gpu_detect.py') --backend 2>$null) | Select-Object -First 1) } catch { }
        if ($gb) { $gb = "$gb".Trim() }
        if ($gb -notin @('cuda', 'rocm', 'vulkan', 'cpu')) { $gb = 'cpu' }
        Write-Host "  gpu_detect: backend consigliato = $gb"
        if ($gb -eq 'rocm') { Write-Warn 'ROCm non e'' disponibile su Windows (fase F8): uso vulkan (glossario su GPU, il resto su CPU).'; $gb = 'vulkan' }
        $GpuBackend = $gb
    } else { Write-Warn '-GpuBackend auto: Python 3.11 non trovato, impossibile rilevare la GPU; si procede come senza il parametro.'; $GpuBackend = '' }
}
if ($GpuBackend -eq 'rocm') { Fail '-GpuBackend rocm non e'' disponibile su Windows (fase F8 del piano Linux/AMD, rinviata).' }
if ($GpuBackend -and $NoGpu -and $GpuBackend -ne 'cpu') { Fail "-NoGpu equivale a -GpuBackend cpu: non si combina con -GpuBackend $GpuBackend" }
if ($GpuBackend -eq 'cpu') { $NoGpu = $true }
if ($GpuBackend -eq 'vulkan') {
    $NoGpu = $true; $LlamaIdx = 'vulkan'
    Write-Warn 'Backend Vulkan: llama-cpp-python usera'' la GPU (solo il glossario); trascrizione e traduzione girano su CPU.'
    if (Test-Path (Join-Path $env:windir 'System32\vulkan-1.dll')) { Write-Ok 'Loader Vulkan (vulkan-1.dll) presente' }
    else { Write-Bad 'vulkan-1.dll non trovata: aggiorna il driver della scheda video.'; Add-Problem 'Driver Vulkan' $true 'Aggiorna il driver della scheda video (AMD/Intel/NVIDIA)' $null }
}

# Driver NVIDIA / GPU
$smi = Find-Exe 'nvidia-smi' @('C:\Windows\System32\nvidia-smi.exe', 'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe')
if ($NoGpu) { Write-Warn 'Modalita'' senza GPU (-NoGpu): l''app gira solo su CPU, ~10 volte piu'' lenta.' }
elseif ($smi) {
    $line = $null; $smiExit = 1
    # l'output va letto per intero: con `| Select-Object -First 1` la pipeline si chiude in anticipo e $LASTEXITCODE non e' 0
    try { $smiOut = @(& $smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null); $smiExit = $LASTEXITCODE; $line = ($smiOut | Select-Object -First 1) } catch { }
    $parts = @(); if ($smiExit -eq 0 -and $line) { $parts = @($line -split ',') }
    if ($parts.Count -ge 3) {
        $gpuName = $parts[0].Trim(); $drv = [double]($parts[1].Trim() -replace '[^0-9.]', ''); $mem = [int](($parts[2] -replace '[^0-9]', ''))
        Write-Ok "GPU: $gpuName, driver $drv, VRAM $mem MiB"
        if ($drv -lt 528) { Write-Bad "Driver troppo vecchio ($drv): per CUDA 12.x serve >= 528 (consigliato >= 560)."; Add-Problem 'Driver NVIDIA' $true 'Aggiorna il driver da nvidia.com/drivers' $null }
        elseif ($drv -lt 560) { Write-Warn "Driver ${drv}: funziona, ma si consiglia >= 560 per CUDA 12.6." }
        if ($mem -lt 6000) { Write-Warn "VRAM $mem MiB: sotto i 6 GB minimi consigliati." }
    } else {
        Write-Bad 'nvidia-smi presente ma non riesce a parlare col driver (nessuna GPU vista o driver guasto).'
        Add-Problem 'Driver NVIDIA' $true 'Reinstalla il driver da nvidia.com/drivers (oppure usa -NoGpu su un PC senza GPU)' $null
    }
} else {
    Write-Bad 'nvidia-smi non trovato: driver NVIDIA assente? (senza GPU l''app gira ma ~10 volte piu'' lenta: usa -NoGpu)'
    Add-Problem 'Driver NVIDIA' $true 'Installa il driver da nvidia.com/drivers (non serve il CUDA Toolkit per torch/Whisper)' $null
}
Write-Host '        (torch e Whisper NON richiedono il CUDA Toolkit: le librerie CUDA arrivano con le ruote pip. Anche llama-cpp-python'
Write-Host '        le trova in torch\lib: l''app aggiunge quella cartella al PATH da sola. Il controllo finale lo verifica.)'

# Visual C++ Redistributable (torch, ctranslate2 e llama.dll richiedono MSVCP140.dll di sistema)
if (Test-Path (Join-Path $env:WINDIR 'System32\msvcp140.dll')) { Write-Ok 'Visual C++ Redistributable 2015-2022 x64' }
else { Write-Bad 'Visual C++ Redistributable mancante (MSVCP140.dll).'; Add-Problem 'Visual C++ Redistributable' $true 'winget install Microsoft.VCRedist.2015+.x64' 'Microsoft.VCRedist.2015+.x64' }

# FFmpeg
$ff = Find-Exe 'ffmpeg' @((Join-Path $env:USERPROFILE 'scoop\shims\ffmpeg.exe'))
$fp = Find-Exe 'ffprobe' @((Join-Path $env:USERPROFILE 'scoop\shims\ffprobe.exe'))
if ($ff -and $fp) { Write-Ok "FFmpeg: $ff" } else { Write-Bad 'FFmpeg/ffprobe non nel PATH.'; Add-Problem 'FFmpeg' $true 'winget install Gyan.FFmpeg (poi riapri il terminale)' 'Gyan.FFmpeg' }

# Tesseract + tessdata
$tessInPath = [bool](Get-Command tesseract -ErrorAction SilentlyContinue)
$tess = Find-Exe 'tesseract' @('C:\Program Files\Tesseract-OCR\tesseract.exe', (Join-Path $env:USERPROFILE 'scoop\shims\tesseract.exe'))
if ($tess -and -not $tessInPath) { Write-Warn "Tesseract trovato in $tess ma NON nel PATH: l'app lo cerca nel PATH o nel percorso 'ocr_tesseract_path' delle Impostazioni. Aggiungilo al PATH." }
if ($tess) {
    $langs = @(); try { $langs = (& $tess --list-langs 2>$null) } catch { }
    if (($langs -contains 'ita') -and ($langs -contains 'eng')) { Write-Ok "Tesseract con ita+eng: $tess" }
    else { Write-Bad "Tesseract trovato ($tess) ma mancano ita/eng."; Add-Problem 'Tesseract ita+eng' $true 'scarica ita.traineddata e eng.traineddata da github.com/tesseract-ocr/tessdata_best nella cartella tessdata' $null }
} else { Write-Bad 'Tesseract non trovato (serve per l''OCR dei sottotitoli bitmap).'; Add-Problem 'Tesseract' $true 'winget install UB-Mannheim.TesseractOCR, poi ita/eng.traineddata da tessdata_best' 'UB-Mannheim.TesseractOCR' }

# MKVToolNix (facoltativo: solo VOBSUB)
$mkvInPath = [bool](Get-Command mkvextract -ErrorAction SilentlyContinue)
$mkv = Find-Exe 'mkvextract' @('C:\Program Files\MKVToolNix\mkvextract.exe', (Join-Path $env:USERPROFILE 'scoop\shims\mkvextract.exe'))
if ($mkv -and -not $mkvInPath -and $mkv -notmatch 'scoop') { Write-Warn "MKVToolNix trovato in $mkv ma NON nel PATH: l'app lo cerca solo nel PATH o nello shim di scoop. Aggiungilo al PATH." }
if ($mkv) { Write-Ok "MKVToolNix: $mkv" } else { Write-Warn 'MKVToolNix non trovato (serve solo per i sottotitoli VOBSUB).'; Add-Problem 'MKVToolNix' $false 'winget install MoritzBunkus.MKVToolNix' 'MoritzBunkus.MKVToolNix' }

# Spazio su disco
try {
    $drive = (Get-Item $VenvRoot).PSDrive
    $freeGb = [math]::Round($drive.Free / 1GB)
    $need = 15; if ($WithCanary) { $need += 10 }; if ($WithModels) { $need += 50 }
    if ($freeGb -lt $need) { Write-Bad "Spazio libero su $($drive.Name): $freeGb GB, ne servono circa $need."; Add-Problem 'Spazio disco' $true "servono ~$need GB liberi" $null }
    else { Write-Ok "Spazio libero su $($drive.Name): $freeGb GB (servono ~$need)" }
} catch { Write-Warn 'Spazio su disco non verificabile.' }

# ------------------------------------------------------------------ credenziali (solo rapporto)
Write-Head 'Credenziali e file da creare a mano (non vengono mai copiati ne'' scritti da questo script)'
$userHome = $env:USERPROFILE
foreach ($f in @(
        @{ n = 'tmdb_api.txt'; d = 'chiave TMDB (locandine): nella cartella del progetto oppure in ~\.transcriberpro\' },
        @{ n = 'omdb_api.txt'; d = 'chiave OMDb (facoltativa): nella cartella del progetto oppure in ~\.transcriberpro\' })) {
    $has = (Test-Path (Join-Path $Root $f.n)) -or (Test-Path (Join-Path $userHome ('.transcriberpro\' + $f.n)))
    if ($has) { Write-Ok "$($f.n) presente" } else { Write-Warn "$($f.n): $($f.d)" }
}
Write-Host '        Nelle Impostazioni dell''app: token HuggingFace (diarizzazione pyannote: accetta le condizioni di'
Write-Host '        pyannote/speaker-diarization-3.1 su huggingface.co), chiavi Claude/OpenAI se usi la traduzione cloud.'

# ------------------------------------------------------------------ installazione dei programmi mancanti
if ($InstallSystemDeps -and -not $CheckOnly -and ($script:Missing.Count + $script:Optional.Count) -gt 0) {
    Write-Head 'Programmi mancanti (winget)'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    foreach ($p in @($script:Missing) + @($script:Optional)) {
        if (-not $p.Winget) { Write-Warn "$($p.Name): manuale -> $($p.Hint)"; continue }
        if (-not $winget) { Write-Warn "winget non disponibile: $($p.Name) -> $($p.Hint)"; continue }
        if (Confirm-Step "Installo $($p.Name) con winget ($($p.Winget))?") {
            & winget install --id $($p.Winget) -e --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { Write-Warn "winget ha restituito $LASTEXITCODE per $($p.Name)" }
        }
    }
    Write-Warn 'Riapri il terminale e rilancia install.ps1: il PATH dei programmi appena installati non e'' visibile a questa sessione.'
}

# ------------------------------------------------------------------ lingue Tesseract (ita+eng)
function Get-TessLangs($exe) {
    $l = @(); try { $l = @(& $exe --list-langs 2>$null) } catch { }
    return $l
}
function Ensure-TessLangs($exe) {
    # Scarica le lingue mancanti da tessdata_best nella cartella tessdata che Tesseract stesso dichiara. Ritorna $true se ita+eng ci sono.
    $langs = Get-TessLangs $exe
    $need = @('ita', 'eng') | Where-Object { $langs -notcontains $_ }
    if ($need.Count -eq 0) { return $true }
    $dir = $null
    $m = [regex]::Match(($langs | Select-Object -First 1), '"([^"]+)"')
    if ($m.Success) { $dir = $m.Groups[1].Value } else { $dir = Join-Path (Split-Path -Parent $exe) 'tessdata' }
    if (-not (Test-Path $dir)) { Write-Warn "Cartella tessdata non trovata ($dir): scarica a mano ita/eng.traineddata da tessdata_best."; return $false }
    if (-not (Confirm-Step "Scarico $($need -join '+') (tessdata_best, ~15 MB ciascuna) in $dir ?")) { return $false }
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
    $oldPref = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
    try {
        foreach ($l in $need) {
            $tmp = Join-Path $env:TEMP "tp_$l.traineddata"
            try {
                Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/tesseract-ocr/tessdata_best/raw/main/$l.traineddata" -OutFile $tmp
            } catch { Write-Warn "Download di $l.traineddata fallito: $($_.Exception.Message)"; continue }
            if (-not (Test-Path $tmp) -or (Get-Item $tmp).Length -lt 4MB) { Write-Warn "$l.traineddata scaricato in modo incompleto: lo ignoro."; Remove-Item $tmp -ErrorAction SilentlyContinue; continue }
            $dest = Join-Path $dir "$l.traineddata"
            try { Copy-Item -LiteralPath $tmp -Destination $dest -Force -ErrorAction Stop }
            catch {
                Write-Warn "Scrittura in $dir negata (cartella di sistema): riprovo con i permessi di amministratore (UAC)."
                $qt = $tmp -replace "'", "''"; $qd = $dest -replace "'", "''"
                try { Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', "Copy-Item -LiteralPath '$qt' -Destination '$qd' -Force" }
                catch { }
                if (-not (Test-Path $dest)) { Write-Warn "Copia con amministratore non riuscita: copia a mano $tmp in $dir (come $l.traineddata)." }
            }
            if (Test-Path $dest) { Remove-Item $tmp -ErrorAction SilentlyContinue }
        }
    } finally { $ProgressPreference = $oldPref }
    $langs = Get-TessLangs $exe
    return (($langs -contains 'ita') -and ($langs -contains 'eng'))
}
if ($InstallSystemDeps -and -not $CheckOnly) {
    $tessNow = Find-Exe 'tesseract' @('C:\Program Files\Tesseract-OCR\tesseract.exe', (Join-Path $env:USERPROFILE 'scoop\shims\tesseract.exe'))
    if ($tessNow) {
        Write-Head 'Lingue Tesseract'
        if (Ensure-TessLangs $tessNow) {
            Write-Ok 'Tesseract con ita+eng'
            $inPath = [bool](Get-Command tesseract -ErrorAction SilentlyContinue)
            if (-not $inPath) { Write-Warn "Tesseract ($tessNow) NON e' nel PATH: aggiungilo al PATH (o imposta 'ocr_tesseract_path' nelle Impostazioni) e riapri il terminale." }
            for ($i = $script:Missing.Count - 1; $i -ge 0; $i--) {
                $nm = $script:Missing[$i].Name
                if ($nm -eq 'Tesseract ita+eng' -or ($nm -eq 'Tesseract' -and $inPath)) { $script:Missing.RemoveAt($i) }
            }
        }
    }
}

# ------------------------------------------------------------------ esito preflight
Write-Head 'Esito prerequisiti'
if ($script:Missing.Count -eq 0) { Write-Ok 'Tutti i prerequisiti necessari sono a posto.' }
else { foreach ($m in $script:Missing) { Write-Bad "$($m.Name): $($m.Hint)" } }
foreach ($m in $script:Optional) { Write-Warn "(facoltativo) $($m.Name): $($m.Hint)" }
if ($CheckOnly) {
    try { Stop-Transcript | Out-Null } catch { }
    if ($script:Missing.Count -gt 0) { exit 2 } else { exit 0 }
}
if (-not $Py) { Write-Bad 'Senza Python 3.11 non posso continuare.'; try { Stop-Transcript | Out-Null } catch { }; exit 2 }
if ($script:Missing.Count -gt 0 -and -not (Confirm-Step 'Ci sono prerequisiti mancanti. Continuo comunque con i pacchetti Python?')) {
    try { Stop-Transcript | Out-Null } catch { }; exit 2
}

# ------------------------------------------------------------------ venv
function Ensure-Venv($dirName, $reqFile, $label) {
    Write-Head "Ambiente Python: $label ($dirName)"
    $req = Join-Path $Root $reqFile
    if (-not (Test-Path $req)) { Fail "File mancante: $req" }
    $venv = Join-Path $VenvRoot $dirName
    $vpy = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $vpy)) {
        Write-Host "  creo il venv in $venv"
        & $Py -m venv $venv | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail "Creazione venv fallita ($venv)" }
    } else {
        $ok = $false
        try { $r = (& $vpy -c "import sys,struct;print(int(sys.version_info[:2]==(3,11) and struct.calcsize('P')==8))" 2>$null); $ok = ($LASTEXITCODE -eq 0 -and $r -and $r.Trim() -eq '1') } catch { }
        if (-not $ok) { Fail "Il venv esistente ($venv) non contiene un Python 3.11 64 bit funzionante (copiato da un altro PC?). Cancellalo e rilancia." }
        Write-Ok 'venv gia'' presente (riuso)'
    }
    & $vpy -m pip install --upgrade pip 2>&1 | Out-Null
    if ($NoGpu -and $dirName -eq 'venv') {
        # Senza driver NVIDIA (nvcuda.dll) la ruota CUDA di llama-cpp-python non carica llama.dll: si usa la ruota CPU, stessa versione del pin.
        # Installata PRIMA di requirements.txt, che la trova gia' soddisfatta e non scarica quella CUDA (~536 MB).
        $llamaVer = $null
        foreach ($ln in (Get-Content $req)) { if ($ln -match '^\s*llama[-_]cpp[-_]python==([0-9.]+)') { $llamaVer = $Matches[1] } }
        if ($llamaVer) {
            Write-Host "  llama-cpp-python $llamaVer (ruota $LlamaIdx, senza GPU NVIDIA)"
            & $vpy -m pip install --force-reinstall --no-deps --only-binary=:all: --index-url "https://abetlen.github.io/llama-cpp-python/whl/$LlamaIdx" "llama_cpp_python==$llamaVer" | Out-Host
            if ($LASTEXITCODE -eq 0) {
                # letto da utils\llm_model_select.py: solo 'vulkan' cambia la scelta del modello
                Set-Content -Path (Join-Path $venv 'llama_backend.txt') -Value $LlamaIdx -Encoding ASCII
            } else {
                Remove-Item (Join-Path $venv 'llama_backend.txt') -ErrorAction SilentlyContinue
                Fail "Download della ruota $LlamaIdx di llama-cpp-python fallito (rete o sito irraggiungibile). Mi fermo: proseguire installerebbe la ruota CUDA, inutile senza GPU NVIDIA. Controlla la connessione e rilancia."
            }
        } else { Write-Warn 'Versione di llama_cpp_python non letta da requirements.txt (formato inatteso): ruota CPU non installata.' }
        # torch/torchaudio CPU (~250 MB invece di ~2,9 GB della ruota +cu126). Si installano PRIMA e si tolgono dal file dei requisiti
        # usato da pip, altrimenti pip le rimpiazzerebbe con le +cu126 dei pin.
        $tv = $null; $av = $null
        foreach ($ln in (Get-Content $req)) {
            if ($ln -match '^\s*torch==([0-9.]+)') { $tv = $Matches[1] }
            if ($ln -match '^\s*torchaudio==([0-9.]+)') { $av = $Matches[1] }
        }
        if ($tv -and $av) {
            Write-Host "  torch $tv / torchaudio $av (ruote CPU, senza GPU)"
            & $vpy -m pip install --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch==$tv" "torchaudio==$av" | Out-Host
            if ($LASTEXITCODE -eq 0) {
                $req = Join-Path $env:TEMP 'tp_requirements_nogpu.txt'
                Get-Content (Join-Path $Root $reqFile) | Where-Object { $_ -notmatch '^\s*(torch|torchaudio)==' } | Set-Content -Path $req -Encoding ASCII
            } else { Fail 'Download delle ruote CPU di torch fallito (rete o download.pytorch.org irraggiungibile). Mi fermo: proseguire installerebbe torch CUDA (+cu126, ~2,9 GB), inutile senza GPU NVIDIA. Controlla la connessione e rilancia con -NoGpu.' }
        } else { Write-Warn 'Versioni di torch/torchaudio non lette da requirements.txt (formato inatteso): ruote CPU non installate.' }
    }
    if ((-not $NoGpu) -and $dirName -eq 'venv' -and (Test-Path (Join-Path $venv 'llama_backend.txt'))) {
        # venv riusato con la ruota CPU/Vulkan di llama (esecuzione precedente con -NoGpu / -GpuBackend): pip la riterrebbe valida
        # (stessa versione), quindi si rimette la ruota CUDA dei requisiti. Senza marcatore non si tocca nulla.
        $llamaVer = $null
        foreach ($ln in (Get-Content $req)) { if ($ln -match '^\s*llama[-_]cpp[-_]python==([0-9.]+)') { $llamaVer = $Matches[1] } }
        if ($llamaVer) {
            Write-Host "  llama-cpp-python ${llamaVer}: ripristino la ruota CUDA (il venv aveva un'altra ruota)"
            & $vpy -m pip install --force-reinstall --no-deps --only-binary=:all: --index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 "llama_cpp_python==$llamaVer" | Out-Host
            if ($LASTEXITCODE -eq 0) { Remove-Item (Join-Path $venv 'llama_backend.txt') -ErrorAction SilentlyContinue }
            else { Write-Warn 'Ruota CUDA di llama-cpp-python non reinstallata: il venv conserva quella di prima.' }
        }
    }
    Write-Host "  pip install -r $reqFile  (puo' richiedere diversi minuti e alcuni GB di download)"
    & $vpy -m pip install -r $req | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "pip install fallito per $reqFile (vedi lerrore sopra; rilancia dopo averlo risolto)" }
    Write-Ok "$label pronto"
    return $vpy
}

$MainPy = Ensure-Venv 'venv' 'requirements.txt' 'principale'
if ($WithNlp)      { [void](Ensure-Venv 'venv_nlp' 'requirements-nlp.txt' 'NLP / spaCy (correzione genere)') }
if ($WithCanary)   { [void](Ensure-Venv 'venv_canary' 'requirements-canary.txt' 'Canary / NeMo (ASR inglese, facoltativo)') }
if ($WithGlossary) { [void](Ensure-Venv 'venv_glossary' 'requirements-glossary.txt' 'Glossario per-show') }
if ($VenvRoot -ne $Root) { Write-Warn "VenvRoot diverso dalla cartella del progetto: l'app cerca i venv secondari accanto a main.py." }

# ------------------------------------------------------------------ modelli
if ($WithModels) {
    Write-Head 'Modelli locali (HuggingFace)'
    $qsize = $QwenSize
    if ($qsize -eq 'auto') {
        $vram = 0
        if (-not $NoGpu) {
            try { $v = @(& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null); $vram = [int](($v | Measure-Object -Maximum).Maximum) } catch { }
        }
        $qsize = if ($vram -ge 12000) { '14b' } else { '7b' }
    }
    if ($qsize -eq '7b') { Write-Host '  Qwen2.5-7B-Instruct Q4_K_M (2 file, ~4,7 GB: ripiego per GPU sotto i 12 GB) -> models\' }
    else { Write-Host '  Qwen2.5-14B-Instruct Q4_K_M (3 file, ~9 GB) -> models\' }
    Write-Host '  NLLB-200 3.3B fine-tuned EN->IT (Chinasky71/nllb-200-3.3b-it-subtitles, molti GB) -> NLLB_Tranined\'
    if (Confirm-Step 'Scarico questi modelli?') {
        $tmp = Join-Path $env:TEMP 'tp_download_models.py'
        @'
import sys
from huggingface_hub import hf_hub_download, snapshot_download
root = sys.argv[1]
if sys.argv[2] == '7b':
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
'@ | Set-Content -Path $tmp -Encoding UTF8
        & $MainPy $tmp $Root $qsize | Out-Host
        if ($LASTEXITCODE -ne 0) { Write-Warn 'Download modelli non completato: rilancia install.ps1 -WithModels (riprende da dove si e'' fermato).' }
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
    Write-Host '  Poi, nelle Impostazioni dell''app, seleziona il percorso di NLLB fine-tuned -> NLLB_Tranined. Il Qwen in models\ (14B o 7B)'
    Write-Host '  lo sceglie l''app da sola in base alla VRAM (glossario e serbatoio), se non imposti un percorso a mano.'
    Write-Host '  Whisper large-v3, Qwen3-ASR, Demucs e pyannote si scaricano da soli al primo uso (pyannote richiede il token HF).'
}

# ------------------------------------------------------------------ TranslateGemma GGUF
# Con -WithModels vale auto; -Gguf none lo esclude. Mai senza dirlo: mostra file e dimensione e chiede conferma (-Yes la salta).
$gg = $Gguf
if (-not $gg) { $gg = if ($WithModels) { 'auto' } else { 'none' } }
if ($gg -ne 'none') {
    Write-Head 'TranslateGemma GGUF (Hugging Face)'
    $gargs = @('--gguf', $gg)
    if ($Yes) { $gargs += '--yes' }
    # -NoGpu vero (ruote CPU): niente GPU, niente GGUF. Con vulkan $NoGpu vale solo per torch: llama usa la GPU e il GGUF serve.
    if ($NoGpu -and $LlamaIdx -ne 'vulkan') { $gargs += '--no-gpu' }
    if ($GgufDir) { $gargs += @('--dest', $GgufDir.TrimEnd('\')) }
    & $MainPy (Join-Path $Root 'utils\gguf_download.py') @gargs | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Warn "Download dei GGUF non completato: rilancia install.ps1 -Gguf $gg (riprende da dove si e' fermato)." }
}

# ------------------------------------------------------------------ controllo finale
$rc = 0
if (-not $SkipVerify) {
    Write-Head 'Controllo finale'
    $sc = @(); if ($NoGpu) { $sc += '--no-gpu' }
    & $MainPy (Join-Path $Root 'scripts_manutenzione\selfcheck_env.py') @sc | Out-Host
    $rc = $LASTEXITCODE
}
Write-Head 'Fatto'
if ($rc -eq 0) { Write-Ok 'Ambiente pronto. Avvio: "Lancia Transcriptor.bat" oppure venv\Scripts\python main.py' }
else { Write-Warn 'Il controllo finale ha segnalato problemi: leggi l''elenco sopra e rilancia install.ps1 dopo averli risolti.' }
try { Stop-Transcript | Out-Null } catch { }
exit $rc
