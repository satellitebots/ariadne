# Host Ariadne on this machine: local models (llama-swap) + the ariadne-tasks MCP endpoint over HTTP with a token.
# Usage:
#   tools\host.ps1                       # start on loopback: models 127.0.0.1:8090, tasks http://127.0.0.1:8791/mcp
#   tools\host.ps1 -Lan                  # tasks endpoint on all interfaces (other machines connect; token required)
#   tools\host.ps1 -Stop                 # stop the tasks endpoint and llama-swap
#   tools\host.ps1 -Install [-Lan]       # also start at logon (Windows scheduled task "Ariadne host", current user)
#   tools\host.ps1 -Uninstall            # remove the scheduled task
# Models always stay on loopback; remote clients give tasks to Ariadne, they never call the models directly.
# For -Lan, allow TCP 8791 in Windows Firewall yourself (private networks only). Client configs:
#   .venv\Scripts\python.exe -m ariadne.host connect --host <this machine's name or IP>
param([switch]$Lan, [switch]$Stop, [switch]$Install, [switch]$Uninstall, [int]$Port = 8791)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root '.ariadne\logs'; New-Item -ItemType Directory $logs -Force | Out-Null
$taskName = 'Ariadne host'

function Stop-Endpoint {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*-m ariadne.host serve*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if ($Uninstall) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "removed '$taskName'"; return }
if ($Stop) { Stop-Endpoint; & (Join-Path $PSScriptRoot 'serve.ps1') -Stop; return }

& (Join-Path $PSScriptRoot 'serve.ps1')                       # models on 127.0.0.1:8090
Stop-Endpoint
$bind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
$cmdLine = "cmd.exe /c `"`"$py`" -m ariadne.host serve --host $bind --port $Port > `"$logs\host.log`" 2>&1`""
$env:PYTHONPATH = $root
$r = Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $root }
if ($r.ReturnValue -ne 0) { throw "could not start the tasks endpoint ($($r.ReturnValue))" }
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep 1
  try { $null = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2; break } catch {}
}
Write-Host "Ariadne tasks endpoint: http://${bind}:$Port/mcp  (token: .ariadne\token; log: .ariadne\logs\host.log)"

if ($Install) {
  $argList = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`"" + $(if ($Lan) { ' -Lan' } else { '' })
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argList -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Force | Out-Null
  Write-Host "installed scheduled task '$taskName' (at logon, $env:USERNAME)"
}
