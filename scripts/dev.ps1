param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonBin = Join-Path $PWD ".venv-rebuild/Scripts/python.exe"
if (!(Test-Path $pythonBin)) { throw "Run ./scripts/setup.ps1 first" }
$departmentWorker = Start-Process -FilePath $pythonBin -ArgumentList @('manage.py','sync_m365_directory','--watch') -WorkingDirectory $PWD -WindowStyle Hidden -PassThru
try {
    & $pythonBin manage.py runserver "127.0.0.1:$Port"
    $devExitCode = $LASTEXITCODE
} finally {
    if (!$departmentWorker.HasExited) { $departmentWorker.Kill() }
}
exit $devExitCode
