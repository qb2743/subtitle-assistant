"""Tests for ASS subtitle renderer."""

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from videocaptioner.core.subtitle import ass_renderer, font_utils


@pytest.fixture(autouse=True)
def use_qapp():
    """Override the conftest.py fixture — these tests don't touch Qt."""
    yield


MINIMAL_ASS_STYLE = """[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,40,1
Style: Secondary,Arial,32,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,10,10,40,1
"""


def _make_bg(tmp_path: Path) -> Path:
    bg = tmp_path / "bg.png"
    Image.new("RGB", (320, 180), (0, 0, 0)).save(bg)
    return bg


def test_render_ass_preview_quotes_ffmpeg_filter_paths(monkeypatch, tmp_path):
    """Regression for issue #1090: -vf ass=...:fontsdir=... must be single-quoted.

    Without quotes, FFmpeg parses the path's `/` as the start of a new filter
    option and aborts with `No option name near '/Python312/Lib/...'` for any
    install path containing `/`.
    """
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ass_renderer.subprocess, "run", fake_run)
    monkeypatch.setattr(ass_renderer, "auto_wrap_ass_file", lambda p, **kw: p)

    ass_renderer.render_ass_preview(
        style_str=MINIMAL_ASS_STYLE,
        preview_text=("hello", None),
        bg_image_path=str(_make_bg(tmp_path)),
    )

    cmd = captured["cmd"]
    vf_index = cmd.index("-vf")
    vf_value = cmd[vf_index + 1]

    assert vf_value.startswith("scale=320:180"), vf_value
    assert ",ass='" in vf_value, f"ass path is not single-quoted: {vf_value}"
    assert "':fontsdir='" in vf_value, f"fontsdir is not single-quoted: {vf_value}"
    assert vf_value.endswith("'"), f"fontsdir path is not closed: {vf_value}"


def test_render_ass_overlay_uses_transparent_rgba_source(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ass_renderer.subprocess, "run", fake_run)
    monkeypatch.setattr(ass_renderer, "auto_wrap_ass_file", lambda path: path)
    monkeypatch.setattr(ass_renderer, "CACHE_PATH", tmp_path)
    monkeypatch.setattr(
        ass_renderer,
        "_convert_ass_overlay_to_straight_alpha",
        lambda _path: None,
    )

    output_path = Path(
        ass_renderer.render_ass_overlay(
            style_str=MINIMAL_ASS_STYLE,
            preview_text=("hello", None),
            width=320,
            height=180,
        )
    )
    try:
        cmd = captured["cmd"]
        source = cmd[cmd.index("-i") + 1]
        subtitle_filter = cmd[cmd.index("-vf") + 1]

        assert source == "color=c=black@0.0:s=320x180,format=rgba"
        assert subtitle_filter.startswith("ass='")
        assert ":fontsdir='" in subtitle_filter
        assert ":alpha=1,format=rgba" in subtitle_filter
        assert cmd[cmd.index("-pix_fmt") + 1] == "rgba"
    finally:
        output_path.unlink(missing_ok=True)


def test_ffmpeg_filter_path_escapes_apostrophes():
    escaped = ass_renderer._escape_ffmpeg_filter_path(r"C:\Users\O'Brien\fonts")
    assert escaped == r"C\:/Users/O'\''Brien/fonts"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_render_ass_overlay_outputs_straight_alpha(tmp_path, monkeypatch):
    style = MINIMAL_ASS_STYLE.replace(",1,2,0,2,", ",1,0,0,2,")
    monkeypatch.setattr(ass_renderer, "CACHE_PATH", tmp_path)

    output_path = Path(
        ass_renderer.render_ass_overlay(
            style_str=style,
            preview_text=("TEST", None),
            width=320,
            height=180,
        )
    )
    try:
        with Image.open(output_path) as image:
            pixels = [
                pixel
                for pixel in image.getdata()
                if 64 <= pixel[3] <= 192
            ]
            assert pixels
            assert min(min(pixel[:3]) for pixel in pixels) >= 240
    finally:
        output_path.unlink(missing_ok=True)


def test_font_variants_map_to_ass_flags(monkeypatch):
    monkeypatch.setattr(
        font_utils,
        "_find_font_record",
        lambda name: {"family_name": "Arial", "style_name": name.rsplit("/", 1)[-1]},
    )

    assert font_utils.get_font_ass_attributes("Arial / Regular") == ("Arial", 0, 0)
    assert font_utils.get_font_ass_attributes("Arial / Bold") == ("Arial", -1, 0)
    assert font_utils.get_font_ass_attributes("Arial / Italic") == ("Arial", 0, -1)


def test_get_video_resolution_handles_empty_ffmpeg_output(monkeypatch):
    monkeypatch.setattr(
        ass_renderer.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, None, None),
    )

    assert ass_renderer._get_video_resolution("missing.mp4") == (1920, 1080)
