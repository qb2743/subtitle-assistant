"""文稿匹配任务线程"""

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.alignment import TextMatchingConfig, TextMatchingTask
from videocaptioner.core.entities import (
    TranscribeConfig,
    TranscribeModelEnum,
    TranscribeOutputFormatEnum,
)
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.common.config import cfg, resolve_elevenlabs_asr_api_key

logger = setup_logger("text_matching_thread")


def _ui_language_to_transcribe(code: str) -> str:
    """文稿匹配 UI 语言代码 → Whisper 语言参数。"""
    if code == "auto":
        return ""
    return code


def _cuda_available() -> bool:
    """Cheap CUDA probe (ffmpeg hwaccel, same gate the subtitle renderer uses).

    faster-whisper-xxl with ``-d cuda`` fails hard on machines without a usable
    GPU, so the alignment flow falls back to CPU before handing the job off.
    Reuses the task factory's session-level TTL cache so a probe already run by
    the transcription flow is not repeated.
    """
    try:
        from videocaptioner.ui.task_factory import _cuda_available_cached

        return _cuda_available_cached()
    except Exception:
        logger.warning("CUDA 探测失败，按不可用处理", exc_info=True)
        return False


def _build_transcribe_config(language: str, device: str = "") -> TranscribeConfig:
    """与主流程转录任务一致，使用全局设置中的 ASR 引擎与 FasterWhisper 参数。"""
    if not device:
        device = cfg.faster_whisper_device.value
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
        # ElevenLabs Scribe：与转录/视频对齐面板共用同一份 Key（留空复用配音 Key）
        elevenlabs_api_key=resolve_elevenlabs_asr_api_key(),
        elevenlabs_api_base=cfg.elevenlabs_asr_base_url.value,
        elevenlabs_model=cfg.elevenlabs_asr_model.value,
        faster_whisper_program=cfg.faster_whisper_program.value,
        faster_whisper_model=cfg.faster_whisper_model.value,
        faster_whisper_model_dir=str(MODEL_PATH),
        faster_whisper_device=device,
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
    warning = pyqtSignal(str)
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
        self.match_rate: Optional[float] = None
        self._cancelled = False

    def run(self):
        try:
            logger.info(f"开始文稿匹配任务: {self.media_path}")
            model = cfg.transcribe_model.value.value
            logger.info(f"使用 ASR 引擎: {model}, 语言: {self.language}")

            # 无可用 GPU 时自动降级 CPU：faster-whisper-xxl 在 cuda 模式下会直接
            # 失败或空转，CPU 模式至少能完成（速度更慢但有明确提示）。
            # 云端引擎（ElevenLabs Scribe / Whisper API）不使用本地设备，跳过探测。
            device = cfg.faster_whisper_device.value
            if (
                cfg.transcribe_model.value == TranscribeModelEnum.FASTER_WHISPER
                and device == "cuda"
                and not _cuda_available()
            ):
                logger.warning("未检测到 CUDA，文稿匹配 ASR 降级为 CPU")
                self.warning.emit(
                    "未检测到可用的 CUDA 显卡，已自动切换为 CPU 模式。"
                    "无独显机器上识别速度会明显变慢，建议在设置中选择更小的 Whisper 模型。"
                )
                device = "cpu"

            output_path = str(Path(self.media_path).with_suffix(".aligned.srt"))
            task = TextMatchingTask(
                TextMatchingConfig(
                    media_path=self.media_path,
                    user_text=self.user_text,
                    output_path=output_path,
                    max_chars=self.max_chars,
                    language=self.language,
                    smart_split=self.smart_split,
                    transcribe_config=_build_transcribe_config(self.language, device),
                )
            )

            def on_progress(percent: int, message: str):
                if self._cancelled:
                    return
                self.progress.emit(percent, message)

            result_path = task.execute(callback=on_progress)
            if self._cancelled:
                return

            # 低置信度预警：文稿与识别内容差异过大时，时间轴很可能不准。
            stats = task.last_stats or {}
            match_rate = stats.get("match_rate")
            if match_rate is not None:
                self.match_rate = float(match_rate)
                threshold = task.config.low_confidence_threshold
                if threshold is not None and match_rate < threshold:
                    self.warning.emit(
                        f"对齐置信度较低（{match_rate:.0f}%），生成的 SRT 时间轴可能不准确，"
                        f"建议检查文稿内容与视频/音频是否一致。"
                    )

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