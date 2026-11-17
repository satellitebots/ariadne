# Start (or restart) Ariadne's local model server: llama-swap on 127.0.0.1:8090 with serving\llama-swap.yaml.
# Usage: tools\serve.ps1 [-Stop] [-Listen 127.0.0.1:8090]
# Logs: logs\llama-swap.log. Stops any llama-swap / llama-server started from serving\bin first.
# Launched through Win32_Process.Create so the server inherits no handles from the caller: a caller that pipes
# this script's output (e.g. `serve.ps1 | Select-Object -Last 3`) returns instead of waiting on the server.
param([switch]$Stop, [string]$Listen = '127.0.0.1:8090')
$root = Split-Path $PSScriptRoot -Parent
$bin = Join-Path $root 'serving\bin'
$swap = Join-Path $bin 'llama-swap-v273\llama-swap.exe'
$cfg = Join-Path $root 'serving\llama-swap.yaml'
Get-Process llama-swap, llama-server -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -and $_.Path.StartsWith($bin) } | Stop-Process -Force
if ($Stop) { Write-Host 'stopped'; return }
$null = & $swap -config $cfg -validate 2>&1
if ($LASTEXITCODE -ne 0) { throw "llama-swap config invalid: $cfg" }
$logs = Join-Path $root 'logs'; New-Item -ItemType Directory $logs -Force | Out-Null
$log = Join-Path $logs 'llama-swap.log'
$cmdLine = "cmd.exe /c `"`"$swap`" -config `"$cfg`" -listen $Listen > `"$log`" 2>&1`""
$r = Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $root }
if ($r.ReturnValue -ne 0) { throw "could not start llama-swap (Win32_Process.Create returned $($r.ReturnValue))" }
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep 1
  try { $null = Invoke-RestMethod "http://$Listen/v1/models" -TimeoutSec 2; Write-Host "llama-swap up on http://$Listen (log: logs\llama-swap.log)"; return } catch {}
}
throw "llama-swap did not come up; see $log"
