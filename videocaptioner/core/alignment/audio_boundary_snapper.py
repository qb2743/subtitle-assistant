"""Snap aligned subtitle boundaries to nearby audio energy edges."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("alignment.audio_boundary")


@dataclass(frozen=True)
class _SpeechInterval:
    start_ms: int
    end_ms: int


def snap_subtitles_to_audio_boundaries(
    asr_data: ASRData,
    audio_path: str,
    window_ms: int = 350,
    padding_ms: int = 40,
) -> ASRData:
    """Move subtitle starts/ends to nearby speech-energy boundaries.

    This is deliberately conservative: only WAV input is inspected, and each
    edge moves at most ``window_ms``. Non-WAV/unsupported audio returns unchanged.
    """
    samples, sample_rate, frame_ms = _read_samples(audio_path)
    if not samples:
        return asr_data

    rms_values = _rms_frames_from_samples(samples, sample_rate, frame_ms)
    intervals = _detect_speech_intervals(rms_values, frame_ms=frame_ms)
    if not intervals:
        return asr_data

    flatness_values = _spectral_flatness_frames(samples, sample_rate, frame_ms)

    snapped: list[ASRDataSeg] = []
    total_ms = len(rms_values) * frame_ms
    for seg in asr_data.segments:
        start = _snap_start(seg.start_time, intervals, window_ms, padding_ms, flatness_values, frame_ms)
        end = _snap_end(seg.end_time, intervals, window_ms, padding_ms, total_ms)
        if end <= start:
            start, end = seg.start_time, seg.end_time
        snapped.append(ASRDataSeg(seg.text, start, end, seg.translated_text))

    _snap_shared_boundaries_to_silence_valleys(
        snapped, list(asr_data.segments), rms_values, intervals, frame_ms, window_ms, padding_ms
    )
    return ASRData(snapped)


def _snap_shared_boundaries_to_silence_valleys(
    segments: list[ASRDataSeg],
    original_segments: list[ASRDataSeg],
    rms_values: list[float],
    intervals: list[_SpeechInterval],
    frame_ms: int,
    window_ms: int,
    padding_ms: int,
) -> None:
    for i in range(len(segments) - 1):
        left = segments[i]
        right = segments[i + 1]
        original_gap = original_segments[i + 1].start_time - original_segments[i].end_time
        if original_gap >= 80:
            continue
        valley = _find_silence_valley(rms_values, frame_ms, left.end_time, right.start_time, window_ms)
        if valley is None:
            continue
        left.end_time = max(left.start_time + 200, valley - padding_ms)
        next_onset = _first_speech_onset_after(intervals, valley, right.end_time, window_ms)
        if next_onset is not None:
            right.start_time = max(right.start_time, min(right.end_time - 200, next_onset - min(padding_ms, 20)))
        if left.end_time > right.start_time:
            mid = (left.end_time + right.start_time) // 2
            left.end_time = mid
            right.start_time = mid


def _first_speech_onset_after(
    intervals: list[_SpeechInterval], valley_ms: int, right_end_ms: int, window_ms: int
) -> int | None:
    limit = min(right_end_ms, valley_ms + window_ms)
    for interval in intervals:
        if valley_ms <= interval.start_ms <= limit:
            return interval.start_ms
    return None


def _find_silence_valley(
    rms_values: list[float],
    frame_ms: int,
    left_ms: int,
    right_ms: int,
    window_ms: int,
) -> int | None:
    center = (left_ms + right_ms) // 2
    lo_ms = max(0, min(left_ms, right_ms) - window_ms // 2)
    hi_ms = min(len(rms_values) * frame_ms, max(left_ms, right_ms) + window_ms // 2)
    lo = max(0, lo_ms // frame_ms)
    hi = min(len(rms_values), max(lo + 1, hi_ms // frame_ms))
    if hi <= lo:
        return None

    sorted_rms = sorted(rms_values)
    noise = sorted_rms[max(0, int(len(sorted_rms) * 0.2) - 1)]
    peak = max(rms_values)
    quiet_threshold = max(noise * 2.0, peak * 0.04)

    best_start = best_len = 0
    run_start: int | None = None
    for idx in range(lo, hi):
        if rms_values[idx] <= quiet_threshold:
            if run_start is None:
                run_start = idx
        elif run_start is not None:
            run_len = idx - run_start
            if run_len > best_len:
                best_start, best_len = run_start, run_len
            run_start = None
    if run_start is not None and hi - run_start > best_len:
        best_start, best_len = run_start, hi - run_start

    if best_len * frame_ms >= 60:
        return (best_start + best_len // 2) * frame_ms

    # No real quiet run: use the lowest-energy frame, but only if it is close to
    # the current boundary estimate so a random breath doesn't steal the split.
    valley_idx = min(range(lo, hi), key=lambda idx: rms_values[idx])
    valley_ms = valley_idx * frame_ms
    if abs(valley_ms - center) > window_ms:
        return None
    return valley_ms


def _snap_start(
    ms: int,
    intervals: list[_SpeechInterval],
    window_ms: int,
    padding_ms: int,
    flatness_values: list[float],
    frame_ms: int,
    max_shift: int = 300,
    min_run: int = 100,
    min_gap: int = 40,
) -> int:
    # Land starts on stable speech (>= min_run ms of continuous energy) rather
    # than short noise/breath/plosive islands. Push the start FORWARD only --
    # never show the subtitle early. A start already inside speech is untouched.
    stable = [iv for iv in intervals if iv.end_ms - iv.start_ms >= min_run]
    for iv in stable:
        if iv.start_ms <= ms <= iv.end_ms:
            return ms
    onset = _find_stable_speech_onset_after(stable, ms, min(max_shift, window_ms))
    if onset is not None and onset - ms >= min_gap:
        iv = next((i for i in stable if i.start_ms == onset), None)
        # Borderline-length islands (just over min_run) might still be a breath
        # or plosive burst. Confirm with spectral flatness: real speech has
        # formant structure (low flatness), noise bursts are flat (high).
        if iv is not None and iv.end_ms - iv.start_ms < min_run * 2 and not _flatness_confirms_speech(flatness_values, frame_ms, onset):
            return ms  # don't shift onto a noise-like island
        return onset + padding_ms
    return ms


def _flatness_confirms_speech(flatness_values: list[float], frame_ms: int, onset_ms: int) -> bool:
    if not flatness_values:
        return True  # no STFT signal → trust the RMS decision
    idx = min(len(flatness_values) - 1, max(0, onset_ms // frame_ms))
    # ponytail: 0.5 separates tonal speech (formants, ~0.1-0.3) from noise bursts (~0.5-0.9)
    return flatness_values[idx] < 0.5


def _find_stable_speech_onset_after(
    intervals: list[_SpeechInterval], ms: int, max_shift: int
) -> int | None:
    # intervals is sorted by start_ms; first match is the nearest onset after ms.
    for iv in intervals:
        if iv.start_ms >= ms and iv.start_ms - ms <= max_shift:
            return iv.start_ms
    return None


def _snap_end(ms: int, intervals: list[_SpeechInterval], window_ms: int, padding_ms: int, total_ms: int) -> int:
    # Same idea for ends: don't let the next word's onset pull the previous
    # subtitle far forward; only allow a small forward snap.
    forward_ms = min(120, window_ms)
    candidates = [iv for iv in intervals if ms - window_ms <= iv.end_ms <= ms + forward_ms]
    if not candidates:
        return ms
    target = min(candidates, key=lambda iv: abs(iv.end_ms - ms)).end_ms
    return min(total_ms, target + padding_ms)


def _read_samples(audio_path: str, frame_ms: int = 20) -> tuple[list[float], int, int]:
    path = Path(audio_path)
    if path.suffix.lower() != ".wav":
        logger.debug("Boundary snapping skipped for non-WAV audio: %s", path)
        return [], 0, frame_ms

    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            raw = wav.readframes(wav.getnframes())
        return _decode_pcm(raw, sample_width, channels), sample_rate, frame_ms
    except (wave.Error, OSError, EOFError) as exc:
        logger.debug("Boundary snapping skipped; cannot read WAV %s: %s", path, exc)
        return [], 0, frame_ms


def _decode_pcm(raw: bytes, sample_width: int, channels: int) -> list[float]:
    if sample_width == 1:
        samples = [b - 128 for b in raw]
    elif sample_width == 2:
        import struct

        samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    elif sample_width == 4:
        import struct

        samples = list(struct.unpack(f"<{len(raw) // 4}i", raw))
    else:
        return []

    if channels > 1:
        samples = samples[::channels]
    return [float(s) for s in samples]


def _rms_frames_from_samples(samples: list[float], sample_rate: int, frame_ms: int) -> list[float]:
    frame_count = max(1, int(sample_rate * frame_ms / 1000))
    out: list[float] = []
    for i in range(0, len(samples), frame_count):
        chunk = samples[i:i + frame_count]
        if not chunk:
            break
        out.append((sum(float(s) * float(s) for s in chunk) / len(chunk)) ** 0.5)
    return out


def _spectral_flatness_frames(samples: list[float], sample_rate: int, frame_ms: int) -> list[float]:
    # Per-frame spectral flatness via STFT. High flatness (->1) = noise-like
    # (breath/plosive); low (->0) = tonal/structured (vowels, formants).
    import numpy as np
    from scipy.signal import stft

    arr = np.asarray(samples, dtype=np.float32)
    nperseg = max(256, int(sample_rate * 0.025))
    if len(arr) < nperseg:
        return []
    hop = max(1, int(sample_rate * frame_ms / 1000))
    noverlap = max(0, nperseg - hop)
    _, _, Z = stft(arr, fs=sample_rate, nperseg=nperseg, noverlap=noverlap, boundary=None, padded=False)
    mag = np.maximum(np.abs(Z), 1e-10)
    flatness = np.exp(np.log(mag).mean(axis=0)) / mag.mean(axis=0)
    return flatness.astype(np.float32).tolist()


def _detect_speech_intervals(
    rms_values: list[float], frame_ms: int = 20, min_speech_ms: int = 80
) -> list[_SpeechInterval]:
    if not rms_values:
        return []

    sorted_rms = sorted(rms_values)
    noise = sorted_rms[max(0, int(len(sorted_rms) * 0.2) - 1)]
    peak = max(rms_values)
    threshold = max(noise * 3.0, peak * 0.08)
    if threshold <= 0:
        return []

    intervals: list[_SpeechInterval] = []
    start: int | None = None
    for idx, value in enumerate(rms_values):
        if value >= threshold and start is None:
            start = idx * frame_ms
        elif value < threshold and start is not None:
            end = idx * frame_ms
            if end - start >= min_speech_ms:
                intervals.append(_SpeechInterval(start, end))
            start = None
    if start is not None:
        end = len(rms_values) * frame_ms
        if end - start >= min_speech_ms:
            intervals.append(_SpeechInterval(start, end))
    return intervals
