"""Tests for the local-Gradio-TTS speech adapter (Dots/VoxCPM in the dubbing pipeline)."""

from pathlib import Path

import pytest

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline, SpeakerProfile
from videocaptioner.core.speech import (
    LocalGradioSpeechSynthesizer,
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)


def _config(provider: str = "dots", **overrides) -> SpeechProviderConfig:
    defaults = {
        "provider": provider,
        "api_key": "",
        "model": provider + "-tts",
        "base_url": "http://127.0.0.1:7860",
        "default_voice": "",
    }
    defaults.update(overrides)
    return SpeechProviderConfig(**defaults)


def test_factory_returns_dots_adapter():
    synth = create_speech_synthesizer(_config("dots"))
    assert isinstance(synth, LocalGradioSpeechSynthesizer)
    assert synth.service_name == "dotstts"


def test_factory_returns_voxcpm_adapter():
    synth = create_speech_synthesizer(_config("voxcpm", base_url="http://127.0.0.1:9880"))
    assert isinstance(synth, LocalGradioSpeechSynthesizer)
    assert synth.service_name == "voxcpmtts"


def test_adapter_synthesizes_and_passes_clone(tmp_path, monkeypatch):
    adapter = LocalGradioSpeechSynthesizer(_config("dots"))
    captured: dict = {}

    def _fake_synthesize(segment, output_path):
        captured["segment"] = segment
        captured["output_path"] = output_path
        Path(output_path).write_bytes(b"fake-wav")
        segment.audio_path = output_path

    monkeypatch.setattr(adapter.engine, "_synthesize", _fake_synthesize)

    result = adapter.synthesize(
        SynthesisRequest(
            text="你好世界",
            output_path=str(tmp_path / "line.wav"),
            clone_audio_path="/ref.wav",
            clone_audio_text="参考文本",
        )
    )

    assert result.format == "wav"
    assert result.output_path.endswith(".wav")
    assert Path(result.output_path).read_bytes() == b"fake-wav"
    assert result.voice == "clone"
    # The clone ref + text were forwarded to the engine.
    assert captured["segment"].text == "你好世界"
    assert captured["segment"].clone_audio_path == "/ref.wav"
    assert captured["segment"].clone_audio_text == "参考文本"


def test_adapter_uses_config_clone_defaults(tmp_path, monkeypatch):
    adapter = LocalGradioSpeechSynthesizer(
        _config("dots", clone_audio_path="/default-ref.wav", clone_audio_text="默认参考文本")
    )
    captured: dict = {}

    def _fake_synthesize(segment, output_path):
        captured["segment"] = segment
        Path(output_path).write_bytes(b"fake-wav")
        segment.audio_path = output_path

    monkeypatch.setattr(adapter.engine, "_synthesize", _fake_synthesize)
    adapter.synthesize(SynthesisRequest(text="你好世界", output_path=str(tmp_path / "line.wav")))

    assert captured["segment"].clone_audio_path == "/default-ref.wav"
    assert captured["segment"].clone_audio_text == "默认参考文本"


def test_adapter_requires_clone_ref(tmp_path, monkeypatch):
    adapter = LocalGradioSpeechSynthesizer(_config("dots"))
    # Skip the real service liveness probe so the clone-ref check is reached.
    monkeypatch.setattr(adapter.engine, "_ensure_service_ready", lambda **kw: None)
    with pytest.raises(ValueError, match="reference audio"):
        adapter.synthesize(SynthesisRequest(text="你好", output_path=str(tmp_path / "line.wav")))


def test_adapter_threads_start_script():
    config = _config(
        "voxcpm",
        base_url="http://127.0.0.1:9880",
        extra={"start_script": "/path/to/start.ps1", "service_start_timeout": 60},
    )
    adapter = LocalGradioSpeechSynthesizer(config)
    assert adapter.engine.config.start_script == "/path/to/start.ps1"
    assert adapter.engine.config.service_start_timeout == 60
    assert adapter.engine.api_url == "http://127.0.0.1:9880"


def test_pipeline_extension_for_local():
    for provider, base_url in (("dots", "http://127.0.0.1:7860"), ("voxcpm", "http://127.0.0.1:9880")):
        cfg = DubbingConfig(
            provider=provider,
            api_key="",
            base_url=base_url,
            model=provider + "-tts",
            voice="",
        )
        assert DubbingPipeline._provider_response_format(cfg) == "wav"
        pipeline = DubbingPipeline(cfg)
        assert pipeline._provider_extension() == "wav"
        assert isinstance(pipeline.synthesizer, LocalGradioSpeechSynthesizer)


def test_dubbing_validation_requires_clone_for_local():
    from videocaptioner.cli.commands.dub import _validate_provider_capabilities

    cfg = DubbingConfig(
        provider="dots", api_key="", base_url="http://127.0.0.1:7860", model="dots-tts", voice=""
    )
    err = _validate_provider_capabilities(cfg)
    assert err is not None
    assert "reference audio" in err

    cfg_with_clone = DubbingConfig(
        provider="dots",
        api_key="",
        base_url="http://127.0.0.1:7860",
        model="dots-tts",
        voice="",
        speaker_profiles={
            "default": SpeakerProfile(name="default", clone_audio_path="/ref.wav", clone_audio_text="ref")
        },
    )
    assert _validate_provider_capabilities(cfg_with_clone) is None

    cfg_with_global_clone = DubbingConfig(
        provider="dots",
        api_key="",
        base_url="http://127.0.0.1:7860",
        model="dots-tts",
        voice="",
        clone_audio_path="/ref.wav",
        clone_audio_text="ref",
    )
    assert _validate_provider_capabilities(cfg_with_global_clone) is None
