import json
from types import SimpleNamespace

import pytest

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import (
    SubtitleConfig,
    SubtitleProcessData,
    TranslatorServiceEnum,
)
from videocaptioner.core.translate.factory import TranslatorFactory
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.ui.thread.subtitle_thread import create_translator_from_config
from videocaptioner.ui.thread.video_translation_thread import _job_output_dir


class NullCache:
    def get(self, key, default=None):
        return default

    def set(self, *args, **kwargs):
        return None

    def delete(self, *args, **kwargs):
        return None


def response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def make_translator(subtitle_action: str) -> LLMTranslator:
    translator = LLMTranslator(
        thread_num=1,
        batch_num=10,
        target_language=TargetLanguage.ENGLISH,
        model="test-model",
        custom_prompt="保留角色名小林",
        is_reflect=True,
        update_callback=None,
        subtitle_action=subtitle_action,
    )
    translator._cache = NullCache()
    return translator


def test_rewrite_full_context_and_single_repair_keep_source_language(monkeypatch):
    system_prompts = []
    replies = iter(
        [
            response(json.dumps({"1": "ERROR", "2": "他马上关上了门"}, ensure_ascii=False)),
            response("小林径直冲进房间"),
        ]
    )

    def fake_call_llm(*, messages, **kwargs):
        system_prompts.append(messages[0]["content"])
        return next(replies)

    monkeypatch.setattr(
        "videocaptioner.core.translate.llm_translator.call_llm", fake_call_llm
    )
    source = ASRData(
        [
            ASRDataSeg("小林冲进了房间", 0, 1000),
            ASRDataSeg("他立刻关上了门", 1000, 2000),
        ]
    )

    result = make_translator("rewrite").translate_subtitle(source)

    assert len(system_prompts) == 2
    assert all("runtime_rewrite_context" in prompt for prompt in system_prompts)
    assert all("Target language:" not in prompt for prompt in system_prompts)
    assert "必须保持每条字幕的原语言" in system_prompts[0]
    assert "原语言" in system_prompts[1]
    assert [segment.text for segment in result.segments] == [
        "小林冲进了房间",
        "他立刻关上了门",
    ]
    assert [segment.translated_text for segment in result.segments] == [
        "小林径直冲进房间",
        "他马上关上了门",
    ]
    assert [(segment.start_time, segment.end_time) for segment in result.segments] == [
        (0, 1000),
        (1000, 2000),
    ]


def test_rewrite_allows_lines_that_should_stay_unchanged():
    translator = make_translator("rewrite")
    rows = [
        SimpleNamespace(index=1, original_text="2026", translated_text="2026"),
        SimpleNamespace(index=2, original_text="小林", translated_text="小林"),
    ]

    translator._guard_translation_quality(rows)

    assert all(not translator._needs_retranslation(row) for row in rows)


def test_rewrite_rejects_a_document_that_was_not_rewritten():
    translator = make_translator("rewrite")
    rows = [
        SimpleNamespace(
            index=1,
            original_text="小林发现门外一直有人等着",
            translated_text="小林发现门外一直有人等着",
        ),
        SimpleNamespace(
            index=2,
            original_text="他马上转身跑回自己的房间",
            translated_text="他马上转身跑回自己的房间",
        ),
    ]

    with pytest.raises(RuntimeError, match="returned the original text"):
        translator._guard_translation_quality(rows)
    assert not translator._is_cacheable_result(rows)


def test_custom_rewrite_prompt_cannot_remove_runtime_guards(monkeypatch):
    translator = make_translator("rewrite")
    translator.translation_prompt = "按我的风格处理，并返回 JSON"
    system_prompts = []

    def fake_call_llm(*, messages, **kwargs):
        system_prompts.append(messages[0]["content"])
        return response("改写结果")

    monkeypatch.setattr(
        "videocaptioner.core.translate.llm_translator.call_llm", fake_call_llm
    )
    translator._translate_chunk_single(
        [SubtitleProcessData(index=1, original_text="这是一句需要改写的字幕")]
    )

    prompt = system_prompts[0]
    assert "Preserve facts, relationships, numbers, names" in prompt
    assert "按我的风格处理" in prompt
    assert "one subtitle text, not JSON" in prompt


def test_rewrite_uses_its_prompt_and_rejects_non_llm(monkeypatch):
    captured = {}

    def fake_create_translator(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(TranslatorFactory, "create_translator", fake_create_translator)
    config = SubtitleConfig(
        translator_service=TranslatorServiceEnum.OPENAI,
        target_language=TargetLanguage.SIMPLIFIED_CHINESE,
        subtitle_action="rewrite",
        need_reflect=True,
        translation_prompt_text="translation prompt",
        rewrite_prompt_text="rewrite prompt",
    )

    create_translator_from_config(config)

    assert captured["subtitle_action"] == "rewrite"
    assert captured["translation_prompt"] == "rewrite prompt"
    assert captured["is_reflect"] is False

    config.translator_service = TranslatorServiceEnum.BING
    with pytest.raises(ValueError, match="仅支持 LLM"):
        create_translator_from_config(config)


def test_rewrite_has_separate_cache_and_output_directory(tmp_path):
    data = [SubtitleProcessData(index=1, original_text="原句")]
    translate_key = make_translator("translate")._get_full_context_cache_key(data)
    rewrite_key = make_translator("rewrite")._get_full_context_cache_key(data)

    assert translate_key != rewrite_key
    assert _job_output_dir(tmp_path / "episode.mp4", "", "rewrite") == (
        tmp_path / "episode_视频洗稿"
    )
