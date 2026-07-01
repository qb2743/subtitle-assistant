import struct
import wave

from videocaptioner.core.alignment.audio_boundary_snapper import snap_subtitles_to_audio_boundaries
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg


def _write_wav(path, regions, total_ms=1600):
    sample_rate = 1000
    samples = []
    for start, end in regions:
        while len(samples) < start:
            samples.append(0)
        while len(samples) < end:
            samples.append(12000)
    while len(samples) < total_ms:
        samples.append(0)

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _write_test_wav(path):
    _write_wav(path, [(200, 700), (1000, 1400)])


def test_snap_subtitles_to_nearby_audio_edges(tmp_path):
    wav = tmp_path / "speech.wav"
    _write_test_wav(wav)
    asr = ASRData(
        [
            ASRDataSeg("first", 120, 780),
            ASRDataSeg("second", 930, 1480),
        ]
    )

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=200, padding_ms=0)

    assert snapped.segments[0].start_time == 200
    assert snapped.segments[0].end_time == 700
    assert snapped.segments[1].start_time == 1000
    assert snapped.segments[1].end_time == 1400


def test_snap_start_ignores_short_trailing_consonant_before_boundary(tmp_path):
    wav = tmp_path / "speech.wav"
    # Previous word's trailing plosive/noise island near 500ms, real next word at 700ms.
    _write_wav(wav, [(480, 560), (700, 1100)], total_ms=1300)
    asr = ASRData([ASRDataSeg("next", 650, 1120)])

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=350, padding_ms=0)

    assert snapped.segments[0].start_time == 700


def test_shared_boundary_snaps_to_silence_valley(tmp_path):
    wav = tmp_path / "speech.wav"
    _write_wav(wav, [(100, 480), (660, 1100)], total_ms=1300)
    asr = ASRData(
        [
            ASRDataSeg("left", 100, 620),
            ASRDataSeg("right", 620, 1100),
        ]
    )

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=300, padding_ms=0)

    assert 520 <= snapped.segments[0].end_time <= 600
    assert snapped.segments[1].start_time == 660


def test_shared_boundary_pushes_next_start_to_speech_onset(tmp_path):
    wav = tmp_path / "speech.wav"
    _write_wav(wav, [(100, 480), (760, 1100)], total_ms=1300)
    asr = ASRData(
        [
            ASRDataSeg("left", 100, 620),
            ASRDataSeg("right", 620, 1100),
        ]
    )

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=300, padding_ms=0)

    assert 520 <= snapped.segments[0].end_time <= 640
    assert snapped.segments[1].start_time == 760


def test_snap_start_pushes_silent_start_to_stable_onset_plus_padding(tmp_path):
    # Start sits in silence 150ms before real speech; a 60ms noise island nearby
    # must NOT be used. Start should move forward to onset + padding_ms.
    wav = tmp_path / "speech.wav"
    _write_wav(wav, [(300, 360), (500, 1000)], total_ms=1100)
    asr = ASRData([ASRDataSeg("word", 350, 1020)])

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=300, padding_ms=40)

    # 60ms island (300-360) is below min_run=100, so onset gate skips it and
    # lands on the 500ms stable onset. +40ms safety delay from padding_ms.
    assert snapped.segments[0].start_time == 540


def test_spectral_flatness_distinguishes_tonal_speech_from_noise_burst():
    import numpy as np

    from videocaptioner.core.alignment.audio_boundary_snapper import (
        _flatness_confirms_speech,
        _spectral_flatness_frames,
    )

    sr = 8000
    t = np.arange(int(sr * 0.3)) / sr
    # Tonal signal (formant-like): two sine partials → low flatness.
    tone = (12000 * np.sin(2 * np.pi * 220 * t) + 8000 * np.sin(2 * np.pi * 440 * t))
    tone_samples = tone.astype(np.float32).tolist()
    flat_tone = _spectral_flatness_frames(tone_samples, sr, frame_ms=20)
    assert flat_tone  # STFT produced frames
    # Onset frame mid-signal should be confirmed as structured speech.
    assert _flatness_confirms_speech(flat_tone, frame_ms=20, onset_ms=200) is True

    # White-noise burst → high flatness → not confirmed as speech.
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(int(sr * 0.3)) * 12000
    flat_noise = _spectral_flatness_frames(noise.astype(np.float32).tolist(), sr, frame_ms=20)
    assert flat_noise
    assert _flatness_confirms_speech(flat_noise, frame_ms=20, onset_ms=200) is False


def test_small_window_does_not_overshoot_when_start_already_at_speech(tmp_path):
    wav = tmp_path / "speech.wav"
    _write_test_wav(wav)
    asr = ASRData([ASRDataSeg("first", 0, 950)])

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=100, padding_ms=0)

    assert snapped.segments[0].start_time == 0
    assert snapped.segments[0].end_time == 950
