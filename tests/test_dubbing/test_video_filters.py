import re
from pathlib import Path

from videocaptioner.core.utils.video_filters import (
    apply_video_filter,
    build_canvas_filter,
    build_random_color_filter,
    build_random_mirror_filter,
    build_video_filter_chain,
    detect_scene_cuts_ffmpeg,
)


def test_canvas_filter_is_stable_and_validates_dimensions():
    assert build_canvas_filter("off") == ""
    assert "scale=1080:1920" in build_canvas_filter("1080x1920")
    assert "setsar=1" in build_canvas_filter((1920, 1080))


def test_random_filters_are_seeded():
    assert build_random_color_filter(seed=7) == build_random_color_filter(seed=7)
    mirror = build_random_mirror_filter([1.0, 2.0], seed=7)
    assert "hflip=enable=" in mirror
    assert build_random_mirror_filter([], seed=7) == ""


def test_random_mirror_is_scattered_in_short_runs():
    mirror = build_random_mirror_filter(
        range(1, 20), video_duration=20.0, min_shot=0, seed=7
    )
    intervals = [
        (float(start), float(end))
        for start, end in re.findall(
            r"gte\(t,([\d.]+)\)\*lt\(t,([\d.]+)\)", mirror
        )
    ]
    assert intervals
    assert all(end - start <= 2.000002 for start, end in intervals)
    assert all(next_start - end >= 1.999998 for (_, end), (next_start, _) in zip(intervals, intervals[1:]))


def test_scene_mirror_keeps_frame_precision_and_prunes_short_shots():
    filters = [
        build_random_mirror_filter(
            [1.0, 1.1, 3.1234567],
            video_duration=8.0,
            min_shot=0,
            seed=seed,
        )
        for seed in range(20)
    ]
    precise = next(value for value in filters if "3.123456" in value)
    assert "hflip=enable=" in precise

    recurring_frame_boundary = build_random_mirror_filter(
        [67.166667], video_duration=70.0, min_shot=0, seed=4
    )
    assert "67.166666" in recurring_frame_boundary

    pruned = build_random_mirror_filter(
        [1.0, 1.1, 4.0],
        video_duration=8.0,
        min_shot=3.0,
        seed=7,
    )
    assert "1.000000" not in pruned
    assert "1.100000" not in pruned


def test_filter_chain_combines_enabled_effects():
    chain = build_video_filter_chain(
        canvas="1080x1920",
        scene_cuts=[1.0],
        random_mirror=True,
        random_color=True,
        seed=1,
    )
    assert "scale=1080:1920" in chain
    assert "eq=" in chain


def test_scene_detection_gracefully_handles_missing_file(tmp_path: Path):
    assert detect_scene_cuts_ffmpeg(tmp_path / "missing.mp4") == []


def test_apply_video_filter_rejects_missing_input(tmp_path: Path):
    try:
        apply_video_filter(tmp_path / "missing.mp4", tmp_path / "out.mp4", "eq=brightness=0")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing input should fail clearly")
