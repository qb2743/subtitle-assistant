"""Pure timeline helpers for the dubbing pipeline.

These functions compute the adjusted placement of each dubbed segment on the
output timeline when ``subtitle_gap_ms`` is enabled. Keeping them pure (no
I/O, no ffmpeg) makes them trivially unit-testable.
"""

from pathlib import Path
from typing import List, Tuple


def compute_timeline_placements(
    start_times_ms: List[int],
    audio_durations_ms: List[int],
    gap_ms: int,
) -> List[Tuple[int, int]]:
    """Compute the adjusted (start_ms, end_ms) placement for each segment.

    When ``gap_ms`` is positive, each segment is pushed right so that no two
    dubbed lines overlap and every line is followed by a ``gap_ms`` of silence:

        start_i = max(original_start_i, prev_end + gap)
        end_i   = start_i + audio_duration_i

    where ``prev_end`` is the previous segment's placement end. With
    ``gap_ms <= 0`` the original timeline is kept unchanged (each segment is
    placed at its own original start).

    Args:
        start_times_ms: original subtitle start time of each segment (ms).
        audio_durations_ms: fitted audio duration of each segment (ms).
        gap_ms: silence inserted after each segment (ms); 0 disables shifting.

    Returns:
        A list of (start_ms, end_ms) pairs, one per segment.
    """
    pairs = list(zip(start_times_ms, audio_durations_ms))
    if gap_ms <= 0:
        return [(start, start + dur) for start, dur in pairs]
    placements: List[Tuple[int, int]] = []
    cursor = 0
    for start, dur in pairs:
        place_start = max(start, cursor)
        placements.append((place_start, place_start + dur))
        cursor = place_start + dur + gap_ms
    return placements


def _ms_to_srt_ts(ms: int) -> str:
    """Convert milliseconds to an SRT timestamp (HH:MM:SS,mmm)."""
    total_seconds, milliseconds = divmod(max(0, ms), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{int(milliseconds):03}"


def write_adjusted_subtitle(
    segments: list,
    placements: List[Tuple[int, int]],
    output_path: str,
) -> str:
    """Write an SRT with the adjusted timing and return the output path.

    ``segments`` must expose ``index`` and ``text`` (e.g. ``DubbingSegment``).
    Each subtitle line is shown from its placement start to its placement end
    (start + audio duration), so display matches what is actually dubbed.

    Args:
        segments: dubbing segments, in timeline order.
        placements: (start_ms, end_ms) per segment, from
            :func:`compute_timeline_placements`.
        output_path: destination SRT path.

    Returns:
        ``output_path``.
    """
    lines: List[str] = []
    for seg, (start, end) in zip(segments, placements):
        lines.append(f"{seg.index}")
        lines.append(f"{_ms_to_srt_ts(start)} --> {_ms_to_srt_ts(end)}")
        lines.append(seg.text)
        lines.append("")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return output_path
