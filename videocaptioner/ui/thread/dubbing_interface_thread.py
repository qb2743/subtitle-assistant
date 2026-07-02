"""配音界面后台线程 - 支持字幕文件和文案直接配音"""

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.dubbing import DubbingPipeline
from videocaptioner.core.dubbing.pipeline import default_dubbed_audio_path
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.task_factory import TaskFactory

logger = setup_logger("dubbing_interface_thread")


class DubbingInterfaceThread(QThread):
    """配音界面任务线程

    支持两种输入模式：
    1. 字幕文件模式：加载 SRT/ASS/VTT → 配音
    2. 文案直接模式：文本 → 自动分段 → 配音
    """

    progress = pyqtSignal(int, str)  # 进度百分比, 状态消息
    error = pyqtSignal(str)  # 错误消息
    finished = pyqtSignal(str)  # 输出文件路径

    def __init__(
        self,
        input_mode: str,
        input_data: str,
        output_path: str = None,
    ):
        """初始化配音线程

        Args:
            input_mode: "subtitle" 或 "text"
            input_data: 字幕文件路径（subtitle模式）或文案文本（text模式）
            output_path: 输出路径（可选，自动生成）
        """
        super().__init__()
        self.input_mode = input_mode
        self.input_data = input_data
        self.output_path = output_path
        self._cancelled = False

    def run(self):
        """执行配音任务"""
        try:
            logger.info(f"开始配音任务，模式: {self.input_mode}")

            # 获取配音配置
            config = TaskFactory.create_dubbing_config()

            if self.input_mode == "subtitle":
                self._run_subtitle_mode(config)
            else:
                self._run_text_mode(config)

        except Exception as e:
            if not self._cancelled:
                error_msg = str(e)
                logger.exception(f"配音任务失败: {error_msg}")
                self.error.emit(error_msg)

    def _run_subtitle_mode(self, config):
        """字幕文件配音模式"""
        subtitle_path = self.input_data
        logger.info(f"字幕文件配音: {subtitle_path}")

        # 1. 加载字幕文件（0-10%）
        self.progress.emit(5, "加载字幕文件...")
        asr_data = ASRData.from_subtitle_file(subtitle_path)

        if self._cancelled:
            return

        if not asr_data.segments:
            raise ValueError("字幕文件为空")

        logger.info(f"加载了 {len(asr_data.segments)} 个字幕段")
        self.progress.emit(10, f"已加载 {len(asr_data.segments)} 个字幕段")

        # 2. 配音合成（10-90%）
        self.progress.emit(15, "初始化配音引擎...")
        pipeline = DubbingPipeline(config)

        logger.info(f"开始配音，provider: {config.provider}")

        # 生成输出路径
        if not self.output_path:
            self.output_path = default_dubbed_audio_path(
                subtitle_path, config.response_format
            )

        output = pipeline.run(
            subtitle_path=subtitle_path,
            output_audio_path=self.output_path,
            callback=self._on_pipeline_progress,
        )

        if self._cancelled:
            return

        logger.info(f"配音完成: {output}")
        self.progress.emit(100, "配音完成")
        self.finished.emit(str(output.audio_path))

    def _run_text_mode(self, config):
        """文案直接配音模式 — 生成临时 SRT 后复用字幕配音流程"""
        import tempfile
        from datetime import datetime

        user_text = self.input_data
        logger.info(f"文案配音，文本长度: {len(user_text)} 字符")

        self.progress.emit(5, "分析文案...")
        segments = self._split_text_into_segments(user_text)

        if self._cancelled:
            return

        logger.info(f"文案分为 {len(segments)} 段")
        self.progress.emit(10, f"已分段: {len(segments)} 段")

        # 构造 ASRData 并写成临时 SRT，pipeline 直接读 SRT
        asr_data = ASRData([
            ASRDataSeg(text=seg, start_time=i * 5000, end_time=(i + 1) * 5000)
            for i, seg in enumerate(segments)
        ])
        # fixed_line_pause 模式下时间戳无意义，确保开启
        config.fixed_line_pause = True

        tmp_srt = tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w", encoding="utf-8")
        try:
            tmp_srt.write(asr_data.to_srt())
            tmp_srt.close()

            self.progress.emit(15, "初始化配音引擎...")
            pipeline = DubbingPipeline(config)
            logger.info(f"开始配音，provider: {config.provider}")

            if not self.output_path:
                output_dir = Path.cwd() / "dubbing"
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.output_path = str(output_dir / f"dubbing_{timestamp}.mp3")
                logger.info(f"自动生成输出路径: {self.output_path}")

            output = pipeline.run(
                subtitle_path=tmp_srt.name,
                output_audio_path=self.output_path,
                callback=self._on_pipeline_progress,
            )
        finally:
            Path(tmp_srt.name).unlink(missing_ok=True)

        if self._cancelled:
            return

        logger.info(f"配音完成: {output}")
        self.progress.emit(100, "配音完成")
        self.finished.emit(str(output.audio_path))

    def _split_text_into_segments(self, text: str) -> list:
        """将文案分割成段落

        按标点符号或换行符分段
        """
        import re

        # 按句号、问号、感叹号、换行符分段
        segments = re.split(r'[。？！\n]+', text)

        # 过滤空段
        segments = [seg.strip() for seg in segments if seg.strip()]

        return segments

    def _on_pipeline_progress(self, progress: int, message: str):
        """配音管线进度回调"""
        if self._cancelled:
            return

        self.progress.emit(progress, message)

    def cancel(self):
        """取消任务"""
        logger.info("请求取消配音任务")
        self._cancelled = True
