# Download the model files pinned in serving\models.lock into models\, verify sha256, keep only verified files.
# Usage: tools\fetch-models.ps1 [-Only <file name>]
param([string]$Only = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$dir = Join-Path $root 'models'; New-Item -ItemType Directory $dir -Force | Out-Null
$ProgressPreference = 'SilentlyContinue'
Get-Content (Join-Path $root 'serving\models.lock') | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object {
  $name, $url, $sha = $_.Split('|')
  if ($Only -and $name -ne $Only) { return }
  $out = Join-Path $dir $name
  if ((Test-Path $out) -and ((Get-FileHash $out -Algorithm SHA256).Hash.ToLower() -eq $sha)) { Write-Host "OK $name (already verified)"; return }
  $part = "$out.part"
  & curl.exe -L --fail --retry 3 -C - -o $part $url
  if ($LASTEXITCODE -ne 0) { throw "download failed for $name (curl exit $LASTEXITCODE); rerun to resume" }
  $got = (Get-FileHash $part -Algorithm SHA256).Hash.ToLower()
  if ($got -ne $sha) { Remove-Item $part -Force; throw "sha256 mismatch for ${name}: got $got expected $sha (file deleted)" }
  Move-Item $part $out -Force
  Write-Host ("OK {0} sha256 verified ({1:N2} GB)" -f $name, ((Get-Item $out).Length / 1e9))
}
