$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
& ./.venv-rebuild/Scripts/python.exe manage.py test @args
exit $LASTEXITCODE
