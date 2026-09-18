param([Parameter(Mandatory=$true)][string]$Python312, [switch]$DownloadModels)
# Explicit, project-local setup. No host PATH, services, audio or agent changes.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$uv = (Get-Command uv -ErrorAction Stop).Source
$hostPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
$ttsPython = Join-Path $projectRoot 'local/tts-python/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $hostPython)) { throw 'Run the main project setup first' }
& $Python312 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Supply an existing Python 3.12 interpreter"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required' }
Push-Location $projectRoot
try {
    if ($DownloadModels) { & $hostPython tools/download_tts_models.py }
    else { & $hostPython tools/download_tts_models.py --verify }
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed speech models are missing or failed verification' }
    # Old readiness must not survive an interrupted dependency upgrade.
    Set-Content -LiteralPath 'local/tts-runtime-ready.json' -Value '{"engines":{}}' -Encoding utf8
    if (-not (Test-Path -LiteralPath $ttsPython)) {
        & $uv venv --python $Python312 local/tts-python
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated speech runtime' }
    }
    & $ttsPython -c 'import sys; assert sys.version_info[:2] == (3, 12)'
    if ($LASTEXITCODE -ne 0) { throw 'Existing speech environment must use Python 3.12' }
    & $uv pip sync --python $ttsPython --only-binary :all: --index https://download.pytorch.org/whl/cpu config/tts-runtime.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Speech dependency installation failed' }
    & $uv pip check --python $ttsPython
    if ($LASTEXITCODE -ne 0) { throw 'Speech dependencies are incompatible' }
    & $ttsPython tools/prepare_tts.py
    if ($LASTEXITCODE -ne 0) { throw 'Local speech configuration failed' }
    & $hostPython tools/check_tts.py
    if ($LASTEXITCODE -ne 0) { throw 'Silent speech verification failed; see local/tts-silent-check.json' }
    Write-Output 'Kokoro and Pocket passed silent checks. Choose an engine in Echo Settings; no playback occurred.'
} finally { Pop-Location }
