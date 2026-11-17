# G2 smoke gate: isolated Hermes home + local model + one task that needs a file-read tool call.
# Usage: tools\gate-smoke.ps1 [-Runs 3] [-Model qwen3.5:9b]
# Pass: every run exits 0 and the answer contains the code word that only exists in the fixture file.
param([int]$Runs = 3, [string]$Model = 'ariadne-qwen3.5-9b', [int]$MaxTurns = 8)
$ErrorActionPreference = 'Stop'
# One gate at a time: gates stop/start the Ariadne gateway, so two overlapping runs kill each other's gateway.
$gateMutex = [System.Threading.Mutex]::new($false, 'Global\AriadneGate')
if (-not $gateMutex.WaitOne(0)) { Write-Host 'another Ariadne gate is running; refusing to overlap'; exit 2 }
$root = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'use-profile.ps1') base | Out-Null
$env:HERMES_HOME = Join-Path $root '.hermes-home'
$hermes = Join-Path $root '.venv\Scripts\hermes.exe'
$scratch = Join-Path $root 'scratch'; New-Item -ItemType Directory $scratch -Force | Out-Null
$logs = Join-Path $root 'logs'; New-Item -ItemType Directory $logs -Force | Out-Null
$results = @()
for ($i = 1; $i -le $Runs; $i++) {
  $word = 'ARIADNE-' + (Get-Random -Minimum 100000 -Maximum 999999)
  $fixture = Join-Path $scratch 'smoke-fixture.txt'
  Set-Content $fixture "The code word is $word." -Encoding ascii
  $q = "Use your file reading tool to read $fixture and reply with only the code word written in it."
  $log = Join-Path $logs "g2-run$i.log"
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $ErrorActionPreference = 'Continue'
  $out = & $hermes chat -q $q --oneshot -Q -m $Model --max-turns $MaxTurns 2>&1 | Out-String
  $code = $LASTEXITCODE; $sw.Stop()
  $ErrorActionPreference = 'Stop'
  Set-Content $log $out
  $found = $out -match [regex]::Escape($word)
  $results += [pscustomobject]@{ run = $i; exit = $code; found = $found; secs = [math]::Round($sw.Elapsed.TotalSeconds, 1); pass = (($code -eq 0) -and $found) }
}
$results | Format-Table -AutoSize | Out-String | Write-Host
$passed = @($results | Where-Object pass).Count
Write-Host "G2: $passed/$Runs passed (model $Model)"
if ($passed -ne $Runs) { exit 1 } else { exit 0 }
