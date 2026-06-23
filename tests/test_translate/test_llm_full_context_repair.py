"""Tests for full-context LLM subtitle translation and repair."""

import json
from types import SimpleNamespace

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage


class NullCache:
    def get(self, key, default=None):
        return default

    def set(self, *args, **kwargs):
        return None

    def delete(self, *args, **kwargs):
        return None


def make_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def make_translator() -> LLMTranslator:
    translator = LLMTranslator(
        thread_num=1,
        batch_num=2,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
        model="test-model",
        custom_prompt="",
        is_reflect=False,
        update_callback=None,
    )
    translator._cache = NullCache()
    return translator


def make_asr_data() -> ASRData:
    return ASRData(
        [
            ASRDataSeg(start_time=0, end_time=1000, text="I am a student"),
            ASRDataSeg(start_time=1000, end_time=2000, text="You are a teacher"),
            ASRDataSeg(
                start_time=2000,
                end_time=3000,
                text="VideoCaptioner is a tool for captioning videos",
            ),
        ]
    )


def test_full_context_sends_indexed_text_without_timestamps(monkeypatch):
    calls = []

    def fake_call_llm(*, messages, model, temperature=1, **kwargs):
        calls.append(messages)
        return make_response(
            json.dumps(
                {
                    "1": "我是学生",
                    "2": "你是老师",
                    "3": "VideoCaptioner 是视频字幕工具",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(
        "videocaptioner.core.translate.llm_translator.call_llm",
        fake_call_llm,
    )

    result = make_translator().translate_subtitle(make_asr_data())

    first_user_message = calls[0][1]["content"]
    assert "-->" not in first_user_message
    assert "00:" not in first_user_message
    assert json.loads(first_user_message) == {
        "1": "I am a student",
        "2": "You are a teacher",
        "3": "VideoCaptioner is a tool for captioning videos",
    }
    assert [seg.start_time for seg in result.segments] == [0, 1000, 2000]
    assert [seg.end_time for seg in result.segments] == [1000, 2000, 3000]


def test_error_and_untranslated_rows_are_retried(monkeypatch):
    responses = iter(
        [
            make_response(
                json.dumps(
                    {
                        "1": "我是学生",
                        "2": "ERROR",
                        "3": "VideoCaptioner is a tool for captioning videos",
                    },
                    ensure_ascii=False,
                )
            ),
            make_response("你是老师"),
            make_response("VideoCaptioner 是视频字幕工具"),
        ]
    )
    user_messages = []

    def fake_call_llm(*, messages, model, temperature=1, **kwargs):
        user_messages.append(messages[1]["content"])
        return next(responses)

    monkeypatch.setattr(
        "videocaptioner.core.translate.llm_translator.call_llm",
        fake_call_llm,
    )

    result = make_translator().translate_subtitle(make_asr_data())

    assert user_messages[0].startswith("{")
    assert user_messages[1:] == [
        "You are a teacher",
        "VideoCaptioner is a tool for captioning videos",
    ]
    assert [seg.translated_text for seg in result.segments] == [
        "我是学生",
        "你是老师",
        "VideoCaptioner 是视频字幕工具",
    ]
