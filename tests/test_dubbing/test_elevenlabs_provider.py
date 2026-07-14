"""Unit tests for the ElevenLabs speech synthesizer.

The elevenlabs SDK client is replaced with fakes (mirroring the approach in
``test_edge_tts_provider.py``) so no real API key or network access is needed.
"""

from pathlib import Path

import pytest

import videocaptioner.core.speech.providers as providers_module
from videocaptioner.core.speech import (
    ElevenLabsSpeechSynthesizer,
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)


class _FakeConvert:
    """Stand-in for ``ElevenLabs().text_to_speech.convert``."""

    last_kwargs: dict | None = None

    def __call__(self, **kwargs) -> iter:
        _FakeConvert.last_kwargs = kwargs
        # The real call returns an Iterator[bytes]; yield two chunks.
        return iter([b"fake-mp3-part1-", b"part2"])


class _FakeTextToSpeech:
    def __init__(self) -> None:
        self.convert = _FakeConvert()


class _FakeElevenLabsClient:
    """Stand-in for the ``elevenlabs.ElevenLabs`` client class."""

    init_kwargs: list[dict] = []

    def __init__(self, **kwargs) -> None:
        _FakeElevenLabsClient.init_kwargs.append(kwargs)
        self.text_to_speech = _FakeTextToSpeech()


class _FakeVoiceSettings:
    calls: list[dict] = []

    def __init__(self, **kwargs) -> None:
        _FakeVoiceSettings.calls.append(kwargs)


@pytest.fixture(autouse=True)
def _install_fakes(monkeypatch):
    """Patch the module-level SDK names so no real client is constructed."""
    monkeypatch.setattr(providers_module, "ElevenLabs", _FakeElevenLabsClient)
    monkeypatch.setattr(providers_module, "VoiceSettings", _FakeVoiceSettings)
    _FakeConvert.last_kwargs = None
    _FakeVoiceSettings.calls = []
    _FakeElevenLabsClient.init_kwargs = []
    yield


def _make_config(**overrides) -> SpeechProviderConfig:
    defaults = {
        "provider": "elevenlabs",
        "api_key": "el-key",
        "model": "eleven_multilingual_v2",
        "default_voice": "21m00Tcm4TlvDq8ikWAM",
    }
    defaults.update(overrides)
    return SpeechProviderConfig(**defaults)


def test_synthesizer_writes_mp3(tmp_path):
    config = _make_config(
        speed=1.1,
        extra={"stability": 0.6, "similarity_boost": 0.8, "use_speaker_boost": False},
    )
    result = ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(text="你好世界", output_path=str(tmp_path / "line.wav"))
    )

    assert result.output_path.endswith(".mp3")
    assert Path(result.output_path).read_bytes() == b"fake-mp3-part1-part2"
    assert result.voice == "21m00Tcm4TlvDq8ikWAM"
    assert result.format == "mp3"

    # Client built with the configured API key + timeout.
    assert _FakeElevenLabsClient.init_kwargs[-1]["api_key"] == "el-key"

    # VoiceSettings received the tuned params plus the shared speed.
    voice_settings = _FakeVoiceSettings.calls[-1]
    assert voice_settings["speed"] == 1.1
    assert voice_settings["stability"] == 0.6
    assert voice_settings["similarity_boost"] == 0.8
    assert voice_settings["use_speaker_boost"] is False

    # convert() was called with the resolved voice/model/format/text.
    convert_kwargs = _FakeConvert.last_kwargs
    assert convert_kwargs["voice_id"] == "21m00Tcm4TlvDq8ikWAM"
    assert convert_kwargs["model_id"] == "eleven_multilingual_v2"
    assert convert_kwargs["output_format"] == "mp3_44100_128"
    assert convert_kwargs["text"] == "你好世界"
    assert convert_kwargs["apply_text_normalization"] == "auto"

    # Provider metadata reflects the tuned settings.
    assert result.provider_metadata["stability"] == 0.6
    assert result.provider_metadata["model_id"] == "eleven_multilingual_v2"


def test_request_voice_overrides_default(tmp_path):
    config = _make_config(default_voice="default-voice-id")
    result = ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(
            text="hi",
            output_path=str(tmp_path / "line.wav"),
            voice="override-voice-id",
        )
    )
    assert result.voice == "override-voice-id"
    assert _FakeConvert.last_kwargs["voice_id"] == "override-voice-id"


def test_text_with_time_is_sent_unchanged(tmp_path):
    text = "By 6:13 PM that same evening"

    ElevenLabsSpeechSynthesizer(_make_config()).synthesize(
        SynthesisRequest(text=text, output_path=str(tmp_path / "line.wav"))
    )

    assert _FakeConvert.last_kwargs["text"] == text


def test_factory_returns_elevenlabs_synthesizer():
    synth = create_speech_synthesizer(_make_config())
    assert isinstance(synth, ElevenLabsSpeechSynthesizer)


def test_missing_api_key_raises():
    with pytest.raises(ValueError):
        ElevenLabsSpeechSynthesizer(_make_config(api_key=""))


def test_voice_cloning_not_supported(tmp_path):
    synth = ElevenLabsSpeechSynthesizer(_make_config())
    with pytest.raises(ValueError):
        synth.synthesize(
            SynthesisRequest(
                text="hi",
                output_path=str(tmp_path / "line.wav"),
                clone_audio_path="ref.wav",
                clone_audio_text="ref text",
            )
        )


def test_default_voice_used_when_none_configured(tmp_path):
    config = _make_config(default_voice="")
    result = ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
    )
    # Falls back to the provider's DEFAULT_VOICE (Rachel).
    assert result.voice == ElevenLabsSpeechSynthesizer.DEFAULT_VOICE
    assert _FakeConvert.last_kwargs["voice_id"] == ElevenLabsSpeechSynthesizer.DEFAULT_VOICE


def test_default_model_used_when_blank(tmp_path):
    config = _make_config(model="")
    ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
    )
    assert _FakeConvert.last_kwargs["model_id"] == ElevenLabsSpeechSynthesizer.DEFAULT_MODEL


def test_extra_defaults_applied(tmp_path):
    # No extra tuning supplied -> voice settings use the documented defaults.
    ElevenLabsSpeechSynthesizer(_make_config()).synthesize(
        SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
    )
    vs = _FakeVoiceSettings.calls[-1]
    assert vs["stability"] == 0.5
    assert vs["similarity_boost"] == 0.75
    assert vs["style"] == 0.0
    assert vs["use_speaker_boost"] is True


def test_api_error_is_wrapped(tmp_path, monkeypatch):
    class _BoomTextToSpeech:
        def convert(self, **kwargs):
            raise RuntimeError("boom")

    class _BoomClient:
        def __init__(self, **kwargs):
            self.text_to_speech = _BoomTextToSpeech()

    monkeypatch.setattr(providers_module, "ElevenLabs", _BoomClient)
    synth = ElevenLabsSpeechSynthesizer(_make_config())
    with pytest.raises(RuntimeError, match="ElevenLabs TTS failed: boom"):
        synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))


def test_multiple_keys_are_parsed(tmp_path):
    config = _make_config(api_key="key-a, key-b; key-c")
    synth = ElevenLabsSpeechSynthesizer(config)
    assert synth.api_keys == ["key-a", "key-b", "key-c"]
    result = synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))
    assert Path(result.output_path).read_bytes() == b"fake-mp3-part1-part2"
    # Round-robin starts at index 0, so the first key is used.
    assert _FakeElevenLabsClient.init_kwargs[-1]["api_key"] == "key-a"
    assert result.provider_metadata["api_key_index"] == 0


def test_round_robin_rotates_starting_key(tmp_path):
    synth = ElevenLabsSpeechSynthesizer(_make_config(api_key="key-a, key-b, key-c"))
    used = []
    for _ in range(3):
        _FakeElevenLabsClient.init_kwargs.clear()
        synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))
        used.append(_FakeElevenLabsClient.init_kwargs[-1]["api_key"])
    assert used == ["key-a", "key-b", "key-c"]
    # Fourth call wraps back to the first key.
    _FakeElevenLabsClient.init_kwargs.clear()
    synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))
    assert _FakeElevenLabsClient.init_kwargs[-1]["api_key"] == "key-a"


def test_switches_to_next_key_on_auth_error(tmp_path, monkeypatch):
    class _AuthError(Exception):
        pass

    monkeypatch.setattr(providers_module, "UnauthorizedError", _AuthError)

    attempted: list[str] = []

    class _TTS:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def convert(self, **kwargs):
            attempted.append(self.api_key)
            if self.api_key == "bad":
                raise _AuthError("unauthorized")
            return iter([b"ok"])

    class _Client:
        def __init__(self, **kwargs) -> None:
            self.text_to_speech = _TTS(kwargs.get("api_key"))

    monkeypatch.setattr(providers_module, "ElevenLabs", _Client)

    config = _make_config(api_key="bad, good")
    result = ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
    )
    assert attempted == ["bad", "good"]
    assert Path(result.output_path).read_bytes() == b"ok"
    assert result.provider_metadata["api_key_index"] == 1


def test_all_keys_fail_raises_clear_error(tmp_path, monkeypatch):
    class _AuthError(Exception):
        pass

    monkeypatch.setattr(providers_module, "UnauthorizedError", _AuthError)

    class _TTS:
        def convert(self, **kwargs):
            raise _AuthError("unauthorized")

    class _Client:
        def __init__(self, **kwargs) -> None:
            self.text_to_speech = _TTS()

    monkeypatch.setattr(providers_module, "ElevenLabs", _Client)

    config = _make_config(api_key="k1, k2, k3")
    with pytest.raises(RuntimeError, match="All 3 ElevenLabs API keys failed"):
        ElevenLabsSpeechSynthesizer(config).synthesize(
            SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
        )


def test_non_auth_error_also_rotates_to_next_key(tmp_path, monkeypatch):
    """Any failure (not just auth) rotates to the next key.

    "出问题就换 API" -- a network/timeout/5xx error on one key must not burn
    the whole dub; the next key is tried, and only when every key has failed
    is an error raised.
    """
    attempted: list[str] = []

    class _TTS:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def convert(self, **kwargs):
            attempted.append(self.api_key)
            raise RuntimeError("network boom")

    class _Client:
        def __init__(self, **kwargs) -> None:
            self.text_to_speech = _TTS(kwargs.get("api_key"))

    monkeypatch.setattr(providers_module, "ElevenLabs", _Client)

    config = _make_config(api_key="k1, k2")
    with pytest.raises(RuntimeError, match="All 2 ElevenLabs API keys failed"):
        ElevenLabsSpeechSynthesizer(config).synthesize(
            SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
        )
    # Both keys are tried before giving up.
    assert attempted == ["k1", "k2"]


def test_non_auth_error_recovers_on_next_key(tmp_path, monkeypatch):
    """A network/timeout error on the first key is recovered by the second.

    This is the core "一个 api 出问题就换，配音不停" guarantee: a non-auth
    failure on one key transparently falls through to a working key instead
    of aborting the synthesis.
    """
    attempted: list[str] = []

    class _TTS:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def convert(self, **kwargs):
            attempted.append(self.api_key)
            if self.api_key == "broken":
                raise RuntimeError("connection reset")
            return iter([b"recovered"])

    class _Client:
        def __init__(self, **kwargs) -> None:
            self.text_to_speech = _TTS(kwargs.get("api_key"))

    monkeypatch.setattr(providers_module, "ElevenLabs", _Client)

    config = _make_config(api_key="broken, working")
    result = ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
    )
    assert attempted == ["broken", "working"]
    assert Path(result.output_path).read_bytes() == b"recovered"
    assert result.provider_metadata["api_key_index"] == 1


def test_streaming_error_during_iteration_switches_key(tmp_path, monkeypatch):
    """A 401 raised while iterating the response (not in convert()) switches keys.

    The real ElevenLabs SDK returns a lazy Iterator[bytes]; the HTTP request
    happens on iteration, so the write loop must be inside the retry try-block.
    """
    class _AuthError(Exception):
        pass

    monkeypatch.setattr(providers_module, "UnauthorizedError", _AuthError)

    class _TTS:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def convert(self, **kwargs):
            def _stream():
                if self.api_key == "bad":
                    raise _AuthError("unauthorized on stream")
                yield b"ok"

            return _stream()

    class _Client:
        def __init__(self, **kwargs) -> None:
            self.text_to_speech = _TTS(kwargs.get("api_key"))

    monkeypatch.setattr(providers_module, "ElevenLabs", _Client)

    config = _make_config(api_key="bad, good")
    result = ElevenLabsSpeechSynthesizer(config).synthesize(
        SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
    )
    assert Path(result.output_path).read_bytes() == b"ok"
    assert result.provider_metadata["api_key_index"] == 1


def test_streaming_error_all_keys_fail(tmp_path, monkeypatch):
    """When every key fails during streaming, all are tried then a clear error raised."""
    class _AuthError(Exception):
        pass

    monkeypatch.setattr(providers_module, "UnauthorizedError", _AuthError)

    class _TTS:
        def convert(self, **kwargs):
            def _stream():
                raise _AuthError("unauthorized on stream")
                yield  # makes this a generator (unreachable)

            return _stream()

    class _Client:
        def __init__(self, **kwargs) -> None:
            self.text_to_speech = _TTS()

    monkeypatch.setattr(providers_module, "ElevenLabs", _Client)

    config = _make_config(api_key="k1, k2, k3")
    with pytest.raises(RuntimeError, match="All 3 ElevenLabs API keys failed"):
        ElevenLabsSpeechSynthesizer(config).synthesize(
            SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav"))
        )
