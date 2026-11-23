# Instalator RPG Chronicles na Windowsa (uruchamiany przez instaluj-windows.bat).
# Można go uruchomić ponownie - pomija to, co już jest, i dokańcza resztę.
# Plik musi być w UTF-8 z BOM i z końcami linii CRLF (Windows PowerShell 5.1) - pilnuje tego test.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # pasek postępu Invoke-WebRequest spowalnia pobieranie kilkukrotnie
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$FfmpegDir = Join-Path $Root "ffmpeg"
$TorchIndex = "https://download.pytorch.org/whl/cpu"
$PythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

function Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Ok([string]$Text) { Write-Host "    [OK] $Text" -ForegroundColor Green }
function Info([string]$Text) { Write-Host "    $Text" }
function Fail([string]$Text) { throw $Text }

function Invoke-Checked([string]$Exe, [string[]]$Arguments, [string]$What) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "$What - błąd (kod $LASTEXITCODE). Przewiń wyżej, żeby zobaczyć szczegóły." }
}

function Find-Python311 {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        # Bez „Stop”: w PowerShellu 5.1 przekierowany stderr programu (brak 3.11) przerwałby skrypt
        $ErrorActionPreference = "Continue"
        $exe = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { return $exe.Trim() }
    }
    return $null
}

Write-Host "RPG Chronicles - instalacja na Windowsie" -ForegroundColor Yellow
Write-Host "Folder programu: $Root"
Write-Host "Potrzebne jest połączenie z internetem i ok. 5 GB miejsca. Całość trwa zwykle 10-20 minut."

try {
    # --- 1. Python 3.11 -------------------------------------------------------------------------
    Step "1/6 Python 3.11"
    $Python = Find-Python311
    if ($Python) {
        Ok "jest: $Python"
    } else {
        Info "Pobieram instalator Pythona 3.11 z python.org..."
        $installer = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
        Invoke-WebRequest -Uri $PythonUrl -OutFile $installer
        Info "Instaluję (tylko dla Twojego konta, bez zmiany innych Pythonów)..."
        $p = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
            "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_test=0", "Include_launcher=1",
            "InstallLauncherAllUsers=0", "SimpleInstall=1")
        if ($p.ExitCode -ne 0) { Fail "Instalacja Pythona nie powiodła się (kod $($p.ExitCode))." }
        Remove-Item $installer -ErrorAction SilentlyContinue
        $Python = Find-Python311
        if (-not $Python) { Fail "Nie znalazłem Pythona 3.11 po instalacji." }
        Ok "zainstalowany: $Python"
    }

    # --- 2. Biblioteki Microsoft Visual C++ (wymaga ich PyTorch) ---------------------------------
    Step "2/6 Biblioteki Microsoft Visual C++"
    $vc = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
    if ($vc -and $vc.Installed -eq 1) {
        Ok "są (wersja $($vc.Version))"
    } else {
        Info "Pobieram Visual C++ Redistributable od Microsoftu. Windows zapyta o zgodę administratora."
        $vcInstaller = Join-Path $env:TEMP "vc_redist.x64.exe"
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vcInstaller
        $p = Start-Process -FilePath $vcInstaller -Wait -PassThru -Verb RunAs -ArgumentList "/install", "/quiet", "/norestart"
        Remove-Item $vcInstaller -ErrorAction SilentlyContinue
        if ($p.ExitCode -notin 0, 1638, 3010) { Fail "Instalacja Visual C++ nie powiodła się (kod $($p.ExitCode))." }
        Ok "zainstalowane"
    }

    # --- 3. ffmpeg (biblioteki współdzielone - potrzebuje ich torchcodec) -------------------------
    Step "3/6 ffmpeg"
    if (Test-Path (Join-Path $FfmpegDir "bin\ffmpeg.exe")) {
        Ok "jest w $FfmpegDir"
    } else {
        Info "Szukam najnowszej wersji (github.com/BtbN/FFmpeg-Builds)..."
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
        $assets = foreach ($a in $release.assets) {
            if ($a.name -match '^ffmpeg-n(\d+)\.(\d+)-latest-win64-gpl-shared-[\d.]+\.zip$') {
                [pscustomobject]@{ Name = $a.name; Url = $a.browser_download_url
                                   Major = [int]$Matches[1]; Minor = [int]$Matches[2] }
            }
        }
        # torchcodec obsługuje ffmpeg 4-9; nowszą wersję bierzemy tylko, gdy nie ma żadnej z tych
        $supported = @($assets | Where-Object { $_.Major -le 9 })
        if ($supported.Count -eq 0) { $supported = @($assets) }
        $asset = $supported | Sort-Object Major, Minor -Descending | Select-Object -First 1
        if (-not $asset) { Fail "Nie znalazłem paczki ffmpeg do pobrania." }
        Info "Pobieram $($asset.Name)..."
        $zip = Join-Path $env:TEMP $asset.Name
        Invoke-WebRequest -Uri $asset.Url -OutFile $zip
        $unpack = Join-Path $env:TEMP "rpg-chronicler-ffmpeg"
        if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $unpack
        $inner = Get-ChildItem $unpack -Directory | Select-Object -First 1
        if (Test-Path $FfmpegDir) { Remove-Item $FfmpegDir -Recurse -Force }
        Move-Item $inner.FullName $FfmpegDir
        Remove-Item $zip, $unpack -Recurse -Force -ErrorAction SilentlyContinue
        Ok "rozpakowany do $FfmpegDir"
    }
    $env:Path = (Join-Path $FfmpegDir "bin") + ";" + $env:Path

    # --- 4. Środowisko Pythona i biblioteki ---------------------------------------------------------
    Step "4/6 Biblioteki programu (PyTorch w wersji na procesor, Whisper, pyannote, okno) - najdłuższy krok"
    if (-not (Test-Path $VenvPython)) {
        Invoke-Checked $Python @("-m", "venv", $Venv) "Tworzenie środowiska .venv"
    }
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip") "Aktualizacja pip"
    # Najpierw torch z indeksu CPU - zwykły pip ściągnąłby wersję z CUDA (kilka GB więcej)
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--index-url", $TorchIndex,
                                 "torch", "torchaudio", "torchcodec") "Instalacja PyTorch"
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--extra-index-url", $TorchIndex,
                                 "-e", "$Root[anthropic,gemini,okno]") "Instalacja programu"
    Ok "zainstalowane"

    # --- 5. Foldery i klucze --------------------------------------------------------------------
    Step "5/6 Foldery i klucze"
    $docs = [Environment]::GetFolderPath("MyDocuments")
    foreach ($name in "Audio_sesje_rpg", "Transkrypcje", "Podsumowania") {
        New-Item -ItemType Directory -Force -Path (Join-Path $docs $name) | Out-Null
    }
    Ok "foldery w $docs : Audio_sesje_rpg (nagrania), Transkrypcje, Podsumowania (kroniki)"

    $envScript = "import sys; from rpg_chronicler import envfile; " +
                 "print(envfile.read().get(sys.argv[1], ''))"
    $hasToken = (& $VenvPython -c $envScript HUGGINGFACE_TOKEN)
    $keys = @{}
    if (-not $hasToken) {
        Info ""
        Info "Token Hugging Face jest potrzebny do rozpoznawania, kto mówi (darmowy):"
        Info "  1. Załóż konto i utwórz token typu Read: https://huggingface.co/settings/tokens"
        Info "  2. Zaakceptuj licencje: https://huggingface.co/pyannote/speaker-diarization-3.1"
        Info "                     oraz https://huggingface.co/pyannote/segmentation-3.0"
        $token = Read-Host "    Wklej token (hf_...) albo naciśnij Enter, żeby pominąć"
        if ($token.Trim()) { $keys["HUGGINGFACE_TOKEN"] = $token.Trim() }
    } else {
        Ok "token Hugging Face już jest"
    }

    $hasProvider = (& $VenvPython -c $envScript LLM_PROVIDER)
    if (-not $hasProvider) {
        Info ""
        Info "Kto ma pisać kroniki?"
        Info "  1 - Gemini (Google, darmowy limit; klucz: https://aistudio.google.com/apikey)"
        Info "  2 - Claude API (płatne za użycie; klucz: https://console.anthropic.com/settings/keys)"
        Info "  3 - Claude Code (plan Pro/Max; wymaga zainstalowanej i zalogowanej komendy claude)"
        $choice = Read-Host "    Wybierz 1, 2 albo 3 [1]"
        switch ($choice.Trim()) {
            "2" { $keys["LLM_PROVIDER"] = "anthropic"; $keyName = "ANTHROPIC_API_KEY" }
            "3" { $keys["LLM_PROVIDER"] = "claude-code"; $keyName = $null }
            default { $keys["LLM_PROVIDER"] = "gemini"; $keyName = "GEMINI_API_KEY" }
        }
        if ($keyName) {
            $key = Read-Host "    Wklej klucz API albo naciśnij Enter, żeby wpisać go później"
            if ($key.Trim()) { $keys[$keyName] = $key.Trim() }
        }
    }
    if ($keys.Count -gt 0) {
        $pairs = foreach ($k in $keys.Keys) { $k; $keys[$k] }
        Invoke-Checked $VenvPython (@("-c", "import sys; from rpg_chronicler import envfile; " +
            "envfile.update(dict(zip(sys.argv[1::2], sys.argv[2::2])))") + $pairs) "Zapis kluczy"
        Ok "zapisane w $(Join-Path $Root '.env')"
    }

    # --- 6. Sprawdzenie i skróty ------------------------------------------------------------------
    Step "6/6 Sprawdzenie i skróty"
    Invoke-Checked $VenvPython @("-c", "import faster_whisper, pyannote.audio, torchcodec.decoders") `
        "Sprawdzenie bibliotek (faster-whisper, pyannote, torchcodec)"
    Ok "biblioteki działają"

    $shell = New-Object -ComObject WScript.Shell
    $console = Join-Path $Root "windows\konsola.bat"
    $pythonw = Join-Path $Venv "Scripts\pythonw.exe"
    $places = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
    foreach ($dir in $places) {
        # Okno programu (pywebview + Edge WebView2 wbudowany w Windows), bez czarnego okna konsoli
        $lnk = $shell.CreateShortcut((Join-Path $dir "RPG Chronicles.lnk"))
        $lnk.TargetPath = $pythonw
        $lnk.Arguments = "-m rpg_chronicler.web"
        $lnk.WorkingDirectory = $Root
        $lnk.Description = "RPG Chronicles - kroniki sesji RPG"
        $lnk.Save()
        # Konsola z komendami rpg-chronicler (dla zaawansowanych)
        $lnk = $shell.CreateShortcut((Join-Path $dir "RPG Chronicles (konsola).lnk"))
        $lnk.TargetPath = Join-Path $env:SystemRoot "System32\cmd.exe"
        $lnk.Arguments = "/k `"`"$console`"`""
        $lnk.WorkingDirectory = $Root
        $lnk.Description = "RPG Chronicles - komendy w konsoli"
        $lnk.Save()
    }
    Ok "skróty „RPG Chronicles” (okno) i „RPG Chronicles (konsola)” na pulpicie i w menu Start"

    Write-Host ""
    Write-Host "Gotowe!" -ForegroundColor Green
    Write-Host "Nagrania wrzucaj do $(Join-Path $docs 'Audio_sesje_rpg') (nazwa: Kampania_RRMMDD, np. Zakon_261123.m4a),"
    Write-Host "a potem otwórz skrót „RPG Chronicles” i kliknij „Przetwórz wszystko”."
} catch {
    Write-Host ""
    Write-Host "[BŁĄD] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Możesz uruchomić instalator ponownie - pominie to, co już się udało."
    exit 1
}
