param([switch]$Demo, [string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program $Arguments" }
}
if (!(Test-Path .venv-rebuild/Scripts/python.exe)) {
    Invoke-Checked $Python @("-c", "import sys; assert (3, 12) <= sys.version_info[:2] <= (3, 13), 'Use Python 3.12 or 3.13'")
    Invoke-Checked $Python @("-m", "venv", ".venv-rebuild")
}
$pythonBin = Join-Path $PWD ".venv-rebuild/Scripts/python.exe"
Invoke-Checked $pythonBin @("-m", "pip", "install", "-r", "requirements.lock")
if (!(Test-Path .env)) { Copy-Item .env.example .env }
Invoke-Checked $pythonBin @("manage.py", "migrate", "--noinput")
Invoke-Checked $pythonBin @("manage.py", "check")
if ($Demo) {
    Invoke-Checked $pythonBin @("manage.py", "seed_demo")
    Invoke-Checked $pythonBin @("manage.py", "seed_department_managers")
}
Write-Host "Environment ready. Run: ./scripts/dev.ps1"
