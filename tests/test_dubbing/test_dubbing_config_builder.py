import math

from videocaptioner.core.entities import TranscribeLanguageEnum
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.dubbing_config_builder import (
    create_dubbing_config_from_cfg,
    diarization_language_from_transcribe,
    parse_speaker_voice_maps,
    speaker_voice_map_for_provider,
    update_speaker_voice_map,
)


def test_local_provider_uses_clone_and_local_url(monkeypatch, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"fake")
    monkeypatch.setattr(cfg.dubbing_provider, "value", "dots")
    monkeypatch.setattr(cfg.dubbing_dots_url, "value", "http://127.0.0.1:7861")
    monkeypatch.setattr(cfg.dubbing_dots_start_script, "value", "D:/AI/dots/start.ps1")
    monkeypatch.setattr(cfg.dubbing_clone_audio_path, "value", str(ref))
    monkeypatch.setattr(cfg.dubbing_clone_audio_text, "value", "参考文本")

    config = create_dubbing_config_from_cfg()

    assert config.provider == "dots"
    assert config.base_url == "http://127.0.0.1:7861"
    assert config.model == "dots-tts"
    assert config.clone_audio_path == str(ref)
    assert config.clone_audio_text == "参考文本"
    assert config.extra["start_script"] == "D:/AI/dots/start.ps1"


def test_non_local_provider_does_not_forward_saved_clone(monkeypatch, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"fake")
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_voice, "value", "zh-CN-XiaoxiaoNeural")
    monkeypatch.setattr(cfg.dubbing_clone_audio_path, "value", str(ref))
    monkeypatch.setattr(cfg.dubbing_clone_audio_text, "value", "参考文本")

    config = create_dubbing_config_from_cfg()

    assert config.provider == "edge"
    assert config.clone_audio_path == ""
    assert config.clone_audio_text == ""


def test_speaker_settings_are_forwarded(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_enable_diarization, "value", True)
    monkeypatch.setattr(cfg.dubbing_speaker_count, "value", 3)
    monkeypatch.setattr(cfg.dubbing_narrator_only, "value", True)
    monkeypatch.setattr(cfg.dubbing_narrator_llm_review, "value", True)

    config = create_dubbing_config_from_cfg()

    assert config.enable_diarization is True
    assert config.speaker_count == 3
    assert config.narrator_only is True
    assert config.narrator_llm_review is True


def test_speaker_voice_maps_are_provider_scoped():
    raw = update_speaker_voice_map(
        '{"gemini": {"spk0": "Kore"}}',
        "edge",
        {"spk0": "zh-CN-XiaoxiaoNeural", "spk1": ""},
    )

    assert parse_speaker_voice_maps(raw) == {
        "edge": {"spk0": "zh-CN-XiaoxiaoNeural"},
        "gemini": {"spk0": "Kore"},
    }
    assert speaker_voice_map_for_provider(raw, "EDGE") == {
        "spk0": "zh-CN-XiaoxiaoNeural"
    }
    assert parse_speaker_voice_maps("not-json") == {}


def test_current_provider_speaker_voices_become_profiles(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_model, "value", "edge-tts")
    monkeypatch.setattr(cfg.dubbing_narrator_only, "value", False)
    monkeypatch.setattr(
        cfg.dubbing_speaker_voice_map,
        "value",
        '{"edge": {"spk0": "zh-CN-XiaoxiaoNeural"}, '
        '"gemini": {"spk0": "Kore"}}',
    )

    config = create_dubbing_config_from_cfg()

    assert set(config.speaker_profiles) == {"spk0"}
    assert config.speaker_profiles["spk0"].voice == "zh-CN-XiaoxiaoNeural"


def test_narrator_only_ignores_hidden_role_voice_mapping(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_model, "value", "edge-tts")
    monkeypatch.setattr(cfg.dubbing_voice, "value", "zh-CN-XiaoxiaoNeural")
    monkeypatch.setattr(cfg.dubbing_narrator_only, "value", True)
    monkeypatch.setattr(
        cfg.dubbing_speaker_voice_map,
        "value",
        '{"edge": {"spk0": "zh-CN-YunxiNeural"}}',
    )

    config = create_dubbing_config_from_cfg()

    assert config.voice == "zh-CN-XiaoxiaoNeural"
    assert config.speaker_profiles == {}


def test_gui_dubbing_uses_configured_gain(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_dubbed_audio_gain_db, "value", -6)

    config = create_dubbing_config_from_cfg()

    assert math.isclose(20 * math.log10(config.dubbed_audio_volume), -6.0)


def test_provider_rejects_other_provider_model(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "fishaudio")
    monkeypatch.setattr(cfg.dubbing_model, "value", "eleven_v3")

    config = create_dubbing_config_from_cfg()

    assert config.model == "s2.1-pro"


def test_subtitle_style_settings_are_forwarded(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.use_subtitle_style, "value", True)
    monkeypatch.setattr(cfg.rounded_bg_font_name, "value", "Test Font")
    monkeypatch.setattr(cfg.rounded_bg_font_size, "value", 42)

    config = create_dubbing_config_from_cfg()

    assert config.subtitle_rounded_style["font_name"] == "Test Font"
    assert config.subtitle_rounded_style["font_size"] == 42


def test_hard_subtitles_use_selected_style_without_legacy_switch(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.use_subtitle_style, "value", False)
    monkeypatch.setattr(cfg.dubbing_embed_subtitle, "value", "hard")
    monkeypatch.setattr(cfg.subtitle_style_name, "value", "default")

    config = create_dubbing_config_from_cfg()

    assert "Style: Default" in config.subtitle_ass_style


def test_narrator_review_forwards_llm_and_auto_language(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_adapt_length, "value", False)
    monkeypatch.setattr(cfg.dubbing_narrator_llm_review, "value", True)
    monkeypatch.setattr(cfg.transcribe_language, "value", type("Lang", (), {"name": "AUTO"})())

    config = create_dubbing_config_from_cfg()

    assert config.narrator_llm_review is True
    assert config.llm_model
    assert config.diarization_language == "auto"


def test_transcribe_language_selects_matching_speaker_model():
    assert diarization_language_from_transcribe(TranscribeLanguageEnum.CHINESE) == "zh"
    assert diarization_language_from_transcribe(TranscribeLanguageEnum.YUE) == "zh"
    assert diarization_language_from_transcribe(TranscribeLanguageEnum.ENGLISH) == "en"
    assert diarization_language_from_transcribe(TranscribeLanguageEnum.AUTO) == "auto"
    assert diarization_language_from_transcribe(TranscribeLanguageEnum.JAPANESE) == "multi"
    assert diarization_language_from_transcribe(TranscribeLanguageEnum.ARABIC) == "multi"
