param([ValidateSet('Save','SavePolicy','SaveApi','Recover','RecoverApi','Status')][string]$Mode='Recover')
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Add-Type -AssemblyName System.Security
$echoRoot=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo'
$echoDocker=(Get-Command docker.exe -ErrorAction Stop).Source
$echoBundle=Join-Path $echoRoot 'agent-bootstrap.dpapi'
$echoPolicy=Join-Path $echoRoot 'home-access.dpapi'
$echoApiBundle=Join-Path $echoRoot 'api-bootstrap.dpapi'
$echoStatus=Join-Path $echoRoot 'recovery-status.json'
$echoScope=[Security.Cryptography.DataProtectionScope]::CurrentUser

function Save-Protected([string]$Path,[byte[]]$Data) {
    $sealed=[Security.Cryptography.ProtectedData]::Protect($Data,$null,$echoScope)
    $temporary=$Path+'.tmp'
    [IO.File]::WriteAllBytes($temporary,$sealed)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}
function Read-Protected([string]$Path) {
    return [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($Path),$null,$echoScope)
}
function Check-Policy($Policy) {
    if (-not $Policy -or $Policy.default_access -notin @('read','hidden') -or
        -not $Policy.devices -or @($Policy.PSObject.Properties.Name).Count -ne 2) { throw 'Invalid home policy' }
    $items=@($Policy.devices.PSObject.Properties)
    if ($items.Count -gt 1000) { throw 'Invalid home policy' }
    foreach ($item in $items) {
        $rule=$item.Value
        if ($item.Name -cnotmatch '^(light|switch|climate|media_player|cover|fan|scene|weather)\.[a-z0-9_]{1,200}$' -or
            @($rule.PSObject.Properties.Name).Count -ne 2 -or $rule.access -notin @('read','hidden','control') -or
            ($rule.access -eq 'control' -and $item.Name -cnotmatch '^(light|switch|climate|media_player|scene)\.') -or
            $rule.room -isnot [string] -or $rule.room.Length -gt 60 -or $rule.room -ne $rule.room.Trim() -or
            $rule.room -match '[\x00-\x1f]') { throw 'Invalid home policy' }
    }
}
function Run-Container([string]$Script,[string]$InputText,[ValidateSet('echo-agent','echo-api')][string]$Container='echo-agent') {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$echoDocker
    $python=if ($Container -eq 'echo-agent') { '/opt/hermes/.venv/bin/python' } else { '/usr/local/bin/python' }
    $start.Arguments='exec -i --user 10000:10000 '+$Container+' '+$python+' -c "'+$Script+'"'
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $start.RedirectStandardInput=$true
    $start.RedirectStandardOutput=$true
    $start.RedirectStandardError=$true
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$start
    if (-not $process.Start()) { throw 'Container command could not start' }
    try {
        $output=$process.StandardOutput.ReadToEndAsync()
        $errors=$process.StandardError.ReadToEndAsync()
        $inputBytes=[Text.Encoding]::UTF8.GetBytes($InputText)
        $process.StandardInput.BaseStream.Write($inputBytes,0,$inputBytes.Length)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(20000)) { $process.Kill(); throw 'Container command timed out' }
        if ($process.ExitCode -ne 0) { throw 'Container command failed' }
        return $output.Result.Trim()
    } finally { $process.Dispose() }
}
function Report([string]$State) {
    $result=@{state=$State;checked_at=[DateTime]::UtcNow.ToString('o')}
    if ($script:echoFailure) { $result.failure=$script:echoFailure }
    if ($script:echoApiState) { $result.api=$script:echoApiState }
    if ($script:echoDiscoveryState) { $result.discovery=$script:echoDiscoveryState }
    if ($script:echoAgentApply) { $result.agent_settings=$script:echoAgentApply }
    [IO.File]::WriteAllText($echoStatus,($result|ConvertTo-Json -Compress))
    Write-Output ($result|ConvertTo-Json -Compress)
}

function Recover-Api {
    if (-not (Test-Path -LiteralPath $echoApiBundle)) { return 'not_provisioned' }
    $running=& $echoDocker inspect echo-api --format '{{.State.Status}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or $running.Trim() -ne 'running') { return 'container_not_running' }
    try {
        $health=Invoke-RestMethod 'http://127.0.0.1:18668/health' -TimeoutSec 3
        if ($health.product -eq 'round-voice') { return 'ready' }
    } catch {}
    $probe=Run-Container "from pathlib import Path; print('bootstrapped' if Path('/run/echo/bootstrapped').exists() else 'waiting')" '' 'echo-api'
    if ($probe -eq 'bootstrapped') { return 'runtime_starting_or_needs_attention' }
    $plaintext=Read-Protected $echoApiBundle
    $script="import sys,json,os; from pathlib import Path; p=Path('/run/echo/bootstrap.json'); data=sys.stdin.buffer.read(); json.loads(data); assert not Path('/run/echo/bootstrapped').exists(); t=p.with_suffix('.tmp'); t.write_bytes(data); os.chmod(t,0o600); t.replace(p); print('provisioned')"
    $null=Run-Container $script ([Text.Encoding]::UTF8.GetString($plaintext)) 'echo-api'
    [Array]::Clear($plaintext,0,$plaintext.Length)
    return 'provisioned'
}

function Recover-Discovery {
    $config=Join-Path $echoRoot 'discovery.json'
    if (-not (Test-Path -LiteralPath $config)) { return 'not_provisioned' }
    $settings=Get-Content -LiteralPath $config -Raw|ConvertFrom-Json
    if ($settings.enabled -ne $true) { return 'disabled' }
    $task=Get-ScheduledTask -TaskName 'Echo Spotify Discovery' -ErrorAction SilentlyContinue
    if (-not $task) { return 'task_missing' }
    $expected=Join-Path $echoRoot 'spotify_discovery.py'
    if (-not $task.Actions.Arguments.Contains($expected)) { throw 'Discovery task identity changed' }
    if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName 'Echo Spotify Discovery'; return 'starting' }
    return 'running'
}

function Get-AgentConfiguration {
    try {
        $health=Invoke-RestMethod 'http://127.0.0.1:18642/health' -TimeoutSec 2
        if ($health.status -eq 'ok') {
            return (Run-Container "from pathlib import Path; print(Path('/opt/data/echo-configuration').read_text())" '')
        }
    } catch {}
    return ''
}

function Apply-AgentSettings {
    # This existing Docker owner is the only process allowed to export a key.
    # The browser queues metadata; no Docker/SSH authority is given to the API.
    $claimScript="import sys; sys.argv=['agent_apply','claim']; from backend.agent_apply import main; main()"
    try { $change=(Run-Container $claimScript '' 'echo-api')|ConvertFrom-Json }
    catch { return 'unavailable' }
    if (-not $change.pending) { return 'idle' }
    $finishScript="import sys; sys.argv=['agent_apply','finish']; from backend.agent_apply import main; main()"
    $actual=Get-AgentConfiguration
    # A lost observation is not a reason to restart a successfully applied agent.
    if ($actual -eq $change.configuration) {
        $result=Run-Container $finishScript (@{id=$change.id;succeeded=$true}|ConvertTo-Json -Compress) 'echo-api'
        if (($result|ConvertFrom-Json).applied) { return 'applied' }
        return 'failed'
    }
    if ($change.resume) {
        if (-not $actual) { return 'waiting' }
        $null=Run-Container $finishScript (@{id=$change.id;succeeded=$false}|ConvertTo-Json -Compress) 'echo-api'
        return 'failed'
    }
    $succeeded=$false
    $failed=$false
    try {
        $plaintext=Read-Protected $echoBundle
        $payload=[Text.Encoding]::UTF8.GetString($plaintext)|ConvertFrom-Json
        [Array]::Clear($plaintext,0,$plaintext.Length)
        if ($change.secret_name -notin @('AZURE_FOUNDRY_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY') -or -not $change.model_config) { throw 'Invalid provider profile' }
        $payload.config.model=$change.model_config
        $replacementSecrets=@{API_SERVER_KEY=$payload.secrets.API_SERVER_KEY}
        $replacementSecrets[$change.secret_name]=$change.provider_key
        $payload.secrets=[pscustomobject]$replacementSecrets
        $payload.personality=$change.settings.personality
        $payload.configuration=$change.configuration
        Save-Protected $echoBundle ([Text.Encoding]::UTF8.GetBytes(($payload|ConvertTo-Json -Depth 30 -Compress)))
        # Keep the protected recovery source aligned without replacing live data.
        $plaintext=Read-Protected $echoApiBundle
        $apiPayload=[Text.Encoding]::UTF8.GetString($plaintext)|ConvertFrom-Json
        [Array]::Clear($plaintext,0,$plaintext.Length)
        $apiPayload.settings=$change.settings
        $apiPayload.provider_key=$change.provider_key
        Save-Protected $echoApiBundle ([Text.Encoding]::UTF8.GetBytes(($apiPayload|ConvertTo-Json -Depth 30 -Compress)))
        $null=& $echoDocker restart --time 10 echo-agent 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Agent restart failed' }
        $script="import sys,json,os; from pathlib import Path; p=Path('/opt/data/.echo-bootstrap.json'); data=sys.stdin.buffer.read(); json.loads(data); assert not Path('/opt/data/runtime.log').exists(); t=p.with_suffix('.tmp'); t.write_bytes(data); os.chmod(t,0o600); t.replace(p); print('provisioned')"
        $null=Run-Container $script ($payload|ConvertTo-Json -Depth 30 -Compress)
        $readyUntil=[DateTime]::UtcNow.AddSeconds(25)
        do {
            $actual=Get-AgentConfiguration
            if ($actual) { $succeeded=$actual -eq $change.configuration; $failed=-not $succeeded; break }
            Start-Sleep -Milliseconds 500
        } while ([DateTime]::UtcNow -lt $readyUntil)
    } catch { $failed=$true }
    if (-not $succeeded -and -not $failed) { return 'waiting' }
    $result=Run-Container $finishScript (@{id=$change.id;succeeded=$succeeded}|ConvertTo-Json -Compress) 'echo-api'
    if (($result|ConvertFrom-Json).applied) { return 'applied' }
    return 'failed'
}

# Serialize recovery and updates across scheduled and interactive invocations.
$echoLock=$null
try {
    $deadline=[DateTime]::UtcNow.AddSeconds(25)
    do {
        try { $echoLock=[IO.File]::Open((Join-Path $echoRoot 'provisioning.lock'),'OpenOrCreate','ReadWrite','None') }
        catch [IO.IOException] { Start-Sleep -Milliseconds 200 }
    } while (-not $echoLock -and [DateTime]::UtcNow -lt $deadline)
    if (-not $echoLock) { throw 'Echo provisioning is busy' }
    if ($Mode -eq 'Status') {
        if (Test-Path -LiteralPath $echoStatus) { Get-Content -LiteralPath $echoStatus -Raw }
        else { Write-Output '{"state":"not_checked"}' }
        exit 0
    }
    if ($Mode -in @('Save','SavePolicy','SaveApi')) {
        $incoming=[Console]::In.ReadToEnd()
        if ($incoming.Length -gt 500000) { throw 'Bootstrap is too large' }
        $value=$incoming|ConvertFrom-Json
        if ($Mode -eq 'Save') {
            Check-Policy $value.home_access
            if (-not $value.config -or -not $value.secrets.API_SERVER_KEY -or
                -not ($value.secrets.AZURE_FOUNDRY_API_KEY -or $value.secrets.OPENAI_API_KEY -or $value.secrets.ANTHROPIC_API_KEY)) { throw 'Invalid bootstrap' }
            Save-Protected $echoBundle ([Text.Encoding]::UTF8.GetBytes($incoming))
            Save-Protected $echoPolicy ([Text.Encoding]::UTF8.GetBytes(($value.home_access|ConvertTo-Json -Depth 15 -Compress)))
            Report 'saved'
        } elseif ($Mode -eq 'SaveApi') {
            Check-Policy $value.home_access
            if (-not $value.settings -or $value.settings.provider -notin @('azure','openai','anthropic','local') -or
                -not $value.provider_key -or $value.api_token.Length -lt 32 -or $value.home_tools_token.Length -lt 32) { throw 'Invalid API bootstrap' }
            if (Test-Path -LiteralPath $echoApiBundle) {
                $previous=[Text.Encoding]::UTF8.GetString((Read-Protected $echoApiBundle))|ConvertFrom-Json
                $storage=$previous.storage_key
            } else {
                $key=New-Object byte[] 32
                $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
                try { $rng.GetBytes($key) } finally { $rng.Dispose() }
                $storage=[Convert]::ToBase64String($key)
                [Array]::Clear($key,0,$key.Length)
            }
            $value|Add-Member -NotePropertyName storage_key -NotePropertyValue $storage -Force
            Save-Protected $echoApiBundle ([Text.Encoding]::UTF8.GetBytes(($value|ConvertTo-Json -Depth 30 -Compress)))
            Report 'api_saved'
        } else {
            Check-Policy $value
            Save-Protected $echoPolicy ([Text.Encoding]::UTF8.GetBytes($incoming))
            $script="import sys,json,os; from pathlib import Path; sys.path.insert(0,'/opt/echo'); from backend.home_policy import validate_policy,policy_hash; v=validate_policy(json.load(sys.stdin)); p=Path('/opt/data/echo-access.json'); t=p.with_suffix('.tmp'); t.write_text(json.dumps(v)); os.chmod(t,0o600); t.replace(p); print(policy_hash(v))"
            $fingerprint=Run-Container $script $incoming
            Write-Output (@{applied=$fingerprint}|ConvertTo-Json -Compress)
        }
        exit 0
    }
    try { $script:echoDiscoveryState=Recover-Discovery }
    catch { $script:echoDiscoveryState='recovery_failed' }
    try { $script:echoApiState=Recover-Api }
    catch { $script:echoApiState='recovery_failed' }
    # A broken validation API must not block the working agent's recovery.
    if ($Mode -eq 'RecoverApi' -and $script:echoApiState -eq 'recovery_failed') { Report 'recovery_failed'; exit 1 }
    if ($Mode -eq 'RecoverApi') { Report $script:echoApiState; exit 0 }
    if (-not (Test-Path -LiteralPath $echoBundle)) { Report 'not_provisioned'; exit 0 }
    $container=& $echoDocker inspect echo-agent --format '{{.State.Status}}' 2>$null
    if ($LASTEXITCODE -ne 0) { Report 'waiting_for_docker_or_container'; exit 0 }
    if ($container.Trim() -ne 'running') { Report 'container_not_running'; exit 0 }
    if ($script:echoApiState -eq 'ready') {
        try { $script:echoAgentApply=Apply-AgentSettings }
        catch { $script:echoAgentApply='failed' }
    }
    # A deliberate stop is respected; recovery never creates or starts containers.
    try {
        $health=Invoke-RestMethod 'http://127.0.0.1:18642/health' -TimeoutSec 3
        if ($health.status -eq 'ok') { Report 'ready'; exit 0 }
    } catch {}
    $probe=Run-Container "from pathlib import Path; print('bootstrapped' if Path('/opt/data/runtime.log').exists() else 'waiting')" ''
    if ($probe -eq 'bootstrapped') { Report 'runtime_starting_or_needs_attention'; exit 0 }
    $plaintext=Read-Protected $echoBundle
    $payload=[Text.Encoding]::UTF8.GetString($plaintext)|ConvertFrom-Json
    if (Test-Path -LiteralPath $echoPolicy) {
        $payload.home_access=[Text.Encoding]::UTF8.GetString((Read-Protected $echoPolicy))|ConvertFrom-Json
    }
    Check-Policy $payload.home_access
    $script="import sys,json,os; from pathlib import Path; p=Path('/opt/data/.echo-bootstrap.json'); data=sys.stdin.buffer.read(); json.loads(data); assert not Path('/opt/data/runtime.log').exists(); t=p.with_suffix('.tmp'); t.write_bytes(data); os.chmod(t,0o600); t.replace(p); print('provisioned')"
    $null=Run-Container $script ($payload|ConvertTo-Json -Depth 30 -Compress)
    [Array]::Clear($plaintext,0,$plaintext.Length)
    Report 'provisioned'
} catch {
    # Neither exception messages nor native stderr may contain bootstrap material.
    $script:echoFailure=@{type=$_.Exception.GetType().Name;line=$_.InvocationInfo.ScriptLineNumber}
    Report 'recovery_failed'
    exit 1
} finally {
    if ($echoLock) { $echoLock.Dispose() }
}
