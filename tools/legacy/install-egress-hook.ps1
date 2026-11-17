# Installs the env-gated egress hook into Ariadne's own .venv (never upstream, never system Python).
# The hook is inert unless ARIADNE_EGRESS_LOG is set. Re-run after recreating .venv.
$root = Split-Path $PSScriptRoot -Parent
$sp = Join-Path $root '.venv\Lib\site-packages'
if (-not (Test-Path $sp)) { throw "no venv site-packages: $sp" }
$tools = Join-Path $root 'tools'
# .pth lines starting with 'import' are executed at interpreter start.
Set-Content (Join-Path $sp 'ariadne_egress.pth') "import sys; sys.path.append(r'$tools'); import egress_hook" -Encoding ascii
Write-Host "installed $sp\ariadne_egress.pth"
