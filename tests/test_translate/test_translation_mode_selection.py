"""测试翻译模式自动切换与用户手动覆盖。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.translate.llm_translator import LLMTranslator
from videocaptioner.core.translate.types import TargetLanguage


def _make_translator(thread_num=3, batch_num=10, target=TargetLanguage.SIMPLIFIED_CHINESE, translation_mode="auto"):
    return LLMTranslator(
        thread_num=thread_num,
        batch_num=batch_num,
        target_language=target,
        model="fake-model",
        custom_prompt="",
        is_reflect=False,
        update_callback=None,
        translation_mode=translation_mode,
    )


def _make_segments(n):
    return [ASRDataSeg(text=f"hello {i}", start_time=i*1000, end_time=i*1000+1000) for i in range(1, n + 1)]


def test_auto_mode_small_subtitle_uses_full_context(monkeypatch):
    """auto 模式下 ≤100 条字幕应使用 full_context。"""
    translator = _make_translator(translation_mode="auto")
    full_context_called = MagicMock(return_value=[
        SimpleNamespace(index=i, original_text=f"hello {i}", translated_text=f"你好 {i}")
        for i in range(1, 11)
    ])
    parallel_called = MagicMock()
    monkeypatch.setattr(translator, "_safe_translate_full_context", full_context_called)
    monkeypatch.setattr(translator, "_parallel_translate", parallel_called)
    monkeypatch.setattr(translator, "_guard_translation_quality", lambda x: None)

    translator.translate_subtitle(ASRData(_make_segments(10)))

    full_context_called.assert_called_once()
    parallel_called.assert_not_called()


def test_auto_mode_large_subtitle_uses_chunked(monkeypatch):
    """auto 模式下 >100 条字幕应使用分块。"""
    translator = _make_translator(thread_num=4, batch_num=20, translation_mode="auto")
    full_context_called = MagicMock()
    parallel_called = MagicMock(return_value=[
        SimpleNamespace(index=i, original_text=f"hello {i}", translated_text=f"你好 {i}")
        for i in range(1, 151)
    ])
    monkeypatch.setattr(translator, "_safe_translate_full_context", full_context_called)
    monkeypatch.setattr(translator, "_parallel_translate", parallel_called)
    monkeypatch.setattr(translator, "_repair_failed_translations", lambda x: None)
    monkeypatch.setattr(translator, "_guard_translation_quality", lambda x: None)

    translator.translate_subtitle(ASRData(_make_segments(150)))

    full_context_called.assert_not_called()
    parallel_called.assert_called_once()


def test_force_full_context_overrides_threshold(monkeypatch):
    """手动选择 full_context 应覆盖自动阈值，>100 条也走 full_context。"""
    translator = _make_translator(translation_mode="full_context")
    full_context_called = MagicMock(return_value=[
        SimpleNamespace(index=i, original_text=f"hello {i}", translated_text=f"你好 {i}")
        for i in range(1, 151)
    ])
    parallel_called = MagicMock()
    monkeypatch.setattr(translator, "_safe_translate_full_context", full_context_called)
    monkeypatch.setattr(translator, "_parallel_translate", parallel_called)
    monkeypatch.setattr(translator, "_guard_translation_quality", lambda x: None)

    translator.translate_subtitle(ASRData(_make_segments(150)))

    full_context_called.assert_called_once()
    parallel_called.assert_not_called()


def test_force_chunked_overrides_threshold(monkeypatch):
    """手动选择 chunked 应覆盖自动阈值，≤100 条也走分块。"""
    translator = _make_translator(thread_num=2, batch_num=50, translation_mode="chunked")
    full_context_called = MagicMock()
    parallel_called = MagicMock(return_value=[
        SimpleNamespace(index=i, original_text=f"hello {i}", translated_text=f"你好 {i}")
        for i in range(1, 11)
    ])
    monkeypatch.setattr(translator, "_safe_translate_full_context", full_context_called)
    monkeypatch.setattr(translator, "_parallel_translate", parallel_called)
    monkeypatch.setattr(translator, "_repair_failed_translations", lambda x: None)
    monkeypatch.setattr(translator, "_guard_translation_quality", lambda x: None)

    translator.translate_subtitle(ASRData(_make_segments(10)))

    full_context_called.assert_not_called()
    parallel_called.assert_called_once()
