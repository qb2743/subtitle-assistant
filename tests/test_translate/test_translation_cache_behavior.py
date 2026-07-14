"""Tests for translation cache invalidation and global cache bypass."""

import json
from types import SimpleNamespace

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import SubtitleProcessData
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.utils.cache import disable_cache, enable_cache


class MemoryCache:
    def __init__(self):
        self.data = {}
        self.deleted = []

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value, **kwargs):
        self.data[key] = value

    def delete(self, key):
        self.deleted.append(key)
        self.data.pop(key, None)


def make_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def make_asr_data() -> ASRData:
    return ASRData(
        [
            ASRDataSeg(start_time=0, end_time=1000, text="line one"),
            ASRDataSeg(start_time=1000, end_time=2000, text="line two"),
            ASRDataSeg(start_time=2000, end_time=3000, text="line three"),
        ]
    )


def make_translator(cache: MemoryCache, translation_prompt: str = "") -> LLMTranslator:
    translator = LLMTranslator(
        thread_num=1,
        batch_num=2,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
        model="test-model",
        custom_prompt="",
        is_reflect=False,
        update_callback=None,
        translation_prompt=translation_prompt,
    )
    translator._cache = cache
    return translator


def make_translate_data() -> list[SubtitleProcessData]:
    return [
        SubtitleProcessData(index=i, original_text=seg.text)
        for i, seg in enumerate(make_asr_data().segments, 1)
    ]


def test_invalid_full_context_cache_is_ignored_and_deleted(monkeypatch):
    enable_cache()
    try:
        cache = MemoryCache()
        translator = make_translator(cache)
        cache_key = translator._get_full_context_cache_key(make_translate_data())
        cache.data[cache_key] = [
            SubtitleProcessData(
                index=1, original_text="line one", translated_text="old"
            ),
            SubtitleProcessData(
                index=2, original_text="line two", translated_text="ERROR"
            ),
            SubtitleProcessData(
                index=3, original_text="line three", translated_text="old"
            ),
        ]

        def fake_call_llm(*, messages, model, temperature=1, **kwargs):
            return make_response(
                json.dumps({"1": "fresh 1", "2": "fresh 2", "3": "fresh 3"})
            )

        monkeypatch.setattr(
            "videocaptioner.core.translate.llm_translator.call_llm",
            fake_call_llm,
        )

        result = translator.translate_subtitle(make_asr_data())

        assert cache_key in cache.deleted
        assert [seg.translated_text for seg in result.segments] == [
            "fresh 1",
            "fresh 2",
            "fresh 3",
        ]
    finally:
        enable_cache()


def test_disabled_cache_bypasses_full_context_cache(monkeypatch):
    cache = MemoryCache()
    translator = make_translator(cache)
    cache_key = translator._get_full_context_cache_key(make_translate_data())
    cache.data[cache_key] = [
        SubtitleProcessData(index=1, original_text="line one", translated_text="old 1"),
        SubtitleProcessData(index=2, original_text="line two", translated_text="old 2"),
        SubtitleProcessData(index=3, original_text="line three", translated_text="old 3"),
    ]

    def fake_call_llm(*, messages, model, temperature=1, **kwargs):
        return make_response(
            json.dumps({"1": "fresh 1", "2": "fresh 2", "3": "fresh 3"})
        )

    monkeypatch.setattr(
        "videocaptioner.core.translate.llm_translator.call_llm",
        fake_call_llm,
    )

    disable_cache()
    try:
        result = translator.translate_subtitle(make_asr_data())
    finally:
        enable_cache()

    assert cache.data[cache_key][0].translated_text == "old 1"
    assert [seg.translated_text for seg in result.segments] == [
        "fresh 1",
        "fresh 2",
        "fresh 3",
    ]


def test_custom_translation_prompt_renders_template_variables():
    translator = make_translator(
        MemoryCache(),
        translation_prompt="Translate into ${target_language}. Notes: ${custom_prompt}",
    )
    translator.custom_prompt = "keep NASA"

    prompt = translator._get_translation_prompt()
    assert "Target language: 简体中文" in prompt
    assert "Translate into 简体中文. Notes: keep NASA" in prompt


def test_custom_translation_prompt_gets_target_language_even_without_variable():
    translator = make_translator(
        MemoryCache(),
        translation_prompt="Translate naturally.",
    )
    translator.custom_prompt = "keep NASA"

    prompt = translator._get_translation_prompt()
    assert "Target language: 简体中文" in prompt
    assert "User terminology and requirements:\nkeep NASA" in prompt
    assert "Translate naturally." in prompt


def test_translation_prompt_changes_full_context_cache_key():
    data = make_translate_data()
    key_a = make_translator(MemoryCache(), translation_prompt="prompt A")._get_full_context_cache_key(data)
    key_b = make_translator(MemoryCache(), translation_prompt="prompt B")._get_full_context_cache_key(data)

    assert key_a != key_b
