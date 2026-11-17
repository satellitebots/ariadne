# A5 failover test: llama-swap primary -> Ollama fallback -> back to primary, inside ONE Hermes session.
# Usage: tools\test-failover.ps1 [-Profile llamaswap]
# Turn 1: llama-swap up; must answer (code word 1). Then llama-swap is stopped.
# Turn 2: same session (--resume); must still answer (code word 2) via the fallback; evidence = Ollama has the
#         fallback model loaded afterwards + new agent.log lines mentioning fallback.
# Turn 3: llama-swap restarted; same session; must answer (code word 3) and llama-swap's log must grow.
# Pass: all three answers correct, fallback evidence present, primary used again on turn 3.
param([string]$Profile = 'llamaswap', [string]$Fallback = 'ariadne-qwen3.5-4b')
$gateMutex = [System.Threading.Mutex]::new($false, 'Global\AriadneGate')
if (-not $gateMutex.WaitOne(0)) { Write-Host 'another Ariadne gate is running; refusing to overlap'; exit 2 }
$root = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'use-profile.ps1') $Profile | Out-Null
$env:HERMES_HOME = Join-Path $root '.hermes-home'
& (Join-Path $PSScriptRoot 'install-guard-pth.ps1') | Out-Null
$env:ARIADNE_GUARD_ALL_PROCS = '1'
$hermes = Join-Path $root '.venv\Scripts\hermes.exe'
$scratch = Join-Path $root 'scratch'; New-Item -ItemType Directory $scratch -Force | Out-Null
$logs = Join-Path $root 'logs'
$agentLog = Join-Path $env:HERMES_HOME 'logs\agent.log'
$swapLog = Join-Path $logs 'llama-swap.log'
function Turn([int]$n, [string]$session) {
  $word = "ARIADNE-T$n-" + (Get-Random -Minimum 10000 -Maximum 99999)
  $fixture = Join-Path $scratch "failover-$n.txt"
  Set-Content $fixture "The code word is $word." -Encoding ascii
  $q = "Use your file reading tool to read $fixture and reply with only the code word written in it."
  $args_ = @('chat', '-q', $q, '--oneshot', '-Q', '--max-turns', '8')
  if ($session) { $args_ += @('--resume', $session) }
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $ErrorActionPreference = 'Continue'
  $out = & $hermes @args_ 2>&1 | Out-String
  $code = $LASTEXITCODE; $sw.Stop()
  Set-Content (Join-Path $logs "a5-failover-turn$n.log") $out
  $sid = ([regex]::Match($out, 'session_id:\s*(\S+)')).Groups[1].Value
  [pscustomobject]@{ turn = $n; exit = $code; ok = (($code -eq 0) -and ($out -match [regex]::Escape($word))); secs = [math]::Round($sw.Elapsed.TotalSeconds, 1); session = $sid }
}
& (Join-Path $PSScriptRoot 'serve.ps1') | Out-Null
$agentStart = if (Test-Path $agentLog) { (Get-Content $agentLog).Count } else { 0 }
$t1 = Turn 1 ''
$session = $t1.session
& (Join-Path $PSScriptRoot 'serve.ps1') -Stop | Out-Null
$t2 = Turn 2 $session
$ollamaHasFallback = [bool]((& ollama ps) -match [regex]::Escape($Fallback))
$fallbackLines = @(Get-Content $agentLog | Select-Object -Skip $agentStart | Where-Object { $_ -match '(?i)fallback' })
& (Join-Path $PSScriptRoot 'serve.ps1') | Out-Null
$swapBefore = (Get-Item $swapLog).Length
$t3 = Turn 3 $session
$swapGrew = (Get-Item $swapLog).Length -gt $swapBefore
& (Join-Path $PSScriptRoot 'serve.ps1') -Stop | Out-Null
$t1, $t2, $t3 | Format-Table -AutoSize | Out-String | Write-Host
Write-Host "same session across turns: $(($t2.session -eq $session) -and ($t3.session -eq $session)) ($session)"
Write-Host "turn 2 evidence: Ollama has $Fallback loaded=$ollamaHasFallback; agent.log fallback lines=$($fallbackLines.Count)"
$fallbackLines | Select-Object -First 6 | ForEach-Object { Write-Host ('  ' + $_.Substring(0, [Math]::Min(220, $_.Length))) }
Write-Host "turn 3 used llama-swap again (its log grew): $swapGrew"
$pass = $t1.ok -and $t2.ok -and $t3.ok -and $ollamaHasFallback -and $swapGrew
Write-Host "FAILOVER: $(if ($pass) {'PASS'} else {'FAIL'})"
if ($pass) { exit 0 } else { exit 1 }
