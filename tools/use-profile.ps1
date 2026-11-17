# Usage: tools\use-profile.ps1 [profile]   (default: base)
# Copies profiles\<profile>\config.yaml into the isolated Hermes home and syncs Ariadne plugins
# (plugins\<name>\ with a plugin.yaml) into <HERMES_HOME>\plugins\. Enabling stays in the profile config.
param([string]$Profile = 'base')
$root = Split-Path $PSScriptRoot -Parent
$home_ = Join-Path $root '.hermes-home'
New-Item -ItemType Directory $home_ -Force | Out-Null
$src = Join-Path $root "profiles\$Profile\config.yaml"
if (-not (Test-Path $src)) { throw "no profile: $src" }
Copy-Item $src (Join-Path $home_ 'config.yaml') -Force
$dest = Join-Path $home_ 'plugins'
New-Item -ItemType Directory $dest -Force | Out-Null
Get-ChildItem (Join-Path $root 'plugins') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'plugin.yaml') } | ForEach-Object {
  $target = Join-Path $dest $_.Name
  if (Test-Path $target) { Remove-Item $target -Recurse -Force }
  Copy-Item $_.FullName $target -Recurse -Exclude '__pycache__','tests'
  Get-ChildItem $target -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
  Get-ChildItem $target -Directory -Filter 'tests' | Remove-Item -Recurse -Force
}
Write-Host "HERMES_HOME=$home_ profile=$Profile"
