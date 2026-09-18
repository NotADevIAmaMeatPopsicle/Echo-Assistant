# Only this receiver executable and home subnet receive Spotify discovery traffic.
# Run from an elevated PowerShell. This leaves network profiles and other rules intact.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$resultPath = Join-Path $projectRoot 'local/firewall-result.json'
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator approval is required' }
    $config = Get-Content -LiteralPath (Join-Path $projectRoot 'local/music.json') -Raw | ConvertFrom-Json
    $address = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $config.interface -ErrorAction Stop
    if ($address.PrefixLength -ne 24 -or $config.interface -notmatch '^192\.168\.87\.\d{1,3}$') { throw 'Home network changed; review the subnet before applying rules' }
    $receiver = (Resolve-Path -LiteralPath (Join-Path $projectRoot 'local/runtime/receiver-target/release/librespot.exe')).Path
    $subnet = $env:ECHO_LAN_SUBNET
    if (-not $subnet) { throw 'Set ECHO_LAN_SUBNET to your home LAN CIDR before configuring the firewall' }
    foreach ($entry in @(@{ Name='RoundVoice-Spotify-TCP'; Protocol='TCP'; Port=18899 }, @{ Name='RoundVoice-Spotify-mDNS'; Protocol='UDP'; Port=5353 })) {
        $existing = Get-NetFirewallRule -Name $entry.Name -ErrorAction SilentlyContinue
        if ($existing) {
            $program = ($existing | Get-NetFirewallApplicationFilter).Program
            if ($program -ne $receiver) { throw 'Existing rule belongs to another receiver path; review it manually' }
            $existing | Remove-NetFirewallRule
        }
        New-NetFirewallRule -Name $entry.Name -DisplayName $entry.Name -Direction Inbound -Action Allow `
            -Program $receiver -Protocol $entry.Protocol -LocalPort $entry.Port -RemoteAddress $subnet `
            -InterfaceAlias $address.InterfaceAlias -Profile Any | Out-Null
    }
    @{ status='applied'; program=$receiver; remote_subnet=$subnet; ports=@('TCP 18899','UDP 5353') } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Output 'Round Voice Spotify firewall rules applied for the home network.'
} catch {
    @{ status='failed'; error=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Error $_.Exception.Message
    exit 1
}
