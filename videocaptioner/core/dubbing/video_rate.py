"""Per-segment video rate change to match a dubbed audio track.

A simplified port of pyVideoTrans ``task/_rate.py``. There is no rubberband and
no multiprocessing: we cut the video into contiguous intervals, apply a single
``setpts={factor}*PTS`` per interval (plus an optional frozen-frame ``tpad``
for the inter-line gap), and concatenate them.

The key design point is a **unified output timeline**: the rate plan fully
covers ``[0, video_duration]`` with head / subtitle-slot / inter-slot / tail
intervals, and the audio placements are derived from the plan's cumulative
output durations. That way the audio track and the picture are always derived
from the same timeline and stay in sync.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# On Windows, suppress "Application Error" crash dialogs for ffmpeg.
_SUBPROCESS_KWARGS: dict = {}
if sys.platform == "win32":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0003)
    _SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


@dataclass
class RatePlanItem:
    """One source-video interval to cut and rate-change.

    Attributes:
        start_ms: interval start in the source video (ms).
        end_ms: interval end in the source video (ms).
        pts_factor: ``setpts`` factor applied to this interval (>1 slows down).
        pad_after_ms: frozen last frame appended after this interval (ms),
            used to hold the inter-line silence gap.
    """

    start_ms: int
    end_ms: int
    pts_factor: float
    pad_after_ms: int


@dataclass
class RatePlan:
    """The full per-interval video rate plan.

    Attributes:
        items: rate instructions, in timeline order. The intervals tile the
            source video contiguously (no gaps), so no picture is dropped.
        total_output_duration_ms: total output duration of the concatenated
            picture (ms), i.e. the sum of every interval's output extent.
    """

    items: List[RatePlanItem] = field(default_factory=list)
    total_output_duration_ms: int = 0


def compute_rate_plan(
    slots: List[Tuple[int, int]],
    audio_durations_ms: List[int],
    gap_ms: int,
    video_duration_ms: int,
    max_slowdown: float,
) -> Tuple[RatePlan, List[Tuple[int, int]], List[float]]:
    """Compute the video rate plan and the audio placements it implies.

    The source video ``[0, video_duration_ms]`` is sliced into contiguous
    intervals: a head ``[0, s_0)``, each subtitle slot ``[s_i, e_i)``, a
    normal-speed inter-slot interval ``[e_i, s_{i+1})`` between slots, and a
    tail ``[e_last, V)``. Zero-length intervals are skipped. Every interval is
    kept in the plan, so no picture is ever dropped.

    Each subtitle owns the source interval from its start to the next subtitle
    start (the final subtitle owns the remaining video). The interval is sped up
    or slowed down to ``dub duration + gap_ms``. This matches pyVideoTrans and
    removes long source pauses left by filtered dialogue lines.

    When even the maximum slow-down cannot fit the audio
    (``d_i > slot_len * max_slowdown``), the audio itself must be compressed a
    second time: ``extra_tempo_i = d_i / (slot_len * max_slowdown)``. The
    pipeline applies that with ``change_tempo`` so the audio always fits.

    Args:
        slots: ``(start_ms, end_ms)`` source-video timecodes of each original
            subtitle.
        audio_durations_ms: fitted audio duration of each dub (ms).
        gap_ms: silence inserted after each dub (ms).
        video_duration_ms: total length of the source video (ms).
        max_slowdown: cap on the slow-down factor (``>1``).

    Returns:
        A ``(plan, placements, extra_tempo)`` tuple. ``placements[i]`` is the
        ``(start_ms, end_ms)`` on the output timeline where dub ``i`` must be
        placed (derived from the cumulative output durations), and
        ``extra_tempo[i]`` is the tempo-compression factor for that dub
        (``1.0`` when no second compression is needed).
    """
    count = min(len(slots), len(audio_durations_ms))
    if count == 0:
        return RatePlan(), [], []

    max_rate = max(1.0, float(max_slowdown))
    gap_ms = max(0, int(gap_ms))
    extra_tempo: List[float] = [1.0] * count
    intervals: List[List] = []
    first_start = max(0, int(slots[0][0]))
    if first_start > 0:
        intervals.append([0, first_start, 1.0, 0, -1])

    for i in range(count):
        start = max(0, int(slots[i][0]))
        if i + 1 < count:
            end = max(start + 1, int(slots[i + 1][0]))
        else:
            end = max(start + 1, int(slots[i][1]), int(video_duration_ms))
        source_duration = end - start
        max_target = source_duration * max_rate
        min_target = source_duration / max_rate
        effective_gap = min(gap_ms, max(0, int(max_target) - 100))
        audio_duration = max(1, int(audio_durations_ms[i]))
        available_audio = max(1, max_target - effective_gap)
        if audio_duration > available_audio:
            extra_tempo[i] = audio_duration / available_audio
        effective_audio = audio_duration / extra_tempo[i]
        target_duration = min(
            max(effective_audio + effective_gap, min_target), max_target
        )
        intervals.append(
            [start, end, target_duration / source_duration, 0, i]
        )

    # Convert intervals to plan items, tracking each slot's output start.
    items: List[RatePlanItem] = []
    slot_output_starts: dict = {}
    cursor = 0
    for s, e, pts, pad, slot_idx in intervals:
        out_dur = (e - s) * pts
        if slot_idx >= 0:
            slot_output_starts[slot_idx] = cursor
        items.append(
            RatePlanItem(start_ms=s, end_ms=e, pts_factor=pts, pad_after_ms=pad)
        )
        cursor += out_dur + pad
    total_output_duration_ms = round(cursor)

    # Audio placements derived from the plan's output timeline.
    placements: List[Tuple[int, int]] = []
    for i in range(len(slots)):
        start = round(slot_output_starts[i])
        audio_eff = round(audio_durations_ms[i] / extra_tempo[i])
        placements.append((start, start + audio_eff))

    plan = RatePlan(items=items, total_output_duration_ms=total_output_duration_ms)
    return plan, placements, extra_tempo


def get_video_duration_ms(video_path: str) -> int:
    """Query a video's duration in milliseconds via ffprobe (0 on failure)."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "json",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            **_SUBPROCESS_KWARGS,
        )
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams", [])
        if not streams or not streams[0].get("duration"):
            return 0
        return int(round(float(streams[0]["duration"]) * 1000))
    except Exception:
        return 0


def _run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)


def apply_video_rate(
    video_path: str,
    plan: RatePlan,
    output_path: str,
    callback: Optional[Callable[[int, str], None]] = None,
) -> None:
    """Rate-change the video per ``plan`` and write ``output_path``.

    Every plan interval is cut from the source (precise seek with ``-ss``
    before ``-i``), slowed by ``setpts={factor}*PTS``, and -- when it carries a
    trailing gap -- extended with a frozen last frame via
    ``tpad=stop_mode=clone``. The clips are concatenated in order and the result
    is moved to ``output_path`` (``shutil.move`` handles cross-drive copies).
    All intermediate clips live in a single temporary directory removed before
    returning.

    Args:
        video_path: source video.
        plan: rate plan from :func:`compute_rate_plan`.
        output_path: destination video path.
        callback: optional ``(progress, message)`` progress callback.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if not plan.items:
        # Nothing to change: copy the source through unchanged.
        _run(["ffmpeg", "-y", "-v", "error", "-i", video_path, "-c", "copy", output_path])
        return

    work = Path(tempfile.mkdtemp(prefix=".vrate_"))
    try:
        clip_paths: List[Path] = []
        total = len(plan.items)
        for i, item in enumerate(plan.items):
            clip = work / f"clip_{i:04d}.mp4"
            start_s = item.start_ms / 1000.0
            dur_s = (item.end_ms - item.start_ms) / 1000.0
            target_s = dur_s * item.pts_factor + item.pad_after_ms / 1000.0
            filters = [f"setpts={item.pts_factor:.6f}*PTS"]
            if item.pad_after_ms > 0:
                filters.append(
                    f"tpad=stop_mode=clone:stop_duration={item.pad_after_ms / 1000.0:.6f}"
                )
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    f"{start_s:.6f}",
                    "-t",
                    f"{dur_s:.6f}",
                    "-i",
                    video_path,
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-g",
                    "1",
                    "-fps_mode",
                    "vfr",
                    "-vf",
                    ",".join(filters),
                    "-t",
                    f"{target_s:.6f}",
                    str(clip),
                ]
            )
            clip_paths.append(clip)
            if callback:
                callback(int((i + 1) / total * 100), f"cutting video segment {i + 1}/{total}")

        concat_list = work / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in clip_paths), encoding="utf-8"
        )
        merged = work / "merged.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(merged),
            ]
        )

        shutil.move(str(merged), output_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
