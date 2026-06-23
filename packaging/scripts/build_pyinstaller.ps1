#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
& (Join-Path $Root "packaging/scripts/prepare_slim_resource.ps1")
$py = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m pip install pyinstaller pillow -q
& $py -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging/字幕助手.spec")
Write-Host "Output: $Root/dist/字幕助手/"
