# Run every check before you commit or push. Exit code is non-zero if anything fails.
#   .\check.ps1          everything
#   .\check.ps1 -Fast    skip the web build (lint and tests only)
param([switch]$Fast)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$py = ".venv\Scripts\python.exe"
$failed = @()

function Step($name, [scriptblock]$cmd) {
    Write-Host "==> $name" -ForegroundColor Cyan
    & $cmd
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "FAILED: $name" -ForegroundColor Red }
}

Step "ruff lint"     { & $py -m ruff check engine ml }
Step "ruff format"   { & $py -m ruff format --check engine ml }
Step "pytest"        { & $py -m pytest -q }
Push-Location web
Step "eslint"        { npx eslint . --max-warnings 0 }
Step "typecheck"     { npx tsc -b }
if (-not $Fast) { Step "web build" { npm run build --silent } }
Pop-Location

if ($failed.Count) { Write-Host "`n$($failed.Count) check(s) failed: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "`nAll checks passed." -ForegroundColor Green
