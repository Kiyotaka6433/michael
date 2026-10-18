# One-command setup for Michael on Windows (CPU only). Safe to re-run: every step skips what is already done.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1                     # vault: ..\Michael Vault
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Vault "D:\Notes"   # or your own vault
#
# Steps: Python venv + packages -> Ollama + writing model -> pandoc -> Node tools (MathJax checker, plugin build)
#        -> Obsidian vault with the plugin -> offline tests. Missing programs are installed with winget only after
#        you confirm; nothing is installed silently.
param(
  [string]$Vault = "",
  [string]$Model = "qwen2.5:7b",
  [switch]$Yes            # install missing programs without asking
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Need($cmd, $wingetId, $why) {
  if (Have $cmd) { return $true }
  Write-Host "$cmd is missing ($why)." -ForegroundColor Yellow
  if (-not (Have "winget")) { Write-Host "Install it manually, then re-run setup.ps1."; return $false }
  $ok = $Yes -or ((Read-Host "Install $wingetId with winget now? [y/N]") -match "^[yY]")
  if (-not $ok) { Write-Host "Skipped. Re-run setup.ps1 after installing it."; return $false }
  winget install --silent --accept-package-agreements --accept-source-agreements $wingetId
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  return (Have $cmd)
}

Step "1/6 Python environment"
if (-not (Need "python" "Python.Python.3.12" "runs the backend")) { exit 1 }
if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
# a running backend locks .venv\Scripts\michael.exe and pip can't replace it: stop this project's backend only
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%' or Name = 'michael.exe'" |
  Where-Object { $_.CommandLine -like "*$Root\.venv*michael*serve*" }
if ($running) {
  $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Write-Host "stopped the running Michael backend (Obsidian's plugin starts it again)"
  Start-Sleep 2
}
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed (see above)." -ForegroundColor Red; exit 1 }
Write-Host "packages installed"

Step "2/6 Ollama and the writing model ($Model)"
if (Need "ollama" "Ollama.Ollama" "runs the local writing model") {
  $have = (& ollama list) -join "`n"
  if ($have -notmatch [regex]::Escape($Model)) { & ollama pull $Model } else { Write-Host "$Model already pulled" }
}

Step "3/6 pandoc (exact LaTeX from arXiv sources)"
[void](Need "pandoc" "JohnMacFarlane.Pandoc" "converts arXiv LaTeX sources")

Step "4/6 Node tools: MathJax checker and the Obsidian plugin"
if (Need "npm" "OpenJS.NodeJS.LTS" "checks formulas with MathJax and builds the plugin") {
  Push-Location tools\mathcheck; npm install --silent; Pop-Location
  Push-Location obsidian-michael; npm install --silent; npm run build; Pop-Location
}

Step "5/6 Obsidian vault with the Michael plugin"
if ($Vault) { & .venv\Scripts\python.exe scripts\setup_obsidian.py $Vault } else { & .venv\Scripts\python.exe scripts\setup_obsidian.py }

Step "6/6 Offline tests"
& .venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "Some tests failed (see above)." -ForegroundColor Red; exit 1 }

Write-Host "`nDone. Open the vault in Obsidian; the plugin starts the backend by itself." -ForegroundColor Green
Write-Host "The first research run downloads the embedding, reranker and verifier models (about 2 GB)."
