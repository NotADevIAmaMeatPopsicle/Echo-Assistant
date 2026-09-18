param([string]$Python = 'python', [switch]$Echo, [string]$EchoPython = '')
# Explicit setup only: installs into this checkout, with no PATH/startup/config changes.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $projectRoot '.venv'
$runtimePython = Join-Path $venv 'Scripts/python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $runtimePython)) {
        & $Python -c 'import sys; assert (3,12) <= sys.version_info < (3,15), "Use Python 3.12 through 3.14"'
        if ($LASTEXITCODE) { throw 'Unsupported or missing Python' }
        & $Python -m venv $venv
        if ($LASTEXITCODE) { throw 'Could not create the project virtual environment' }
    }
    & $runtimePython -m pip install -r backend/requirements-windows.lock.txt
    if ($LASTEXITCODE) { throw 'Project dependency installation failed' }
    & $runtimePython -X utf8 tools/install_voice_model.py
    if ($LASTEXITCODE) { throw 'Verified local voice model setup failed' }
    if ($Echo) {
        if ($EchoPython) { & $EchoPython -X utf8 tools/install_aec.py }
        else { & py -3.13 -X utf8 tools/install_aec.py }
        if ($LASTEXITCODE) { throw 'Echo cancellation requires an existing 64-bit Python 3.13; see docs/SETUP.md' }
    }
    Write-Output 'Voice runtime ready. Run tools/run.ps1 start. Spotify has its separate pinned build in docs/MUSIC.md.'
} finally { Pop-Location }
