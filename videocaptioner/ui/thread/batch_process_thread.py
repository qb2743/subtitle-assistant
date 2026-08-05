import queue
import threading
import time
from functools import partial
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.core.entities import (
    BatchTaskStatus,
    BatchTaskType,
    TranscribeTask,
)
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.dubbing_thread import DubbingThread
from videocaptioner.ui.thread.subtitle_thread import SubtitleThread
from videocaptioner.ui.thread.transcript_thread import TranscriptThread
from videocaptioner.ui.thread.video_synthesis_thread import VideoSynthesisThread
from videocaptioner.ui.thread.video_translation_thread import VideoTranslationThread

logger = setup_logger("batch_process_thread")


class BatchTask:
    def __init__(self, file_path: str, task_type: BatchTaskType):
        self.file_path = file_path
        self.task_type = task_type
        self.status = BatchTaskStatus.WAITING
        self.progress = 0
        self.error_message = ""
        self.current_thread: Optional[QThread] = None
        self.cancelled = False


class BatchProcessThread(QThread):
    # 信号定义
    task_progress = pyqtSignal(str, int, str)  # file_path, progress, status
    task_error = pyqtSignal(str, str)  # file_path, error_message
    task_completed = pyqtSignal(str)  # file_path

    def __init__(self):
        super().__init__()
        self.task_queue = queue.Queue()
        self.current_tasks: Dict[str, BatchTask] = {}
        self.max_concurrent_tasks = 1
        self.is_running = False
        self.factory = TaskFactory()
        self.threads = []  # 保存所有创建的线程
        self._state_lock = threading.RLock()
        self.finished.connect(self._restart_if_needed)

    def add_task(self, task: BatchTask):
        with self._state_lock:
            self.threads = [thread for thread in self.threads if thread.isRunning()]
            self.task_queue.put(task)
            self.current_tasks[task.file_path] = task
            self.is_running = True
            if not self.isRunning():
                self.start()

    def _restart_if_needed(self):
        with self._state_lock:
            if self.is_running and not self.task_queue.empty() and not self.isRunning():
                self.start()

    def run(self):
        while True:
            # 检查是否有正在运行的任务数量是否达到上限
            with self._state_lock:
                if not self.is_running:
                    return
                tasks = tuple(self.current_tasks.values())
            running_tasks = sum(
                1
                for task in tasks
                if task.status == BatchTaskStatus.RUNNING
            )

            if running_tasks < self.max_concurrent_tasks:
                try:
                    # 非阻塞方式获取任务
                    task = self.task_queue.get_nowait()
                    self._process_task(task)
                except queue.Empty:
                    time.sleep(0.1)  # 避免CPU过度使用
            else:
                time.sleep(0.1)

    def _process_task(self, batch_task: BatchTask):
        try:
            if not self._task_is_active(batch_task):
                return
            batch_task.status = BatchTaskStatus.RUNNING
            self.task_progress.emit(
                batch_task.file_path, 0, str(BatchTaskStatus.RUNNING)
            )

            if batch_task.task_type == BatchTaskType.TRANSCRIBE:
                self._handle_transcribe_task(batch_task)
            elif batch_task.task_type == BatchTaskType.SUBTITLE:
                self._handle_subtitle_task(batch_task)
            elif batch_task.task_type == BatchTaskType.DUBBING:
                self._handle_dubbing_task(batch_task)
            elif batch_task.task_type == BatchTaskType.TRANS_SUB:
                self._handle_trans_sub_task(batch_task)
            elif batch_task.task_type == BatchTaskType.FULL_PROCESS:
                self._handle_full_process_task(batch_task)
            elif batch_task.task_type == BatchTaskType.VIDEO_TRANSLATION:
                self._handle_video_translation_task(batch_task)

        except Exception as e:
            logger.exception(f"处理任务失败: {str(e)}")
            batch_task.status = BatchTaskStatus.FAILED
            batch_task.error_message = str(e)
            self.task_error.emit(batch_task.file_path, str(e))

    def _on_progress_wrapper(self, batch_task: BatchTask, progress: int, message: str):
        """进度信号包装器"""
        if self._task_is_active(batch_task):
            self.task_progress.emit(batch_task.file_path, progress, message)

    def _on_error_wrapper(self, batch_task: BatchTask, error: str):
        """错误信号包装器"""
        if not self._task_is_active(batch_task):
            return
        batch_task.status = BatchTaskStatus.FAILED
        batch_task.error_message = error
        self.task_error.emit(batch_task.file_path, error)

    def _on_finished_wrapper(self, batch_task: BatchTask, task=None):
        """完成信号包装器"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)
        if not self._task_is_active(batch_task):
            return
        batch_task.status = BatchTaskStatus.COMPLETED
        batch_task.progress = 100
        self.task_completed.emit(batch_task.file_path)

    def _task_is_active(self, batch_task: BatchTask) -> bool:
        with self._state_lock:
            return (
                self.is_running
                and not batch_task.cancelled
                and self.current_tasks.get(batch_task.file_path) is batch_task
            )

    def _start_thread(self, batch_task: BatchTask, thread: QThread) -> bool:
        with self._state_lock:
            if not self._task_is_active(batch_task):
                if thread in self.threads:
                    self.threads.remove(thread)
                return False
            thread.start()
            return True

    def _handle_transcribe_task(self, batch_task: BatchTask):
        # self.max_concurrent_tasks = 3
        task = self.factory.create_transcribe_task(batch_task.file_path)
        thread = TranscriptThread(task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(  # type: ignore
            partial(self._on_progress_wrapper, batch_task)  # type: ignore
        )
        thread.error.connect(  # type: ignore
            partial(self._on_error_wrapper, batch_task)  # type: ignore
        )
        thread.finished.connect(  # type: ignore
            partial(self._on_finished_wrapper, batch_task)  # type: ignore
        )

        self._start_thread(batch_task, thread)

    def _handle_subtitle_task(self, batch_task: BatchTask):
        logger.info(f"开始处理字幕任务: {batch_task.file_path}")

        task = self.factory.create_subtitle_task(batch_task.file_path)
        thread = SubtitleThread(task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(  # type: ignore
            partial(self._on_progress_wrapper, batch_task)  # type: ignore
        )
        thread.error.connect(  # type: ignore
            partial(self._on_error_wrapper, batch_task)  # type: ignore
        )
        thread.finished.connect(  # type: ignore
            partial(self._on_finished_wrapper, batch_task)  # type: ignore
        )

        self._start_thread(batch_task, thread)

    def _handle_dubbing_task(self, batch_task: BatchTask):
        """处理配音任务"""
        logger.info(f"开始处理配音任务: {batch_task.file_path}")

        # 从工厂创建配音配置
        config = self.factory.create_dubbing_config()

        # 检查是否有同名视频文件（用于合成配音视频）
        video_path = None
        subtitle_path = Path(batch_task.file_path)
        for ext in ['.mp4', '.mov', '.mkv', '.avi', '.webm']:
            potential_video = subtitle_path.with_suffix(ext)
            if potential_video.exists():
                video_path = str(potential_video)
                logger.info(f"找到同名视频文件: {video_path}")
                break

        thread = DubbingThread(batch_task.file_path, config, video_path)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(  # type: ignore
            partial(self._on_progress_wrapper, batch_task)  # type: ignore
        )
        thread.error.connect(  # type: ignore
            partial(self._on_error_wrapper, batch_task)  # type: ignore
        )
        thread.finished.connect(  # type: ignore
            partial(self._on_finished_wrapper, batch_task)  # type: ignore
        )

        self._start_thread(batch_task, thread)

    def _handle_trans_sub_task(self, batch_task: BatchTask):
        trans_task = self.factory.create_transcribe_task(
            batch_task.file_path, need_next_task=True
        )
        thread = TranscriptThread(trans_task)
        batch_task.current_thread = thread
        self.current_tasks[batch_task.file_path] = batch_task

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self._on_trans_sub_progress_wrapper, batch_task)
        )
        thread.error.connect(partial(self._on_error_wrapper, batch_task))
        thread.finished.connect(
            partial(self._on_trans_sub_finished_wrapper, batch_task)
        )

        self._start_thread(batch_task, thread)

    def _on_trans_sub_progress_wrapper(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """转录+字幕任务进度包装器"""
        progress = progress // 2  # 转录占50%进度
        self.task_progress.emit(batch_task.file_path, progress, message)

    def _on_trans_sub_finished_wrapper(
        self, batch_task: BatchTask, task: TranscribeTask
    ):
        """转录+字幕任务转录完成包装器"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)
        if not self._task_is_active(batch_task):
            return

        # 创建字幕任务
        if not task.output_path:
            raise ValueError("Task output_path is None")
        subtitle_task = self.factory.create_subtitle_task(
            task.output_path, batch_task.file_path, need_next_task=True
        )
        thread = SubtitleThread(subtitle_task)
        batch_task.current_thread = thread
        self.current_tasks[batch_task.file_path] = batch_task

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self._on_trans_sub_subtitle_progress_wrapper, batch_task)
        )
        thread.error.connect(partial(self._on_error_wrapper, batch_task))
        thread.finished.connect(partial(self._on_finished_wrapper, batch_task))

        self._start_thread(batch_task, thread)

    def _on_trans_sub_subtitle_progress_wrapper(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """转录+字幕任务字幕进度包装器"""
        progress = 50 + progress // 2  # 字幕处理占后50%进度
        self.task_progress.emit(batch_task.file_path, progress, message)

    def _handle_full_process_task(self, batch_task: BatchTask):
        # 首先创建转录任务
        trans_task = self.factory.create_transcribe_task(
            batch_task.file_path, need_next_task=True
        )
        thread = TranscriptThread(trans_task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(partial(self.on_full_process_progress, batch_task))
        thread.error.connect(partial(self._on_error_wrapper, batch_task))
        thread.finished.connect(partial(self.on_full_process_finished, batch_task))

        self._start_thread(batch_task, thread)

    def _handle_video_translation_task(self, batch_task: BatchTask):
        """批量执行视频翻译，跳过需要人工点击的两个复核停顿。"""
        thread = VideoTranslationThread(
            batch_task.file_path,
            manual_review=False,
            translation_review=False,
        )
        batch_task.current_thread = thread
        self.threads.append(thread)
        thread.progress.connect(partial(self._on_progress_wrapper, batch_task))
        thread.error.connect(partial(self._on_error_wrapper, batch_task))
        thread.finished.connect(partial(self._on_finished_wrapper, batch_task))
        self._start_thread(batch_task, thread)

    def on_full_process_progress(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """处理全流程任务的转录进度"""
        if self._task_is_active(batch_task) and batch_task.status == BatchTaskStatus.RUNNING:
            progress_value = progress // 3  # 转录占33%进度
            self.task_progress.emit(batch_task.file_path, progress_value, message)

    def on_full_process_finished(self, batch_task: BatchTask, task: TranscribeTask):
        """处理转录完成后开始字幕任务"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)
        if not self._task_is_active(batch_task):
            return

        # 转录完成后创建字幕任务
        if not task.output_path:
            raise ValueError("Task output_path is None")
        subtitle_task = self.factory.create_subtitle_task(
            task.output_path,
            batch_task.file_path,
            need_next_task=True,
        )
        thread = SubtitleThread(subtitle_task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self.on_full_process_subtitle_progress, batch_task)
        )
        thread.error.connect(partial(self._on_error_wrapper, batch_task))
        thread.finished.connect(
            partial(self.on_full_process_subtitle_finished, batch_task)
        )

        self._start_thread(batch_task, thread)

    def on_full_process_subtitle_progress(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """处理全流程任务中字幕部分的进度"""
        if self._task_is_active(batch_task) and batch_task.status == BatchTaskStatus.RUNNING:
            progress_value = 33 + progress // 3  # 字幕处理占中间33%进度
            self.task_progress.emit(batch_task.file_path, progress_value, message)

    def on_full_process_subtitle_finished(
        self, batch_task: BatchTask, video_path: str, subtitle_path: str
    ):
        """处理字幕完成后开始视频合成任务"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)
        if not self._task_is_active(batch_task):
            return

        # 字幕完成后创建视频合成任务
        synthesis_task = self.factory.create_synthesis_task(video_path, subtitle_path)
        thread = VideoSynthesisThread(synthesis_task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self.on_full_process_synthesis_progress, batch_task)
        )
        thread.error.connect(partial(self._on_error_wrapper, batch_task))
        thread.finished.connect(partial(self._on_finished_wrapper, batch_task))

        self._start_thread(batch_task, thread)

    def on_full_process_synthesis_progress(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """处理全流程任务中视频合成部分的进度"""
        if self._task_is_active(batch_task) and batch_task.status == BatchTaskStatus.RUNNING:
            progress_value = 66 + progress // 3  # 视频合成占最后34%进度
            self.task_progress.emit(batch_task.file_path, progress_value, message)

    def stop_task(self, file_path: str):
        with self._state_lock:
            task = self.current_tasks.pop(file_path, None)
            if task is None:
                return
            task.cancelled = True
            with self.task_queue.mutex:
                self.task_queue.queue = type(self.task_queue.queue)(
                    queued
                    for queued in self.task_queue.queue
                    if queued.file_path != file_path
                )
        if task.current_thread:
            self._stop_thread_async(task.current_thread)

    def stop_all(self):
        with self._state_lock:
            self.is_running = False
            for task in self.current_tasks.values():
                task.cancelled = True
            threads = tuple(self.threads)
            self.current_tasks.clear()
            with self.task_queue.mutex:
                self.task_queue.queue.clear()
            self.requestInterruption()
        for thread in threads:
            self._stop_thread_async(thread)

    @staticmethod
    def _stop_thread_async(thread: QThread):
        thread.requestInterruption()
        stopper = getattr(thread, "cancel", None) or getattr(thread, "stop", None)
        if not callable(stopper):
            return

        def stop_worker():
            try:
                stopper()
            except Exception as exc:  # noqa: BLE001
                logger.warning("停止批处理子任务失败: %s", exc)

        threading.Thread(target=stop_worker, daemon=True).start()
