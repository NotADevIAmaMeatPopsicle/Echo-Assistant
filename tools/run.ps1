param([ValidateSet('start','stop','status')][string]$Action = 'start', [switch]$Usb, [switch]$PlayMusic, [switch]$DisplayOnly)
# Starts the selected host's existing services; never installs software or changes agent configuration.
$ErrorActionPreference = 'Stop'
if ($DisplayOnly -and ($Action -ne 'start' -or $Usb -or $PlayMusic)) { throw '-DisplayOnly is for start without round-board USB or music options.' }
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run tools/setup.ps1 first to create the local Python runtime' }
$local = Join-Path $projectRoot 'local'
New-Item -ItemType Directory -Path $local -Force | Out-Null
$targetPath=Join-Path $local 'host-target.json'
if (Test-Path -LiteralPath $targetPath) {
    if ($DisplayOnly) { throw '-DisplayOnly starts a local host. This checkout is assigned to a remote host; use its configured deployment.' }
    $target=Get-Content -LiteralPath $targetPath -Raw|ConvertFrom-Json
    if ($target.mode -eq 'migrating') { throw 'Echo is moving between hosts. Wait for the transfer to finish.' }
    if ($target.mode -ne 'remote') { throw 'Unknown Echo host target' }
    if ($Usb) { throw 'Use the documented host rollback before taking USB ownership from Remote host.' }
    $arguments=@('-X','utf8',(Join-Path $PSScriptRoot 'remote_device.py'),$Action)
    if ($PlayMusic) { $arguments+='--play-music' }
    & $python @arguments
    exit $LASTEXITCODE
}

function Read-Health {
    try { return Invoke-RestMethod 'http://127.0.0.1:8768/health' -TimeoutSec 2 }
    catch { return $null }
}
function Wait-Closed([string]$Name) {
    $record = Join-Path $local ($Name + '-process.json')
    $until = (Get-Date).AddSeconds(35)
    while ((Test-Path -LiteralPath $record) -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 200 }
    if (Test-Path -LiteralPath $record) { throw "$Name did not stop cleanly; inspect the process before retrying" }
}
function Test-BridgeRunning {
    $recordPath = Join-Path $local 'voice-process.json'
    if (-not (Test-Path -LiteralPath $recordPath)) { return $false }
    try {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$record.pid)
        return $process -and $process.CommandLine.Replace('/','\').Contains($projectRoot.Replace('/','\')) -and $process.CommandLine.Contains('-m backend.voice')
    } catch { return $false }
}

Push-Location $projectRoot
try {
    if ($Action -eq 'status') { & $python -X utf8 tools/doctor.py; exit $LASTEXITCODE }
    if ($Action -eq 'stop') {
        & $python -X utf8 -m backend.voice --stop
        Wait-Closed 'voice'
        & $python -X utf8 -m backend.app --stop
        Wait-Closed 'api'
        Write-Output 'Round Voice services stopped. The board disarms when its heartbeat ends.'
        exit 0
    }
    $echoSettingsPath = Join-Path $local 'echo-settings.json'
    if (Test-Path -LiteralPath $echoSettingsPath) {
        $echoSettings = Get-Content -LiteralPath $echoSettingsPath -Raw | ConvertFrom-Json
        if ($echoSettings.settings.agent_runtime -eq 'hermes') {
            & $python -X utf8 tools/remote_agent.py tunnel
            if ($LASTEXITCODE -ne 0) { Write-Warning 'The Remote host connection is unavailable. Local device controls will still start.' }
        }
    }
    $health = Read-Health
    if ($health -and $health.product -ne 'round-voice') { throw 'Port 8768 belongs to another service' }
    if (-not $health) {
        Start-Process -FilePath $python -ArgumentList '-X utf8 -m backend.app' -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $local 'api-output.log') -RedirectStandardError (Join-Path $local 'api-health.log') | Out-Null
        $until = (Get-Date).AddSeconds(15)
        do { Start-Sleep -Milliseconds 250; $health = Read-Health } while (-not $health -and (Get-Date) -lt $until)
        if (-not $health -or $health.product -ne 'round-voice') { throw 'Local API did not start; inspect local/api-health.log' }
    }
    if ($DisplayOnly) {
        Write-Output 'Echo host is ready for paired displays. Open tools/open_ui.py --display. This launch did not start a round-board listener.'
        exit 0
    }
    if ($health.device_transport -notin @('usb_connected','wifi_connected') -and -not (Test-BridgeRunning)) {
        $executable = $python
        $arguments = '-X utf8 -m backend.voice'
        if ($Usb) { $arguments += ' --usb' }
        if ($PlayMusic) { $arguments += ' --play-music' }
        # The bridge lock prevents duplicate ownership, including a connecting bridge.
        Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $local 'voice-output.log') -RedirectStandardError (Join-Path $local 'voice-health.log') | Out-Null
    }
    $until = (Get-Date).AddSeconds(15)
    do { Start-Sleep -Milliseconds 250; $health = Read-Health } while (($health.device_transport -notin @('usb_connected','wifi_connected') -or $null -eq $health.speaker_muted) -and (Get-Date) -lt $until)
    if ($health.device_transport -in @('usb_connected','wifi_connected')) {
        if ($health.speaker_muted -eq $true) { Write-Output 'Round Voice is connected with speaker output muted. Touch controls are available.' }
        elseif ($health.wake_word -eq 'muted') { Write-Output 'Round Voice is connected with the microphone muted. Touch controls are available.' }
        else { Write-Output 'Round Voice is ready. Say Hey Echo or Okay Echo.' }
    }
    else { Write-Output 'Local API started. The bridge is waiting for the paired board; run tools/run.ps1 status for details.' }
} finally { Pop-Location }
exit 0
