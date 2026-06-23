"""Wiring tests: ElevenLabs is selectable in the dubbing pipeline.

Verifies that ``DubbingConfig(provider="elevenlabs")`` flows through to an
``ElevenLabsSpeechSynthesizer``, that provider-specific ``extra`` options are
forwarded to the speech config, and that the pipeline selects mp3 output for
ElevenLabs (matching the SDK's ``mp3_44100_128`` output format).
"""

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
from videocaptioner.core.speech import ElevenLabsSpeechSynthesizer


def _make_config(**overrides) -> DubbingConfig:
    defaults = {
        "provider": "elevenlabs",
        "api_key": "el-key",
        "base_url": "",
        "model": "eleven_multilingual_v2",
        "voice": "21m00Tcm4TlvDq8ikWAM",
        "extra": {"stability": 0.7, "similarity_boost": 0.85},
    }
    defaults.update(overrides)
    return DubbingConfig(**defaults)


def test_pipeline_builds_elevenlabs_synthesizer():
    pipeline = DubbingPipeline(_make_config())
    assert isinstance(pipeline.synthesizer, ElevenLabsSpeechSynthesizer)


def test_pipeline_forwards_extra_to_synthesizer():
    pipeline = DubbingPipeline(_make_config())
    assert pipeline.synthesizer.config.extra == {
        "stability": 0.7,
        "similarity_boost": 0.85,
    }


def test_pipeline_selects_mp3_extension_for_elevenlabs():
    pipeline = DubbingPipeline(_make_config())
    assert pipeline._provider_extension() == "mp3"


def test_pipeline_response_format_is_mp3_for_elevenlabs():
    config = _make_config()
    assert DubbingPipeline._provider_response_format(config) == "mp3"
