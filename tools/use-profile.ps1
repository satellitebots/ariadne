# Usage: tools\use-profile.ps1 [profile]   (default: base)
# Copies profiles\<profile>\config.yaml into the isolated Hermes home.
param([string]$Profile = 'base')
$root = Split-Path $PSScriptRoot -Parent
$home_ = Join-Path $root '.hermes-home'
New-Item -ItemType Directory $home_ -Force | Out-Null
$src = Join-Path $root "profiles\$Profile\config.yaml"
if (-not (Test-Path $src)) { throw "no profile: $src" }
Copy-Item $src (Join-Path $home_ 'config.yaml') -Force
Write-Host "HERMES_HOME=$home_ profile=$Profile"
