import pytest

from videocaptioner.core.dubbing.presets import (
    available_dubbing_presets,
    elevenlabs_voice_options,
    get_dubbing_preset,
    normalize_dubbing_voice,
    validate_dubbing_voice,
)


def test_available_presets_include_main_providers():
    presets = available_dubbing_presets()

    assert "siliconflow-cn-female" in presets
    assert "gemini-en-friendly" in presets
    assert "edge-cn-female" in presets


def test_get_dubbing_preset():
    preset = get_dubbing_preset("siliconflow-cn-female")

    assert preset.provider == "siliconflow"
    assert preset.model == "FunAudioLLM/CosyVoice2-0.5B"
    assert preset.voice.endswith(":anna")


def test_get_dubbing_preset_unknown():
    with pytest.raises(ValueError, match="Unknown dubbing preset"):
        get_dubbing_preset("missing")


def test_normalize_siliconflow_short_voice_alias():
    voice = normalize_dubbing_voice("siliconflow", "FunAudioLLM/CosyVoice2-0.5B", "anna")

    assert voice == "FunAudioLLM/CosyVoice2-0.5B:anna"


def test_validate_gemini_unknown_voice():
    error = validate_dubbing_voice("gemini", "not-a-voice")

    assert error is not None
    assert "Unknown Gemini voice" in error


def test_normalize_edge_short_voice_alias():
    voice = normalize_dubbing_voice("edge", "edge-tts", "xiaoxiao")

    assert voice == "zh-CN-XiaoxiaoNeural"


def test_validate_edge_voice_alias_and_full_id():
    assert validate_dubbing_voice("edge", "xiaoxiao") is None
    assert validate_dubbing_voice("edge", "zh-CN-XiaoxiaoNeural") is None
    assert "Edge TTS voice" in (validate_dubbing_voice("edge", "badvoice") or "")


def test_available_presets_include_elevenlabs():
    presets = available_dubbing_presets()
    assert "elevenlabs-multilingual-female" in presets
    assert "elevenlabs-multilingual-male" in presets
    assert "elevenlabs-narrator" in presets


def test_get_elevenlabs_preset_resolves_to_voice_id():
    preset = get_dubbing_preset("elevenlabs-multilingual-female")
    assert preset.provider == "elevenlabs"
    assert preset.model == "eleven_multilingual_v2"
    # Rachel's voice id
    assert preset.voice == "21m00Tcm4TlvDq8ikWAM"


def test_normalize_elevenlabs_short_alias():
    assert normalize_dubbing_voice("elevenlabs", "eleven_multilingual_v2", "rachel") == "21m00Tcm4TlvDq8ikWAM"
    assert normalize_dubbing_voice("elevenlabs", "eleven_multilingual_v2", "Adam") == "pNInz6obpgDQGcFmaJgB"


def test_normalize_elevenlabs_full_descriptive_name():
    voice = normalize_dubbing_voice(
        "elevenlabs",
        "eleven_multilingual_v2",
        "Roger - Laid-Back Casual Resonant",
    )
    assert voice == "CwhRBWXzGAHq8TQ4Fs17"


def test_normalize_elevenlabs_raw_voice_id_passthrough():
    # A voice id not in the static catalog (e.g. a cloned voice) is passed through.
    raw = "ClOnEdVoIcE123456"
    assert normalize_dubbing_voice("elevenlabs", "eleven_multilingual_v2", raw) == raw


def test_validate_elevenlabs_alias_and_raw_id():
    assert validate_dubbing_voice("elevenlabs", "rachel") is None
    assert validate_dubbing_voice("elevenlabs", "21m00Tcm4TlvDq8ikWAM") is None
    # A raw opaque token (cloned/library voice) is accepted.
    assert validate_dubbing_voice("elevenlabs", "AbCd1234EFGH") is None


def test_validate_elevenlabs_rejects_unknown_descriptive_name():
    error = validate_dubbing_voice("elevenlabs", "Some Made Up Name")
    assert error is not None
    assert "ElevenLabs voice" in error


def test_elevenlabs_voice_options_returns_catalog():
    options = elevenlabs_voice_options()
    assert len(options) > 0
    aliases = {v.alias for v in options}
    assert "rachel" in aliases
    assert "roger" in aliases
    # Every entry has a voice_id and a name.
    for v in options:
        assert v.voice_id
        assert v.name
