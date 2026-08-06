import pytest

from videocaptioner.ui.view.subtitle_style_interface import (
    select_preview_top_height,
)


@pytest.mark.parametrize(
    ("configured_canvas", "player_canvas", "expected"),
    [
        ((1080, 1920), (1920, 1080), 420),
        ((1920, 1080), (1080, 1920), 390),
        (None, (1080, 1920), 420),
        (None, (1920, 1080), 390),
    ],
)
def test_select_preview_top_height_uses_effective_canvas_orientation(
    configured_canvas, player_canvas, expected
):
    assert select_preview_top_height(configured_canvas, player_canvas) == expected
