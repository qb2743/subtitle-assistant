"""Small, dependency-free FFmpeg video filter helpers.

The helpers in this module only construct filter expressions (or inspect
FFmpeg's ``showinfo`` output).  Keeping this logic separate from the dubbing
pipeline makes the optional visual effects easy to test and safe to skip when
FFmpeg/scene detection is unavailable.
"""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

_PTS_TIME_RE = re.compile(r"pts_time\s*:\s*(-?(?:\d+(?:\.\d*)?|\.\d+))")
_CANVAS_RE = re.compile(r"^(\d{2,5})x(\d{2,5})$")


def _normalise_canvas(canvas: str | Sequence[int] | None) -> tuple[int, int] | None:
    """Return a validated ``(width, height)`` pair, or ``None`` for off."""

    if canvas is None or canvas == "" or str(canvas).lower() in {"off", "none", "false"}:
        return None
    if isinstance(canvas, str):
        match = _CANVAS_RE.fullmatch(canvas.strip())
        if not match:
            raise ValueError("canvas must be 'off' or '<width>x<height>'")
        width, height = (int(match.group(1)), int(match.group(2)))
    else:
        if len(canvas) != 2:
            raise ValueError("canvas sequence must contain width and height")
        width, height = int(canvas[0]), int(canvas[1])
    if width <= 0 or height <= 0:
        raise ValueError("canvas dimensions must be positive")
    return width, height


def build_canvas_filter(canvas: str | Sequence[int] | None) -> str:
    """Build a scale-and-pad filter preserving the source aspect ratio.

    ``off``/``None`` returns an empty string.  The output has square pixels and
    a stable canvas size, which is important when subsequent filters are
    concatenated or subtitles are burned in.
    """

    size = _normalise_canvas(canvas)
    if size is None:
        return ""
    width, height = size
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )


def _normalise_scene_cuts(scene_cuts: Iterable[object] | None) -> list[float]:
    values = []
    for value in scene_cuts or ():
        # Accept callers that already represented scenes as ``(start, end)``
        # pairs or ``{"start": ..., "end": ...}`` records.
        if isinstance(value, dict):
            candidates = (value.get("start"), value.get("end"))
        elif isinstance(value, (tuple, list)):
            candidates = value
        else:
            candidates = (value,)
        for candidate in candidates:
            try:
                number = float(candidate)
            except (TypeError, ValueError):
                continue
            if number >= 0:
                values.append(number)
    return sorted(set(values))


def build_random_mirror_filter(
    scene_cuts: Iterable[object] | None,
    *,
    video_duration: float | None = None,
    min_shot: float = 0.0,
    seed: int | None = None,
) -> str:
    """Build a scene-aware, deterministic random mirror filter.

    Scene cuts are timestamps in seconds.  Each interval is randomly selected
    for mirroring; an interval is represented with ``gte(t,start)*lt(t,end)``.
    The final interval is open-ended.  A seed makes renders reproducible while
    still giving different scenes independent mirror decisions.
    """

    cuts = _normalise_scene_cuts(scene_cuts)
    if not cuts:
        # With no scene metadata, leave the video untouched.  This avoids a
        # surprising full-video flip when detection failed or was disabled.
        return ""
    try:
        duration = float(video_duration) if video_duration is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if duration > 0:
        cuts = [cut for cut in cuts if 0.05 < cut < duration - 0.05]
        try:
            minimum = max(0.0, float(min_shot))
        except (TypeError, ValueError):
            minimum = 0.0
        if minimum:
            kept: list[float] = []
            previous = 0.0
            for cut in cuts:
                if cut - previous >= minimum:
                    kept.append(cut)
                    previous = cut
            if kept and duration - kept[-1] < minimum:
                kept.pop()
            cuts = kept

    boundaries: list[float | None] = [0.0, *cuts]
    if duration > 0:
        boundaries.append(duration)
    else:
        boundaries.append(None)

    rng = random.Random(seed)
    # Keep mirrors scattered: 1-3 normal shots, then 1 mirrored shot and
    # occasionally 2. This avoids long accidental runs from independent coin
    # flips while retaining a different pattern for every render.
    states: list[bool] = []
    while len(states) < len(boundaries) - 1:
        states.extend([False] * rng.randint(1, 3))
        states.extend([True] * (2 if rng.random() < 0.25 else 1))
    states = states[: len(boundaries) - 1]
    if states and not any(states):
        states[-1] = True
    segments: list[tuple[float, float | None, bool]] = []
    for start, end, flipped in zip(boundaries, boundaries[1:], states):
        assert start is not None
        if segments and segments[-1][2] == flipped:
            segments[-1] = (segments[-1][0], end, flipped)
        else:
            segments.append((start, end, flipped))

    flipped_segments = [(start, end) for start, end, flipped in segments if flipped]
    if not flipped_segments:
        return ""
    if (
        duration > 0
        and len(flipped_segments) == 1
        and flipped_segments[0][0] == 0
        and flipped_segments[0][1] == duration
    ):
        return "hflip"
    # showinfo prints six decimals and can round a recurring frame timestamp
    # upward (for example 67.166666... -> 67.166667). Move detected boundaries
    # back one microsecond so the new scene's first frame cannot inherit the
    # previous scene's mirror state.
    enabled = []
    for start, end in flipped_segments:
        safe_start = max(0.0, start - 0.000001) if start else 0.0
        if end is None:
            enabled.append(f"gte(t,{safe_start:.6f})")
        else:
            safe_end = max(safe_start, end - 0.000001)
            enabled.append(
                f"gte(t,{safe_start:.6f})*lt(t,{safe_end:.6f})"
            )
    return "hflip=enable='" + "+".join(enabled) + "'"


def build_random_color_filter(*, seed: int | None = None) -> str:
    """Build a mild random ``eq`` color adjustment.

    Values intentionally stay within a conservative range so subtitles and
    skin tones remain usable.  The result is deterministic for a given seed.
    """

    rng = random.Random(seed)
    brightness = rng.uniform(-0.06, 0.06)
    contrast = rng.uniform(0.94, 1.08)
    saturation = rng.uniform(0.92, 1.12)
    return (
        "eq="
        f"brightness={brightness:.4f}:"
        f"contrast={contrast:.4f}:"
        f"saturation={saturation:.4f}"
    )


def detect_scene_cuts_ffmpeg(
    video_path: str | Path,
    *,
    threshold: float = 0.3,
    ffmpeg_bin: str = "ffmpeg",
    timeout: float | None = None,
) -> list[float]:
    """Detect scene boundaries using FFmpeg's ``select`` + ``showinfo``.

    FFmpeg writes ``showinfo`` records to stderr.  Missing files, an unavailable
    executable, or a non-zero FFmpeg exit return an empty list so optional
    mirror effects do not make an otherwise valid dubbing job fail.
    """

    if not 0 < float(threshold) <= 1:
        raise ValueError("threshold must be between 0 and 1")
    path = Path(video_path)
    if not path.is_file():
        return []
    vf = f"select='gt(scene,{float(threshold):g})',showinfo"
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(path),
        "-vf",
        vf,
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    timestamps = []
    for match in _PTS_TIME_RE.finditer(result.stderr or ""):
        value = float(match.group(1))
        if value >= 0:
            timestamps.append(value)
    # FFmpeg may report a timestamp more than once for unusual inputs.
    return sorted(set(timestamps))


def build_video_filter_chain(
    *,
    canvas: str | Sequence[int] | None = None,
    scene_cuts: Iterable[object] | None = None,
    video_duration: float | None = None,
    random_mirror: bool = False,
    random_color: bool = False,
    seed: int | None = None,
) -> str:
    """Combine enabled visual effects into one FFmpeg ``-vf`` expression."""

    filters: list[str] = []
    canvas_filter = build_canvas_filter(canvas)
    if canvas_filter:
        filters.append(canvas_filter)
    if random_mirror:
        mirror_filter = build_random_mirror_filter(
            scene_cuts,
            video_duration=video_duration,
            seed=seed,
        )
        if mirror_filter:
            filters.append(mirror_filter)
    if random_color:
        filters.append(build_random_color_filter(seed=seed))
    return ",".join(filters)


def apply_video_filter(
    input_path: str | Path,
    output_path: str | Path,
    filter_chain: str,
    *,
    ffmpeg_bin: str = "ffmpeg",
    video_codec: str = "libx264",
    preset: str = "medium",
    crf: int = 23,
) -> None:
    """Render ``filter_chain`` while copying the source audio streams.

    This is intentionally a small primitive for the pipeline's optional
    post-processing stage.  An empty chain is treated as a no-op copy and
    does not invoke FFmpeg.
    """

    source = Path(input_path)
    destination = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not filter_chain:
        if source.resolve() != destination.resolve():
            destination.write_bytes(source.read_bytes())
        return
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-vf",
        filter_chain,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        video_codec,
        "-preset",
        preset,
        "-crf",
        str(int(crf)),
        "-c:a",
        "copy",
        str(destination),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"FFmpeg unavailable: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:]
        raise RuntimeError("FFmpeg video filter failed" + (f": {detail[0]}" if detail else ""))
    if not destination.is_file():
        raise RuntimeError("FFmpeg completed without creating the output video")


__all__ = [
    "build_canvas_filter",
    "build_random_mirror_filter",
    "build_random_color_filter",
    "build_video_filter_chain",
    "apply_video_filter",
    "detect_scene_cuts_ffmpeg",
]
