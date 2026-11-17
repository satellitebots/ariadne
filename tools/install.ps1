# Install Ariadne on a Windows machine with an NVIDIA GPU, or check what is missing.
#   powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Check     # report only, change nothing
#   powershell -ExecutionPolicy Bypass -File tools\install.ps1            # install whatever is missing
#   ... -Slack                                                             # also the Slack channel dependencies
# Supported entry points: Slack, the terminal (CLI) and MCP (Claude and other large models).
# Every download is pinned: winget packages by id, Hermes by commit (hermes.lock), Python packages by upstream
# uv.lock, binaries by sha256 (serving\bin.lock), model files by sha256 (serving\models.lock), Ollama models by tag.
param([switch]$Check, [switch]$Slack)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$missing = New-Object System.Collections.Generic.List[string]
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Step($name, [scriptblock]$test, [scriptblock]$fix, $why) {
  if (& $test) { Write-Host ("  ok       {0}" -f $name); return }
  if ($Check) { Write-Host ("  MISSING  {0} - {1}" -f $name, $why); $missing.Add($name); return }
  Write-Host ("  install  {0} - {1}" -f $name, $why); & $fix
  if (-not (& $test)) { throw "$name still missing after install; see the output above" }
}
function Winget($id) { winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements | Out-Host
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') }

Write-Host "Ariadne install ($(if ($Check) { 'check only' } else { 'install' })) in $root"
Write-Host "System"
Step 'NVIDIA driver (nvidia-smi)' { Has nvidia-smi } { throw 'Install the NVIDIA driver from nvidia.com, then rerun.' } 'GPU for the local models'
Step 'winget' { Has winget } { throw 'winget (App Installer) is required: install it from the Microsoft Store.' } 'installs the tools below'
Step 'git' { Has git } { Winget 'Git.Git' } 'source control, Hermes checkout'
Step 'uv' { Has uv } { Winget 'astral-sh.uv' } 'Python and the pinned Hermes environment'
Step 'Node.js (npx)' { Has npx.cmd } { Winget 'OpenJS.NodeJS.LTS' } 'runs the Chrome browser MCP server'
Step 'Ollama' { Has ollama } { Winget 'Ollama.Ollama' } 'stores the model weights; fallback model server'
Step 'Google Chrome' { Test-Path 'C:\Program Files\Google\Chrome\Application\chrome.exe' } { Winget 'Google.Chrome' } 'the visible browser'

Write-Host "Hermes (pinned)"
$lock = @{}; Get-Content (Join-Path $root 'hermes.lock') | ForEach-Object { $k, $v = $_.Split('=', 2); $lock[$k] = $v }
$up = Join-Path $root 'upstream'
Step "Hermes at $($lock.commit)" { (Test-Path "$up\.git") -and ((git -C $up rev-parse --short=10 HEAD) -eq $lock.commit) } {
  if (-not (Test-Path "$up\.git")) { git clone $lock.repo $up }
  git -C $up fetch origin; git -C $up checkout --detach $lock.commit } 'the agent engine, never edited'
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
$extras = @('--extra', 'mcp') + $(if ($Slack) { @('--extra', 'slack') } else { @() })
Step 'Python env (.venv, Hermes + MCP)' { (Test-Path $venvPy) -and ((& $venvPy -c 'import mcp, ruamel.yaml; print(1)' 2>$null) -eq '1') } {
  $env:UV_PROJECT_ENVIRONMENT = Join-Path $root '.venv'
  uv sync --project $up --frozen --no-dev @extras
  uv pip install --python $venvPy pytest==9.1.1 } 'Hermes, MCP SDK, tests'
if ($Slack) { Step 'Slack SDK' { (& $venvPy -c 'import slack_bolt; print(1)' 2>$null) -eq '1' } {
  $env:UV_PROJECT_ENVIRONMENT = Join-Path $root '.venv'; uv sync --project $up --frozen --no-dev @extras
  uv pip install --python $venvPy pytest==9.1.1 } 'Slack channel (Socket Mode)' }

Write-Host "Serving binaries and models"
$bin = Join-Path $root 'serving\bin'
Get-Content (Join-Path $root 'serving\bin.lock') | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object {
  $name, $ver = $_.Split('|')[0, 1]
  $dir = switch ($name) { 'cudart' { "llama.cpp-$ver" } 'cudart-sd' { "sd.cpp-$ver" } default { "$name-$ver" } }
  $marker = switch ($name) { 'cudart' { 'cudart64_12.dll' } 'cudart-sd' { 'cudart64_12.dll' } default { '*.exe' } }
  Step "$name $ver" { @(Get-ChildItem (Join-Path $bin $dir) -Recurse -Filter $marker -ErrorAction SilentlyContinue).Count -gt 0 } {
    & (Join-Path $PSScriptRoot 'fetch-serving-bins.ps1') -Only $name } 'pinned release, sha256-verified'
}
Get-Content (Join-Path $root 'serving\models.lock') | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object {
  $name = $_.Split('|')[0]
  Step "model $name" { Test-Path (Join-Path $root "models\$name") } { & (Join-Path $PSScriptRoot 'fetch-models.ps1') -Only $name } 'pinned, sha256-verified'
}
foreach ($tag in 'qwen3.5:9b', 'qwen3.5:4b', 'qwen3-embedding:0.6b') {
  Step "Ollama model $tag" { (ollama list 2>$null | Select-String -SimpleMatch $tag) } { ollama pull $tag } 'weights llama-swap serves'
}
Get-ChildItem (Join-Path $root 'serving\ollama') -Filter *.Modelfile | ForEach-Object {
  $tag = $_.BaseName
  Step "Ollama tag $tag" { (ollama list 2>$null | Select-String -SimpleMatch $tag) } { ollama create $tag -f $_.FullName } '64K-context fallback'
}

Write-Host "Ariadne"
Step 'gateway profile (.hermes-home)' { Test-Path (Join-Path $root '.hermes-home\skills\ariadne-tasks\SKILL.md') } {
  & (Join-Path $PSScriptRoot 'use-profile.ps1') ariadne } 'Hermes gateway with the ariadne-tasks MCP server'
Step 'flows compiled (.ariadne\homes)' { Test-Path (Join-Path $root '.ariadne\homes\coding\config.yaml') } {
  $env:PYTHONPATH = $root; & $venvPy -m ariadne.flows } 'one Hermes worker home per flow'

if ($Check) {
  if ($missing.Count) { Write-Host "`n$($missing.Count) missing: $($missing -join ', '). Run tools\install.ps1 to install them."; exit 1 }
  Write-Host "`nEverything is installed."; exit 0
}
Write-Host "`nInstalled. Start it: tools\host.ps1 (add -Lan for other machines). Clients: .venv\Scripts\python.exe -m ariadne.host connect"
