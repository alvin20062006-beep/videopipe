$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$aria = Join-Path $root "vendor\aria2\aria2-1.37.0-win-64bit-build1\aria2c.exe"
$nm3u8 = Join-Path $root "vendor\N_m3u8DL-RE\N_m3u8DL-RE.exe"

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $aria) -or -not (Test-Path -LiteralPath $nm3u8)) {
    $answer = Read-Host "VideoPipe dependencies are missing. Install them now? [Y/n]"
    if ($answer -and $answer -notmatch "^[Yy]") { exit 1 }
    & (Join-Path $root "install-dependencies.ps1")
}

Set-Location $root
Write-Host "VideoPipe is running at http://127.0.0.1:8765/" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop."
& $python -m uvicorn app:app --host 127.0.0.1 --port 8765
