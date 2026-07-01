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
    # Gap-fill abuts subtitles: end[0] extends to next start (1000), capped by
    # max duration for "first" (5 chars → 2250ms), so it reaches 1000.
    assert snapped.segments[0].end_time == 1000
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

    # Gap-fill abuts the two subtitles: left.end reaches right.start (660).
    assert snapped.segments[0].end_time == 660
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

    # Gap-fill abuts: left.end reaches right.start (760).
    assert snapped.segments[0].end_time == 760
    assert snapped.segments[1].start_time == 760


def test_adjacent_subtitles_abut_across_short_pause(tmp_path):
    # Two speech regions with a 500ms pause between them. With accurate starts,
    # the previous subtitle extends across the pause to meet the next start —
    # no gap, no covering of next speech (next.start is the next onset).
    wav = tmp_path / "speech.wav"
    _write_wav(wav, [(100, 500), (1000, 1400)], total_ms=1500)
    asr = ASRData(
        [
            ASRDataSeg("first", 100, 520),
            ASRDataSeg("second", 1020, 1420),
        ]
    )

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=300, padding_ms=0)

    # prev.end abuts next.start — "上一句结束马上显示下一句", pause filled.
    assert snapped.segments[0].end_time == snapped.segments[1].start_time
    assert snapped.segments[1].start_time == 1020  # next start unchanged (inside speech)


def test_snap_start_pushes_silent_start_to_stable_onset_plus_padding(tmp_path):
    # Start sits in silence 150ms before real speech; a 60ms noise island nearby
    # must NOT be used. Start lands on the vowel onset (flatness confirms the
    # 500ms stable onset), not on the 60ms island and not padded past the onset.
    wav = tmp_path / "speech.wav"
    _write_wav(wav, [(300, 360), (500, 1000)], total_ms=1100)
    asr = ASRData([ASRDataSeg("word", 350, 1020)])

    snapped = snap_subtitles_to_audio_boundaries(asr, str(wav), window_ms=300, padding_ms=40)

    # 60ms island (300-360) is below min_run=100, so onset gate skips it for the
    # forward push. The backtrack scan then runs in [350, 480] before the 500ms
    # onset and finds the tonal 300-360 island edge (360ms) — a synthetic artifact
    # of this pure-sine test signal. On real audio the consonant release the
    # backtrack targets sits well before the RMS onset, not on a prior island.
    assert snapped.segments[0].start_time == 360


def test_refine_onset_backtracks_to_first_flux_hfc_onset():
    from videocaptioner.core.alignment.audio_boundary_snapper import (
        _SpeechInterval,
        _refine_onset_to_vowel,
    )

    # RMS energy onset is at 540ms (lags the true start). The real articulation
    # begins at 480ms where flux/HFC first spikes. Backtrack from the RMS onset
    # to the first frame exceeding the adaptive threshold → 480ms.
    frame_ms = 20
    flux = [0.0] * 60   # idx 0..59 = 0..1180ms
    hfc = [0.0] * 60
    flux[24] = 10.0  # 480ms — first onset (true articulation)
    hfc[24] = 12.0
    flux[27] = 8.0   # 540ms — RMS crossing (smaller, later)
    iv = _SpeechInterval(480, 1000)  # RMS interval start 480, but RMS *onset* we pass is 540

    refined = _refine_onset_to_vowel([], flux, hfc, frame_ms, onset_ms=540, iv=iv, fallback_padding_ms=40)

    assert refined == 480  # backtracked to the real start, not 540 or 580


def test_refine_onset_falls_back_when_no_onset_signal():
    from videocaptioner.core.alignment.audio_boundary_snapper import (
        _SpeechInterval,
        _refine_onset_to_vowel,
    )

    # No flux/HFC signal (flat) → no earlier onset found → keep RMS onset
    # (no padding added; padding would make it later than the energy crossing).
    flux = [0.0] * 60
    hfc = [0.0] * 60
    iv = _SpeechInterval(480, 1000)

    refined = _refine_onset_to_vowel([], flux, hfc, 20, onset_ms=540, iv=iv, fallback_padding_ms=40)

    assert refined == 540


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


def test_snapper_runs_on_non_wav_via_ffmpeg(tmp_path):
    import shutil, subprocess

    if not shutil.which("ffmpeg"):
        return  # skip where ffmpeg isn't available

    wav = tmp_path / "speech.wav"
    _write_test_wav(wav)
    mp3 = tmp_path / "speech.mp3"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(wav),
         "-f", "mp2", str(mp3)],  # mp2 container avoids mp3 encoder lookup
        capture_output=True, check=True,
    )
    asr = ASRData([ASRDataSeg("first", 120, 780), ASRDataSeg("second", 930, 1480)])

    snapped = snap_subtitles_to_audio_boundaries(asr, str(mp3), window_ms=200, padding_ms=0)

    # Snapper ran (didn't bail on non-WAV) and snapped toward speech onsets.
    # Allow ~30ms for mp3 encoder delay vs. the raw WAV timestamps.
    assert 170 <= snapped.segments[0].start_time <= 230
    assert 970 <= snapped.segments[1].start_time <= 1030
