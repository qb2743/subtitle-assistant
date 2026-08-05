"""Tests for the Fish Audio speech provider and dubbing wiring.

``requests.post`` is faked so no network is needed. Verifies the /v1/tts
payload, the /model voice-clone upload flow, and provider registration.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_multiple_keys_are_parsed_and_deduplicated():
    synth = FishAudioSpeechSynthesizer(_config(api_key="key-a, key-b; key-a key-c"))
    assert synth.api_keys == ["key-a", "key-b", "key-c"]


def test_paid_tier_concurrency_is_not_clamped_to_starter():
    synth = FishAudioSpeechSynthesizer(
        _config(extra={"concurrency_per_key": 15})
    )
    assert synth.concurrency_per_key == 15


def test_round_robin_rotates_starting_key(tmp_path, _install_fake_post):
    posts, _ = _install_fake_post
    synth = FishAudioSpeechSynthesizer(_config(api_key="key-a,key-b,key-c"))

    key_indices = []
    for index in range(4):
        result = synth.synthesize(
            SynthesisRequest(text="hi", output_path=str(tmp_path / f"{index}.wav"))
        )
        key_indices.append(result.provider_metadata["api_key_index"])

    assert [post["headers"]["Authorization"] for post in posts] == [
        "Bearer key-a",
        "Bearer key-b",
        "Bearer key-c",
        "Bearer key-a",
    ]
    assert key_indices == [0, 1, 2, 0]


def test_private_voice_stays_on_first_key_but_shared_voice_rotates(
    tmp_path,
    _install_fake_post,
):
    posts, _ = _install_fake_post
    private_synth = FishAudioSpeechSynthesizer(
        _config(api_key="key-a,key-b", default_voice="private-voice")
    )
    for index in range(2):
        private_synth.synthesize(
            SynthesisRequest(
                text="hi",
                output_path=str(tmp_path / f"private-{index}.wav"),
            )
        )

    shared_synth = FishAudioSpeechSynthesizer(
        _config(
            api_key="key-a,key-b",
            default_voice="public-voice",
            extra={"shared_voice_ids": ["public-voice"]},
        )
    )
    for index in range(2):
        shared_synth.synthesize(
            SynthesisRequest(
                text="hi",
                output_path=str(tmp_path / f"public-{index}.wav"),
            )
        )

    assert [post["headers"]["Authorization"] for post in posts] == [
        "Bearer key-a",
        "Bearer key-a",
        "Bearer key-a",
        "Bearer key-b",
    ]


def test_auth_error_switches_to_next_key(tmp_path, _install_fake_post):
    posts, responses = _install_fake_post
    responses.extend(
        [
            _FakeResponse(status=401),
            _FakeResponse(content=b"working-key"),
        ]
    )
    synth = FishAudioSpeechSynthesizer(_config(api_key="bad,good"))

    result = synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))

    assert [post["headers"]["Authorization"] for post in posts] == [
        "Bearer bad",
        "Bearer good",
    ]
    assert Path(result.output_path).read_bytes() == b"working-key"
    assert result.provider_metadata["api_key_index"] == 1


def test_rate_limit_retries_same_key_with_backoff(
    tmp_path,
    _install_fake_post,
    monkeypatch,
):
    posts, responses = _install_fake_post
    responses.extend(
        [
            _FakeResponse(status=429, headers={"Retry-After": "2"}),
            _FakeResponse(content=b"after-backoff"),
        ]
    )
    sleeps = []
    monkeypatch.setattr(providers_module.time, "sleep", sleeps.append)
    synth = FishAudioSpeechSynthesizer(_config(api_key="key-a,key-b"))

    result = synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))

    assert [post["headers"]["Authorization"] for post in posts] == [
        "Bearer key-a",
        "Bearer key-a",
    ]
    assert sleeps == [2.0]
    assert Path(result.output_path).read_bytes() == b"after-backoff"


@pytest.mark.parametrize("failure", ["server", "network"])
def test_transient_failure_retries_same_key(
    tmp_path,
    monkeypatch,
    failure,
):
    posts = []

    def post(url, **kwargs):
        posts.append({"url": url, **kwargs})
        if len(posts) == 1:
            if failure == "server":
                return _FakeResponse(status=503)
            raise providers_module.requests.Timeout("timed out")
        return _FakeResponse(content=b"recovered")

    sleeps = []
    monkeypatch.setattr(providers_module.requests, "post", post)
    monkeypatch.setattr(providers_module.time, "sleep", sleeps.append)
    synth = FishAudioSpeechSynthesizer(_config(api_key="key-a,key-b"))

    result = synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))

    assert [post["headers"]["Authorization"] for post in posts] == [
        "Bearer key-a",
        "Bearer key-a",
    ]
    assert sleeps == [1.0]
    assert Path(result.output_path).read_bytes() == b"recovered"


def test_all_keys_fail_with_clear_error(tmp_path, _install_fake_post):
    posts, responses = _install_fake_post
    responses.extend([_FakeResponse(status=401), _FakeResponse(status=403)])
    synth = FishAudioSpeechSynthesizer(_config(api_key="key-a,key-b"))

    with pytest.raises(
        RuntimeError,
        match="All 2 Fish Audio API keys failed",
    ) as exc_info:
        synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))

    authorizations = [post["headers"]["Authorization"] for post in posts]
    assert authorizations == ["Bearer key-a", "Bearer key-b"]
    assert all("," not in authorization for authorization in authorizations)
    assert "key-a" not in str(exc_info.value)
    assert "key-b" not in str(exc_info.value)


def test_empty_audio_error_is_not_reported_as_http_200(
    tmp_path,
    _install_fake_post,
):
    _, responses = _install_fake_post
    responses.append(_FakeResponse(content=b""))
    synth = FishAudioSpeechSynthesizer(_config())

    with pytest.raises(RuntimeError, match="empty audio body") as exc_info:
        synth.synthesize(SynthesisRequest(text="hi", output_path=str(tmp_path / "line.wav")))

    assert "HTTP 200" not in str(exc_info.value)


def test_each_key_has_its_own_five_request_concurrency_limit(
    tmp_path,
    monkeypatch,
):
    lock = threading.Lock()
    first_wave = threading.Barrier(10)
    in_flight = {"key-a": 0, "key-b": 0}
    max_in_flight = {"key-a": 0, "key-b": 0}

    def post(_url, **kwargs):
        key = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        with lock:
            in_flight[key] += 1
            max_in_flight[key] = max(max_in_flight[key], in_flight[key])
        try:
            try:
                first_wave.wait(timeout=3)
            except threading.BrokenBarrierError:
                pass
            return _FakeResponse()
        finally:
            with lock:
                in_flight[key] -= 1

    monkeypatch.setattr(providers_module.requests, "post", post)
    synth = FishAudioSpeechSynthesizer(
        _config(
            api_key="key-a,key-b",
            extra={"concurrency_per_key": 5},
        )
    )

    def synthesize(index):
        return synth.synthesize(
            SynthesisRequest(
                text=f"line {index}",
                output_path=str(tmp_path / f"line-{index}.wav"),
            )
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(synthesize, range(12)))

    assert len(results) == 12
    assert max_in_flight == {"key-a": 5, "key-b": 5}


def test_failed_key_fallback_still_respects_working_key_limit(tmp_path, monkeypatch):
    lock = threading.Lock()
    release = threading.Event()
    good_in_flight = 0
    good_peak = 0

    def post(_url, **kwargs):
        nonlocal good_in_flight, good_peak
        key = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        if key == "bad":
            return _FakeResponse(status=401)
        with lock:
            good_in_flight += 1
            good_peak = max(good_peak, good_in_flight)
            if good_in_flight == 5:
                release.set()
        try:
            release.wait(timeout=3)
            return _FakeResponse()
        finally:
            with lock:
                good_in_flight -= 1

    monkeypatch.setattr(providers_module.requests, "post", post)
    synth = FishAudioSpeechSynthesizer(
        _config(api_key="bad,good", extra={"concurrency_per_key": 5})
    )

    def synthesize(index):
        return synth.synthesize(
            SynthesisRequest(
                text=f"line {index}",
                output_path=str(tmp_path / f"fallback-{index}.wav"),
            )
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(synthesize, range(12)))

    assert len(results) == 12
    assert good_peak == 5


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


def test_voice_clone_stays_on_first_account_key(tmp_path, _install_fake_post):
    posts, responses = _install_fake_post
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref-audio")
    responses.extend(
        [
            _FakeResponse(json_data={"_id": "model_private"}),
            _FakeResponse(content=b"cloned"),
        ]
    )
    synth = FishAudioSpeechSynthesizer(_config(api_key="account-a,account-b"))

    synth.synthesize(
        SynthesisRequest(
            text="clone me",
            output_path=str(tmp_path / "out.wav"),
            clone_audio_path=str(ref),
            clone_audio_text="reference transcript",
        )
    )

    assert [post["headers"]["Authorization"] for post in posts] == [
        "Bearer account-a",
        "Bearer account-a",
    ]


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


def test_voice_clone_cache_is_scoped_to_key_and_api_base(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref-audio")
    transcript = "reference transcript"
    first = FishAudioSpeechSynthesizer(_config(api_key="key-a", base_url="https://api.fish.audio"))
    other_key = FishAudioSpeechSynthesizer(
        _config(api_key="key-b", base_url="https://api.fish.audio")
    )
    other_base = FishAudioSpeechSynthesizer(
        _config(api_key="key-a", base_url="https://fish.example.test")
    )

    cache_keys = {
        first._voice_cache_key(ref, transcript, first.api_keys[0]),
        other_key._voice_cache_key(ref, transcript, other_key.api_keys[0]),
        other_base._voice_cache_key(ref, transcript, other_base.api_keys[0]),
    }

    assert len(cache_keys) == 3


def test_concurrent_voice_clone_uploads_reference_once(
    tmp_path,
    _install_fake_post,
):
    posts, responses = _install_fake_post
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"ref-audio")
    responses.append(_FakeResponse(json_data={"_id": "model_shared"}))
    responses.extend(_FakeResponse(content=b"audio") for _ in range(6))
    synth = FishAudioSpeechSynthesizer(_config(default_voice=""))

    def synthesize(index):
        return synth.synthesize(
            SynthesisRequest(
                text=f"line {index}",
                output_path=str(tmp_path / f"{index}.wav"),
                clone_audio_path=str(ref),
                clone_audio_text="reference transcript",
            )
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(synthesize, range(6)))

    assert len(results) == 6
    assert len([post for post in posts if post["url"].endswith("/model")]) == 1
    assert len([post for post in posts if post["url"].endswith("/v1/tts")]) == 6


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
