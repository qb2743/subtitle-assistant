"""Snap aligned subtitle boundaries to nearby audio energy edges."""

from __future__ import annotations

import os
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
    debug_log: list | None = None,
) -> ASRData:
    """Move subtitle starts/ends to nearby speech-energy boundaries.

    Starts are landed on the vowel onset (via spectral-flatness refinement of
    the RMS energy onset), so they sit on real speech rather than a plosive
    release burst or a fixed padding guess. Ends snap to speech tails. Adjacent
    subtitles abut (prev.end → next.start) so there is no gap and no covering
    of the next sentence's speech. Non-decodable audio returns unchanged.

    If ``debug_log`` is passed, each processed segment appends a dict with the
    in/out start and end and the RMS interval it snapped toward, so a caller can
    dump the full snap chain to diagnose which stage mis-timed a subtitle.
    """
    samples, sample_rate, frame_ms = _read_samples(audio_path)
    if not samples:
        return asr_data

    rms_values = _rms_frames_from_samples(samples, sample_rate, frame_ms)
    intervals = _detect_speech_intervals(rms_values, frame_ms=frame_ms)
    if not intervals:
        return asr_data

    flatness_values = _spectral_flatness_frames(samples, sample_rate, frame_ms)
    flux_values, hfc_values = _onset_strength_frames(samples, sample_rate, frame_ms)

    snapped: list[ASRDataSeg] = []
    total_ms = len(rms_values) * frame_ms
    for seg in asr_data.segments:
        start = _snap_start(
            seg.start_time, intervals, window_ms, padding_ms,
            flatness_values, flux_values, hfc_values, frame_ms,
        )
        end = _snap_end(seg.end_time, intervals, window_ms, padding_ms, total_ms)
        if end <= start:
            start, end = seg.start_time, seg.end_time
        snapped.append(ASRDataSeg(seg.text, start, end, seg.translated_text))
        if debug_log is not None:
            debug_log.append({
                "text": seg.text,
                "in_start_ms": seg.start_time,
                "in_end_ms": seg.end_time,
                "out_start_ms": start,
                "out_end_ms": end,
                "start_shift_ms": start - seg.start_time,
                "end_shift_ms": end - seg.end_time,
                "nearby_interval": _nearest_interval(seg.start_time, intervals),
            })

    _snap_shared_boundaries_to_silence_valleys(
        snapped, list(asr_data.segments), rms_values, intervals, frame_ms, window_ms, padding_ms
    )
    _fill_gaps_to_next_start(snapped)
    return ASRData(snapped)


def _nearest_interval(ms: int, intervals: list[_SpeechInterval]) -> dict | None:
    if not intervals:
        return None
    iv = min(intervals, key=lambda iv: abs(((iv.start_ms + iv.end_ms) // 2) - ms))
    return {"start_ms": iv.start_ms, "end_ms": iv.end_ms}


def _fill_gaps_to_next_start(segments: list[ASRDataSeg]) -> None:
    # Abut adjacent subtitles: extend each end to the next start so "上一句结束
    # 马上显示下一句". Accurate vowel-onset starts make this safe — next.start
    # lands on the next vowel, so prev.end reaching it never covers next speech.
    # The per-text max duration caps how far a short line can span, so long
    # silences (several seconds) naturally keep a gap instead of dragging.
    for i in range(len(segments) - 1):
        cur = segments[i]
        nxt_start = segments[i + 1].start_time
        if nxt_start <= cur.end_time:
            continue
        chars = max(1, len(cur.text.strip()))
        max_dur_ms = max(3000, int(1000 + chars * 250))
        desired = min(cur.start_time + max_dur_ms, nxt_start)
        cur.end_time = max(cur.end_time, desired)


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
    flux_values: list[float],
    hfc_values: list[float],
    frame_ms: int,
    max_shift: int = 300,
    min_run: int = 100,
    min_gap: int = 40,
) -> int:
    # Land starts on stable speech (>= min_run ms of continuous energy) rather
    # than short noise/breath/plosive islands. Push the start FORWARD only --
    # never show the subtitle early. A start already inside speech is refined to
    # the true syllable onset inside the interval.
    stable = [iv for iv in intervals if iv.end_ms - iv.start_ms >= min_run]
    for iv in stable:
        if iv.start_ms <= ms <= iv.end_ms:
            # Already inside speech: refine to the syllable onset nearest ms,
            # so the subtitle starts at the actual articulation, not wherever
            # the ASR/DTW estimate landed (often mid-consonant or mid-vowel).
            return _refine_to_nearest_onset(flux_values, hfc_values, frame_ms, ms, iv)
    onset = _find_stable_speech_onset_after(stable, ms, min(max_shift, window_ms))
    if onset is not None and onset - ms >= min_gap:
        iv = next((i for i in stable if i.start_ms == onset), None)
        # Borderline-length islands (just over min_run) might still be a breath
        # or plosive burst. Confirm with spectral flatness: real speech has
        # formant structure (low flatness), noise bursts are flat (high).
        if iv is not None and iv.end_ms - iv.start_ms < min_run * 2 and not _flatness_confirms_speech(flatness_values, frame_ms, onset):
            return ms  # don't shift onto a noise-like island
        # The RMS onset is the energy-threshold crossing, which lags the true
        # articulation (consonant release) by tens of ms. Backtrack up to 200ms
        # before it to the first flux/HFC onset — the real start — but never
        # earlier than the ASR estimate ``ms`` so the subtitle is never early.
        return _refine_onset_to_vowel(
            flatness_values, flux_values, hfc_values, frame_ms, onset, iv, padding_ms,
            min_start_ms=ms,
        )
    return ms


def _refine_to_nearest_onset(
    flux_values: list[float], hfc_values: list[float], frame_ms: int, ms: int, iv: _SpeechInterval
) -> int:
    # When the estimate is already inside a speech interval, snap to the nearest
    # flux/HFC onset within the interval — the actual syllable boundary — rather
    # than sitting mid-phone. Prefer the onset at or just before ms (the listener
    # already hears the syllable), falling back to ms if none found nearby.
    if not flux_values and not hfc_values:
        return ms
    lo = max(0, iv.start_ms // frame_ms)
    hi = min(len(flux_values) - 1, (iv.end_ms // frame_ms) - 1)
    if hi <= lo:
        return ms
    cur = ms // frame_ms
    # Adaptive threshold: median of the fused onset strength in the interval.
    strengths = [max(flux_values[i], hfc_values[i]) for i in range(lo, hi + 1)]
    strengths.sort()
    threshold = strengths[len(strengths) // 2] * 1.5 if strengths else 0
    if threshold <= 0:
        return ms
    # Search outward from cur for the nearest onset frame.
    for delta in range(0, max(cur - lo, hi - cur) + 1):
        for idx in (cur - delta, cur + delta):
            if lo <= idx <= hi and idx < len(flux_values) and max(flux_values[idx], hfc_values[idx]) >= threshold:
                return idx * frame_ms
    return ms


def _refine_onset_to_vowel(
    flatness_values: list[float], flux_values: list[float], hfc_values: list[float],
    frame_ms: int, onset_ms: int, iv: _SpeechInterval | None, fallback_padding_ms: int,
    min_start_ms: int = 0, lookback_ms: int = 200,
) -> int:
    # The RMS energy onset lags the true articulation: it crosses the threshold
    # only after the consonant release/plosive has already begun. The real start
    # is the first significant flux/HFC onset in the ~200ms BEFORE the RMS
    # crossing — HFC catches the high-frequency consonant release earliest. Never
    # backtrack past ``min_start_ms`` (the ASR estimate, so we never show early).
    if not flux_values and not hfc_values:
        return onset_ms
    hi = onset_ms // frame_ms
    lo = max(min_start_ms // frame_ms, (onset_ms - lookback_ms) // frame_ms)
    if hi <= lo or hi >= len(flux_values):
        return onset_ms
    # Threshold from the pre-window (mostly silence/noise) so a real onset stands
    # out: a consonant release is several× the silence baseline.
    pre = [max(flux_values[i], hfc_values[i]) for i in range(lo, hi) if 0 <= i < len(flux_values)]
    if not pre:
        return onset_ms
    pre.sort()
    baseline = pre[len(pre) // 2]
    peak = max(pre[-1], max(flux_values[hi], hfc_values[hi]) if hi < len(flux_values) else 0)
    threshold = max(baseline * 3, peak * 0.4)
    if threshold <= 0:
        return onset_ms
    # Scan backward from just before the RMS onset (the RMS frame itself is a peak
    # by construction; the real articulation is the EARLIEST peak before it).
    # Require each candidate to be tonal (low flatness) so a preceding noise/breath
    # island — which also produces a flux spike — is rejected as a false onset.
    for idx in range(hi - 1, lo - 1, -1):
        if 0 <= idx < len(flux_values) and max(flux_values[idx], hfc_values[idx]) >= threshold:
            if _flatness_confirms_speech(flatness_values, frame_ms, idx * frame_ms):
                return idx * frame_ms
    # No earlier onset found: keep the RMS onset itself (don't add padding — that
    # would push the start later than the energy crossing, making it late).
    return onset_ms


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
    if path.suffix.lower() == ".wav":
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

    # Non-WAV (mp3/m4a/etc.): decode to 16-bit mono PCM via ffmpeg, which is
    # already a project dependency. Without this, the snapper silently bails
    # on mp3 input and ASR timestamps go uncorrected.
    try:
        import subprocess

        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
             "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        return _decode_pcm(proc.stdout, 2, 1), 16000, frame_ms
    except Exception as exc:
        logger.debug("Boundary snapping skipped; cannot decode %s via ffmpeg: %s", path, exc)
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
    mag = _stft_magnitude(samples, sample_rate, frame_ms)
    if mag is None:
        return []
    return _flatness_from_magnitude(mag)


def _stft_magnitude(samples: list[float], sample_rate: int, frame_ms: int):
    """Shared STFT magnitude spectrum, one column per frame_ms hop.

    Returns ``np.ndarray`` of shape ``(n_freq, n_frames)`` or ``None`` if too
    short. Reused by flatness, spectral flux, and HFC so the FFT cost is paid
    once.
    """
    import numpy as np
    from scipy.signal import stft

    arr = np.asarray(samples, dtype=np.float32)
    nperseg = max(256, int(sample_rate * 0.025))
    if len(arr) < nperseg:
        return None
    hop = max(1, int(sample_rate * frame_ms / 1000))
    noverlap = max(0, nperseg - hop)
    _, _, Z = stft(arr, fs=sample_rate, nperseg=nperseg, noverlap=noverlap, boundary=None, padded=False)
    return np.maximum(np.abs(Z), 1e-10)


def _flatness_from_magnitude(mag) -> list[float]:
    import numpy as np
    flatness = np.exp(np.log(mag).mean(axis=0)) / mag.mean(axis=0)
    return flatness.astype(np.float32).tolist()


def _onset_strength_frames(samples: list[float], sample_rate: int, frame_ms: int) -> tuple[list[float], list[float]]:
    """Per-frame onset detection: (spectral_flux, hfc).

    - Spectral flux: sum of positive magnitude increases frame-to-frame. Catches
      the spectral change at any speech onset, including vowels.
    - HFC (high-frequency content): sum(magnitude * bin_index). Consonants and
      plosives concentrate energy at high frequencies and at the very first
      instant of articulation, so HFC peaks EARLIER than RMS energy crosses its
      threshold — this is what fixes starts that show up late.

    Both share one STFT. Returned per frame (frame_ms hop).
    """
    import numpy as np

    mag = _stft_magnitude(samples, sample_rate, frame_ms)
    if mag is None or mag.shape[1] < 2:
        return [], []
    n_freq, n_frames = mag.shape
    freqs = np.arange(n_freq)  # bin index ∝ frequency, used as HFC weight
    # Rectified spectral flux: positive part of frame-to-frame magnitude diff.
    flux = np.maximum(mag[:, 1:] - mag[:, :-1], 0).sum(axis=0)
    flux = np.pad(flux, (1, 0), mode="constant")  # align frame 0 (no prior → 0)
    # HFC per frame; emphasize the rise by taking flux-weighted high-freq content.
    hfc = (mag * freqs[:, None]).sum(axis=0)
    hfc_flux = np.maximum(hfc[1:] - hfc[:-1], 0)
    hfc_flux = np.pad(hfc_flux, (1, 0), mode="constant")
    return flux.astype(np.float32).tolist(), hfc_flux.astype(np.float32).tolist()


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


def _diagnose_onsets(audio_path: str) -> None:
    """Probe: print how far the flux/HFC backtrack pulls starts earlier than the
    RMS energy onset, across every speech interval. Run with::

        python -m videocaptioner.core.alignment.audio_boundary_snapper AUDIO

    A row "RMS=5400 refined=5340 earlier by 60ms" means the backtrack found a
    real consonant release 60ms before the energy crossed its threshold. The
    summary prints how many starts moved earlier / stayed / moved later —
    "moved later" should always be 0 (backtrack never adds delay).
    """
    import statistics

    samples, sample_rate, frame_ms = _read_samples(audio_path)
    if not samples:
        print(f"cannot decode {audio_path}")
        return
    rms = _rms_frames_from_samples(samples, sample_rate, frame_ms)
    intervals = _detect_speech_intervals(rms, frame_ms)
    if not intervals:
        print("no speech intervals")
        return
    flat = _spectral_flatness_frames(samples, sample_rate, frame_ms)
    flux, hfc = _onset_strength_frames(samples, sample_rate, frame_ms)

    earlier: list[int] = []
    same = 0
    later = 0
    shown = 0
    for iv in intervals:
        rms_onset = iv.start_ms
        ms = max(0, rms_onset - 100)  # simulate ASR estimate 100ms before onset
        refined = _refine_onset_to_vowel(flat, flux, hfc, frame_ms, rms_onset, iv, 40, min_start_ms=ms)
        shift = rms_onset - refined
        if shift > 0:
            earlier.append(shift)
        elif shift == 0:
            same += 1
        else:
            later += 1
        if shown < 25:
            print(f"  RMS={rms_onset:7d}ms refined={refined:7d}ms  {'earlier by '+str(shift)+'ms' if shift>0 else ('same' if shift==0 else 'LATER by '+str(-shift)+'ms')}")
            shown += 1
    print(f"\n{len(intervals)} intervals:")
    print(f"  refined earlier: {len(earlier)}  (median {int(statistics.median(earlier)) if earlier else 0}ms, max {max(earlier) if earlier else 0}ms)")
    print(f"  kept at RMS onset: {same}")
    print(f"  refined later (regression!): {later}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m videocaptioner.core.alignment.audio_boundary_snapper AUDIO_FILE")
        sys.exit(2)
    _diagnose_onsets(sys.argv[1])
