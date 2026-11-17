# Installs a loader into Ariadne's own .venv (never upstream, never system Python) that starts the offline
# guard in EVERY Python process of the venv - the Hermes CLI included, which does not load plugins - when
# ARIADNE_GUARD_ALL_PROCS=1 (logic in tools\guard_loader.py). The Hermes plugin still guards the gateway on
# its own; the guard's process-wide marker stops double wrapping. Re-run after recreating .venv.
$root = Split-Path $PSScriptRoot -Parent
$sp = Join-Path $root '.venv\Lib\site-packages'
if (-not (Test-Path $sp)) { throw "no venv site-packages: $sp" }
$tools = Join-Path $root 'tools'
# .pth lines starting with 'import' are executed at interpreter start; same shape as ariadne_egress.pth.
Set-Content (Join-Path $sp 'ariadne_offline_guard.pth') "import sys; sys.path.append(r'$tools'); import guard_loader" -Encoding ascii
Write-Host "installed $sp\ariadne_offline_guard.pth"
