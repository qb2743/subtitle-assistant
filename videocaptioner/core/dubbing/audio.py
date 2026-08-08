"""Audio helpers for dubbing timeline assembly."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from .video_rate import RatePlan, map_source_interval

# On Windows, suppress "Application Error" crash dialogs for ffmpeg/ffprobe
_SUBPROCESS_KWARGS: dict = {}
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0003)
    _SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW

# Configure ffmpeg/ffprobe paths for pydub
for _attr, _name in (("converter", "ffmpeg"), ("ffprobe", "ffprobe")):
    _path = shutil.which(_name)
    if _path:
        setattr(AudioSegment, _attr, _path)


def get_audio_duration_ms(path: str) -> int:
    audio = AudioSegment.from_file(path)
    return len(audio)


def trim_trailing_silence(
    input_path: str,
    output_path: str,
    *,
    min_silence_len: int = 100,
    silence_thresh: int = -45,
) -> str:
    """Remove only synthetic silence at the end of a TTS clip."""
    audio = AudioSegment.from_file(input_path)
    nonsilent = detect_nonsilent(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        seek_step=10,
    )
    if not nonsilent or len(audio) - nonsilent[-1][1] <= 30:
        return input_path
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    audio[: nonsilent[-1][1]].export(output_path, format="wav")
    return output_path


def create_silence_file(output_path: str, duration_ms: int) -> str:
    """Write a silent wav of ``duration_ms`` and return its path.

    Used by the fixed inter-line pause mode to insert pauses between
    dubbed subtitle lines.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    silence = AudioSegment.silent(duration=max(0, duration_ms), frame_rate=48000)
    silence.export(output_path, format="wav")
    return output_path


def change_tempo(input_path: str, output_path: str, factor: float) -> None:
    """Change audio tempo without changing pitch using ffmpeg atempo."""
    factor = max(0.5, min(100.0, factor))
    filters = _atempo_filters(factor)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        input_path,
        "-filter:a",
        ",".join(filters),
        output_path,
    ]
    subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)


def create_timeline_audio(
    segments: list[tuple[str, int]],
    output_path: str,
    duration_ms: int,
    volume: float = 1.0,
) -> None:
    """Place segment audio files on a silent timeline."""
    timeline = AudioSegment.silent(
        duration=max(duration_ms, 1), frame_rate=48000
    ).set_channels(2)
    gain_db = _linear_to_db(volume)
    for audio_path, start_ms in segments:
        clip = AudioSegment.from_file(audio_path)
        if volume != 1.0:
            clip += gain_db
        timeline = timeline.overlay(clip, position=max(0, start_ms))
    suffix = Path(output_path).suffix.lower().lstrip(".") or "wav"
    fmt = "mp3" if suffix == "mp3" else "wav"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    timeline.export(output_path, format=fmt)


def overlay_source_audio_intervals(
    source_path: str,
    output_path: str,
    intervals: list[tuple[int, int]],
    rate_plan: RatePlan | None = None,
    blocking_intervals: list[tuple[int, int]] | None = None,
) -> None:
    """Overlay protected source audio, including gaps before narration resumes."""
    bridge_gaps = blocking_intervals is not None
    blockers: list[tuple[int, int]] = []
    for raw_start, raw_end in blocking_intervals or []:
        start, end = max(0, int(raw_start)), max(0, int(raw_end))
        if end > start:
            blockers.append((start, end))
    blockers.sort()

    merged: list[tuple[int, int]] = []
    for raw_start, raw_end in sorted(intervals):
        start, end = max(0, int(raw_start)), max(0, int(raw_end))
        if end <= start:
            continue
        if merged:
            previous_end = merged[-1][1]
            gap_has_blocker = any(
                block_start < start and block_end > previous_end
                for block_start, block_end in blockers
            )
            if start <= previous_end or (bridge_gaps and not gap_has_blocker):
                merged[-1] = (merged[-1][0], max(previous_end, end))
                continue
        merged.append((start, end))
    if not merged:
        return

    source = AudioSegment.from_file(source_path)
    output = AudioSegment.from_file(output_path)
    for start, end in merged:
        if bridge_gaps:
            next_block_start = next(
                (
                    block_start
                    for block_start, block_end in blockers
                    if block_end > end
                ),
                len(source),
            )
            end = min(len(source), max(end, next_block_start))
        clip = source[start:end]
        if not clip:
            continue
        target_start = (
            map_source_interval(rate_plan, start, end)[0]
            if rate_plan is not None
            else start
        )
        required_duration = target_start + len(clip)
        if required_duration > len(output):
            output += AudioSegment.silent(
                duration=required_duration - len(output),
                frame_rate=output.frame_rate,
            )
        output = output.overlay(clip, position=target_start)

    suffix = Path(output_path).suffix.lower().lstrip(".")
    output.export(output_path, format="mp3" if suffix == "mp3" else "wav")


def mux_dubbed_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    *,
    mix_original_audio: bool = False,
    original_audio_volume: float = 0.25,
    dubbed_audio_volume: float = 1.0,
) -> None:
    """Replace or mix a video's audio track with dubbed audio."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if mix_original_audio and _video_has_audio(video_path):
        filter_complex = (
            f"[0:a]volume={original_audio_volume}[a0];"
            f"[1:a]volume={dubbed_audio_volume}[a1];"
            "[a0][a1]amix=inputs=2:duration=longest:"
            "dropout_transition=0:normalize=0[a]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-strict",
            "-2",
            "-movflags",
            "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-strict",
            "-2",
            "-movflags",
            "+faststart",
            output_path,
        ]
    subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)


def _atempo_filters(factor: float) -> list[str]:
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return filters


def _linear_to_db(volume: float) -> float:
    if volume <= 0:
        return -120.0
    import math

    return 20 * math.log10(volume)


def _video_has_audio(video_path: str) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "json",
        video_path,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, **_SUBPROCESS_KWARGS)
    data = json.loads(result.stdout or "{}")
    return bool(data.get("streams"))
