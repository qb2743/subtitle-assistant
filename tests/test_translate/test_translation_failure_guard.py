"""LLM 翻译失败保护测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage


def _make_translator(target=TargetLanguage.SIMPLIFIED_CHINESE):
    return LLMTranslator(
        thread_num=1,
        batch_num=5,
        target_language=target,
        model="fake-model",
        custom_prompt="",
        is_reflect=False,
        update_callback=None,
    )


def _make_segments(texts):
    return [
        SubtitleProcessData_proxy(idx, text, translated)
        for idx, (text, translated) in enumerate(texts, 1)
    ]


class SubtitleProcessData_proxy(SimpleNamespace):
    """轻量代理，匹配 SubtitleProcessData 的字段。"""
    pass


def test_guard_all_failed_raises_error():
    """所有行都翻译失败时应抛出 RuntimeError，而不是静默回填原文。"""
    translator = _make_translator()
    data = [
        SimpleNamespace(index=i, original_text=f"hello {i}", translated_text="")
        for i in range(1, 11)
    ]
    with pytest.raises(RuntimeError, match="Translation failed for 10/10"):
        translator._guard_translation_quality(data)


def test_guard_partial_failure_warns_but_passes():
    """少数失败（<50%）只警告，不抛异常。"""
    translator = _make_translator()
    data = [
        SimpleNamespace(index=1, original_text="hello 1", translated_text="你好 1"),
        SimpleNamespace(index=2, original_text="hello 2", translated_text="你好 2"),
        SimpleNamespace(index=3, original_text="hello 3", translated_text=""),
        SimpleNamespace(index=4, original_text="hello 4", translated_text="你好 4"),
    ]
    # 不应抛异常
    translator._guard_translation_quality(data)


def test_guard_translated_equals_original_counts_as_failed():
    """翻译结果等于原文（非英语目标）应计为失败。"""
    translator = _make_translator(target=TargetLanguage.SIMPLIFIED_CHINESE)
    data = [
        SimpleNamespace(index=i, original_text="hello world", translated_text="hello world")
        for i in range(1, 11)
    ]
    with pytest.raises(RuntimeError, match="Translation failed for 10/10"):
        translator._guard_translation_quality(data)


def test_guard_english_target_allows_translated_equals_original():
    """英语目标下，翻译=原文不算失败（英语到英语合理）。"""
    translator = _make_translator(target=TargetLanguage.ENGLISH)
    data = [
        SimpleNamespace(index=i, original_text="hello world", translated_text="hello world")
        for i in range(1, 11)
    ]
    translator._guard_translation_quality(data)  # 不抛异常


def test_guard_skips_empty_original():
    """空原文行不计入失败统计。"""
    translator = _make_translator()
    data = [
        SimpleNamespace(index=1, original_text="", translated_text=""),
        SimpleNamespace(index=2, original_text="hello", translated_text="你好"),
    ]
    translator._guard_translation_quality(data)  # 不抛异常


def test_guard_no_translatable_content_skipped():
    """只有标点/数字的原文行不计入失败统计。"""
    translator = _make_translator()
    data = [
        SimpleNamespace(index=1, original_text="...", translated_text=""),
        SimpleNamespace(index=2, original_text="123", translated_text=""),
        SimpleNamespace(index=3, original_text="hello", translated_text="你好"),
    ]
    translator._guard_translation_quality(data)  # 不抛异常
