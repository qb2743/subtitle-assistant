#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Slim = Join-Path $Root "packaging/slim_resource"
$ThirdParty = Join-Path $Root "packaging/third_party/ffmpeg"
$BundledFw = Join-Path $Root "resource/bin/Faster-Whisper-XXL"

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

# FFmpeg tools: prefer third_party, then bundled Faster-Whisper, then project root.
$ffDst = Join-Path $Slim "bin/ffmpeg"
New-Item -ItemType Directory -Force -Path $ffDst | Out-Null

$tools = @("ffmpeg.exe", "ffprobe.exe")
foreach ($tool in $tools) {
    $src = Join-Path $ThirdParty $tool
    if (-not (Test-Path $src)) { $src = Join-Path $BundledFw $tool }
    if (-not (Test-Path $src)) { $src = Join-Path $Root $tool }
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $ffDst $tool) -Force
        Write-Host "Bundled $tool from $src"
    }
}

$missingTools = $tools | Where-Object { -not (Test-Path (Join-Path $ffDst $_)) }
if ($missingTools.Count -gt 0) {
    Write-Host "Downloading ffmpeg essentials..."
    $zip = Join-Path $Root "packaging/third_party/ffmpeg-essentials.zip"
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $tmp = Join-Path $Root "packaging/third_party/_fftmp"
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    foreach ($tool in $missingTools) {
        $found = Get-ChildItem $tmp -Recurse -Filter $tool | Select-Object -First 1
        if ($found) {
            Copy-Item $found.FullName (Join-Path $ffDst $tool) -Force
            Write-Host "Bundled $tool from download"
        }
    }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Done: $Slim"