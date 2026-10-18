# Start Countersign: builds the web app if needed, then runs the engine on :8000.
#   .\run.ps1                 normal
#   .\run.ps1 -Eval           also allow the IndiaCall simulator to fix challenges
#   .\run.ps1 -Dummy          skip model loading (UI work without a GPU)
param([switch]$Eval, [switch]$Dummy, [int]$Port = 8000)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "No .venv yet. See docs/RUNBOOK.md (Setup)." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "web\dist\index.html")) {
    Write-Host "Building web app..."
    Push-Location web; npm install; npm run build; Pop-Location
}
if ($Eval) { $env:COUNTERSIGN_EVAL = "1" }
if ($Dummy) { $env:COUNTERSIGN_S1 = "dummy"; $env:COUNTERSIGN_S2 = "0"; $env:COUNTERSIGN_ASR = "tiny" }

Write-Host "Countersign on http://localhost:$Port  (demo panel: /demo)" -ForegroundColor Cyan
& .venv\Scripts\python.exe -m uvicorn engine.app:app --host 0.0.0.0 --port $Port --ws-max-size 1048576
