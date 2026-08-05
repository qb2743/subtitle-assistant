import time
from threading import Event

from videocaptioner.core.entities import BatchTaskType, TranscribeTask
from videocaptioner.ui.thread.batch_process_thread import BatchProcessThread, BatchTask
from videocaptioner.ui.thread.video_translation_thread import VideoTranslationThread


class _SlowCancelableThread:
    def __init__(self):
        self.cancel_started = Event()
        self.release_cancel = Event()
        self.interrupted = False

    def requestInterruption(self):
        self.interrupted = True

    def cancel(self):
        self.cancel_started.set()
        self.release_cancel.wait(2)


class _StartTrackingThread:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


def test_stop_all_is_non_blocking_and_cancels_active_thread():
    dispatcher = BatchProcessThread()
    child = _SlowCancelableThread()
    task = BatchTask("video.mp4", BatchTaskType.VIDEO_TRANSLATION)
    task.current_thread = child
    dispatcher.current_tasks[task.file_path] = task
    dispatcher.threads.append(child)

    started = time.monotonic()
    dispatcher.stop_all()
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert task.cancelled is True
    assert dispatcher.current_tasks == {}
    assert dispatcher.task_queue.empty()
    assert child.interrupted is True
    assert child.cancel_started.wait(1)
    child.release_cancel.set()


def test_cancelled_stage_cannot_launch_next_stage():
    dispatcher = BatchProcessThread()
    task = BatchTask("video.mp4", BatchTaskType.FULL_PROCESS)
    task.cancelled = True
    task.current_thread = object()
    dispatcher.current_tasks[task.file_path] = task
    dispatcher.threads.append(task.current_thread)
    dispatcher.is_running = True
    transcribe_task = TranscribeTask()
    transcribe_task.output_path = "subtitle.srt"

    dispatcher.on_full_process_finished(task, transcribe_task)

    assert dispatcher.threads == []


def test_clear_prevents_thread_created_during_dispatch_from_starting():
    dispatcher = BatchProcessThread()
    task = BatchTask("video.mp4", BatchTaskType.VIDEO_TRANSLATION)
    child = _StartTrackingThread()
    dispatcher.current_tasks[task.file_path] = task
    dispatcher.is_running = True

    dispatcher.stop_all()
    dispatcher.threads.append(child)

    assert dispatcher._start_thread(task, child) is False
    assert child.started is False
    assert dispatcher.threads == []


def test_stop_task_keeps_other_waiting_tasks():
    dispatcher = BatchProcessThread()
    first = BatchTask("first.mp4", BatchTaskType.VIDEO_TRANSLATION)
    second = BatchTask("second.mp4", BatchTaskType.VIDEO_TRANSLATION)
    dispatcher.current_tasks = {
        first.file_path: first,
        second.file_path: second,
    }
    dispatcher.task_queue.put(first)
    dispatcher.task_queue.put(second)

    dispatcher.stop_task(first.file_path)

    assert first.cancelled is True
    assert list(dispatcher.task_queue.queue) == [second]
    assert list(dispatcher.current_tasks) == [second.file_path]


def test_video_translation_cancel_reaches_active_child():
    child = _SlowCancelableThread()
    child.release_cancel.set()
    thread = VideoTranslationThread("video.mp4")
    thread._active_child = child

    thread.cancel()

    assert thread._cancelled is True
    assert child.interrupted is True
    assert child.cancel_started.is_set()
