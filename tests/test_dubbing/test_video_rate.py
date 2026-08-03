"""Tests for per-segment video rate change (video_autorate).

The unified timeline model: the rate plan tiles the source video contiguously
(head / slots / inter-slot / tail), audio placements are derived from the
plan's cumulative output durations, and the concat output must reproduce the
plan's total duration (no picture dropped).
"""

import json
import shutil
import subprocess

import pytest

from videocaptioner.core.dubbing.video_rate import (
    RatePlan,
    apply_video_rate,
    compute_rate_plan,
)


# ---------------------------------------------------------------- pure plan


def test_rate_plan_full_coverage_keeps_inter_slot_frames():
    # 槽[1000,2000] 与 [4000,5000] 之间(2000..4000)以及头尾都必须保留。
    slots = [(1000, 2000), (4000, 5000)]
    plan, placements, extra = compute_rate_plan(
        slots, [1000, 1000], 0, video_duration_ms=6000, max_slowdown=2.0
    )
    # 5 个区间:head / slot0 / inter / slot1 / tail。
    assert [(i.start_ms, i.end_ms) for i in plan.items] == [
        (0, 1000),
        (1000, 2000),
        (2000, 4000),
        (4000, 5000),
        (5000, 6000),
    ]
    # 音频都不超槽 → 全部 pts=1.0。
    assert all(i.pts_factor == 1.0 for i in plan.items)
    # 输出总长 = 各区间输出时长之和 = 1000+1000+2000+1000+1000。
    assert plan.total_output_duration_ms == 6000
    assert plan.total_output_duration_ms == sum(
        (i.end_ms - i.start_ms) * i.pts_factor + i.pad_after_ms
        for i in plan.items
    )
    # 音频放置从输出时间轴累积推导。
    assert placements == [(1000, 2000), (4000, 5000)]


def test_rate_plan_sync_accumulation():
    # 验证 placement_i 起点 == 前序区间输出时长累积。
    slots = [(1000, 2000), (4000, 5000)]
    plan, placements, extra = compute_rate_plan(
        slots, [1000, 1000], 0, video_duration_ms=6000, max_slowdown=2.0
    )
    # slot0 起点 = head(1000);slot1 起点 = head(1000)+slot0(1000)+inter(2000)。
    assert placements[0][0] == 1000
    assert placements[1][0] == 4000


def test_rate_plan_slowdown_slot():
    slots = [(1000, 2000), (3000, 5000)]
    plan, placements, extra = compute_rate_plan(
        slots, [2000, 1000], 0, video_duration_ms=6000, max_slowdown=2.0
    )
    # slot0 音频 2000 > 槽 1000 → pts=2.0;slot1 音频 1000 == 槽 → pts=1.0。
    slot_pts = {i.start_ms: i.pts_factor for i in plan.items}
    assert slot_pts[1000] == pytest.approx(2.0)
    assert slot_pts[3000] == 1.0
    # 输出总长 = head1000 + slot0 2000 + inter1000 + slot1 2000 + tail1000。
    assert plan.total_output_duration_ms == 7000
    # 音频仍未超长,无需二次压缩。
    assert extra == [1.0, 1.0]


def test_rate_plan_extra_tempo_when_audio_too_long():
    # 音频 6000 = 3×槽长(1000)×max(2.0) → extra_tempo=3.0。
    slots = [(0, 1000)]
    plan, placements, extra = compute_rate_plan(
        slots, [6000], 0, video_duration_ms=1000, max_slowdown=2.0
    )
    assert extra == [3.0]
    # 槽 pts 被打到上限 2.0,音频被压缩后必然放得下。
    assert plan.items[0].pts_factor == pytest.approx(2.0)
    assert placements == [(0, 2000)]  # 6000/3.0 = 2000
    assert plan.total_output_duration_ms == 2000


def test_rate_plan_gap_pads_frozen_frame():
    # gap>0 时每个槽后追加冻结帧,输出时间轴相应顺延。
    slots = [(0, 1000), (2000, 3000)]
    plan, placements, extra = compute_rate_plan(
        slots, [1000, 1000], 500, video_duration_ms=4000, max_slowdown=2.0
    )
    # slot0 与 slot1 都带 pad_after=500。
    assert {i.start_ms: i.pad_after_ms for i in plan.items if i.pts_factor == 1.0}[0] == 500
    # 输出总长 = 1000+500 + 1000 + 1000+500 + 1000 = 5000。
    assert plan.total_output_duration_ms == 5000
    # slot1 起点 = slot0(1000+500 pad) + inter(1000) = 2500。
    assert placements[1][0] == 2500


def test_rate_plan_empty():
    plan, placements, extra = compute_rate_plan(
        [], [], 0, video_duration_ms=0, max_slowdown=2.0
    )
    assert plan.items == []
    assert plan.total_output_duration_ms == 0
    assert placements == []
    assert extra == []


# ------------------------------------------------------------- ffmpeg smoke


_ffmpeg = shutil.which("ffmpeg")
_ffprobe = shutil.which("ffprobe")


def _have_ffmpeg() -> bool:
    if not _ffmpeg or not _ffprobe:
        return False
    try:
        subprocess.run([_ffmpeg, "-version"], capture_output=True, check=True, timeout=20)
        return True
    except Exception:
        return False


def _video_duration_ms(path) -> int:
    out = subprocess.run(
        [
            _ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout or "{}")
    stream = data.get("streams", [{}])[0]
    duration = float(stream.get("duration", 0))
    return int(round(duration * 1000))


def _make_video(path, seconds=6):
    subprocess.run(
        [
            _ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=320x240:rate=30",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_apply_video_rate_keeps_inter_slot_frames(tmp_path):
    # 6s 视频,槽[1000,2000]与[4000,5000],中段 2000..4000 必须保留。
    video = tmp_path / "src.mp4"
    _make_video(video, seconds=6)
    plan, placements, _ = compute_rate_plan(
        [(1000, 2000), (4000, 5000)], [1000, 1000], 0, 6000, 2.0
    )
    out = tmp_path / "out.mp4"
    apply_video_rate(str(video), plan, str(out))
    assert out.exists() and out.stat().st_size > 0
    # 输出 ≈ 计划总长 6000ms(±100ms 容差),证明中段画面没有丢。
    assert abs(_video_duration_ms(out) - plan.total_output_duration_ms) < 100


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_apply_video_rate_slowdown_matches_plan(tmp_path):
    # slot0 音频超槽 → 减速到 2.0,输出总长仍等于计划。
    video = tmp_path / "src.mp4"
    _make_video(video, seconds=6)
    plan, placements, _ = compute_rate_plan(
        [(1000, 2000), (3000, 5000)], [2000, 1000], 0, 6000, 2.0
    )
    out = tmp_path / "out.mp4"
    apply_video_rate(str(video), plan, str(out))
    assert out.exists() and out.stat().st_size > 0
    assert abs(_video_duration_ms(out) - plan.total_output_duration_ms) < 150


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_apply_video_rate_empty_plan_copies(tmp_path):
    video = tmp_path / "src.mp4"
    _make_video(video, seconds=1)
    out = tmp_path / "out.mp4"
    apply_video_rate(str(video), RatePlan(), str(out))
    assert out.exists() and out.stat().st_size > 0