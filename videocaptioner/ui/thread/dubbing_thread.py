"""Dubbing thread for batch processing."""

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
from videocaptioner.core.dubbing.pipeline import default_dubbed_audio_path
from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("dubbing_thread")


class DubbingThread(QThread):
    """配音任务线程

    处理单个字幕文件的配音生成，支持进度回调和错误处理。
    """

    progress = pyqtSignal(int, str)  # 进度百分比, 状态消息
    error = pyqtSignal(str)  # 错误消息
    finished = pyqtSignal(str)  # 输出文件路径

    def __init__(self, subtitle_path: str, config: DubbingConfig, video_path: str = None):
        """初始化配音线程

        Args:
            subtitle_path: 字幕文件路径 (.srt, .ass, .vtt, .json)
            config: 配音配置
            video_path: 可选的视频文件路径（用于合成配音视频）
        """
        super().__init__()
        self.subtitle_path = subtitle_path
        self.config = config
        self.video_path = video_path
        self._cancelled = False

    def run(self):
        """执行配音任务"""
        try:
            logger.info(f"开始配音任务: {self.subtitle_path}")

            pipeline = DubbingPipeline(self.config)

            if self._cancelled:
                return

            output_audio = default_dubbed_audio_path(
                self.subtitle_path, self.config.response_format
            )
            output_video = None
            if self.video_path:
                base = Path(self.video_path)
                output_video = str(base.with_stem(base.stem + "_dubbed"))

            logger.info(f"开始配音，使用 provider: {self.config.provider}")
            result = pipeline.run(
                subtitle_path=self.subtitle_path,
                output_audio_path=output_audio,
                video_path=self.video_path,
                output_video_path=output_video,
                callback=self._on_pipeline_progress,
            )

            if self._cancelled:
                return

            final_path = str(result.video_path or result.audio_path)
            logger.info(f"配音完成: {final_path}")
            self.progress.emit(100, "配音完成")
            self.finished.emit(final_path)

        except Exception as e:
            if not self._cancelled:
                error_msg = str(e)
                logger.exception(f"配音任务失败: {error_msg}")
                self.error.emit(error_msg)

    def _on_pipeline_progress(self, progress: int, message: str = ""):
        """配音管线进度回调"""
        if self._cancelled:
            return
        self.progress.emit(progress, message or "")

    def cancel(self):
        """取消配音任务"""
        logger.info("请求取消配音任务")
        self._cancelled = True
