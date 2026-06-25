#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
& (Join-Path $Root "packaging/scripts/prepare_slim_resource.ps1")
$py = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $py)) { $py = "python" }
# venv 由 uv 创建时没有 pip，自动回退到 uv 装包
$hasPip = & $py -c "import pip" 2>$null
if ($LASTEXITCODE -eq 0 -and $hasPip -ne $null) {
    & $py -m pip install pyinstaller pillow -q
} else {
    Write-Host "pip not available in venv, using uv"
    uv pip install --python $py pyinstaller pillow -q
}
& $py -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging/字幕助手.spec")
Write-Host "Output: $Root/dist/字幕助手/"
