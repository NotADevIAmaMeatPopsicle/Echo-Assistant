# Project-local, pinned Spotify Connect receiver. No user PATH or host audio changes.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtime = Join-Path $projectRoot 'local/runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$installer = Join-Path $runtime 'rustup-init.exe'
$url = 'https://static.rust-lang.org/rustup/archive/1.28.2/x86_64-pc-windows-msvc/rustup-init.exe'
Invoke-WebRequest $url -OutFile $installer
Invoke-WebRequest ($url + '.sha256') -OutFile ($installer + '.sha256')
$checksum = ((Get-Content -LiteralPath ($installer + '.sha256') -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $checksum.ToLowerInvariant()) { throw 'Rustup checksum mismatch' }
$env:CARGO_HOME = Join-Path $runtime 'cargo'
$env:RUSTUP_HOME = Join-Path $runtime 'rustup'
$env:CARGO_BUILD_JOBS = '2'
& $installer -y --no-modify-path --profile minimal --default-toolchain 1.90.0
if ($LASTEXITCODE) { throw 'Project-local Rust setup failed' }
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run tools/setup.ps1 before building the receiver' }
& $python -X utf8 (Join-Path $projectRoot 'tools/build_receiver.py')
if ($LASTEXITCODE) { throw 'Controlled Spotify receiver build failed' }
