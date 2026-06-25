# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — 字幕助手 GUI（不含 Faster-Whisper 与模型）
# 用法见 packaging/README.md

from pathlib import Path

ROOT = Path(SPEC).resolve().parent.parent
SLIM = ROOT / "packaging" / "slim_resource"

block_cipher = None


def _icon_path():
    for name in ("logo.ico", "logo.png"):
        p = ROOT / "resource" / "assets" / name
        if p.is_file():
            return str(p)
    return None


def _datas():
    pairs = []
    for sub in ("assets", "subtitle_style", "translations", "fonts"):
        src = SLIM / sub
        if not src.is_dir():
            src = ROOT / "resource" / sub
        if src.is_dir():
            pairs.append((str(src), f"resource/{sub}"))
    ff = SLIM / "bin" / "ffmpeg" / "ffmpeg.exe"
    if ff.is_file():
        pairs.append((str(ff.parent), "resource/bin/ffmpeg"))
    return pairs


a = Analysis(
    [str(ROOT / "videocaptioner" / "ui" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_datas(),
    hiddenimports=[
        "videocaptioner",
        "videocaptioner.ui.main",
        "videocaptioner.cli.main",
        "PyQt5",
        "qfluentwidgets",
        "openai",
        "edge_tts",
        "elevenlabs",
        "dtw",
        "numpy",
        "pydub",
        "gradio_client",
        "diskcache",
        "tenacity",
        "json_repair",
        "langdetect",
        "requests",
        "yt_dlp",
        "modelscope",
        "psutil",
        "GPUtil",
        "fontTools",
        "PIL",
        # dtw 依赖 scipy，必须收集（原 excludes 误删导致 ModuleNotFoundError）
        "scipy",
        "scipy.spatial",
        "scipy.sparse",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "torch", "tensorflow"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="字幕助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_path(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="字幕助手",
)