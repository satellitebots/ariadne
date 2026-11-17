# Download the binaries pinned in serving\bin.lock, verify sha256, then extract into serving\bin\<name>-<version>\.
# A file whose hash does not match is deleted and the script stops; nothing unverified is extracted or run.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$bin = Join-Path $root 'serving\bin'; $dl = Join-Path $bin '_downloads'
New-Item -ItemType Directory $dl -Force | Out-Null
$ProgressPreference = 'SilentlyContinue'
Get-Content (Join-Path $root 'serving\bin.lock') | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object {
  $name, $ver, $url, $sha = $_.Split('|')
  $zip = Join-Path $dl (Split-Path $url -Leaf)
  if (-not (Test-Path $zip)) { Invoke-WebRequest $url -OutFile $zip -UseBasicParsing }
  $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
  if ($got -ne $sha) { Remove-Item $zip -Force; throw "sha256 mismatch for $name ${ver}: got $got expected $sha (file deleted)" }
  $dest = Join-Path $bin "$name-$ver"
  if ($name -eq 'cudart') { $dest = Join-Path $bin "llama.cpp-$ver" }  # CUDA runtime DLLs go next to llama-server.exe
  New-Item -ItemType Directory $dest -Force | Out-Null
  Expand-Archive $zip -DestinationPath $dest -Force
  Write-Host ("OK {0} {1} sha256 verified ({2:N1} MB) -> {3}" -f $name, $ver, ((Get-Item $zip).Length / 1e6), $dest)
}
