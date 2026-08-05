"""Tests for the subtitle_gap_ms timeline placement pure functions."""

from videocaptioner.core.dubbing.models import DubbingSegment
from videocaptioner.core.dubbing.timeline import (
    compute_timeline_placements,
    write_adjusted_subtitle,
)


def test_gap_zero_keeps_original_timeline():
    # gap=0 是不变语义:每段仍放在各自原始 start。
    placements = compute_timeline_placements(
        [0, 1000], [2000, 2000], 0
    )
    assert placements == [(0, 2000), (1000, 3000)]


def test_gap_no_overlap_no_move():
    # 段之间原时间轴无重叠,即使有 gap 也保持原位。
    placements = compute_timeline_placements(
        [0, 4000], [1000, 1000], 500
    )
    assert placements == [(0, 1000), (4000, 5000)]


def test_gap_shifts_overlapping_segment():
    # 段 1 音频(2000ms)超出段 0 结束点,顺延到 cursor 之后。
    placements = compute_timeline_placements(
        [0, 1000], [2000, 2000], 500
    )
    # 段 0: 0..2000,cursor=2500;段 1: max(1000,2500)=2500 .. 4500
    assert placements == [(0, 2000), (2500, 4500)]


def test_gap_continuous_overlap_accumulates():
    # 连续重叠时逐段累积顺延。
    placements = compute_timeline_placements(
        [0, 500, 900], [1000, 1000, 1000], 100
    )
    assert placements == [(0, 1000), (1100, 2100), (2200, 3200)]


def test_write_adjusted_subtitle(tmp_path):
    segments = [
        DubbingSegment(index=1, start_ms=0, end_ms=1000, text="Hello"),
        DubbingSegment(index=2, start_ms=1000, end_ms=2000, text="World"),
    ]
    placements = [(0, 500), (1500, 2000)]
    out = tmp_path / "out.adjusted.srt"
    returned = write_adjusted_subtitle(segments, placements, str(out))
    assert returned == str(out)
    content = out.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:00,500" in content
    assert "00:00:01,500 --> 00:00:02,000" in content
    assert "Hello" in content
    assert "World" in content
