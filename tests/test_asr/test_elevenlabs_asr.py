"""ElevenLabs Scribe 云端转录渠道的单元测试。

全部离线：HTTP 层被 monkeypatch 掉，不消耗真实额度。
"""

from pathlib import Path

import pytest
import requests

from videocaptioner.core.asr import elevenlabs_asr as el
from videocaptioner.core.asr.elevenlabs_asr import (
    DEFAULT_BASE_URL,
    ElevenLabsASR,
    ElevenLabsASRError,
    add_inferred_spacing,
    build_speech_to_text_url,
    check_elevenlabs_asr_connection,
    group_words_into_lines,
    join_word_texts,
    map_elevenlabs_words,
    normalize_base_url,
    normalize_language,
)
from videocaptioner.core.entities import (
    TranscribeConfig,
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
)

AUDIO_FIXTURE = Path(__file__).parent.parent / "fixtures" / "audio" / "zh.mp3"


class FakeResponse:
    """最小化的 requests.Response 替身。"""

    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


SCRIBE_PAYLOAD = {
    "language_code": "zh",
    "text": "你好世界",
    "words": [
        {"text": "你好", "start": 0.0, "end": 0.5, "type": "word"},
        {"text": "世界", "start": 0.6, "end": 1.1, "type": "word"},
        {"text": "。", "start": 1.1, "end": 1.2, "type": "word"},
    ],
}


def _asr(**kwargs) -> ElevenLabsASR:
    params = {
        "audio_input": str(AUDIO_FIXTURE),
        "api_key": "key-one",
        "model": "scribe_v2",
        "need_word_time_stamp": True,
        "use_cache": False,
    }
    params.update(kwargs)
    return ElevenLabsASR(**params)


# --------------------------------------------------------------------- 纯函数


class TestBaseUrlHandling:
    def test_empty_falls_back_to_official_endpoint(self):
        assert normalize_base_url("") == DEFAULT_BASE_URL
        assert normalize_base_url(None) == DEFAULT_BASE_URL

    def test_strips_endpoint_and_v1_suffix(self):
        assert (
            normalize_base_url("https://api.elevenlabs.io/v1/") == DEFAULT_BASE_URL
        )
        assert (
            normalize_base_url("https://api.elevenlabs.io/v1/speech-to-text")
            == DEFAULT_BASE_URL
        )

    def test_rejects_non_http_values(self):
        assert normalize_base_url("api.elevenlabs.io") == DEFAULT_BASE_URL
        assert normalize_base_url("ftp://example.com") == DEFAULT_BASE_URL

    def test_keeps_custom_gateway(self):
        assert normalize_base_url("https://gateway.local/proxy") == (
            "https://gateway.local/proxy"
        )

    def test_build_url(self):
        assert build_speech_to_text_url("") == f"{DEFAULT_BASE_URL}/v1/speech-to-text"
        assert (
            build_speech_to_text_url("https://gateway.local/")
            == "https://gateway.local/v1/speech-to-text"
        )


class TestNormalizeLanguage:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("zh", "zh"),
            ("EN", "en"),
            ("zh-Hans", "zh"),
            ("zh_CN", "zh"),
            ("yue", "yue"),
            ("auto", ""),
            ("", ""),
            (None, ""),
            # 带地区/书写系统后缀时只保留主语言；非语言代码原样透传，由 API 报 422
            ("not-a-language", "not"),
            ("zhongwen", ""),
        ],
    )
    def test_values(self, raw, expected):
        assert normalize_language(raw) == expected


class TestWordMapping:
    def test_spacing_becomes_leading_space_of_next_word(self):
        words = map_elevenlabs_words(
            [
                {"text": "Hello", "start": 0, "end": 0.4, "type": "word"},
                {"text": " ", "start": 0.4, "end": 0.4, "type": "spacing"},
                {"text": "world", "start": 0.4, "end": 0.9, "type": "word"},
            ]
        )
        assert [w["word"] for w in words] == ["Hello", " world"]

    def test_audio_events_are_dropped(self):
        words = map_elevenlabs_words(
            [
                {"text": "hi", "start": 0, "end": 0.2, "type": "word"},
                {"text": "(laughter)", "start": 0.2, "end": 0.4, "type": "audio_event"},
            ]
        )
        assert [w["word"] for w in words] == ["hi"]

    def test_invalid_timestamps_dropped_and_spacing_not_leaked(self):
        words = map_elevenlabs_words(
            [
                {"text": "你", "start": 0, "end": 0.1, "type": "word"},
                {"text": " ", "start": 0.1, "end": 0.1, "type": "spacing"},
                {"text": "bad", "start": None, "end": 0.2, "type": "word"},
                {"text": "好", "start": 0.3, "end": 0.4, "type": "word"},
            ]
        )
        # "bad" 被丢弃后，它前面的 spacing 不能泄漏到 "好" 上。
        assert [w["word"] for w in words] == ["你", "好"]

    def test_missing_type_kept_when_text_and_time_present(self):
        words = map_elevenlabs_words([{"text": "ok", "start": 1, "end": 2}])
        assert words == [{"word": "ok", "start": 1.0, "end": 2.0}]

    def test_non_list_payload(self):
        assert map_elevenlabs_words(None) == []
        assert map_elevenlabs_words({"text": "x"}) == []

    def test_spacing_inferred_for_ascii_pairs(self):
        words = add_inferred_spacing(
            [
                {"word": "Hello", "start": 0, "end": 1},
                {"word": "world", "start": 1, "end": 2},
            ]
        )
        assert join_word_texts(words) == "Hello world"

    def test_no_space_inserted_for_cjk(self):
        words = add_inferred_spacing(
            [
                {"word": "你好", "start": 0, "end": 1},
                {"word": "世界", "start": 1, "end": 2},
            ]
        )
        assert join_word_texts(words) == "你好世界"

    def test_space_inserted_after_ascii_punctuation(self):
        words = add_inferred_spacing(
            [
                {"word": "Hello,", "start": 0, "end": 1},
                {"word": "world", "start": 1, "end": 2},
            ]
        )
        assert join_word_texts(words) == "Hello, world"


class TestSentenceGrouping:
    def test_break_on_strong_punctuation(self):
        lines = group_words_into_lines(
            [
                {"word": "你好", "start": 0.0, "end": 0.5},
                {"word": "世界。", "start": 0.5, "end": 1.0},
                {"word": "再见", "start": 1.05, "end": 1.5},
            ]
        )
        assert [line["text"] for line in lines] == ["你好世界。", "再见"]

    def test_break_on_pause(self):
        lines = group_words_into_lines(
            [
                {"word": "one", "start": 0.0, "end": 0.5},
                {"word": "two", "start": 0.6, "end": 1.0},
                {"word": "three", "start": 2.0, "end": 2.4},
            ],
            gap_ms=500,
        )
        assert [line["text"] for line in lines] == ["one two", "three"]

    def test_break_on_max_chars(self):
        words = [
            {"word": f"w{i}", "start": i, "end": i + 0.9} for i in range(12)
        ]
        lines = group_words_into_lines(words, max_chars=8)
        assert len(lines) > 1
        # 长度边界在「追加完整个词之后」判定，所以一行最多超出一个最长的词加一个空格。
        assert max(len(line["text"]) for line in lines) <= 8 + 3 + 1
        assert all(len(line["text"].split()) <= 4 for line in lines)

    def test_break_on_max_words(self):
        words = [
            {"word": f"w{i}", "start": i, "end": i + 0.9} for i in range(10)
        ]
        lines = group_words_into_lines(words, max_words=3, max_chars=999)
        assert len(lines) == 4

    def test_timestamps_come_from_group_edges(self):
        lines = group_words_into_lines(
            [
                {"word": "a", "start": 1.0, "end": 1.5},
                {"word": "b", "start": 1.5, "end": 2.0},
                {"word": "c", "start": 3.0, "end": 3.5},
            ],
            gap_ms=500,
        )
        assert lines[0]["start"] == 1.0 and lines[0]["end"] == 2.0
        assert lines[1]["start"] == 3.0 and lines[1]["end"] == 3.5

    def test_empty_input(self):
        assert group_words_into_lines([]) == []


# --------------------------------------------------------------------- 实例行为


class TestSegmentBuilding:
    def test_word_level_segments(self):
        asr = _asr(need_word_time_stamp=True)
        segments = asr._make_segments(SCRIBE_PAYLOAD)
        assert [seg.text for seg in segments] == ["你好", "世界", "。"]
        assert segments[0].start_time == 0
        assert segments[0].end_time == 500

    def test_sentence_level_segments_when_words_not_needed(self):
        asr = _asr(need_word_time_stamp=False)
        segments = asr._make_segments(SCRIBE_PAYLOAD)
        assert len(segments) == 1
        assert segments[0].text == "你好世界。"
        assert segments[0].start_time == 0
        assert segments[0].end_time == 1200

    def test_falls_back_to_single_segment_without_words(self):
        asr = _asr(need_word_time_stamp=True)
        segments = asr._make_segments({"text": "只有整段文本", "words": []})
        assert len(segments) == 1
        assert segments[0].text == "只有整段文本"
        assert segments[0].end_time == int(asr.audio_duration * 1000)

    def test_empty_payload_yields_no_segments(self):
        asr = _asr()
        assert asr._make_segments({"text": "", "words": []}) == []

    def test_cache_key_ignores_api_key(self):
        first = _asr(api_key="secret-a")
        second = _asr(api_key="secret-b")
        assert first._get_key() == second._get_key()
        assert "secret" not in first._get_key()


class TestApiKeyValidation:
    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="API key"):
            _asr(api_key="")

    def test_key_string_is_parsed_into_multiple_keys(self):
        asr = _asr(api_key="k1, k2\nk3;k4")
        assert asr.api_keys == ["k1", "k2", "k3", "k4"]


class TestMultiKeyRotation:
    def test_second_key_used_when_first_is_unauthorized(self, monkeypatch):
        calls: list[str] = []

        def fake_post(self, api_key):
            calls.append(api_key)
            if api_key == "bad":
                raise ElevenLabsASRError(
                    "HTTP 401", status_code=401, retriable=False
                )
            return SCRIBE_PAYLOAD

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        asr = _asr(api_key="bad,good")
        # 让轮询从第一个 key 开始，保证测试确定性
        monkeypatch.setattr(asr, "_rotated_keys", lambda: ["bad", "good"])

        data = asr._submit()
        assert data is SCRIBE_PAYLOAD
        assert calls == ["bad", "good"]

    def test_all_keys_failed_raises_with_count(self, monkeypatch):
        def fake_post(self, api_key):
            raise ElevenLabsASRError("HTTP 401", status_code=401)

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        asr = _asr(api_key="k1,k2")
        with pytest.raises(RuntimeError, match="All 2 ElevenLabs API keys failed"):
            asr._submit()

    def test_rate_limit_retries_same_key(self, monkeypatch):
        calls: list[str] = []
        sleeps: list[float] = []

        def fake_post(self, api_key):
            calls.append(api_key)
            if len(calls) == 1:
                raise ElevenLabsASRError(
                    "HTTP 429", status_code=429, retriable=True, retry_after=0.01
                )
            return SCRIBE_PAYLOAD

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        monkeypatch.setattr(el.time, "sleep", lambda seconds: sleeps.append(seconds))
        asr = _asr(api_key="only-key")

        assert asr._submit() is SCRIBE_PAYLOAD
        assert calls == ["only-key", "only-key"]
        assert sleeps == [0.01]

    def test_non_rate_limit_error_switches_key_without_retry(self, monkeypatch):
        calls: list[str] = []

        def fake_post(self, api_key):
            calls.append(api_key)
            if api_key == "k1":
                raise ElevenLabsASRError("HTTP 500", status_code=500)
            return SCRIBE_PAYLOAD

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        asr = _asr(api_key="k1,k2")
        monkeypatch.setattr(asr, "_rotated_keys", lambda: ["k1", "k2"])

        asr._submit()
        assert calls == ["k1", "k2"]

    def test_unexpected_exception_also_rotates(self, monkeypatch):
        calls: list[str] = []

        def fake_post(self, api_key):
            calls.append(api_key)
            if api_key == "k1":
                raise ValueError("boom")
            return SCRIBE_PAYLOAD

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        asr = _asr(api_key="k1,k2")
        monkeypatch.setattr(asr, "_rotated_keys", lambda: ["k1", "k2"])

        assert asr._submit() is SCRIBE_PAYLOAD
        assert calls == ["k1", "k2"]

    def test_rotation_cursor_is_shared_between_instances(self, monkeypatch):
        """ChunkedASR 为每个分块新建实例，游标必须跨实例推进。"""
        returned: list[list[str]] = []

        def fake_post(self, api_key):
            return SCRIBE_PAYLOAD

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        monkeypatch.setattr(
            ElevenLabsASR,
            "_submit",
            lambda self, callback=None: returned.append(self._rotated_keys())
            or SCRIBE_PAYLOAD,
        )

        el._key_cursors.clear()
        first = _asr(api_key="a,b,c")
        second = _asr(api_key="a,b,c")
        first._submit()
        second._submit()

        assert returned[0][0] == "a"
        assert returned[1][0] == "b"


class TestHttpLayer:
    def test_successful_response_returned(self, monkeypatch):
        captured: dict = {}

        def fake_post(url, headers=None, files=None, data=None, timeout=None):
            captured.update(
                url=url, headers=headers, files=files, data=data, timeout=timeout
            )
            return FakeResponse(200, SCRIBE_PAYLOAD)

        monkeypatch.setattr(el.requests, "post", fake_post)
        asr = _asr(api_key="k1", language="zh")
        payload = asr._post_once("k1")

        assert payload == SCRIBE_PAYLOAD
        assert captured["url"] == f"{DEFAULT_BASE_URL}/v1/speech-to-text"
        assert captured["headers"] == {"xi-api-key": "k1"}
        assert captured["data"]["model_id"] == "scribe_v2"
        assert captured["data"]["timestamps_granularity"] == "word"
        assert captured["data"]["tag_audio_events"] == "false"
        assert captured["data"]["language_code"] == "zh"
        assert captured["files"]["file"][0].endswith(".mp3")

    def test_http_error_carries_status(self, monkeypatch):
        monkeypatch.setattr(
            el.requests,
            "post",
            lambda *a, **kw: FakeResponse(422, None, text="bad model"),
        )
        asr = _asr(api_key="k1")
        with pytest.raises(ElevenLabsASRError) as excinfo:
            asr._post_once("k1")
        assert excinfo.value.status_code == 422
        assert excinfo.value.retriable is False

    def test_429_is_retriable_with_retry_after(self, monkeypatch):
        monkeypatch.setattr(
            el.requests,
            "post",
            lambda *a, **kw: FakeResponse(
                429, None, text="slow down", headers={"retry-after": "7"}
            ),
        )
        asr = _asr(api_key="k1")
        with pytest.raises(ElevenLabsASRError) as excinfo:
            asr._post_once("k1")
        assert excinfo.value.retriable is True
        assert excinfo.value.retry_after == 7.0

    def test_timeout_is_retriable(self, monkeypatch):
        def fake_post(*args, **kwargs):
            raise requests.Timeout("timed out")

        monkeypatch.setattr(el.requests, "post", fake_post)
        asr = _asr(api_key="k1")
        with pytest.raises(ElevenLabsASRError) as excinfo:
            asr._post_once("k1")
        assert excinfo.value.retriable is True

    def test_network_error_is_retriable(self, monkeypatch):
        def fake_post(*args, **kwargs):
            raise requests.ConnectionError("no route")

        monkeypatch.setattr(el.requests, "post", fake_post)
        asr = _asr(api_key="k1")
        with pytest.raises(ElevenLabsASRError) as excinfo:
            asr._post_once("k1")
        assert excinfo.value.retriable is True

    def test_non_json_body_raises(self, monkeypatch):
        monkeypatch.setattr(
            el.requests, "post", lambda *a, **kw: FakeResponse(200, None, text="<html>")
        )
        asr = _asr(api_key="k1")
        with pytest.raises(ElevenLabsASRError, match="non-JSON"):
            asr._post_once("k1")


class TestFriendlyErrors:
    @pytest.mark.parametrize(
        "status,needle",
        [
            (401, "无效或未授权"),
            (403, "无效或未授权"),
            (402, "额度"),
            (429, "限流"),
            (422, "拒绝了请求"),
        ],
    )
    def test_status_messages(self, status, needle):
        message = el._friendly_error(ElevenLabsASRError("x", status_code=status))
        assert needle in message

    def test_unknown_error(self):
        assert "boom" in el._friendly_error(RuntimeError("boom"))


# --------------------------------------------------------------------- 端到端


class TestTranscribePipeline:
    def test_transcribe_uses_elevenlabs_channel(self, monkeypatch):
        """transcribe() 应走 ElevenLabs 渠道并把返回结果交给调用方。"""
        from videocaptioner.core.asr import transcribe

        monkeypatch.setattr(ElevenLabsASR, "_post_once", lambda self, key: SCRIBE_PAYLOAD)

        config = TranscribeConfig(
            transcribe_model=TranscribeModelEnum.ELEVENLABS,
            transcribe_language="zh",
            need_word_time_stamp=False,
            output_format=TranscribeOutputFormatEnum.SRT,
            elevenlabs_api_key="k1,k2",
            elevenlabs_model="scribe_v2",
        )

        progress: list[tuple[int, str]] = []
        result = transcribe(
            str(AUDIO_FIXTURE),
            config,
            callback=lambda pct, msg: progress.append((pct, msg)),
        )

        assert [seg.text for seg in result.segments] == ["你好世界。"]
        assert progress, "应至少上报一次进度"

    def test_missing_key_surfaces_runtime_error(self, monkeypatch):
        from videocaptioner.core.asr import transcribe

        config = TranscribeConfig(
            transcribe_model=TranscribeModelEnum.ELEVENLABS,
            transcribe_language="zh",
            need_word_time_stamp=False,
            elevenlabs_api_key="",
        )
        with pytest.raises(ValueError, match="API key"):
            transcribe(str(AUDIO_FIXTURE), config)


class TestConnectionCheck:
    def test_missing_key_reports_failure(self):
        ok, message = check_elevenlabs_asr_connection("", "", "scribe_v2")
        assert ok is False
        assert "API key" in message

    def test_success_returns_transcript(self, monkeypatch):
        def fake_post(self, api_key):
            return {"text": "hello", "words": [{"text": "hello", "start": 0, "end": 1}]}

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        ok, message = check_elevenlabs_asr_connection("k1", "", "scribe_v2")
        assert ok is True
        assert "hello" in message

    def test_failure_returns_reason(self, monkeypatch):
        def fake_post(self, api_key):
            raise ElevenLabsASRError("HTTP 401", status_code=401)

        monkeypatch.setattr(ElevenLabsASR, "_post_once", fake_post)
        ok, message = check_elevenlabs_asr_connection("k1", "", "scribe_v2")
        assert ok is False
        assert "无效或未授权" in message


class TestPlatformAvailability:
    def test_channel_is_listed_for_all_platforms(self):
        from videocaptioner.core.utils.platform_utils import (
            get_available_transcribe_models,
            is_model_available,
        )

        assert TranscribeModelEnum.ELEVENLABS in get_available_transcribe_models()
        assert is_model_available(TranscribeModelEnum.ELEVENLABS) is True

    def test_language_capability_supports_auto(self):
        from videocaptioner.core.entities import get_asr_language_capability

        capability = get_asr_language_capability(TranscribeModelEnum.ELEVENLABS)
        assert capability.supports_auto is True
        assert capability.supported_languages
