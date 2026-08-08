"""Regression tests for the subtitle-panel word-splitting bug.

Placed outside ``tests/test_subtitle/`` on purpose: that directory's conftest
creates a QApplication (autouse), which cannot run headless. These tests drive
``SubtitleThread.run()`` directly — pyqtSignal connect/emit work without a
QApplication.

Bug being guarded: with ``need_split`` enabled the pipeline split every
subtitle line into single words *before* validating the LLM; when the LLM was
missing/unreachable the task failed but the preview stayed stuck at
word-per-line. Fix: validate the LLM first and skip the destructive split when
no LLM is available. Also guards the video-alignment panel's split switch no
longer sharing ``cfg.need_split`` with the subtitle panel.
"""

import tempfile
from pathlib import Path

from videocaptioner.core.entities import (
    SubtitleConfig,
    SubtitleTask,
    TranslatorServiceEnum,
)
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.subtitle_thread import SubtitleThread

_SRT_LINES = [
    ("今天天气非常好我们决定一起去郊外游玩顺便拍些照片", 0, 6000),
    ("到了目的地以后我们发现这里的风景比想象中还要漂亮很多", 6000, 12000),
]


def _fmt(ms: int) -> str:
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _make_srt(tmp_path: Path) -> Path:
    path = tmp_path / "in.srt"
    content = "\n".join(
        f"{i + 1}\n{_fmt(t0)} --> {_fmt(t1)}\n{text}\n"
        for i, (text, t0, t1) in enumerate(_SRT_LINES)
    )
    path.write_text(content, encoding="utf-8")
    return path


def _run_thread(task: SubtitleTask) -> dict:
    """Run SubtitleThread.run() synchronously, collecting signals."""
    thread = SubtitleThread(task)
    result: dict = {}
    thread.update_all.connect(
        lambda data: result.setdefault("update_all", []).append(len(data))
    )
    thread.finished.connect(lambda *a: result.setdefault("finished", True))
    thread.error.connect(lambda e: result.setdefault("error", str(e)))
    thread.run()
    return result


def _make_task(subtitle_path: str, output_path: str, **overrides) -> SubtitleTask:
    config = SubtitleConfig(
        need_split=True,
        need_optimize=False,
        thread_num=2,
        batch_size=5,
        max_word_count_cjk=20,
        max_word_count_english=12,
        target_language=TargetLanguage.ENGLISH,
        **overrides,
    )
    return SubtitleTask(
        queued_at=None,
        subtitle_path=subtitle_path,
        output_path=output_path,
        subtitle_config=config,
    )


def test_need_split_without_llm_keeps_original_sentences(tmp_path):
    """need_split on but no LLM: the split must be skipped, the preview must
    never receive word-level data, and the output keeps the original lines."""
    src = _make_srt(tmp_path)
    out = tmp_path / "out.srt"
    task = _make_task(str(src), str(out))

    result = _run_thread(task)

    assert "error" not in result, result.get("error")
    assert "finished" in result
    # No word-level preview update (the destructive split was skipped).
    assert "update_all" not in result
    # Output contains the original sentence-level lines, not single words.
    content = out.read_text(encoding="utf-8")
    assert content.count("-->") == 2
    assert "今天天气非常好我们决定一起去郊外游玩顺便拍些照片" in content


def test_need_split_with_unreachable_llm_errors_before_splitting(tmp_path):
    """LLM configured but unreachable: the task errors BEFORE the destructive
    word split, so the preview is never replaced with word-per-line data."""
    src = _make_srt(tmp_path)
    out = tmp_path / "out.srt"
    task = _make_task(
        str(src),
        str(out),
        need_translate=True,
        translator_service=TranslatorServiceEnum.OPENAI,
        base_url="http://127.0.0.1:1/v1",
        api_key="sk-test",
        llm_model="gpt-4o",
    )

    result = _run_thread(task)

    assert "error" in result
    assert "update_all" not in result, "preview must not be replaced with words"


def test_video_align_split_switch_is_isolated_from_subtitle_need_split():
    """The video-alignment panel's split switch has its own config item so it
    cannot flip the subtitle panel's need_split (and vice versa)."""
    assert hasattr(cfg, "video_align_need_split")
    # Both default to True (preserves current behavior), but they are
    # independent config items — changing one must not change the other.
    original = bool(cfg.need_split.value)
    cfg.video_align_need_split.value = not original
    assert bool(cfg.need_split.value) == original
    assert bool(cfg.video_align_need_split.value) != original


def test_create_transcribe_task_honors_explicit_word_timestamp_flag(tmp_path):
    """create_transcribe_task accepts an explicit need_word_time_stamp so the
    video-alignment flow can use its own switch instead of cfg.need_split."""
    file_path = str(tmp_path / "clip.mp4")
    on = TaskFactory.create_transcribe_task(
        file_path, need_next_task=True, need_word_time_stamp=True
    )
    off = TaskFactory.create_transcribe_task(
        file_path, need_next_task=True, need_word_time_stamp=False
    )
    assert on.transcribe_config.need_word_time_stamp is True
    assert off.transcribe_config.need_word_time_stamp is False
