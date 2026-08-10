"""ConfigSnapshot 快照行为测试：批量任务入队后不再受全局 cfg 变动影响。

背景：批量任务在轮到每个视频时才构建任务配置。修复前任务运行时读取
全局 cfg，批量运行期间在字幕面板修改目标语言等设置会污染队列中尚未
处理的任务。修复后入队即创建 ConfigSnapshot，任务配置统一从快照读取。
"""

from videocaptioner.core.entities import BatchTaskType
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.common.config_snapshot import ConfigSnapshot
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.batch_process_thread import (
    BatchProcessThread,
    BatchTask,
)


def _set_target_language(monkeypatch, lang: TargetLanguage):
    monkeypatch.setattr(cfg.target_language, "value", lang)


def test_snapshot_keeps_value_after_cfg_changes(monkeypatch):
    _set_target_language(monkeypatch, TargetLanguage.ENGLISH)
    snapshot = ConfigSnapshot()
    _set_target_language(monkeypatch, TargetLanguage.SIMPLIFIED_CHINESE)

    assert cfg.target_language.value == TargetLanguage.SIMPLIFIED_CHINESE
    assert snapshot.target_language.value == TargetLanguage.ENGLISH


def test_create_subtitle_task_uses_snapshot(monkeypatch):
    _set_target_language(monkeypatch, TargetLanguage.ENGLISH)
    snapshot = ConfigSnapshot()
    _set_target_language(monkeypatch, TargetLanguage.SIMPLIFIED_CHINESE)

    task = TaskFactory.create_subtitle_task("video.mp4", cfg_source=snapshot)

    assert task.subtitle_config.target_language == TargetLanguage.ENGLISH


def test_create_subtitle_task_without_snapshot_follows_live_cfg(monkeypatch):
    _set_target_language(monkeypatch, TargetLanguage.SIMPLIFIED_CHINESE)

    task = TaskFactory.create_subtitle_task("video.mp4")

    assert task.subtitle_config.target_language == TargetLanguage.SIMPLIFIED_CHINESE


def test_create_dubbing_config_uses_snapshot(monkeypatch):
    monkeypatch.setattr(cfg.dubbing_provider, "value", "edge")
    monkeypatch.setattr(cfg.dubbing_voice, "value", "zh-CN-XiaoxiaoNeural")
    snapshot = ConfigSnapshot()
    monkeypatch.setattr(cfg.dubbing_provider, "value", "elevenlabs")
    monkeypatch.setattr(cfg.dubbing_model, "value", "eleven_flash_v2_5")

    config = TaskFactory.create_dubbing_config(cfg_source=snapshot)

    assert config.provider == "edge"
    assert config.voice == "zh-CN-XiaoxiaoNeural"


def test_add_task_attaches_snapshot(monkeypatch):
    dispatcher = BatchProcessThread()
    monkeypatch.setattr(dispatcher, "start", lambda: None)  # 避免真实启动线程
    task = BatchTask("video.mp4", BatchTaskType.SUBTITLE)

    dispatcher.add_task(task)

    assert task.config_snapshot is not None
    assert dispatcher.current_tasks[task.file_path] is task


def test_existing_snapshot_is_kept_when_reenqueue(monkeypatch):
    dispatcher = BatchProcessThread()
    monkeypatch.setattr(dispatcher, "start", lambda: None)
    _set_target_language(monkeypatch, TargetLanguage.ENGLISH)
    task = BatchTask("video.mp4", BatchTaskType.SUBTITLE)
    dispatcher.add_task(task)
    snapshot = task.config_snapshot
    _set_target_language(monkeypatch, TargetLanguage.SIMPLIFIED_CHINESE)

    # 再次入队（如重新排队）不应覆盖已有快照
    dispatcher.add_task(task)

    assert task.config_snapshot is snapshot
