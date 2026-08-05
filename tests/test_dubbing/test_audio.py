from pydub import AudioSegment
from pydub.generators import Sine

from videocaptioner.core.dubbing.audio import (
    get_audio_duration_ms,
    trim_trailing_silence,
)


def test_trim_trailing_silence_keeps_spoken_audio(tmp_path):
    source = tmp_path / "tts.wav"
    output = tmp_path / "tts.trimmed.wav"
    (Sine(440).to_audio_segment(duration=300).apply_gain(-10) + AudioSegment.silent(400)).export(
        source, format="wav"
    )

    result = trim_trailing_silence(str(source), str(output))

    assert result == str(output)
    assert 280 <= get_audio_duration_ms(result) <= 320
