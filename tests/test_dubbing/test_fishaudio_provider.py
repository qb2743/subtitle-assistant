"""Tests for the Fish Audio speech provider and dubbing wiring.

``requests.post`` is faked so no network is needed. Verifies the /v1/tts
payload, the /model voice-clone upload flow, and provider registration.
"""

from pathlib import Path

import pytest

import videocaptioner.core.speech.providers as providers_module
from videocaptioner.core.speech import (
    FishAudioSpeechSynthesizer,
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)


class _FakeResponse:
    def __init__(self, *, content=b"fake-mp3", json_data=None, status=200, headers=None):
        self.content = content
        self._json = json_data
        self.status_code = status
        self.headers = headers or {"content-type": "audio/mpeg"}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json or {}


class _DictCache:
    """In-memory stand-in for diskcache to keep tests hermetic."""

    def __init__(self):
        self._d = {}

    def get(self, key):
        return self._d.get(key)

    def set(self, key, value, expire=None):
        self._d[key] = value


@pytest.fixture(autouse=True)
def _install_fake_post(monkeypatch):
    posts = []
    responses: list[_FakeResponse] = []

    def _fake_post(url, **kwargs):
        posts.append({"url": url, **kwargs})
        if responses:
            return responses.pop(0)
        return _FakeResponse()

    monkeypatch.setattr(providers_module.requests, "post", _fake_post)
    monkeypatch.setattr(providers_module, "get_tts_cache", lambda: _DictCache())
    yield posts, responses


def _config(**overrides) -> SpeechProviderConfig:
    defaults = {
        "provider": "fishaudio",
        "api_key": "fa-test",
        "model": "s1",
        "base_url": "https://api.fish.audio",
        "default_voice": "",
        "response_format": "mp3",
        "sample_rate": 32000,
        "speed": 1.0,
    }
    defaults.update(overrides)
    return SpeechProviderConfig(**defaults)


def test_factory_returns_fishaudio_synthesizer():
    synth = create_speech_synthesizer(_config())
    assert isinstance(synth, FishAudioSpeechSynthesizer)


def test_missing_api_key_raises():
    with pytest.raises(ValueError):
        FishAudioSpeechSynthesizer(_config(api_key=""))


def test_synthesize_posts_correct_payload_and_writes_audio(tmp_path, _install_fake_post):
    posts, _ = _install_fake_post
    synth = FishAudioSpeechSynthesizer(_config(default_voice="abc123", speed=1.5))
    result = synth.synthesize(
        SynthesisRequest(text="hello world", output_path=str(tmp_path / "line.wav"))
    )
    assert result.output_path.endswith(".mp3")
    assert Path(result.output_path).read_bytes() == b"fake-mp3"
    assert result.voice == "abc123"
    assert result.format == "mp3"

    assert len(posts) == 1
    post = posts[0]
    assert post["url"] == "https://api.fish.audio/v1/tts"
    assert post["headers"]["Authorization"] == "Bearer fa-test"
    # model is an HTTP header (per Fish Audio API), never a body field
    assert post["headers"]["model"] == "s1"
    body = post["json"]
    assert body["text"] == "hello world"
    assert body["reference_id"] == "abc123"
    assert body["format"] == "mp3"
    assert body["prosody"] == {"speed": 1.5}
    assert "model" not in body
    assert "streaming" not in body


def test_synthesize_uses_base_model_when_no_voice(tmp_path, _install_fake_post):
    posts, _ = _install_fake_post
    synth = FishAudioSpeechSynthesizer(_config(default_voice="", model="s1"))
    synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "x.wav")))
    body = posts[0]["json"]
    assert "reference_id" not in body
    # no reference_id -> model header still required and sent
    assert posts[0]["headers"]["model"] == "s1"
    assert "model" not in body


def test_voice_clone_uploads_then_uses_reference_id(tmp_path, _install_fake_post):
    posts, responses = _install_fake_post
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref-audio")

    # First call: POST /model returns a model _id; second: /v1/tts audio.
    responses.append(_FakeResponse(json_data={"_id": "model_abc"}))
    responses.append(_FakeResponse(content=b"cloned-mp3"))

    synth = FishAudioSpeechSynthesizer(_config(default_voice=""))
    result = synth.synthesize(
        SynthesisRequest(
            text="clone me",
            output_path=str(tmp_path / "out.wav"),
            clone_audio_path=str(ref),
            clone_audio_text="reference transcript",
        )
    )
    assert Path(result.output_path).read_bytes() == b"cloned-mp3"
    assert result.voice == "model_abc"

    assert posts[0]["url"] == "https://api.fish.audio/model"
    data = posts[0]["data"]
    assert data["type"] == "tts"
    assert data["train_mode"] == "fast"
    assert data["texts"] == "reference transcript"
    files = posts[0]["files"]
    assert "voices" in files

    assert posts[1]["url"] == "https://api.fish.audio/v1/tts"
    assert posts[1]["json"]["reference_id"] == "model_abc"


def test_voice_clone_caches_reference_id(tmp_path, _install_fake_post):
    posts, responses = _install_fake_post
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref-audio")
    responses.append(_FakeResponse(json_data={"_id": "model_cached"}))
    responses.append(_FakeResponse(content=b"first"))
    responses.append(_FakeResponse(content=b"second"))

    synth = FishAudioSpeechSynthesizer(_config(default_voice=""))
    synth.synthesize(
        SynthesisRequest(text="a", output_path=str(tmp_path / "1.wav"),
                         clone_audio_path=str(ref), clone_audio_text="t")
    )
    synth.synthesize(
        SynthesisRequest(text="b", output_path=str(tmp_path / "2.wav"),
                         clone_audio_path=str(ref), clone_audio_text="t")
    )
    # Only one /model upload; two /v1/tts calls.
    model_posts = [p for p in posts if p["url"].endswith("/model")]
    tts_posts = [p for p in posts if p["url"].endswith("/v1/tts")]
    assert len(model_posts) == 1
    assert len(tts_posts) == 2


def test_selected_voice_wins_over_leftover_clone_audio(tmp_path, _install_fake_post):
    """已选音色必须优先于残留的 clone 音频——防止 dots 残留参考音频劫持 Fish Audio。

    用户报告：从 dots 切到 Fish Audio 后，dots 配置的参考音频被带到 Fish Audio，
    导致选了默认音色却走了语音克隆。修复后已选音色优先，clone 字段被忽略。
    """
    posts, responses = _install_fake_post
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref-audio")
    # 即便请求带了 clone 字段，也只应有一次 /v1/tts，reference_id = 已选音色
    responses.append(_FakeResponse(content=b"voice-mp3"))

    synth = FishAudioSpeechSynthesizer(_config(default_voice="preset_rid"))
    result = synth.synthesize(
        SynthesisRequest(
            text="hi",
            output_path=str(tmp_path / "out.wav"),
            clone_audio_path=str(ref),
            clone_audio_text="leftover transcript",
        )
    )
    assert Path(result.output_path).read_bytes() == b"voice-mp3"
    assert result.voice == "preset_rid"
    # 不应触发 /model 上传，只有一次 /v1/tts，且 reference_id 是已选音色
    assert len(posts) == 1
    assert posts[0]["url"] == "https://api.fish.audio/v1/tts"
    assert posts[0]["json"]["reference_id"] == "preset_rid"
    assert [p for p in posts if p["url"].endswith("/model")] == []


def test_resolve_provider_accepts_fishaudio():
    from videocaptioner.cli.commands.dub import _resolve_provider

    assert _resolve_provider("fishaudio") == "fishaudio"


def test_validate_voice_accepts_opaque_id():
    from videocaptioner.core.dubbing.presets import validate_dubbing_voice

    assert validate_dubbing_voice("fishaudio", "model_abc123") is None
    assert validate_dubbing_voice("fishaudio", "") is None


def test_normalize_voice_passthrough():
    from videocaptioner.core.dubbing.presets import normalize_dubbing_voice

    assert normalize_dubbing_voice("fishaudio", "s1", "model_xyz") == "model_xyz"


def test_fishaudio_preset_voices_are_unique_and_nonempty():
    from videocaptioner.core.dubbing.presets import FISHAUDIO_PRESET_VOICES

    assert len(FISHAUDIO_PRESET_VOICES) >= 5
    names = [name for name, _ in FISHAUDIO_PRESET_VOICES]
    rids = [rid for _, rid in FISHAUDIO_PRESET_VOICES]
    assert all(names) and all(rids)
    assert len(rids) == len(set(rids)), "preset reference_ids must be unique"
