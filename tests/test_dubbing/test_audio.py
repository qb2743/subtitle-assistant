from pydub import AudioSegment
from pydub.generators import Sine

from videocaptioner.core.dubbing.audio import (
    create_timeline_audio,
    get_audio_duration_ms,
    mux_dubbed_audio,
    overlay_source_audio_intervals,
    trim_trailing_silence,
)
from videocaptioner.core.dubbing.video_rate import RatePlan, RatePlanItem


def test_trim_trailing_silence_keeps_spoken_audio(tmp_path):
    source = tmp_path / "tts.wav"
    output = tmp_path / "tts.trimmed.wav"
    (Sine(440).to_audio_segment(duration=300).apply_gain(-10) + AudioSegment.silent(400)).export(
        source, format="wav"
    )

    result = trim_trailing_silence(str(source), str(output))

    assert result == str(output)
    assert 280 <= get_audio_duration_ms(result) <= 320


def test_trim_trailing_silence_removes_low_level_tail_noise(tmp_path):
    source = tmp_path / "tts-noisy-tail.wav"
    output = tmp_path / "tts-noisy-tail.trimmed.wav"
    spoken = Sine(440).to_audio_segment(duration=300).apply_gain(-10)
    low_level_tail = Sine(120).to_audio_segment(duration=400).apply_gain(-55)
    (spoken + low_level_tail).export(source, format="wav")

    result = trim_trailing_silence(str(source), str(output))

    assert result == str(output)
    assert 280 <= get_audio_duration_ms(result) <= 320


def test_create_timeline_audio_keeps_full_positive_gain_in_stereo(tmp_path):
    source = tmp_path / "source.wav"
    output = tmp_path / "timeline.wav"
    tone = Sine(440).to_audio_segment(duration=500).apply_gain(-30)
    tone.export(source, format="wav")

    create_timeline_audio(
        [(str(source), 0)],
        str(output),
        duration_ms=500,
        volume=10 ** (8 / 20),
    )

    timeline = AudioSegment.from_file(output)
    assert timeline.channels == 2
    assert 7.5 < timeline.dBFS - tone.dBFS < 8.5


def test_overlay_source_audio_intervals_maps_and_merges(tmp_path):
    source = tmp_path / "source.wav"
    output = tmp_path / "dubbed.wav"
    tone = Sine(440).to_audio_segment(duration=1500).apply_gain(-12)
    (AudioSegment.silent(duration=1000, frame_rate=tone.frame_rate) + tone).export(
        source, format="wav"
    )
    AudioSegment.silent(duration=500, frame_rate=tone.frame_rate).export(
        output, format="wav"
    )
    plan = RatePlan(
        items=[
            RatePlanItem(0, 1000, 2.0, 0),
            RatePlanItem(1000, 2500, 1.0, 0),
        ],
        total_output_duration_ms=3500,
    )

    overlay_source_audio_intervals(
        str(source),
        str(output),
        [(1000, 1300), (1200, 1500), (1700, 1900), (2300, 2500)],
        rate_plan=plan,
        blocking_intervals=[(1950, 2250)],
    )

    mixed = AudioSegment.from_file(output)
    assert 3490 <= len(mixed) <= 3510
    assert mixed[1800:1900].dBFS == float("-inf")
    assert abs(mixed[2050:2150].dBFS - mixed[2250:2350].dBFS) < 1
    assert mixed[2550:2650].dBFS > -40
    assert mixed[2900:2940].dBFS > -40
    assert mixed[3050:3150].dBFS == float("-inf")


def test_mux_original_audio_keeps_dubbed_gain(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.audio._video_has_audio", lambda _path: True
    )
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.audio.subprocess.run",
        lambda command, **_kwargs: commands.append(command),
    )

    mux_dubbed_audio(
        "video.mp4",
        "dub.wav",
        str(tmp_path / "output.mp4"),
        mix_original_audio=True,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "dropout_transition=0:normalize=0" in filter_complex
