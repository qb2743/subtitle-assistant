#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Slim = Join-Path $Root "packaging/slim_resource"
$ThirdParty = Join-Path $Root "packaging/third_party/ffmpeg"
$BundledFw = Join-Path $Root "resource/bin/Faster-Whisper-XXL/ffmpeg.exe"

foreach ($sub in @("assets", "subtitle_style", "translations", "fonts")) {
    $src = Join-Path $Root "resource/$sub"
    $dst = Join-Path $Slim $sub
    if (-not (Test-Path $src)) {
        if ($sub -eq "fonts") { continue }
        throw "Missing $src"
    }
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Copy-Item $src $dst -Recurse
    Write-Host "Copied $sub"
}

Get-ChildItem (Join-Path $Slim "assets") -Filter "donate_*.jpg" -ErrorAction SilentlyContinue | Remove-Item -Force

# logo.ico for PyInstaller / Inno
$py = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py (Join-Path $Root "packaging/scripts/make_logo_ico.py")

# ffmpeg — 优先 third_party，其次 Faster-Whisper 自带（不打包整个 FW）
$ffDst = Join-Path $Slim "bin/ffmpeg"
New-Item -ItemType Directory -Force -Path $ffDst | Out-Null
$ffSrc = Join-Path $ThirdParty "ffmpeg.exe"
if (-not (Test-Path $ffSrc)) { $ffSrc = $BundledFw }
if (Test-Path $ffSrc) {
    Copy-Item $ffSrc (Join-Path $ffDst "ffmpeg.exe") -Force
    Write-Host "Bundled ffmpeg.exe from $ffSrc"
} else {
    Write-Host "Downloading ffmpeg essentials..."
    $zip = Join-Path $Root "packaging/third_party/ffmpeg-essentials.zip"
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Root "packaging/third_party/_fftmp") -Force
    $found = Get-ChildItem (Join-Path $Root "packaging/third_party/_fftmp") -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if ($found) {
        Copy-Item $found.FullName (Join-Path $ffDst "ffmpeg.exe") -Force
        Write-Host "Bundled ffmpeg.exe from download"
    }
    Remove-Item (Join-Path $Root "packaging/third_party/_fftmp") -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Done: $Slim"