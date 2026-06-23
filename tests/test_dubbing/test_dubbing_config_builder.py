from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.dubbing_config_builder import create_dubbing_config_from_cfg


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
