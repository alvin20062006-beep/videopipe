param([switch]$Force)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT" -or -not [Environment]::Is64BitOperatingSystem) {
    throw "VideoPipe V1 installer supports 64-bit Windows only."
}

$root = $PSScriptRoot
Set-Location $root
$vendor = Join-Path $root "vendor"
$venv = Join-Path $root ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$ariaDir = Join-Path $vendor "aria2\aria2-1.37.0-win-64bit-build1"
$ariaExe = Join-Path $ariaDir "aria2c.exe"
$nmDir = Join-Path $vendor "N_m3u8DL-RE"
$nmExe = Join-Path $nmDir "N_m3u8DL-RE.exe"
$temp = Join-Path ([IO.Path]::GetTempPath()) ("videopipe-install-" + [guid]::NewGuid().ToString("N"))

function Assert-Sha256([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 verification failed for $([IO.Path]::GetFileName($Path))."
    }
}

try {
    New-Item -ItemType Directory -Force -Path $temp, $vendor | Out-Null
    $python = (Get-Command python -ErrorAction Stop).Source

    if ($Force -and (Test-Path -LiteralPath $venv)) { Remove-Item -LiteralPath $venv -Recurse -Force }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "[1/4] Creating Python virtual environment..."
        & $python -m venv $venv
        if ($LASTEXITCODE) { throw "Unable to create the Python virtual environment." }
    }
    Write-Host "[1/4] Installing Python dependencies..."
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE) { throw "Unable to install Python dependencies." }

    if ($Force -and (Test-Path -LiteralPath (Split-Path $ariaDir))) { Remove-Item -LiteralPath (Split-Path $ariaDir) -Recurse -Force }
    if (-not (Test-Path -LiteralPath $ariaExe)) {
        Write-Host "[2/4] Downloading Aria2..."
        $ariaZip = Join-Path $temp "aria2.zip"
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip" -OutFile $ariaZip
        Assert-Sha256 $ariaZip "67d015301eef0b612191212d564c5bb0a14b5b9c4796b76454276a4d28d9b288"
        New-Item -ItemType Directory -Force -Path (Split-Path $ariaDir) | Out-Null
        Expand-Archive -LiteralPath $ariaZip -DestinationPath (Split-Path $ariaDir) -Force
    }

    if ($Force -and (Test-Path -LiteralPath $nmDir)) { Remove-Item -LiteralPath $nmDir -Recurse -Force }
    if (-not (Test-Path -LiteralPath $nmExe)) {
        Write-Host "[3/4] Downloading N_m3u8DL-RE..."
        $headers = @{ "User-Agent" = "VideoPipe dependency installer" }
        $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest"
        $asset = $release.assets | Where-Object { $_.name -match "_win-x64_.*\.zip$" } | Select-Object -First 1
        if (-not $asset) { throw "The latest N_m3u8DL-RE Windows x64 package was not found." }
        $nmZip = Join-Path $temp "N_m3u8DL-RE.zip"
        Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $asset.browser_download_url -OutFile $nmZip
        if ($asset.digest -match "^sha256:(.+)$") { Assert-Sha256 $nmZip $Matches[1] }
        New-Item -ItemType Directory -Force -Path $nmDir | Out-Null
        Expand-Archive -LiteralPath $nmZip -DestinationPath $nmDir -Force
        $foundNm = Get-ChildItem -LiteralPath $nmDir -Recurse -Filter "N_m3u8DL-RE.exe" | Select-Object -First 1
        if ($foundNm -and $foundNm.FullName -ne $nmExe) { Copy-Item -LiteralPath $foundNm.FullName -Destination $nmExe }
    }

    Write-Host "[4/4] Verifying installation..."
    if (-not (Test-Path -LiteralPath $ariaExe)) { throw "Aria2 installation is incomplete." }
    if (-not (Test-Path -LiteralPath $nmExe)) { throw "N_m3u8DL-RE installation is incomplete." }
    & $venvPython -c "import app, imageio_ffmpeg; from pathlib import Path; assert app.ARIA2_EXE.exists(); assert app.NM3U8_EXE.exists(); assert Path(imageio_ffmpeg.get_ffmpeg_exe()).exists(); print('VideoPipe dependencies are ready.')"
    if ($LASTEXITCODE) { throw "VideoPipe dependency verification failed." }

    $edge = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "C:\Program Files\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $edge) { Write-Warning "Microsoft Edge was not found. Browser media discovery will be unavailable." }
    Write-Host "Installation complete. Run .\start.ps1" -ForegroundColor Green
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
