# -*- coding: utf-8 -*-
"""视频翻译全流程面板。"""

import json
from hashlib import sha256
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    DoubleSpinBox,
    FluentStyleSheet,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    Slider,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
    ToolButton,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from videocaptioner.config import CACHE_PATH, MODEL_PATH
from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.dubbing.presets import (
    EDGE_VOICE_ALIASES,
    FISHAUDIO_PRESET_VOICES,
    GEMINI_VOICES,
    SILICONFLOW_VOICE_ALIASES,
    elevenlabs_voice_options,
)
from videocaptioner.core.entities import (
    SubtitleLayoutEnum,
    SupportedVideoFormats,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    TranslatorServiceEnum,
)
from videocaptioner.core.translate.types import GOOGLE_LANG_MAP, TargetLanguage
from videocaptioner.core.utils.model_downloader import ModelDownloader
from videocaptioner.core.utils.model_urls import (
    DIARIZATION_MULTILINGUAL_MODEL_SIZE,
    diarization_model_filename,
    diarization_model_urls,
)
from videocaptioner.core.utils.platform_utils import open_folder
from videocaptioner.core.voices.loader import load_edge_voices_from_json
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.dubbing_config_builder import (
    diarization_language_from_transcribe,
    dubbing_model_options,
    resolve_dubbing_model,
    resolve_dubbing_voice,
)
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.video_info_thread import VideoInfoThread
from videocaptioner.ui.thread.video_translation_thread import (
    VideoTranslationThread,
    _job_output_dir,
)
from videocaptioner.ui.view.subtitle_interface import SubtitleInterface

REVIEW_TIMEOUT_SECONDS = 30

_OPENAI_VOICE_OPTIONS = [
    ("Alloy - 中性", "alloy"),
    ("Echo - 男声", "echo"),
    ("Fable - 英式男声", "fable"),
    ("Onyx - 深沉男声", "onyx"),
    ("Nova - 女声", "nova"),
    ("Shimmer - 女声", "shimmer"),
]
_DEFAULT_VOICES = {
    "edge": EDGE_VOICE_ALIASES["xiaoxiao"],
    "elevenlabs": "21m00Tcm4TlvDq8ikWAM",
    "gemini": "Kore",
    "siliconflow": SILICONFLOW_VOICE_ALIASES["alex"],
    "openai": "alloy",
    "fishaudio": FISHAUDIO_PRESET_VOICES[0][1],
}


def _cached_voice_options(provider: str) -> list[tuple[str, str]]:
    try:
        data = json.loads((CACHE_PATH / f"voices_{provider}.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return []
    return [
        (str(item.get("name") or item.get("voice_id")), str(item["voice_id"]))
        for item in data
        if isinstance(item, dict) and item.get("voice_id")
    ]


def alignment_voice_options(
    provider: str, target_language: TargetLanguage | None
) -> list[tuple[str, str]]:
    """Return local, non-blocking voice choices for the alignment page."""
    provider = provider.strip().lower()
    if provider == "edge":
        language_code = GOOGLE_LANG_MAP.get(target_language, "zh-CN").split("-", 1)[0]
        if language_code == "tl":
            language_code = "fil"
        return list(load_edge_voices_from_json().get(language_code, {}).items())
    if provider == "elevenlabs":
        options = [(voice.name, voice.voice_id) for voice in elevenlabs_voice_options()]
        options.extend(_cached_voice_options(provider))
    elif provider == "gemini":
        options = [(voice, voice) for voice in sorted(GEMINI_VOICES)]
    elif provider == "siliconflow":
        options = [
            ("Anna - 女声", SILICONFLOW_VOICE_ALIASES["anna"]),
            ("Alex - 男声", SILICONFLOW_VOICE_ALIASES["alex"]),
            ("Benjamin - 深沉男声", SILICONFLOW_VOICE_ALIASES["benjamin"]),
        ]
    elif provider == "openai":
        options = list(_OPENAI_VOICE_OPTIONS)
    elif provider == "fishaudio":
        options = list(FISHAUDIO_PRESET_VOICES)
        options.extend(_cached_voice_options(provider))
        options.append(("参考音频克隆（沿用配音面板设置）", ""))
    else:
        return []

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, voice in options:
        if voice not in seen:
            unique.append((name, voice))
            seen.add(voice)
    return unique


def _multilingual_diarization_model_path() -> Path:
    return (
        Path(MODEL_PATH)
        / "diarization"
        / diarization_model_filename("embedding_multi")
    )


def _multilingual_diarization_model_ready() -> bool:
    path = _multilingual_diarization_model_path()
    return path.is_file() and path.stat().st_size == DIARIZATION_MULTILINGUAL_MODEL_SIZE


class DiarizationModelDownloadThread(QThread):
    """Download the optional multilingual speaker model off the GUI thread."""

    progress = pyqtSignal(float, str)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target = _multilingual_diarization_model_path()
        self.downloader = ModelDownloader(self.target.parent)

    def run(self):
        try:
            path = self.downloader.download(
                diarization_model_urls("embedding_multi")[0],
                filename=self.target.name,
                progress=self.progress.emit,
            )
            if path.stat().st_size != DIARIZATION_MULTILINGUAL_MODEL_SIZE:
                path.unlink(missing_ok=True)
                raise RuntimeError("模型文件大小校验失败，请重新下载")
            self.succeeded.emit(str(path))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def stop(self):
        self.downloader.cancel()


class DiarizationModelDownloadDialog(MessageBoxBase):
    """On-demand multilingual speaker-model manager."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(560)
        self.download_thread = None

        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("说话人识别模型管理", self))
        title_row.addStretch()
        open_button = PushButton(FIF.FOLDER, "打开模型目录", self)
        open_button.clicked.connect(self._open_model_folder)
        title_row.addWidget(open_button)
        self.viewLayout.addLayout(title_row)

        self.viewLayout.addWidget(
            BodyLabel(
                "多语种 SimAMResNet34（96.2 MiB）\n"
                "用于自动检测及日语、韩语、法语、俄语等非中英文音频。",
                self,
            )
        )
        action_row = QHBoxLayout()
        self.status_label = BodyLabel("", self)
        self.download_button = PushButton(FIF.DOWNLOAD, "下载", self)
        self.download_button.clicked.connect(self._start_download)
        action_row.addWidget(self.status_label)
        action_row.addStretch()
        action_row.addWidget(self.download_button)
        self.viewLayout.addLayout(action_row)

        self.progress_bar = ProgressBar(self)
        self.progress_label = BodyLabel("", self)
        self.progress_bar.hide()
        self.progress_label.hide()
        self.viewLayout.addWidget(self.progress_bar)
        self.viewLayout.addWidget(self.progress_label)
        self.yesButton.hide()
        self.cancelButton.setText("关闭")
        self._refresh_status()

    def _refresh_status(self):
        ready = _multilingual_diarization_model_ready()
        self.status_label.setText("已下载" if ready else "未下载")
        self.download_button.setText("重新下载" if ready else "下载")

    def _open_model_folder(self):
        folder = _multilingual_diarization_model_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        open_folder(str(folder))

    def _start_download(self):
        if self.download_thread and self.download_thread.isRunning():
            return
        self.download_button.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.progress_label.setText("正在连接下载源...")
        self.progress_label.show()
        self.download_thread = DiarizationModelDownloadThread(self)
        self.download_thread.progress.connect(self._on_progress)
        self.download_thread.succeeded.connect(self._on_download_succeeded)
        self.download_thread.failed.connect(self._on_download_failed)
        self.download_thread.start()

    def _on_progress(self, value: float, message: str):
        if value >= 0:
            self.progress_bar.setValue(int(value))
        self.progress_label.setText(message)

    def _on_download_succeeded(self, _path: str):
        self.progress_bar.setValue(100)
        self.progress_label.setText("多语种说话人识别模型下载完成")
        self.download_button.setEnabled(True)
        self.cancelButton.setEnabled(True)
        self._refresh_status()
        InfoBar.success(
            title="下载成功",
            content="多语种说话人识别模型已可用",
            duration=3000,
            parent=self,
        )

    def _on_download_failed(self, message: str):
        self.download_button.setEnabled(True)
        self.cancelButton.setEnabled(True)
        self.progress_bar.hide()
        self.progress_label.hide()
        InfoBar.error(
            title="下载失败", content=message, duration=5000, parent=self
        )

    def reject(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.stop()
        super().reject()


class VideoInputCard(CardWidget):
    """视频优先输入卡片，只接受音视频文件。"""

    fileSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = ""
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addWidget(BodyLabel("源视频", self))
        self.drop_hint = QLabel("拖拽视频文件到这里\nMP4 / MKV / MOV / AVI / ...", self)
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setMinimumHeight(58)
        self.drop_hint.setStyleSheet(
            "QLabel { border: 2px dashed #666; border-radius: 4px; padding: 15px; color: #888; }"
        )
        layout.addWidget(self.drop_hint)
        self.select_btn = PushButton(FIF.FOLDER, "选择视频", self)
        self.select_btn.clicked.connect(self._select_file)
        layout.addWidget(self.select_btn, 0, Qt.AlignCenter)

    def _select_file(self):
        formats = " ".join(f"*.{item.value}" for item in SupportedVideoFormats)
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", f"视频文件 ({formats})")
        if path:
            self.set_file(path)

    def set_file(self, path: str):
        self.file_path = path
        self.drop_hint.setText(f"✓ {Path(path).name}")
        self.drop_hint.setStyleSheet(
            "QLabel { border: 1px solid #0078d4; border-radius: 4px; padding: 15px; color: #0078d4; }"
        )
        self.fileSelected.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower().lstrip(".") in {item.value for item in SupportedVideoFormats}:
                self.set_file(path)
                break


def _format_review_time(value) -> str:
    try:
        milliseconds = max(0, int(value))
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _review_srt_text(dropped: list[dict]) -> str:
    lines = []
    for number, item in enumerate(dropped, 1):
        start = _format_review_time(item.get("start_time")).replace(".", ",")
        end = _format_review_time(item.get("end_time")).replace(".", ",")
        lines.extend(
            [str(number), f"{start} --> {end}", str(item.get("text") or ""), ""]
        )
    return "\n".join(lines)


class NarratorReviewDialog(QDialog):
    """说话人过滤后的删除字幕复核。"""

    def __init__(
        self,
        report: dict,
        dropped: list[dict],
        parent=None,
        *,
        saved_review: bool = False,
        preselected: set[int] | None = None,
    ):
        super().__init__(parent)
        self.dropped = dropped
        self.saved_review = saved_review
        preselected = preselected or set()
        self.setWindowTitle("复核已删除字幕")
        self.resize(980, 540)
        FluentStyleSheet.FLUENT_WINDOW.apply(self)
        if isDarkTheme():
            self.setStyleSheet(
                """
                QDialog { background-color: #202020; color: #f2f2f2; }
                QTableWidget {
                    background-color: #2b2b2b;
                    alternate-background-color: #303030;
                    color: #f2f2f2;
                    gridline-color: #454545;
                    selection-background-color: #3a8f68;
                    selection-color: #ffffff;
                }
                QHeaderView::section {
                    background-color: #333333;
                    color: #f2f2f2;
                    border: 0;
                    border-bottom: 1px solid #454545;
                    padding: 5px;
                }
                QTableCornerButton::section {
                    background-color: #333333;
                    border: 0;
                    border-bottom: 1px solid #454545;
                }
                """
            )
        self.table = QTableWidget(self)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["恢复", "开始", "结束", "说话人", "字幕内容", "AI 标签", "删除原因"]
        )
        self.table.setRowCount(len(dropped))
        for row, item in enumerate(dropped):
            check = QTableWidgetItem()
            check.setCheckState(
                Qt.Checked
                if int(item.get("index", -1)) in preselected
                else Qt.Unchecked
            )
            self.table.setItem(row, 0, check)
            values = (
                _format_review_time(item.get("start_time")),
                _format_review_time(item.get("end_time")),
                str(item.get("speaker") or "未知"),
                str(item.get("text") or ""),
                str(item.get("llm_label") or "—"),
                str(item.get("llm_reason") or item.get("reason") or ""),
            )
            for column, value in enumerate(values, 1):
                self.table.setItem(row, column, QTableWidgetItem(value))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 95)
        self.table.setColumnWidth(2, 95)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 330)
        self.table.setColumnWidth(5, 85)
        summary_text = (
            f"主说话人: {report.get('narrator_speaker_id') or '未知'}，"
            f"实际删除 {len(dropped)} 条。"
        )
        summary_text += (
            "勾选后将在下次运行时恢复。"
            if saved_review
            else "勾选需要恢复的字幕。"
        )
        summary = BodyLabel(summary_text, self)
        self.continue_btn = PrimaryPushButton(
            FIF.ACCEPT,
            "保存下次恢复项" if saved_review else "恢复选中并继续",
            self,
        )
        self.continue_btn.clicked.connect(self.accept)
        cancel = PushButton(
            FIF.CANCEL, "关闭" if saved_review else "全部保留当前筛选", self
        )
        cancel.clicked.connect(self.reject)
        select_all = PushButton("全选", self)
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none = PushButton("全不选", self)
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        export = PushButton(FIF.SAVE, "导出删除字幕", self)
        export.clicked.connect(self._export_dropped)
        buttons = QHBoxLayout()
        buttons.addWidget(select_all)
        buttons.addWidget(select_none)
        buttons.addWidget(export)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.continue_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        if not saved_review:
            self._remaining_seconds = REVIEW_TIMEOUT_SECONDS
            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._tick_countdown)
            self._update_countdown_text()
            self._countdown_timer.start(1000)

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)

    def _export_dropped(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出被删除字幕", "被删除字幕.srt", "SRT 字幕 (*.srt)"
        )
        if path:
            Path(path).write_text(_review_srt_text(self.dropped), encoding="utf-8")

    def _tick_countdown(self):
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self._countdown_timer.stop()
            self.accept()
            return
        self._update_countdown_text()

    def _update_countdown_text(self):
        self.continue_btn.setText(
            f"继续流程（{self._remaining_seconds} 秒后自动）"
        )

    def restore_indices(self) -> list[int]:
        return [
            row
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.Checked
        ]


class VideoAlignmentInterface(QWidget):
    """视频转录、翻译、配音、画面对齐的一站式工作流。"""

    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("videoAlignmentInterface")
        self.workflow_thread = None
        self.preview_frame_thread = None
        self._preview_frame_threads = []
        self._diarization_model_dialog = None
        self._translation_review_timer = QTimer(self)
        self._translation_review_timer.timeout.connect(
            self._tick_translation_review
        )
        self._translation_review_remaining = 0
        self._config_loading = True
        self._setup_ui()
        self._load_config()
        self._refresh_tts_models()
        self._refresh_tts_voices()
        self._config_loading = False

    def _setup_ui(self):
        self.setStyleSheet("VideoAlignmentInterface { background: transparent; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")
        content = QWidget(self)
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.video_input = VideoInputCard(self)
        layout.addWidget(self.video_input)

        workflow_card = CardWidget(self)
        workflow = QVBoxLayout(workflow_card)
        workflow.setContentsMargins(12, 10, 12, 10)
        workflow.setSpacing(6)
        workflow.addWidget(BodyLabel("翻译流程设置", self))

        workflow_columns = QHBoxLayout()
        workflow_columns.setSpacing(18)
        workflow_left = QVBoxLayout()
        workflow_right = QVBoxLayout()
        workflow_left.setSpacing(5)
        workflow_right.setSpacing(5)
        self.transcribe_model_combo = self._enum_combo(workflow_left, "转录渠道 / 模型", TranscribeModelEnum, cfg.transcribe_model.value)
        self.source_language_combo = self._enum_combo(workflow_left, "源语言", TranscribeLanguageEnum, cfg.transcribe_language.value)
        self.target_language_combo = self._enum_combo(workflow_left, "目标语言", TargetLanguage, cfg.target_language.value)
        self.translator_combo = self._enum_combo(workflow_right, "字幕翻译渠道", TranslatorServiceEnum, cfg.translator_service.value)
        self.tts_provider_combo = ComboBox(self)
        self.tts_provider_combo.addItems([
            "edge - Edge TTS (免费)", "elevenlabs - ElevenLabs", "gemini - Gemini",
            "siliconflow - SiliconFlow", "openai - OpenAI TTS", "fishaudio - Fish Audio",
            "dots - Dots-TTS (本地)", "voxcpm - VoxCPM (本地)",
        ])
        self._add_widget_row(workflow_right, "配音渠道", self.tts_provider_combo)
        self.tts_model_combo = ComboBox(self)
        self.tts_model_combo.setPlaceholderText("当前渠道无需选择模型")
        self._add_widget_row(workflow_right, "配音模型", self.tts_model_combo)
        self.tts_voice_combo = ComboBox(self)
        self.tts_voice_combo.setPlaceholderText("选择音色")
        self._add_widget_row(workflow_right, "音色", self.tts_voice_combo)
        voice_hint = BodyLabel("API 密钥和参考音频沿用“配音”面板设置。", self)
        voice_hint.setStyleSheet("color: #888; font-size: 12px;")
        workflow_right.addWidget(voice_hint)
        self.optimize_switch = self._switch_row(workflow_right, "字幕校正", bool(cfg.need_optimize.value))
        workflow_columns.addLayout(workflow_left, 1)
        workflow_columns.addLayout(workflow_right, 1)
        workflow.addLayout(workflow_columns)
        split_row = QHBoxLayout()
        split_row.addWidget(BodyLabel("自动拆分字幕:", self))
        self.split_switch = SwitchButton(self)
        self.split_switch.setChecked(bool(cfg.need_split.value))
        split_row.addWidget(self.split_switch)
        split_row.addSpacing(12)
        split_row.addWidget(BodyLabel("中日韩上限", self))
        self.max_cjk_spin = SpinBox(self)
        self.max_cjk_spin.setRange(8, 100)
        self.max_cjk_spin.setValue(int(cfg.max_word_count_cjk.value))
        self.max_cjk_spin.setSuffix(" 字")
        self.max_cjk_spin.setFixedWidth(140)
        split_row.addWidget(self.max_cjk_spin)
        split_row.addWidget(BodyLabel("其他语言上限", self))
        self.max_words_spin = SpinBox(self)
        self.max_words_spin.setRange(8, 100)
        self.max_words_spin.setValue(int(cfg.max_word_count_english.value))
        self.max_words_spin.setSuffix(" 词")
        self.max_words_spin.setFixedWidth(140)
        split_row.addWidget(self.max_words_spin)
        split_row.addStretch()
        workflow.addLayout(split_row)
        layout.addWidget(workflow_card)

        self.options_card = CardWidget(self)
        options = QVBoxLayout(self.options_card)
        options.setContentsMargins(12, 10, 12, 10)
        options.setSpacing(6)
        options.addWidget(BodyLabel("全流程选项", self))
        options_columns = QHBoxLayout()
        options_columns.setSpacing(18)
        options_left = QVBoxLayout()
        options_right = QVBoxLayout()
        options_left.setSpacing(4)
        options_right.setSpacing(4)
        diarization_row = QHBoxLayout()
        diarization_row.addWidget(BodyLabel("说话人识别:", self))
        self.diarization_switch = SwitchButton(self)
        self.diarization_switch.setChecked(bool(cfg.dubbing_enable_diarization.value))
        diarization_row.addWidget(self.diarization_switch)
        diarization_row.addStretch()
        self.diarization_model_btn = PushButton(FIF.DOWNLOAD, "模型管理", self)
        self.diarization_model_btn.setToolTip("下载或重新下载多语种说话人识别模型")
        self.diarization_model_btn.clicked.connect(
            self._show_diarization_model_manager
        )
        diarization_row.addWidget(self.diarization_model_btn)
        options_left.addLayout(diarization_row)
        self.speaker_count_combo = self._combo_row(options_left, "说话人数上限", [("不限（自动）", 0), *( (f"{n} 人", n) for n in (2, 3, 4, 5, 6))])
        self.narrator_only_switch = self._switch_row(options_left, "仅保留解说", bool(cfg.dubbing_narrator_only.value))
        manual_review_row = QHBoxLayout()
        manual_review_row.addWidget(BodyLabel("删除字幕复核:", self))
        manual_review_row.addStretch()
        self.review_dropped_btn = PushButton(FIF.VIEW, "查看已删字幕", self)
        self.review_dropped_btn.setEnabled(False)
        self.review_dropped_btn.clicked.connect(self._open_saved_narrator_review)
        manual_review_row.addWidget(self.review_dropped_btn)
        options_left.addLayout(manual_review_row)
        self.llm_review_switch = self._switch_row(options_left, "LLM 复核删除字幕", bool(cfg.dubbing_narrator_llm_review.value))
        self.video_autorate_switch = self._switch_row(options_left, "画面变速对齐", bool(cfg.dubbing_video_autorate.value))
        self.random_mirror_switch = self._switch_row(options_left, "随机镜像", bool(cfg.dubbing_random_mirror.value))
        self.random_color_switch = self._switch_row(options_left, "随机调色", bool(cfg.dubbing_random_color.value))
        self.canvas_combo = self._combo_row(options_right, "统一画布", [("关闭", "off"), ("竖屏 1080x1920", "1080x1920"), ("横屏 1920x1080", "1920x1080")])
        self.embed_combo = ComboBox(self)
        self.embed_combo.addItem("无", userData="none")
        self.embed_combo.addItem("烧录硬字幕", userData="hard")
        embed_row = QHBoxLayout()
        embed_row.addWidget(BodyLabel("嵌入硬字幕:", self))
        embed_row.addWidget(self.embed_combo, 1)
        self.subtitle_style_btn = PushButton(FIF.FONT, "字幕样式", self)
        self.subtitle_style_btn.setToolTip("打开字幕样式配置")
        self.subtitle_style_btn.clicked.connect(self._open_subtitle_style)
        embed_row.addWidget(self.subtitle_style_btn)
        options_right.addLayout(embed_row)
        self.gap_ms_spin = self._spin_row(options_right, "语音间隔", 0, 2000, " ms", int(cfg.dubbing_subtitle_gap_ms.value))
        self.dubbed_gain_spin = self._spin_row(
            options_right,
            "主配音增益",
            -20,
            20,
            " dB",
            int(cfg.dubbing_dubbed_audio_gain_db.value),
        )
        self.separate_vocal_switch = self._switch_row(options_right, "分离人声背景声", bool(cfg.dubbing_separate_vocal.value))
        self.embed_bgm_switch = self._switch_row(options_right, "重新嵌入背景声", bool(cfg.dubbing_embed_bgm.value))
        self.bgm_loop_switch = self._switch_row(options_right, "背景音循环", bool(cfg.dubbing_bgm_loop.value))
        self.bgm_volume_slider, self.bgm_volume_spin = self._volume_row(
            options_right, float(cfg.dubbing_bgm_volume.value)
        )
        self.extra_bgm_edit = LineEdit(self)
        self.extra_bgm_edit.setReadOnly(True)
        self.extra_bgm_edit.setText(cfg.dubbing_extra_bgm_path.value or "")
        self._add_widget_row(options_right, "额外背景音频", self.extra_bgm_edit, browse=True, clear=True)
        self.output_dir_edit = LineEdit(self)
        self.output_dir_edit.setReadOnly(True)
        self.output_dir_edit.setPlaceholderText("留空：在源视频旁创建“视频名_视频翻译”文件夹")
        self.output_dir_edit.setText(cfg.dubbing_output_dir.value or "")
        self._add_widget_row(options_right, "输出目录", self.output_dir_edit, directory=True, clear=True)
        options_columns.addLayout(options_left, 1)
        options_columns.addLayout(options_right, 1)
        options.addLayout(options_columns)
        layout.addWidget(self.options_card)

        self.editor_title = BodyLabel("字幕翻译表格（转录完成后可编辑）", self)
        self.editor_title.setVisible(False)
        layout.addWidget(self.editor_title)
        self.subtitle_editor = SubtitleInterface(self)
        self.subtitle_editor.command_bar.hide()
        self.subtitle_editor.start_button.hide()
        self.subtitle_editor.remove_widget()
        self.subtitle_editor.setMinimumHeight(360)
        self.subtitle_editor.setVisible(False)
        layout.addWidget(self.subtitle_editor)
        self.confirm_translation_btn = PrimaryPushButton(FIF.ACCEPT, "确认字幕并开始配音", self)
        self.confirm_translation_btn.setVisible(False)
        self.confirm_translation_btn.clicked.connect(self._confirm_translation)
        layout.addWidget(self.confirm_translation_btn)

        self.start_btn = PrimaryPushButton(FIF.PLAY, "选择视频后开始全流程", self)
        self.start_btn.clicked.connect(self._start)
        layout.addWidget(self.start_btn)
        self.open_folder_btn = PushButton(FIF.FOLDER, "打开输出目录", self)
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        layout.addWidget(self.open_folder_btn)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = BodyLabel("", self)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.scroll_area.setWidget(content)
        root.addWidget(self.scroll_area)

        self.video_input.fileSelected.connect(self._on_video_selected)
        self.tts_provider_combo.currentIndexChanged.connect(self._on_tts_provider_changed)
        self.target_language_combo.currentIndexChanged.connect(self._refresh_tts_voices)
        for widget in (
            self.transcribe_model_combo, self.source_language_combo,
            self.target_language_combo, self.translator_combo,
            self.tts_model_combo, self.tts_voice_combo,
            self.optimize_switch, self.split_switch, self.max_cjk_spin,
            self.max_words_spin, self.diarization_switch, self.speaker_count_combo,
            self.narrator_only_switch, self.llm_review_switch,
            self.video_autorate_switch, self.random_mirror_switch, self.random_color_switch,
            self.canvas_combo, self.embed_combo, self.gap_ms_spin,
            self.dubbed_gain_spin,
            self.separate_vocal_switch, self.embed_bgm_switch, self.bgm_loop_switch,
            self.bgm_volume_slider, self.bgm_volume_spin, self.extra_bgm_edit,
            self.output_dir_edit,
        ):
            signal = getattr(widget, "checkedChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "textChanged", None)
            if signal:
                signal.connect(self._persist)
        self.diarization_switch.checkedChanged.connect(self._update_enabled)
        self.split_switch.checkedChanged.connect(self._update_enabled)
        self.narrator_only_switch.checkedChanged.connect(self._update_enabled)
        self.embed_bgm_switch.checkedChanged.connect(self._update_enabled)
        self.separate_vocal_switch.checkedChanged.connect(self._update_enabled)
        self.extra_bgm_edit.textChanged.connect(self._update_enabled)
        self._update_enabled()

    def _enum_combo(self, layout, label, enum_type, value):
        combo = ComboBox(self)
        for item in enum_type:
            combo.addItem(item.value, userData=item)
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        self._add_widget_row(layout, label, combo)
        return combo

    def _add_widget_row(self, layout, label, widget, browse=False, clear=False, directory=False):
        row = QHBoxLayout()
        row.addWidget(BodyLabel(f"{label}:", self))
        row.addWidget(widget, 1)
        if browse or directory:
            button = ToolButton(FIF.FOLDER, self)
            button.clicked.connect(lambda: self._browse_path(widget, directory))
            row.addWidget(button)
        if clear:
            button = ToolButton(FIF.DELETE, self)
            button.clicked.connect(widget.clear)
            row.addWidget(button)
        layout.addLayout(row)

    def _switch_row(self, layout, label, value=False):
        switch = SwitchButton(self)
        switch.setChecked(value)
        row = QHBoxLayout()
        row.addWidget(BodyLabel(f"{label}:", self))
        row.addWidget(switch)
        row.addStretch()
        layout.addLayout(row)
        return switch

    def _combo_row(self, layout, label, items):
        combo = ComboBox(self)
        for text, data in items:
            combo.addItem(text, userData=data)
        row = QHBoxLayout()
        row.addWidget(BodyLabel(f"{label}:", self))
        row.addWidget(combo)
        row.addStretch()
        layout.addLayout(row)
        return combo

    def _spin_row(self, layout, label, minimum, maximum, suffix, value):
        spin = SpinBox(self)
        spin.setRange(minimum, maximum)
        spin.setSuffix(suffix)
        spin.setValue(value)
        row = QHBoxLayout()
        row.addWidget(BodyLabel(f"{label}:", self))
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    def _volume_row(self, layout, value):
        slider = Slider(Qt.Horizontal, self)
        slider.setRange(0, 100)
        spin = DoubleSpinBox(self)
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(value)
        slider.setValue(round(value * 100))
        slider.valueChanged.connect(lambda v: spin.setValue(v / 100))
        spin.valueChanged.connect(lambda v: slider.setValue(round(v * 100)))
        row = QHBoxLayout()
        row.addWidget(BodyLabel("背景音量:", self))
        row.addWidget(slider)
        row.addWidget(spin)
        layout.addLayout(row)
        return slider, spin

    def _browse_path(self, widget, directory=False):
        if directory:
            path = QFileDialog.getExistingDirectory(self, "选择输出目录", widget.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择背景音频", "", "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)")
        if path:
            widget.setText(path)

    def _open_subtitle_style(self):
        main_window = self.window()
        style_interface = getattr(main_window, "subtitleStyleInterface", None)
        switch_to = getattr(main_window, "switchTo", None)
        if style_interface is not None and callable(switch_to):
            switch_to(style_interface)
            style_interface.updatePreview()
            return
        self._warn("无法打开字幕样式", "请从左侧导航栏打开“字幕样式”")

    def _show_diarization_model_manager(self):
        if self._diarization_model_dialog is None:
            self._diarization_model_dialog = DiarizationModelDownloadDialog(self)
        self._diarization_model_dialog.exec_()

    def _requires_multilingual_diarization(self) -> bool:
        language = diarization_language_from_transcribe(
            self.source_language_combo.currentData()
        )
        return language not in {"zh", "en"}

    def _on_video_selected(self, path: str):
        self.start_btn.setEnabled(True)
        self._last_narrator_review_path = ""
        self._refresh_narrator_review_button()
        self._preview_frame_threads = [
            thread for thread in self._preview_frame_threads if thread.isRunning()
        ]

        video_path = Path(path)
        try:
            stat = video_path.stat()
        except OSError:
            return

        fingerprint = f"{video_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
        cache_key = sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
        thumbnail_path = (
            Path(cfg.work_dir.value) / "subtitle_preview" / f"{cache_key}.jpg"
        )
        if thumbnail_path.is_file():
            self._set_subtitle_preview_background(str(thumbnail_path), path)
            return

        thread = VideoInfoThread(path, str(thumbnail_path))
        self.preview_frame_thread = thread
        self._preview_frame_threads.append(thread)
        thread.finished.connect(
            lambda info: self._on_preview_frame_ready(info.thumbnail_path, path)
        )
        thread.start()

    def _on_preview_frame_ready(self, thumbnail_path: str, selected_video: str):
        if thumbnail_path and Path(thumbnail_path).is_file():
            self._set_subtitle_preview_background(thumbnail_path, selected_video)

    def _set_subtitle_preview_background(self, thumbnail_path: str, selected_video: str):
        if self.video_input.file_path != selected_video:
            return
        cfg.set(cfg.subtitle_preview_image, thumbnail_path)
        style_interface = getattr(self.window(), "subtitleStyleInterface", None)
        if style_interface is not None:
            style_interface.updatePreview()

    def _load_config(self):
        provider = cfg.dubbing_provider.value or "edge"
        for index in range(self.tts_provider_combo.count()):
            if self.tts_provider_combo.itemText(index).startswith(provider):
                self.tts_provider_combo.setCurrentIndex(index)
                break
        index = self.speaker_count_combo.findData(int(cfg.dubbing_speaker_count.value or 0))
        self.speaker_count_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.canvas_combo.findData(cfg.dubbing_canvas.value or "off")
        self.canvas_combo.setCurrentIndex(index if index >= 0 else 0)
        index = self.embed_combo.findData(cfg.dubbing_embed_subtitle.value or "none")
        self.embed_combo.setCurrentIndex(index if index >= 0 else 0)

    def _tts_provider_id(self) -> str:
        return self.tts_provider_combo.currentText().split(" - ", 1)[0].strip().lower()

    def _on_tts_provider_changed(self, *_args):
        self._refresh_tts_models()
        self._refresh_tts_voices()
        self._persist()

    def _refresh_tts_models(self):
        provider = self._tts_provider_id()
        options = dubbing_model_options(provider)
        saved_model = ""
        if (cfg.dubbing_provider.value or "edge") == provider:
            saved_model = (cfg.dubbing_model.value or "").strip()

        self.tts_model_combo.blockSignals(True)
        self.tts_model_combo.clear()
        for text, model in options:
            self.tts_model_combo.addItem(text, userData=model)
        if options:
            model = resolve_dubbing_model(provider, saved_model)
            index = self.tts_model_combo.findData(model)
            self.tts_model_combo.setCurrentIndex(index if index >= 0 else 0)
            self.tts_model_combo.setEnabled(True)
        else:
            model = resolve_dubbing_model(provider, saved_model)
            self.tts_model_combo.addItem("当前渠道使用默认模型", userData=model)
            self.tts_model_combo.setEnabled(False)
        self.tts_model_combo.blockSignals(False)

    def _refresh_tts_voices(self, *_args):
        provider = self._tts_provider_id()
        options = alignment_voice_options(provider, self.target_language_combo.currentData())
        saved_voice = ""
        if (cfg.dubbing_provider.value or "edge") == provider:
            saved_voice = (cfg.dubbing_voice.value or "").strip()
        option_ids = {voice for _name, voice in options}
        if provider != "edge" and saved_voice and saved_voice not in option_ids:
            options.append((f"当前音色 - {saved_voice}", saved_voice))
            option_ids.add(saved_voice)

        self.tts_voice_combo.blockSignals(True)
        self.tts_voice_combo.clear()
        if not options:
            self.tts_voice_combo.addItem("使用“配音”面板的参考音频", userData="")
            self.tts_voice_combo.setEnabled(False)
        else:
            for name, voice in options:
                self.tts_voice_combo.addItem(name, userData=voice)
            target = saved_voice if saved_voice in option_ids else _DEFAULT_VOICES.get(provider)
            index = self.tts_voice_combo.findData(target)
            self.tts_voice_combo.setCurrentIndex(index if index >= 0 else 0)
            self.tts_voice_combo.setEnabled(True)
        self.tts_voice_combo.blockSignals(False)

    def _persist(self, *_args):
        if self._config_loading:
            return
        cfg.transcribe_model.value = self.transcribe_model_combo.currentData()
        cfg.transcribe_language.value = self.source_language_combo.currentData()
        cfg.target_language.value = self.target_language_combo.currentData()
        cfg.translator_service.value = self.translator_combo.currentData()
        cfg.need_translate.value = True
        cfg.need_optimize.value = self.optimize_switch.isChecked()
        cfg.need_split.value = self.split_switch.isChecked()
        cfg.max_word_count_cjk.value = self.max_cjk_spin.value()
        cfg.max_word_count_english.value = self.max_words_spin.value()
        provider = self._tts_provider_id()
        cfg.dubbing_provider.value = provider
        cfg.dubbing_model.value = resolve_dubbing_model(
            provider, str(self.tts_model_combo.currentData() or "")
        )
        cfg.dubbing_voice.value = resolve_dubbing_voice(
            provider, str(self.tts_voice_combo.currentData() or "")
        )
        cfg.dubbing_enable_diarization.value = self.diarization_switch.isChecked()
        cfg.dubbing_speaker_count.value = int(self.speaker_count_combo.currentData() or 0)
        cfg.dubbing_narrator_only.value = self.narrator_only_switch.isChecked()
        cfg.dubbing_narrator_llm_review.value = self.llm_review_switch.isChecked()
        cfg.dubbing_video_autorate.value = self.video_autorate_switch.isChecked()
        cfg.dubbing_random_mirror.value = self.random_mirror_switch.isChecked()
        cfg.dubbing_random_color.value = self.random_color_switch.isChecked()
        cfg.dubbing_canvas.value = self.canvas_combo.currentData() or "off"
        cfg.dubbing_embed_subtitle.value = self.embed_combo.currentData() or "none"
        cfg.dubbing_subtitle_gap_ms.value = self.gap_ms_spin.value()
        cfg.dubbing_dubbed_audio_gain_db.value = self.dubbed_gain_spin.value()
        cfg.dubbing_separate_vocal.value = self.separate_vocal_switch.isChecked()
        cfg.dubbing_embed_bgm.value = self.embed_bgm_switch.isChecked()
        cfg.dubbing_bgm_loop.value = self.bgm_loop_switch.isChecked()
        cfg.dubbing_bgm_volume.value = self.bgm_volume_spin.value()
        cfg.dubbing_extra_bgm_path.value = self.extra_bgm_edit.text().strip()
        cfg.dubbing_output_dir.value = self.output_dir_edit.text().strip()
        cfg.save()

    def _update_enabled(self, *_args):
        split_enabled = self.split_switch.isChecked()
        self.max_cjk_spin.setEnabled(split_enabled)
        self.max_words_spin.setEnabled(split_enabled)
        enabled = self.diarization_switch.isChecked()
        self.speaker_count_combo.setEnabled(enabled)
        self.narrator_only_switch.setEnabled(enabled)
        self.llm_review_switch.setEnabled(enabled and self.narrator_only_switch.isChecked())
        bgm_enabled = self.embed_bgm_switch.isChecked() or bool(
            self.extra_bgm_edit.text().strip()
        )
        self.bgm_loop_switch.setEnabled(bgm_enabled)
        self.bgm_volume_slider.setEnabled(bgm_enabled)
        self.bgm_volume_spin.setEnabled(bgm_enabled)

    def _start(self):
        self._translation_review_timer.stop()
        self._persist()
        if not self.video_input.file_path:
            self._warn("请选择视频", "视频翻译流程必须先选择源视频文件")
            return
        if (
            self.diarization_switch.isChecked()
            and self._requires_multilingual_diarization()
            and not _multilingual_diarization_model_ready()
        ):
            self._warn(
                "需要下载模型",
                "当前源语言需要多语种说话人识别模型，请先完成下载",
            )
            self._show_diarization_model_manager()
            return
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setVisible(True)
        self.status_label.setText("准备中...")
        self.workflow_thread = VideoTranslationThread(
            self.video_input.file_path,
            manual_review=False,
            translation_review=True,
        )
        self.workflow_thread.progress.connect(self._on_progress)
        self.workflow_thread.narrator_review_saved.connect(self._on_narrator_review_saved)
        self.workflow_thread.translation_ready.connect(self._on_translation_ready)
        self.workflow_thread.error.connect(self._on_error)
        self.workflow_thread.finished.connect(self._on_finished)
        self.workflow_thread.start()

    def _review_path(self) -> Path | None:
        saved = Path(getattr(self, "_last_narrator_review_path", ""))
        if saved.is_file():
            return saved
        if not self.video_input.file_path:
            return None
        output = _job_output_dir(
            Path(self.video_input.file_path), self.output_dir_edit.text()
        )
        reviews = sorted(
            (output / "中间文件").glob("*-narrator-review.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return reviews[0] if reviews else None

    def _refresh_narrator_review_button(self):
        path = self._review_path()
        self.review_dropped_btn.setEnabled(path is not None)
        self.review_dropped_btn.setToolTip(
            str(path) if path else "完成一次说话人筛选后可查看实际删除的字幕"
        )

    def _on_narrator_review_saved(self, path: str):
        self._last_narrator_review_path = path
        self._refresh_narrator_review_button()

    def _open_saved_narrator_review(self):
        path = self._review_path()
        if path is None:
            self._warn("暂无删除记录", "请先完成一次说话人筛选")
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            dropped = payload.get("dropped") or []
            dialog = NarratorReviewDialog(
                payload.get("report") or {},
                dropped,
                self,
                saved_review=True,
                preselected={
                    int(index) for index in payload.get("restore_on_next_run", [])
                },
            )
            if dialog.exec_():
                rows = dialog.restore_indices()
                payload["restore_on_next_run"] = [
                    dropped[row]["index"] for row in rows if row < len(dropped)
                ]
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                InfoBar.success(
                    title="复核记录已保存",
                    content="勾选字幕会在下次运行时恢复，现有成片不会被直接修改",
                    duration=3000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
        except Exception as exc:
            self._warn("读取删除记录失败", str(exc))

    def _on_translation_ready(self, subtitle_path):
        task = TaskFactory.create_subtitle_task(subtitle_path, self.video_input.file_path, need_next_task=True)
        task.subtitle_path = subtitle_path
        task.output_path = subtitle_path
        self.subtitle_editor.set_task(task)
        self.editor_title.setVisible(True)
        self.subtitle_editor.setVisible(True)
        self.confirm_translation_btn.setEnabled(True)
        self.confirm_translation_btn.setVisible(True)
        self._translation_review_remaining = REVIEW_TIMEOUT_SECONDS
        self._update_translation_review_text()
        self._translation_review_timer.start(1000)
        self.status_label.setText("请检查并编辑翻译字幕，倒计时结束后自动继续")

    def _tick_translation_review(self):
        self._translation_review_remaining -= 1
        if self._translation_review_remaining <= 0:
            self._confirm_translation()
            return
        self._update_translation_review_text()

    def _update_translation_review_text(self):
        self.confirm_translation_btn.setText(
            f"确认字幕并开始配音（{self._translation_review_remaining} 秒后自动）"
        )

    def _confirm_translation(self):
        if not self.confirm_translation_btn.isVisible() or not self.confirm_translation_btn.isEnabled():
            return
        self._translation_review_timer.stop()
        self.confirm_translation_btn.setEnabled(False)
        self.confirm_translation_btn.setText("正在保存字幕并开始配音...")
        self.status_label.setText("正在保存字幕并开始配音...")
        QApplication.processEvents()
        QTimer.singleShot(0, self._finish_translation_review)

    def _finish_translation_review(self):
        try:
            if self.subtitle_editor.model._data and self.subtitle_editor.subtitle_path:
                from videocaptioner.core.asr.asr_data import ASRData

                ASRData.from_json(self.subtitle_editor.model._data).to_srt(
                    layout=SubtitleLayoutEnum.ONLY_TRANSLATE,
                    save_path=self.subtitle_editor.subtitle_path,
                )
        except Exception as exc:
            if self.workflow_thread:
                self.workflow_thread.cancel()
            self._on_error(f"保存复核字幕失败: {exc}")
            return
        self.editor_title.setVisible(False)
        self.subtitle_editor.setVisible(False)
        self.confirm_translation_btn.setVisible(False)
        if self.workflow_thread:
            self.workflow_thread.continue_translation()

    def _on_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def _on_error(self, message):
        self._translation_review_timer.stop()
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"失败: {message}")
        InfoBar.error(title="视频翻译失败", content=message, duration=INFOBAR_DURATION_ERROR, position=InfoBarPosition.TOP, parent=self)

    def _on_finished(self, output_path):
        self._translation_review_timer.stop()
        self.start_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("视频翻译完成")
        self._last_output_path = output_path
        self.open_folder_btn.setVisible(True)
        self._refresh_narrator_review_button()
        self.finished.emit(output_path)

    def _open_output_folder(self):
        import os

        output = getattr(self, "_last_output_path", "")
        folder = str(Path(output).parent) if output else self.output_dir_edit.text().strip()
        if folder and Path(folder).exists():
            os.startfile(folder)

    def _warn(self, title, content):
        InfoBar.warning(title=title, content=content, duration=INFOBAR_DURATION_WARNING, position=InfoBarPosition.TOP, parent=self)

    def closeEvent(self, event):
        self._translation_review_timer.stop()
        if self.workflow_thread and self.workflow_thread.isRunning():
            self.workflow_thread.cancel()
        super().closeEvent(event)
