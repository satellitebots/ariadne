# G3 egress gate: run the G2 smoke task with the egress hook active in every Ariadne Python process
# (CLI + auto-started gateway + Python children); fail on any non-local host.
# Usage: tools\gate-egress.ps1 [-Profile base] [-Model ariadne-qwen3.5-9b] [-DeadProxy] [-Tag g3] [-TailSecs 20] [-ExpectGuardBlocks]
# -DeadProxy also points HTTP(S)_PROXY at a closed local port so proxied calls fail fast instead of leaving.
# -TailSecs keeps the gateway alive after the answer to catch background refreshes, then stops it.
# -ExpectGuardBlocks additionally requires >= 1 offline_guard block (use with -Profile guard-proof: proves
#  the guard, not config, stopped the egress).
param([string]$Profile = 'base', [string]$Model = 'ariadne-qwen3.5-9b', [switch]$DeadProxy,
      [string]$Tag = 'g3', [int]$TailSecs = 20, [switch]$ExpectGuardBlocks)
# One gate at a time: gates stop/start the Ariadne gateway, so two overlapping runs kill each other's gateway.
$gateMutex = [System.Threading.Mutex]::new($false, 'Global\AriadneGate')
if (-not $gateMutex.WaitOne(0)) { Write-Host 'another Ariadne gate is running; refusing to overlap'; exit 2 }
$root = Split-Path $PSScriptRoot -Parent
function Stop-AriadneGateway {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'gateway run' -and
    $_.CommandLine -match [regex]::Escape($root) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
& (Join-Path $PSScriptRoot 'install-egress-hook.ps1') | Out-Null
& (Join-Path $PSScriptRoot 'use-profile.ps1') $Profile | Out-Null
Stop-AriadneGateway
$env:HERMES_HOME = Join-Path $root '.hermes-home'
& (Join-Path $PSScriptRoot 'install-guard-pth.ps1') | Out-Null
$env:ARIADNE_GUARD_ALL_PROCS = '1'  # guard every Ariadne Python process, the CLI included
if ($DeadProxy) { $env:HTTPS_PROXY = 'http://127.0.0.1:9'; $env:HTTP_PROXY = 'http://127.0.0.1:9'; $env:NO_PROXY = 'localhost,127.0.0.1,::1' }
$py = Join-Path $root '.venv\Scripts\python.exe'
$hermes = Join-Path $root '.venv\Scripts\hermes.exe'
$logs = Join-Path $root 'logs'; New-Item -ItemType Directory $logs -Force | Out-Null
$scratch = Join-Path $root 'scratch'; New-Item -ItemType Directory $scratch -Force | Out-Null
$log = Join-Path $logs "$Tag-egress.jsonl"; Remove-Item $log -ErrorAction SilentlyContinue
$guardLog = Join-Path $env:HERMES_HOME 'logs\offline_guard.jsonl'; Remove-Item $guardLog -ErrorAction SilentlyContinue
$env:ARIADNE_EGRESS_LOG = $log
$word = 'ARIADNE-' + (Get-Random -Minimum 100000 -Maximum 999999)
$fixture = Join-Path $scratch 'smoke-fixture.txt'
Set-Content $fixture "The code word is $word." -Encoding ascii
$q = "Use your file reading tool to read $fixture and reply with only the code word written in it."
$sw = [Diagnostics.Stopwatch]::StartNew()
$ErrorActionPreference = 'Continue'
$out = & $hermes chat -q $q --oneshot -Q -m $Model --max-turns 8 2>&1 | Out-String
$code = $LASTEXITCODE; $sw.Stop()
Start-Sleep -Seconds $TailSecs
Stop-AriadneGateway
Remove-Item Env:\ARIADNE_EGRESS_LOG
Set-Content (Join-Path $logs "$Tag-output.log") $out
if (-not (Test-Path $log)) { New-Item $log -ItemType File | Out-Null }
& $py (Join-Path $PSScriptRoot 'egress_report.py') $log | Tee-Object (Join-Path $logs "$Tag-report.txt")
$ext = $LASTEXITCODE
$guardBlocks = 0
if (Test-Path $guardLog) {
  $guardBlocks = @(Get-Content $guardLog | Where-Object { $_.Trim() }).Count
  Copy-Item $guardLog (Join-Path $logs "$Tag-guard.jsonl") -Force
}
Write-Host ("G3[{0}]: hermes exit={1} answer_ok={2} secs={3} external={4} guard_blocks={5}" -f $Tag, $code, ($out -match [regex]::Escape($word)), [math]::Round($sw.Elapsed.TotalSeconds,1), $(if ($ext) {'YES'} else {'none'}), $guardBlocks)
# A failed task can hide egress (it may crash before the network code runs), so it fails the gate too.
$taskOk = ($code -eq 0) -and ($out -match [regex]::Escape($word))
if ($ExpectGuardBlocks -and $guardBlocks -lt 1) { Write-Host 'expected offline_guard blocks, saw none'; $taskOk = $false }
if ($ext -ne 0 -or -not $taskOk) { exit 1 } else { exit 0 }
