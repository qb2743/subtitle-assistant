"""文稿匹配任务线程"""

from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.alignment import TextMatchingConfig, TextMatchingTask
from videocaptioner.core.entities import TranscribeConfig, TranscribeOutputFormatEnum
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.common.config import cfg

logger = setup_logger("text_matching_thread")


def _ui_language_to_transcribe(code: str) -> str:
    """文稿匹配 UI 语言代码 → Whisper 语言参数。"""
    if code == "auto":
        return ""
    return code


def _build_transcribe_config(language: str) -> TranscribeConfig:
    """与主流程转录任务一致，使用全局设置中的 ASR 引擎与 FasterWhisper 参数。"""
    return TranscribeConfig(
        transcribe_model=cfg.transcribe_model.value,
        transcribe_language=_ui_language_to_transcribe(language),
        need_word_time_stamp=True,  # 逐字时间戳：DTW 对齐到字级，时间更准；停顿处可断句
        output_format=TranscribeOutputFormatEnum.SRT,
        whisper_model=cfg.whisper_model.value,
        whisper_api_key=cfg.whisper_api_key.value,
        whisper_api_base=cfg.whisper_api_base.value,
        whisper_api_model=cfg.whisper_api_model.value,
        whisper_api_prompt=cfg.whisper_api_prompt.value,
        faster_whisper_program=cfg.faster_whisper_program.value,
        faster_whisper_model=cfg.faster_whisper_model.value,
        faster_whisper_model_dir=str(MODEL_PATH),
        faster_whisper_device=cfg.faster_whisper_device.value,
        faster_whisper_vad_filter=True,  # 文稿匹配依赖稳定语音段时间轴，贴近 txt2srt 默认
        faster_whisper_vad_threshold=cfg.faster_whisper_vad_threshold.value,
        faster_whisper_vad_method=cfg.faster_whisper_vad_method.value,
        faster_whisper_ff_mdx_kim2=cfg.faster_whisper_ff_mdx_kim2.value,
        faster_whisper_one_word=cfg.faster_whisper_one_word.value,
        faster_whisper_prompt=cfg.faster_whisper_prompt.value,
    )


class TextMatchingThread(QThread):
    """文稿匹配任务线程（ASR + DTW，复用 TextMatchingTask）"""

    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(
        self,
        media_path: str,
        user_text: str,
        max_chars: int = 30,
        language: str = "auto",
        smart_split: bool = True,
        asr_engine: str = "faster_whisper",
    ):
        super().__init__()
        self.media_path = media_path
        self.user_text = user_text
        self.max_chars = max_chars
        self.language = language
        self.smart_split = smart_split
        self.asr_engine = asr_engine
        self._cancelled = False

    def run(self):
        try:
            logger.info(f"开始文稿匹配任务: {self.media_path}")
            model = cfg.transcribe_model.value.value
            logger.info(f"使用 ASR 引擎: {model}, 语言: {self.language}")

            output_path = str(Path(self.media_path).with_suffix(".aligned.srt"))
            task = TextMatchingTask(
                TextMatchingConfig(
                    media_path=self.media_path,
                    user_text=self.user_text,
                    output_path=output_path,
                    max_chars=self.max_chars,
                    language=self.language,
                    smart_split=self.smart_split,
                    transcribe_config=_build_transcribe_config(self.language),
                )
            )

            def on_progress(percent: int, message: str):
                if self._cancelled:
                    return
                self.progress.emit(percent, message)

            result_path = task.execute(callback=on_progress)
            if self._cancelled:
                return

            logger.info(f"文稿匹配完成: {result_path}")
            self.finished.emit(str(result_path))

        except Exception as e:
            if not self._cancelled:
                error_msg = str(e)
                logger.exception(f"文稿匹配失败: {error_msg}")
                self.error.emit(error_msg)

    def cancel(self):
        logger.info("请求取消文稿匹配任务")
        self._cancelled = True