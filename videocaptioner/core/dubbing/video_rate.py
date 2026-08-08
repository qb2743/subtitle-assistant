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
    locked_slots: Optional[List[Tuple[int, int]]] = None,
) -> Tuple[RatePlan, List[Tuple[int, int]], List[float]]:
    """Compute the video rate plan and the audio placements it implies.

    The source video ``[0, video_duration_ms]`` is sliced into contiguous
    intervals: a head ``[0, s_0)``, each subtitle slot ``[s_i, e_i)``, a
    normal-speed inter-slot interval ``[e_i, s_{i+1})`` between slots, and a
    tail ``[e_last, V)``. Zero-length intervals are skipped. Every interval is
    kept in the plan, so no picture is ever dropped.

    Each dubbed subtitle owns the source interval from its start to the next
    subtitle event. ``locked_slots`` add display-only events for original-film
    dialogue. A locked event owns its interval at ``1.0x`` and its explicit
    source range always takes priority over a dubbed interval. This keeps the
    original dialogue picture untouched without sending that text to TTS.

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
        locked_slots: source intervals that must remain at normal speed.

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
    normalized_slots = [
        (max(0, int(start)), max(max(0, int(start)) + 1, int(end)))
        for start, end in slots[:count]
    ]
    normalized_locked = [
        (max(0, int(start)), max(max(0, int(start)) + 1, int(end)))
        for start, end in (locked_slots or [])
    ]
    video_end = max(
        int(video_duration_ms),
        *(end for _start, end in normalized_slots),
        *(end for _start, end in normalized_locked),
    )

    event_by_start: dict[int, tuple[str, Optional[int]]] = {}
    for index, (start, _end) in enumerate(normalized_slots):
        event_by_start.setdefault(start, ("dub", index))
    for start, _end in normalized_locked:
        event_by_start[start] = ("locked", None)
    event_starts = sorted(start for start in event_by_start if start < video_end)

    items: List[RatePlanItem] = []
    slot_output_starts: dict[int, float] = {}
    cursor = 0.0
    if event_starts and event_starts[0] > 0:
        items.append(RatePlanItem(0, event_starts[0], 1.0, 0))
        cursor = float(event_starts[0])

    for event_position, start in enumerate(event_starts):
        end = (
            event_starts[event_position + 1]
            if event_position + 1 < len(event_starts)
            else video_end
        )
        if end <= start:
            continue
        kind, slot_index = event_by_start[start]
        boundaries = {start, end}
        for locked_start, locked_end in normalized_locked:
            if start < locked_start < end:
                boundaries.add(locked_start)
            if start < locked_end < end:
                boundaries.add(locked_end)
        ordered = sorted(boundaries)
        pieces: list[tuple[int, int, bool]] = []
        for piece_start, piece_end in zip(ordered, ordered[1:]):
            protected = kind == "locked" or any(
                locked_start < piece_end and locked_end > piece_start
                for locked_start, locked_end in normalized_locked
            )
            pieces.append((piece_start, piece_end, protected))

        if kind == "dub" and slot_index is not None:
            slot_output_starts[slot_index] = cursor
            fixed_duration = sum(
                piece_end - piece_start
                for piece_start, piece_end, protected in pieces
                if protected
            )
            flexible_duration = (end - start) - fixed_duration
            min_target = fixed_duration + flexible_duration / max_rate
            max_target = fixed_duration + flexible_duration * max_rate
            effective_gap = min(gap_ms, max(0, int(max_target) - 100))
            audio_duration = max(1, int(audio_durations_ms[slot_index]))
            available_audio = max(1.0, max_target - effective_gap)
            if audio_duration > available_audio:
                extra_tempo[slot_index] = audio_duration / available_audio
            effective_audio = audio_duration / extra_tempo[slot_index]
            target_duration = min(
                max(effective_audio + effective_gap, min_target), max_target
            )
            pts_factor = (
                (target_duration - fixed_duration) / flexible_duration
                if flexible_duration > 0
                else 1.0
            )
        else:
            pts_factor = 1.0

        for piece_start, piece_end, protected in pieces:
            factor = 1.0 if protected else pts_factor
            items.append(RatePlanItem(piece_start, piece_end, factor, 0))
            cursor += (piece_end - piece_start) * factor

    total_output_duration_ms = round(cursor)
    plan = RatePlan(items=items, total_output_duration_ms=total_output_duration_ms)

    placements: List[Tuple[int, int]] = []
    for index, (source_start, _source_end) in enumerate(normalized_slots):
        start = round(
            slot_output_starts.get(
                index,
                map_source_timestamp(plan, source_start, edge="start"),
            )
        )
        audio_eff = round(audio_durations_ms[index] / extra_tempo[index])
        placements.append((start, start + audio_eff))

    return plan, placements, extra_tempo


def map_source_timestamp(plan: RatePlan, timestamp_ms: int, *, edge: str = "start") -> int:
    """Map one source-video timestamp onto the output timeline."""
    timestamp = max(0, int(timestamp_ms))
    if not plan.items:
        return timestamp
    cursor = 0.0
    last_end = 0
    for item in plan.items:
        if timestamp < item.start_ms:
            return round(cursor + timestamp - last_end)
        if item.start_ms <= timestamp < item.end_ms:
            return round(cursor + (timestamp - item.start_ms) * item.pts_factor)
        item_end = cursor + (item.end_ms - item.start_ms) * item.pts_factor
        if timestamp == item.end_ms and edge == "end":
            return round(item_end)
        cursor = item_end + item.pad_after_ms
        last_end = item.end_ms
        if timestamp == item.end_ms:
            continue
    return round(cursor + max(0, timestamp - last_end))


def map_source_interval(
    plan: RatePlan, start_ms: int, end_ms: int
) -> Tuple[int, int]:
    """Map a source interval without absorbing padding at its right edge."""
    start = map_source_timestamp(plan, start_ms, edge="start")
    end = map_source_timestamp(plan, end_ms, edge="end")
    return start, max(start + 1, end)


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
