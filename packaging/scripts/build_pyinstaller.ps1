#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
$BuildRoot = $Root
$BuildJunction = $null

try {
    # Qt 5 reports its plugin directory as question marks when Python starts
    # from a non-ASCII path. Build through a temporary ASCII junction instead.
    if ($Root -match '[^\x00-\x7F]') {
        $BuildJunction = Join-Path ([System.IO.Path]::GetTempPath()) (
            "subtitle-assistant-build-" + [guid]::NewGuid().ToString("N")
        )
        New-Item -ItemType Junction -Path $BuildJunction -Target $Root | Out-Null
        $BuildRoot = $BuildJunction
        Write-Host "Using ASCII build path: $BuildRoot"
    }

    & (Join-Path $BuildRoot "packaging/scripts/prepare_slim_resource.ps1")
    $py = Join-Path $BuildRoot ".venv/Scripts/python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    # venv 由 uv 创建时没有 pip，自动回退到 uv 装包
    & $py -c "import pip" 2>$null
    $hasPip = $LASTEXITCODE -eq 0
    if ($hasPip) {
        & $py -m pip install pyinstaller pillow -q
    } else {
        Write-Host "pip not available in venv, using uv"
        uv pip install --python $py pyinstaller pillow -q
    }

    $sourceVersion = & $py -c (
        "import runpy; print(runpy.run_path('videocaptioner/_version.py')['__version__'])"
    )
    if ($LASTEXITCODE -ne 0 -or -not $sourceVersion) {
        throw "Unable to read the source version"
    }
    $pretendVersionName = "SETUPTOOLS_SCM_PRETEND_VERSION"
    $previousPretendVersion = [Environment]::GetEnvironmentVariable(
        $pretendVersionName,
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        $pretendVersionName,
        $sourceVersion,
        "Process"
    )
    try {
        if ($hasPip) {
            & $py -m pip install --no-deps --force-reinstall --editable $Root -q
        } else {
            uv pip install --python $py --no-deps --reinstall --editable $Root -q
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Project metadata refresh failed with exit code $LASTEXITCODE"
        }
    } finally {
        [Environment]::SetEnvironmentVariable(
            $pretendVersionName,
            $previousPretendVersion,
            "Process"
        )
    }

    & $py -m PyInstaller --noconfirm --clean (Join-Path $BuildRoot "packaging/字幕助手.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    $distInfo = Join-Path $Root (
        "dist/字幕助手/_internal/videocaptioner-$sourceVersion.dist-info"
    )
    if (-not (Test-Path -LiteralPath $distInfo)) {
        throw "Bundled project metadata does not match version $sourceVersion"
    }
} finally {
    if ($BuildJunction -and (Test-Path -LiteralPath $BuildJunction)) {
        Remove-Item -LiteralPath $BuildJunction -Force
    }
}
Write-Host "Output: $Root/dist/字幕助手/"
