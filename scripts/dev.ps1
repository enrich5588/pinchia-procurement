param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonBin = Join-Path $PWD ".venv-rebuild/Scripts/python.exe"
if (!(Test-Path $pythonBin)) { throw "Run ./scripts/setup.ps1 first" }
& $pythonBin manage.py runserver "127.0.0.1:$Port"
exit $LASTEXITCODE
