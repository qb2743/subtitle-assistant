"""Tests for the OpenAI (OpenAI-compatible) speech provider and dubbing wiring.

The openai SDK client is faked so no network is needed. Verifies a custom
base_url is forwarded (so OpenAI-format TTS wrappers work).
"""

from pathlib import Path

import pytest

import videocaptioner.core.speech.providers as providers_module
from videocaptioner.core.dubbing import DubbingConfig, SpeakerProfile
from videocaptioner.core.speech import (
    OpenAISpeechSynthesizer,
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)


class _FakeStreamResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream_to_file(self, path):
        Path(path).write_bytes(b"fake-mp3")


class _FakeSpeech:
    last_kwargs: dict | None = None

    def __init__(self):
        self.with_streaming_response = self

    def create(self, **kwargs):
        _FakeSpeech.last_kwargs = kwargs
        return _FakeStreamResponse()


class _FakeAudio:
    def __init__(self):
        self.speech = _FakeSpeech()


class _FakeOpenAIClient:
    init_kwargs: list = []

    def __init__(self, **kwargs):
        _FakeOpenAIClient.init_kwargs.append(kwargs)
        self.audio = _FakeAudio()


@pytest.fixture(autouse=True)
def _install_fake(monkeypatch):
    monkeypatch.setattr(providers_module, "_OpenAIClient", _FakeOpenAIClient)
    _FakeOpenAIClient.init_kwargs.clear()
    _FakeSpeech.last_kwargs = None
    yield


def _config(**overrides) -> SpeechProviderConfig:
    defaults = {
        "provider": "openai",
        "api_key": "sk-test",
        "model": "tts-1",
        "base_url": "https://my-tts.example.com/v1",
        "default_voice": "alloy",
    }
    defaults.update(overrides)
    return SpeechProviderConfig(**defaults)


def test_factory_returns_openai_synthesizer():
    synth = create_speech_synthesizer(_config())
    assert isinstance(synth, OpenAISpeechSynthesizer)


def test_custom_base_url_forwarded_to_client():
    OpenAISpeechSynthesizer(_config(base_url="https://my-tts.example.com/v1"))
    kw = _FakeOpenAIClient.init_kwargs[-1]
    assert kw["api_key"] == "sk-test"
    assert kw["base_url"] == "https://my-tts.example.com/v1"
    assert kw["max_retries"] == 3


def test_synthesize_writes_mp3_and_calls_endpoint(tmp_path):
    synth = OpenAISpeechSynthesizer(_config(default_voice="nova", speed=1.0))
    result = synth.synthesize(
        SynthesisRequest(text="hello world", output_path=str(tmp_path / "line.wav"))
    )
    assert result.output_path.endswith(".mp3")
    assert Path(result.output_path).read_bytes() == b"fake-mp3"
    assert result.voice == "nova"
    assert result.format == "mp3"
    assert result.provider_metadata["base_url"] == "https://my-tts.example.com/v1"
    # The OpenAI-format request payload.
    kw = _FakeSpeech.last_kwargs
    assert kw["model"] == "tts-1"
    assert kw["voice"] == "nova"
    assert kw["input"] == "hello world"
    assert kw["response_format"] == "mp3"
    assert kw["speed"] == 1.0


def test_missing_api_key_raises():
    with pytest.raises(ValueError):
        OpenAISpeechSynthesizer(_config(api_key=""))


def test_voice_cloning_not_supported(tmp_path):
    synth = OpenAISpeechSynthesizer(_config())
    with pytest.raises(ValueError, match="voice cloning"):
        synth.synthesize(
            SynthesisRequest(
                text="hi",
                output_path=str(tmp_path / "line.wav"),
                clone_audio_path="ref.wav",
                clone_audio_text="ref",
            )
        )


def test_resolve_provider_accepts_all_seven():
    from videocaptioner.cli.commands.dub import _resolve_provider

    for p in ("siliconflow", "gemini", "edge", "elevenlabs", "dots", "voxcpm", "openai"):
        assert _resolve_provider(p) == p
    with pytest.raises(ValueError):
        _resolve_provider("bogus")


def test_openai_validation_rejects_cloning():
    from videocaptioner.cli.commands.dub import _validate_provider_capabilities

    cfg = DubbingConfig(
        provider="openai",
        api_key="sk-test",
        base_url="https://my-tts.example.com/v1",
        model="tts-1",
        voice="alloy",
        speaker_profiles={
            "default": SpeakerProfile(name="default", clone_audio_path="ref.wav", clone_audio_text="ref")
        },
    )
    err = _validate_provider_capabilities(cfg)
    assert err is not None
    assert "voice cloning" in err
