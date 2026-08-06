from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtMultimedia import QMediaPlayer

from videocaptioner.ui.components.SubtitleVideoPreview import (
    SubtitleVideoPreview,
    _SoftwareVideoSurface,
    format_media_time,
    select_preview_canvas_size,
    select_preview_view_size,
)


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (-1, "00:00"),
        (0, "00:00"),
        (61_000, "01:01"),
        (3_661_000, "01:01:01"),
    ],
)
def test_format_media_time(milliseconds, expected):
    assert format_media_time(milliseconds) == expected


def test_native_video_size_wins_after_metadata_is_loaded():
    size = select_preview_canvas_size(
        forced_canvas=None,
        has_video=True,
        source_changed=False,
        native_size=(640, 480),
        poster_size=(1280, 720),
        current_size=(1280, 720),
    )

    assert size == (640, 480)


def test_poster_size_is_used_while_new_video_metadata_loads():
    size = select_preview_canvas_size(
        forced_canvas=None,
        has_video=True,
        source_changed=True,
        native_size=(1920, 1080),
        poster_size=(480, 852),
        current_size=(1280, 720),
    )

    assert size == (480, 852)


@pytest.mark.parametrize(
    ("canvas_size", "available_size", "expected"),
    [
        ((1080, 1920), (1461, 276), (155, 276)),
        ((1920, 1080), (1461, 276), (491, 276)),
        ((1920, 1080), (320, 276), (320, 180)),
    ],
)
def test_preview_view_size_follows_canvas_aspect_ratio(
    canvas_size, available_size, expected
):
    assert select_preview_view_size(canvas_size, available_size) == expected


def test_fit_view_resets_transform_before_fitting():
    scene_rect = MagicMock()
    scene_rect.isValid.return_value = True
    scene = MagicMock()
    scene.sceneRect.return_value = scene_rect
    view = MagicMock()
    preview = SimpleNamespace(scene=scene, view=view)

    SubtitleVideoPreview.fitView(preview)

    assert view.method_calls == [
        call.resetTransform(),
        call.fitInView(scene_rect, Qt.KeepAspectRatio),
    ]


def test_playing_state_does_not_hide_poster_before_first_frame():
    preview = SimpleNamespace(
        _has_started=False,
        playBar=SimpleNamespace(playButton=MagicMock()),
        posterItem=MagicMock(),
    )

    SubtitleVideoPreview._on_player_state_changed(
        preview, QMediaPlayer.PlayingState
    )

    assert preview._has_started is False
    preview.posterItem.setVisible.assert_not_called()


def test_position_change_does_not_hide_poster_before_first_frame():
    preview = SimpleNamespace(
        _has_started=False,
        _source_path="video.mp4",
        player=SimpleNamespace(duration=lambda: 80_000),
        posterItem=MagicMock(),
        timeLabel=MagicMock(),
    )

    SubtitleVideoPreview._update_time_label(preview, 40_000)

    assert preview._has_started is False
    preview.posterItem.setVisible.assert_not_called()
    preview.timeLabel.setText.assert_called_once_with("00:40 / 01:20")


def test_first_software_video_frame_hides_poster():
    image = MagicMock()
    image.isNull.return_value = False
    image.width.return_value = 1080
    image.height.return_value = 1920
    preview = SimpleNamespace(
        _has_started=False,
        _source_path="video.mp4",
        _forced_canvas=(1080, 1920),
        _canvas_size=(1080, 1920),
        _layout_video_frame=MagicMock(),
        posterItem=MagicMock(),
    )

    with patch(
        "videocaptioner.ui.components.SubtitleVideoPreview.QPixmap"
    ) as pixmap_class:
        SubtitleVideoPreview._on_video_frame_available(preview, image)

    assert preview._has_started is True
    assert preview._native_size == (1080, 1920)
    pixmap_class.fromImage.assert_called_once_with(image)
    preview._layout_video_frame.assert_called_once_with()
    preview.posterItem.setVisible.assert_called_once_with(False)


def test_invalid_software_video_frame_keeps_poster_visible():
    image = MagicMock()
    image.isNull.return_value = True
    preview = SimpleNamespace(
        _has_started=False,
        _source_path="video.mp4",
        posterItem=MagicMock(),
    )

    SubtitleVideoPreview._on_video_frame_available(preview, image)

    assert preview._has_started is False
    preview.posterItem.setVisible.assert_not_called()


def test_software_video_surface_throttles_before_mapping_frame():
    frame = MagicMock()
    surface = SimpleNamespace(
        _FRAME_INTERVAL_MS=33,
        _frame_clock=SimpleNamespace(elapsed=lambda: 120),
        _last_frame_ms=100,
    )

    assert _SoftwareVideoSurface.present(surface, frame) is True

    frame.isValid.assert_not_called()
    frame.map.assert_not_called()


def test_software_video_surface_reset_keeps_first_frame():
    surface = SimpleNamespace(_FRAME_INTERVAL_MS=33, _last_frame_ms=100)

    _SoftwareVideoSurface.resetFrameThrottle(surface)

    assert surface._last_frame_ms == -33
