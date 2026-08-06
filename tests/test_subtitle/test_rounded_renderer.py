from pathlib import Path

import pytest
from PIL import Image, ImageFont

from videocaptioner.core.subtitle import rounded_renderer
from videocaptioner.core.subtitle.styles import RoundedBgStyle


@pytest.fixture(autouse=True)
def use_qapp():
    """These renderer tests do not need a QApplication."""
    yield


def test_render_rounded_overlay_is_transparent_rgba(monkeypatch):
    monkeypatch.setattr(
        rounded_renderer,
        "get_font",
        lambda _size, _name: ImageFont.load_default(),
    )

    output_path = Path(
        rounded_renderer.render_rounded_overlay(
            primary_text="Preview subtitle",
            secondary_text="",
            width=320,
            height=180,
            style=RoundedBgStyle(font_size=32, margin_bottom=20),
        )
    )
    try:
        with Image.open(output_path) as image:
            assert image.mode == "RGBA"
            assert image.size == (320, 180)
            alpha_min, alpha_max = image.getchannel("A").getextrema()
            assert alpha_min == 0
            assert alpha_max > 0
            assert image.getpixel((0, 0))[3] == 0
    finally:
        output_path.unlink(missing_ok=True)
