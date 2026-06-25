# -*- coding: utf-8 -*-
"""配音界面 - 支持字幕文件配音和文案直接配音"""

import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    Slider,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from videocaptioner.config import BIN_PATH, CACHE_PATH

from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.entities import SupportedSubtitleFormats
from videocaptioner.core.speech.api_keys import parse_api_keys
from videocaptioner.core.tts.local_tts_defaults import (
    DEFAULT_DOTS_PACKAGE_URL,
    DEFAULT_VOXCPM_PACKAGE_URL,
    DOTS_TTS_PROJECT_URL,
    PYVIDEOTRANS_F5_TTS_BUNDLE_URL,
    PYVIDEOTRANS_F5TTS_TUTORIAL_URL,
    VOXCPM_PROJECT_URL,
)
from videocaptioner.core.voices.loader import get_all_languages, get_voices_by_language
from videocaptioner.ui.components.ApiKeysEditorDialog import ApiKeysEditorDialog
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.task_factory import resolve_dubbing_voice
from videocaptioner.ui.thread.dubbing_interface_thread import DubbingInterfaceThread
from videocaptioner.ui.thread.file_download_thread import Aria2Downloader, RequestsDownloader


class SubtitleInputCard(CardWidget):
    """字幕文件输入卡片"""

    fileSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.setup_ui()

    def setup_ui(self):
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title = BodyLabel("字幕文件", self)
        layout.addWidget(title)

        self.drop_hint = QLabel("拖拽字幕文件\nSRT / ASS / VTT", self)
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setWordWrap(True)
        self.drop_hint.setMinimumHeight(72)
        self.drop_hint.setStyleSheet(
            "QLabel { border: 2px dashed #666; border-radius: 4px; "
            "padding: 12px 10px; color: #888; font-size: 13px; }"
        )
        layout.addWidget(self.drop_hint, 1)

        self.select_btn = PushButton(FIF.DOCUMENT, "选择文件", self)
        self.select_btn.clicked.connect(self._select_file)
        layout.addWidget(self.select_btn, 0, Qt.AlignCenter)

    def _select_file(self):
        valid_formats = [f"*.{fmt.value}" for fmt in SupportedSubtitleFormats]
        filters = f"字幕文件 ({' '.join(valid_formats)});;所有文件 (*.*)"

        file_path, _ = QFileDialog.getOpenFileName(self, "选择字幕文件", "", filters)
        if file_path:
            self._set_file(file_path)

    def _set_file(self, file_path: str):
        self.file_path = file_path
        file_name = Path(file_path).name
        self.drop_hint.setText(f"✓ {file_name}")
        self.drop_hint.setWordWrap(True)  # 启用自动换行
        self.drop_hint.setStyleSheet(
            "QLabel { border: 1px solid #0078d4; border-radius: 4px; "
            "padding: 15px; color: #0078d4; font-size: 13px; }"
        )
        self.fileSelected.emit(file_path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        if files:
            self._set_file(files[0])

    def get_file_path(self) -> Optional[str]:
        return self.file_path


class TextInputCard(CardWidget):
    """文案输入卡片"""

    textChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 标题栏
        header_layout = QHBoxLayout()
        title = BodyLabel("配音文案", self)
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.char_count_label = BodyLabel("0 字符", self)
        self.char_count_label.setStyleSheet("color: #888;")
        header_layout.addWidget(self.char_count_label)

        layout.addLayout(header_layout)

        # 文本输入框
        self.text_edit = PlainTextEdit(self)
        self.text_edit.setPlaceholderText(
            "在这里输入需要配音的文案...\n\n"
            "支持多行文本，会自动分段。\n"
            "适用于广告词、旁白、有声书等场景。"
        )
        self.text_edit.setMinimumHeight(180)
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        # 按钮栏
        btn_layout = QHBoxLayout()
        self.import_btn = PushButton(FIF.DOCUMENT, "导入TXT", self)
        self.import_btn.clicked.connect(self._import_file)
        self.clear_btn = ToolButton(FIF.DELETE, self)
        self.clear_btn.clicked.connect(self.text_edit.clear)

        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    def _on_text_changed(self):
        text = self.text_edit.toPlainText()
        self.char_count_label.setText(f"{len(text)} 字符")
        self.textChanged.emit()

    def _import_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文本文件", "", "文本文件 (*.txt *.md);;所有文件 (*.*)"
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.text_edit.setPlainText(f.read())
            except Exception as e:
                InfoBar.error(
                    title="导入失败",
                    content=f"无法读取文件: {str(e)}",
                    duration=INFOBAR_DURATION_ERROR,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()


class DubbingInterface(QWidget):
    """配音主界面"""

    finished = pyqtSignal(str)  # 输出文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dubbingInterface")
        self.worker_thread = None
        self.quota_poll_timer = None  # 配额轮询定时器
        self.last_quota_percentage = 0  # 上次查询的配额百分比
        self.is_playing = False  # 音频播放状态
        self._config_loading = False
        self.setup_ui()
        self._connect_dubbing_auto_save()
        self.load_config()

    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        self.scroll_widget = QWidget(self)
        self.scroll_widget.setStyleSheet("background: transparent;")
        main_layout = QHBoxLayout(self.scroll_widget)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 左侧布局
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)

        # 配音模式选择
        mode_card = CardWidget(self)
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(15, 15, 15, 15)

        mode_title = BodyLabel("配音模式", self)
        mode_layout.addWidget(mode_title)

        self.mode_subtitle = QRadioButton("字幕文件配音", self)
        self.mode_text = QRadioButton("文案直接配音", self)
        self.mode_subtitle.setChecked(True)

        # 设置单选按钮样式，使用白色字体
        radio_style = "QRadioButton { font-weight: normal; font-size: 14px; color: white; }"
        self.mode_subtitle.setStyleSheet(radio_style)
        self.mode_text.setStyleSheet(radio_style)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_subtitle)
        self.mode_group.addButton(self.mode_text)

        mode_layout.addWidget(self.mode_subtitle)
        mode_layout.addWidget(self.mode_text)

        left_layout.addWidget(mode_card)

        # 输入区域（字幕文件）
        self.subtitle_input = SubtitleInputCard(self)
        left_layout.addWidget(self.subtitle_input)

        # 输入区域（文案文本）
        self.text_input = TextInputCard(self)
        self.text_input.setVisible(False)
        left_layout.addWidget(self.text_input)

        # 配音引擎
        engine_card = CardWidget(self)
        engine_layout = QVBoxLayout(engine_card)
        engine_layout.setContentsMargins(15, 15, 15, 15)
        engine_layout.setSpacing(8)

        engine_title = BodyLabel("配音引擎", self)
        engine_layout.addWidget(engine_title)

        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems([
            "edge - Edge TTS (免费)",
            "elevenlabs - ElevenLabs",
            "gemini - Gemini",
            "siliconflow - SiliconFlow",
            "openai - OpenAI TTS",
            "dots - Dots-TTS (本地)",
            "voxcpm - VoxCPM (本地)",
        ])
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        engine_layout.addWidget(self.provider_combo)

        left_layout.addWidget(engine_card)

        # 语言和音色设置
        voice_card = CardWidget(self)
        voice_layout = QVBoxLayout(voice_card)
        voice_layout.setContentsMargins(15, 15, 15, 15)
        voice_layout.setSpacing(10)

        voice_title = BodyLabel("语言与音色", self)
        voice_layout.addWidget(voice_title)

        # 语言选择
        lang_layout = QHBoxLayout()
        lang_layout.setSpacing(8)
        lang_label = BodyLabel("语言:", self)
        lang_label.setFixedWidth(60)
        lang_layout.addWidget(lang_label)

        self.language_combo = ComboBox(self)
        self.language_combo.setPlaceholderText("选择语言")
        lang_layout.addWidget(self.language_combo, 1)
        voice_layout.addLayout(lang_layout)

        # 音色选择
        voice_select_layout = QHBoxLayout()
        voice_select_layout.setSpacing(8)
        voice_label = BodyLabel("音色:", self)
        voice_label.setFixedWidth(60)
        voice_select_layout.addWidget(voice_label)

        self.voice_combo = ComboBox(self)
        self.voice_combo.setPlaceholderText("选择音色")
        voice_select_layout.addWidget(self.voice_combo, 1)

        # 试听按钮
        self.preview_btn = ToolButton(FIF.PLAY_SOLID, self)
        self.preview_btn.setToolTip("试听音色")
        self.preview_btn.clicked.connect(self._preview_voice)
        voice_select_layout.addWidget(self.preview_btn)

        voice_layout.addLayout(voice_select_layout)

        # 模型选择（仅 ElevenLabs 可见）
        model_layout = QHBoxLayout()
        model_layout.setSpacing(8)
        self.model_label = BodyLabel("模型:", self)
        self.model_label.setFixedWidth(60)
        model_layout.addWidget(self.model_label)

        self.model_combo = ComboBox(self)
        self.model_combo.addItems([
            "eleven_flash_v2_5 - Flash v2.5 快速（推荐）",
            "eleven_multilingual_v2 - Multilingual v2 高保真",
            "eleven_v3 - v3 最强表现力 70+语言",
            "eleven_turbo_v2_5 - Turbo v2.5 快速",
            "eleven_monolingual_v1 - Monolingual v1 仅英文",
        ])
        model_layout.addWidget(self.model_combo, 1)
        voice_layout.addLayout(model_layout)

        clone_audio_layout = QHBoxLayout()
        self.clone_audio_label = BodyLabel("参考音频:", self)
        self.clone_audio_label.setFixedWidth(60)
        clone_audio_layout.addWidget(self.clone_audio_label)
        self.clone_audio_edit = LineEdit(self)
        self.clone_audio_edit.setPlaceholderText("选择或粘贴 wav/mp3/flac 参考音频路径")
        self.clone_audio_edit.textChanged.connect(self._on_clone_audio_changed)
        clone_audio_layout.addWidget(self.clone_audio_edit, 1)
        self.clone_btn = ToolButton(FIF.FOLDER, self)
        self.clone_btn.setToolTip("选择参考音频")
        self.clone_btn.clicked.connect(self._select_clone_audio)
        clone_audio_layout.addWidget(self.clone_btn)
        voice_layout.addLayout(clone_audio_layout)

        self.clone_summary = BodyLabel("", self)
        self.clone_summary.setStyleSheet("color: #888; font-size: 12px;")
        voice_layout.addWidget(self.clone_summary)

        self.clone_text_label = BodyLabel("参考文本:", self)
        self.clone_text_label.setVisible(False)
        voice_layout.addWidget(self.clone_text_label)

        self.clone_text_edit = PlainTextEdit(self)
        self.clone_text_edit.setPlaceholderText("输入参考音频对应的文字内容")
        self.clone_text_edit.setMinimumHeight(96)
        self.clone_text_edit.setVisible(False)
        voice_layout.addWidget(self.clone_text_edit)

        self.clone_hint_label = BodyLabel("", self)
        self.clone_hint_label.setStyleSheet("color: #888; font-size: 12px;")
        self.clone_hint_label.setVisible(False)
        voice_layout.addWidget(self.clone_hint_label)

        self.clone_audio_path = ""
        self.clone_audio_text = ""

        # 默认隐藏模型选择
        self.model_label.setVisible(False)
        self.model_combo.setVisible(False)

        # 提示信息
        self.hint_label = BodyLabel("💡 选择语言后自动加载音色列表", self)
        self.hint_label.setStyleSheet("color: #888; font-size: 12px;")
        voice_layout.addWidget(self.hint_label)

        left_layout.addWidget(voice_card)

        left_layout.addStretch()

        # 右侧布局
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)

        # 配音参数
        params_card = CardWidget(self)
        params_layout = QVBoxLayout(params_card)
        params_layout.setContentsMargins(15, 15, 15, 15)
        params_layout.setSpacing(10)

        params_title = BodyLabel("配音参数", self)
        params_layout.addWidget(params_title)

        # 时间策略
        timing_layout = QHBoxLayout()
        timing_layout.addWidget(BodyLabel("时间策略:", self))
        self.timing_combo = ComboBox(self)
        self.timing_combo.addItems([
            "balanced - 平衡模式",
            "strict - 严格对齐",
            "natural - 自然语速",
            "none - 不限制"
        ])
        timing_layout.addWidget(self.timing_combo)
        timing_layout.addStretch()
        params_layout.addLayout(timing_layout)

        # 音频模式
        audio_layout = QHBoxLayout()
        audio_layout.addWidget(BodyLabel("音频模式:", self))
        self.audio_mode_combo = ComboBox(self)
        self.audio_mode_combo.addItems([
            "replace - 替换原音",
            "mix - 混合原音",
            "duck - 压低原音"
        ])
        audio_layout.addWidget(self.audio_mode_combo)
        audio_layout.addStretch()
        params_layout.addLayout(audio_layout)

        # 自动调整
        self.adapt_switch = SwitchButton(self)
        adapt_layout = QHBoxLayout()
        adapt_layout.addWidget(BodyLabel("自动调整过长行:", self))
        adapt_layout.addWidget(self.adapt_switch)
        adapt_layout.addStretch()
        params_layout.addLayout(adapt_layout)

        # 固定停顿
        pause_layout = QHBoxLayout()
        self.pause_switch = SwitchButton(self)
        self.pause_switch.checkedChanged.connect(self._on_pause_toggled)
        pause_layout.addWidget(BodyLabel("固定停顿:", self))
        pause_layout.addWidget(self.pause_switch)
        pause_layout.addStretch()
        params_layout.addLayout(pause_layout)

        pause_ms_layout = QHBoxLayout()
        pause_ms_layout.addWidget(BodyLabel("停顿时长:", self))
        self.pause_ms_spin = SpinBox(self)
        self.pause_ms_spin.setRange(100, 5000)
        self.pause_ms_spin.setValue(1000)
        self.pause_ms_spin.setSuffix(" ms")
        pause_ms_layout.addWidget(self.pause_ms_spin)
        pause_ms_layout.addStretch()
        params_layout.addLayout(pause_ms_layout)

        # 语速控制
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(BodyLabel("语速:", self))

        self.speed_slider = Slider(Qt.Horizontal, self)
        self.speed_slider.setRange(50, 200)  # 0.5x 到 2.0x
        self.speed_slider.setValue(100)  # 默认 1.0x
        self.speed_slider.setFixedWidth(180)
        self.speed_slider.valueChanged.connect(self._on_speed_slider_changed)
        speed_layout.addWidget(self.speed_slider)

        self.speed_spin = DoubleSpinBox(self)
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSuffix("x")
        self.speed_spin.setFixedWidth(80)
        self.speed_spin.valueChanged.connect(self._on_speed_spin_changed)
        speed_layout.addWidget(self.speed_spin)

        self.speed_reset_btn = ToolButton(FIF.SYNC, self)
        self.speed_reset_btn.setToolTip("重置为默认速度 (1.0x)")
        self.speed_reset_btn.clicked.connect(self._on_speed_reset)
        speed_layout.addWidget(self.speed_reset_btn)

        speed_layout.addStretch()
        params_layout.addLayout(speed_layout)

        right_layout.addWidget(params_card)

        # API Key
        api_card = CardWidget(self)
        api_layout = QVBoxLayout(api_card)
        api_layout.setContentsMargins(15, 15, 15, 15)
        api_layout.setSpacing(10)

        api_title = BodyLabel("API 配置", self)
        api_layout.addWidget(api_title)

        # API Base URL（仅 OpenAI TTS 可见）
        api_base_layout = QHBoxLayout()
        self.api_base_label = BodyLabel("API Base:", self)
        api_base_layout.addWidget(self.api_base_label)

        self.api_base_edit = LineEdit(self)
        self.api_base_edit.setPlaceholderText("https://api.openai.com/v1")
        api_base_layout.addWidget(self.api_base_edit, 1)
        api_layout.addLayout(api_base_layout)

        local_url_layout = QHBoxLayout()
        self.local_url_label = BodyLabel("服务 URL:", self)
        local_url_layout.addWidget(self.local_url_label)
        self.local_url_edit = LineEdit(self)
        self.local_url_edit.setPlaceholderText("http://127.0.0.1:7860")
        self.local_url_edit.textChanged.connect(self._on_local_url_changed)
        local_url_layout.addWidget(self.local_url_edit, 1)
        api_layout.addLayout(local_url_layout)

        voxcpm_version_layout = QHBoxLayout()
        self.voxcpm_version_label = BodyLabel("VoxCPM 版本:", self)
        voxcpm_version_layout.addWidget(self.voxcpm_version_label)
        self.voxcpm_version_combo = ComboBox(self)
        self.voxcpm_version_combo.addItems(["v2", "v1", "hf"])
        self.voxcpm_version_combo.currentIndexChanged.connect(self._persist_dubbing_settings)
        voxcpm_version_layout.addWidget(self.voxcpm_version_combo)
        voxcpm_version_layout.addStretch()
        api_layout.addLayout(voxcpm_version_layout)

        start_script_layout = QHBoxLayout()
        self.start_script_label = BodyLabel("启动脚本:", self)
        start_script_layout.addWidget(self.start_script_label)
        self.start_script_edit = LineEdit(self)
        self.start_script_edit.setPlaceholderText("可选：PowerShell 启动脚本路径")
        self.start_script_edit.textChanged.connect(self._on_start_script_changed)
        start_script_layout.addWidget(self.start_script_edit, 1)
        self.start_script_btn = ToolButton(FIF.FOLDER, self)
        self.start_script_btn.setToolTip("选择启动脚本")
        self.start_script_btn.clicked.connect(self._select_start_script)
        start_script_layout.addWidget(self.start_script_btn)
        api_layout.addLayout(start_script_layout)

        package_layout = QHBoxLayout()
        self.package_url_label = BodyLabel("环境包 URL:", self)
        package_layout.addWidget(self.package_url_label)
        self.package_url_edit = LineEdit(self)
        self.package_url_edit.setPlaceholderText(
            "可选：zip/7z 下载地址（VoxCPM 可参考 pyvideotrans 教程页整合包）"
        )
        self.package_url_edit.textChanged.connect(self._on_package_url_changed)
        package_layout.addWidget(self.package_url_edit, 1)
        self.download_package_btn = ToolButton(FIF.DOWNLOAD, self)
        self.download_package_btn.setToolTip("下载并解压本地 TTS 环境包")
        self.download_package_btn.clicked.connect(self._download_local_package)
        package_layout.addWidget(self.download_package_btn)
        api_layout.addLayout(package_layout)

        self.local_service_hint = BodyLabel("", self)
        self.local_service_hint.setStyleSheet("color: #888; font-size: 12px;")
        api_layout.addWidget(self.local_service_hint)

        # API Key 输入和测试按钮
        api_input_layout = QHBoxLayout()
        self.api_key_edit = LineEdit(self)
        self.api_key_edit.setPlaceholderText("点击「管理密钥」添加 API Key")
        self.api_key_edit.setReadOnly(True)
        api_input_layout.addWidget(self.api_key_edit, 1)

        self.manage_keys_btn = PushButton(FIF.EDIT, "管理密钥", self)
        self.manage_keys_btn.clicked.connect(self._open_api_keys_dialog)
        api_input_layout.addWidget(self.manage_keys_btn)

        # 测试 API 按钮
        self.test_api_btn = ToolButton(FIF.SYNC, self)
        self.test_api_btn.setToolTip("测试 API 并获取音色")
        self.test_api_btn.clicked.connect(self._test_api)
        api_input_layout.addWidget(self.test_api_btn)

        api_layout.addLayout(api_input_layout)

        self.api_keys_summary = BodyLabel("", self)
        self.api_keys_summary.setStyleSheet("color: #888; font-size: 12px;")
        api_layout.addWidget(self.api_keys_summary)

        # ElevenLabs 配额显示（默认隐藏）
        self.quota_label = BodyLabel("", self)
        self.quota_label.setStyleSheet("color: #666; font-size: 12px;")
        self.quota_label.setVisible(False)
        api_layout.addWidget(self.quota_label)

        self.reset_date_label = BodyLabel("", self)
        self.reset_date_label.setStyleSheet("color: #888; font-size: 11px;")
        self.reset_date_label.setVisible(False)
        api_layout.addWidget(self.reset_date_label)

        api_hint = BodyLabel("💡 支持多 Key：换行或英文逗号分隔", self)
        api_hint.setStyleSheet("color: #888; font-size: 12px;")
        api_layout.addWidget(api_hint)

        right_layout.addWidget(api_card)

        # 输出路径
        output_card = CardWidget(self)
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(15, 15, 15, 15)

        output_title = BodyLabel("输出", self)
        output_layout.addWidget(output_title)

        path_layout = QHBoxLayout()
        self.output_edit = LineEdit(self)
        self.output_edit.setPlaceholderText("自动生成输出路径")
        path_layout.addWidget(self.output_edit)

        browse_btn = ToolButton(FIF.FOLDER, self)
        browse_btn.clicked.connect(self._browse_output)
        path_layout.addWidget(browse_btn)

        output_layout.addLayout(path_layout)

        right_layout.addWidget(output_card)

        # 执行按钮
        self.start_btn = PrimaryPushButton(FIF.PLAY, "开始配音", self)
        self.start_btn.setFixedHeight(36)
        self.start_btn.clicked.connect(self._start_dubbing)
        right_layout.addWidget(self.start_btn)

        # 进度
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        self.status_label = BodyLabel("", self)
        self.status_label.setVisible(False)
        right_layout.addWidget(self.status_label)

        right_layout.addStretch()

        # 添加左右布局
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 1)
        self.scroll_area.setWidget(self.scroll_widget)
        root_layout.addWidget(self.scroll_area)

        # 连接模式切换
        self.mode_subtitle.toggled.connect(self._on_mode_changed)

        # 连接语言切换
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)

        # 初始化语言列表
        self._load_languages()

        # 初始化音频播放器用于试听
        self.media_player = QMediaPlayer()
        self.media_player.error.connect(self._on_player_error)
        self.media_player.stateChanged.connect(self._on_player_state_changed)  # 监听播放状态变化

        # 连接 API Key 变化（通过管理对话框保存后刷新）
        self._quota_debounce_timer = QTimer(self)
        self._quota_debounce_timer.setSingleShot(True)
        self._quota_debounce_timer.setInterval(800)
        self._quota_debounce_timer.timeout.connect(self._maybe_refresh_elevenlabs_quota)
        self.api_base_edit.textChanged.connect(self._on_api_base_changed)

    def _connect_dubbing_auto_save(self):
        """配音面板改动即时写入全局 cfg，批量配音与主页线程共用。"""
        self.voice_combo.currentIndexChanged.connect(self._persist_dubbing_settings)
        self.timing_combo.currentIndexChanged.connect(self._persist_dubbing_settings)
        self.audio_mode_combo.currentIndexChanged.connect(self._persist_dubbing_settings)
        self.adapt_switch.checkedChanged.connect(self._persist_dubbing_settings)
        self.pause_switch.checkedChanged.connect(self._persist_dubbing_settings)
        self.pause_ms_spin.valueChanged.connect(self._persist_dubbing_settings)
        self.speed_spin.valueChanged.connect(self._persist_dubbing_settings)
        self.model_combo.currentIndexChanged.connect(self._persist_dubbing_settings)
        self.clone_audio_edit.textChanged.connect(self._persist_dubbing_settings)
        self.clone_text_edit.textChanged.connect(self._persist_dubbing_settings)

    def _persist_dubbing_settings(self, *_args):
        """将当前配音面板状态保存到 cfg（与 TaskFactory.create_dubbing_config 一致）。"""
        if self._config_loading:
            return
        provider_text = self.provider_combo.currentText()
        provider = provider_text.split(" - ")[0].strip().lower()

        timing_text = self.timing_combo.currentText()
        timing_value = timing_text.split(" - ")[0] if " - " in timing_text else timing_text

        audio_mode_text = self.audio_mode_combo.currentText()
        audio_mode_value = (
            audio_mode_text.split(" - ")[0] if " - " in audio_mode_text else audio_mode_text
        )

        voice_id = self.voice_combo.currentData()
        raw_voice = voice_id if voice_id else ""
        cfg.dubbing_voice.value = resolve_dubbing_voice(provider, raw_voice)

        cfg.dubbing_provider.value = provider
        cfg.dubbing_timing.value = timing_value
        cfg.dubbing_audio_mode.value = audio_mode_value
        cfg.dubbing_adapt_length.value = self.adapt_switch.isChecked()
        cfg.dubbing_fixed_line_pause.value = self.pause_switch.isChecked()
        cfg.dubbing_fixed_line_pause_ms.value = self.pause_ms_spin.value()
        cfg.dubbing_speed.value = self.speed_spin.value()
        cfg.dubbing_api_base.value = self.api_base_edit.text()
        cfg.dubbing_clone_audio_path.value = self.clone_audio_edit.text().strip()
        cfg.dubbing_clone_audio_text.value = self.clone_text_edit.toPlainText().strip()
        pkg = self.package_url_edit.text().strip()
        cfg.dubbing_local_package_url.value = pkg
        if provider == "dots":
            cfg.dubbing_dots_package_url.value = pkg
            cfg.dubbing_dots_url.value = self.local_url_edit.text().strip()
            cfg.dubbing_dots_start_script.value = self.start_script_edit.text().strip()
            cfg.dubbing_model.value = "dots-tts"
        elif provider == "voxcpm":
            cfg.dubbing_voxcpm_package_url.value = pkg
            cfg.dubbing_voxcpm_url.value = self.local_url_edit.text().strip()
            cfg.dubbing_voxcpm_start_script.value = self.start_script_edit.text().strip()
            cfg.dubbing_voxcpm_version.value = self.voxcpm_version_combo.currentText() or "v2"
            cfg.dubbing_model.value = "voxcpm"
        if self._provider_id() == "elevenlabs":
            model_text = self.model_combo.currentText()
            cfg.dubbing_model.value = (
                model_text.split(" - ")[0] if " - " in model_text else model_text
            )
        cfg.save()

    def _primary_api_key(self) -> str:
        """用于测试/配额查询的第一个有效 Key。"""
        keys = parse_api_keys(cfg.dubbing_api_key.value)
        return keys[0] if keys else ""

    def _sync_api_key_display(self):
        """根据配置刷新只读摘要行。"""
        raw = cfg.dubbing_api_key.value or ""
        keys = parse_api_keys(raw)
        if not keys:
            self.api_key_edit.setText("")
            self.api_keys_summary.setText("未配置 API Key")
        elif len(keys) == 1:
            k = keys[0]
            mask = f"{k[:8]}…{k[-4:]}" if len(k) > 14 else k
            self.api_key_edit.setText(mask)
            self.api_keys_summary.setText("已配置 1 个 Key")
        else:
            self.api_key_edit.setText(f"已配置 {len(keys)} 个 API Key")
            self.api_keys_summary.setText(
                "已配置多个 Key，配额显示第一个 Key 的用量"
            )

    def _open_api_keys_dialog(self):
        dialog = ApiKeysEditorDialog(cfg.dubbing_api_key.value, self)
        if dialog.exec():
            cfg.dubbing_api_key.value = dialog.get_text()
            cfg.save()
            self._sync_api_key_display()
            self._schedule_quota_refresh()

    def _schedule_quota_refresh(self):
        if self._provider_id() == "elevenlabs":
            self._quota_debounce_timer.start()

    def _provider_id(self) -> str:
        text = self.provider_combo.currentText()
        return text.split(" - ")[0].lower() if " - " in text else text.lower()

    def _maybe_refresh_elevenlabs_quota(self):
        if self._provider_id() != "elevenlabs":
            return
        if self._primary_api_key():
            self._query_elevenlabs_quota()
        else:
            self.quota_label.setText("配额: 未查询")
            self.reset_date_label.setText("")

    def _on_api_key_changed(self):
        """兼容旧逻辑：保存后刷新显示与配额。"""
        self._sync_api_key_display()
        self._schedule_quota_refresh()

    def _on_api_base_changed(self):
        """API Base 改变时自动保存"""
        cfg.dubbing_api_base.value = self.api_base_edit.text()
        cfg.save()

    def _save_voice_cache(self, provider: str, voices: list):
        """保存音色列表到缓存文件"""
        try:
            import json
            from ...config import CACHE_PATH
            cache_file = CACHE_PATH / f"voices_{provider}.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(voices, f, ensure_ascii=False, indent=2)
            print(f"已保存 {provider} 音色列表到: {cache_file}")
        except Exception as e:
            print(f"保存音色缓存失败: {e}")

    def _load_voice_cache(self, provider: str) -> list:
        """从缓存文件加载音色列表"""
        try:
            import json
            from ...config import CACHE_PATH
            cache_file = CACHE_PATH / f"voices_{provider}.json"
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    voices = json.load(f)
                print(f"已从缓存加载 {provider} 音色列表，共 {len(voices)} 个")
                return voices
        except Exception as e:
            print(f"加载音色缓存失败: {e}")
        return []

    def _query_elevenlabs_quota(self):
        """查询 ElevenLabs API 配额"""
        api_key = self._primary_api_key()
        if not api_key:
            self.quota_label.setText("配额: 未查询")
            self.reset_date_label.setText("")
            return

        self.quota_label.setText("配额: 查询中…")

        # 创建查询线程
        self.quota_thread = ElevenLabsQuotaThread(api_key)
        self.quota_thread.finished.connect(self._on_quota_query_finished)
        self.quota_thread.error.connect(self._on_quota_query_error)
        self.quota_thread.start()

    def _on_quota_query_finished(self, quota_info: dict):
        """配额查询成功"""
        char_count = quota_info.get("character_count", 0)
        char_limit = quota_info.get("character_limit", 10000)
        reset_date = quota_info.get("reset_date", "未知")
        reset_unix = quota_info.get("next_character_count_reset_unix", 0)

        # 计算剩余配额
        remaining = char_limit - char_count
        percentage = (char_count / char_limit * 100) if char_limit > 0 else 0
        self.last_quota_percentage = percentage

        # 更新显示
        self.quota_label.setText(f"配额: {char_count:,} / {char_limit:,} 字符 ({percentage:.1f}%)")
        self.reset_date_label.setText(f"重置日期: {reset_date}")

        # 根据剩余配额设置颜色
        if percentage >= 90:
            self.quota_label.setStyleSheet("color: #d32f2f; font-size: 12px; font-weight: bold;")
        elif percentage >= 70:
            self.quota_label.setStyleSheet("color: #f57c00; font-size: 12px;")
        else:
            self.quota_label.setStyleSheet("color: #388e3c; font-size: 12px;")

        # 启动或调整轮询定时器
        self._start_quota_polling(percentage, reset_unix)

    def _on_quota_query_error(self, error_msg: str):
        """配额查询失败"""
        self.quota_label.setText(f"配额: 查询失败")
        self.reset_date_label.setText(f"错误: {error_msg}")
        self.quota_label.setStyleSheet("color: #999; font-size: 12px;")

    def _start_quota_polling(self, percentage: float, reset_unix: int):
        """启动配额轮询定时器"""
        from PyQt5.QtCore import QTimer
        from datetime import datetime

        # 停止旧的定时器
        if self.quota_poll_timer:
            self.quota_poll_timer.stop()
            self.quota_poll_timer = None

        # 根据配额使用情况决定轮询间隔
        if percentage >= 95:
            # 配额几乎用完：每5分钟检查一次
            interval_ms = 5 * 60 * 1000
            print("配额 ≥95%，启动高频轮询（5分钟）")
        elif percentage >= 90:
            # 配额接近上限：每15分钟检查一次
            interval_ms = 15 * 60 * 1000
            print("配额 ≥90%，启动中频轮询（15分钟）")
        else:
            # 配额充足：每小时检查一次
            interval_ms = 60 * 60 * 1000
            print("配额 <90%，启动低频轮询（1小时）")

        # 创建定时器
        self.quota_poll_timer = QTimer(self)
        self.quota_poll_timer.timeout.connect(self._query_elevenlabs_quota)
        self.quota_poll_timer.start(interval_ms)

        # 如果有重置时间，在重置后自动查询
        if reset_unix > 0:
            current_time = datetime.now().timestamp()
            time_until_reset = reset_unix - current_time

            if 0 < time_until_reset < 86400:  # 24小时内会重置
                # 在重置后5分钟查询
                reset_check_ms = int((time_until_reset + 300) * 1000)
                QTimer.singleShot(reset_check_ms, self._query_elevenlabs_quota)
                print(f"已设置重置后自动查询，将在 {time_until_reset/3600:.1f} 小时后执行")

    def _stop_quota_polling(self):
        """停止配额轮询"""
        if self.quota_poll_timer:
            self.quota_poll_timer.stop()
            self.quota_poll_timer = None
            print("已停止配额轮询")

    def _on_player_error(self, error):
        """播放器错误处理"""
        if error != QMediaPlayer.NoError:
            print(f"Media player error: {self.media_player.errorString()}")

    def load_config(self):
        """从配置加载"""
        self._config_loading = True
        # 加载 provider
        provider = cfg.dubbing_provider.value
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemText(i).startswith(provider):
                self.provider_combo.setCurrentIndex(i)
                break

        # 加载其他配置
        saved_voice = cfg.dubbing_voice.value

        # 根据保存的值匹配带中文的选项
        timing_value = cfg.dubbing_timing.value
        for i in range(self.timing_combo.count()):
            if self.timing_combo.itemText(i).startswith(timing_value):
                self.timing_combo.setCurrentIndex(i)
                break

        audio_mode_value = cfg.dubbing_audio_mode.value
        for i in range(self.audio_mode_combo.count()):
            if self.audio_mode_combo.itemText(i).startswith(audio_mode_value):
                self.audio_mode_combo.setCurrentIndex(i)
                break

        self.adapt_switch.setChecked(cfg.dubbing_adapt_length.value)
        self.pause_switch.setChecked(cfg.dubbing_fixed_line_pause.value)
        self.pause_ms_spin.setValue(cfg.dubbing_fixed_line_pause_ms.value)
        self.speed_spin.setValue(cfg.dubbing_speed.value)
        self._sync_api_key_display()
        self.api_base_edit.setText(cfg.dubbing_api_base.value)
        self.clone_audio_edit.setText(cfg.dubbing_clone_audio_path.value or "")
        self.clone_text_edit.setPlainText(cfg.dubbing_clone_audio_text.value or "")
        self._load_local_provider_fields(provider)

        saved_model = (cfg.dubbing_model.value or "").strip()
        if saved_model:
            for i in range(self.model_combo.count()):
                if self.model_combo.itemText(i).startswith(saved_model):
                    self.model_combo.setCurrentIndex(i)
                    break

        # 尝试从保存的音色恢复语言选择
        if saved_voice:
            self._restore_voice_selection(saved_voice)

        self._maybe_refresh_elevenlabs_quota()
        self._config_loading = False
        self._on_provider_changed(self.provider_combo.currentText())

    def save_config(self):
        """保存到配置（开始配音前再写一次，与自动保存逻辑一致）。"""
        self._persist_dubbing_settings()

    def _on_mode_changed(self, checked):
        """模式切换"""
        if self.mode_subtitle.isChecked():
            self.subtitle_input.setVisible(True)
            self.text_input.setVisible(False)
            self.timing_combo.setEnabled(True)
            self.audio_mode_combo.setEnabled(True)
        else:
            self.subtitle_input.setVisible(False)
            self.text_input.setVisible(True)
            self.timing_combo.setEnabled(False)
            self.audio_mode_combo.setEnabled(False)

    def _on_pause_toggled(self, checked):
        """固定停顿开关切换"""
        if checked:
            InfoBar.warning(
                title="提示",
                content="开启固定停顿后，时间策略将失效",
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _on_speed_slider_changed(self, value):
        """语速滑块变化 - 更新输入框"""
        speed = value / 100.0  # 50-200 -> 0.5-2.0
        self.speed_spin.blockSignals(True)  # 防止循环触发
        self.speed_spin.setValue(speed)
        self.speed_spin.blockSignals(False)

    def _on_speed_spin_changed(self, value):
        """语速输入框变化 - 更新滑块"""
        slider_value = int(value * 100)  # 0.5-2.0 -> 50-200
        self.speed_slider.blockSignals(True)  # 防止循环触发
        self.speed_slider.setValue(slider_value)
        self.speed_slider.blockSignals(False)

    def _on_speed_reset(self):
        """重置语速为默认值 1.0x"""
        self.speed_spin.setValue(1.0)

    def _on_provider_changed(self, text):
        """Provider 改变时的提示和界面更新"""
        import logging
        logger = logging.getLogger(__name__)

        provider = text.split(" - ")[0].lower() if " - " in text else text.lower()
        logger.info(f"Provider 切换到: {provider}")

        # 如果切换到非 ElevenLabs，停止配额轮询
        if provider != "elevenlabs":
            self._stop_quota_polling()

        # 根据不同引擎更新界面
        self._set_local_controls_visible(False)
        if provider == "edge":
            # Edge TTS：显示语言和音色选择，隐藏 API Base
            logger.info("设置 Edge TTS 界面...")
            self.language_combo.setVisible(True)
            self.voice_combo.setVisible(True)
            self.preview_btn.setVisible(True)  # Edge TTS 试听
            self.model_label.setVisible(False)  # 隐藏模型选择
            self.model_combo.setVisible(False)
            self.quota_label.setVisible(False)  # 隐藏配额
            self.reset_date_label.setVisible(False)
            self.hint_label.setText("💡 选择语言后自动加载音色列表")
            self.api_key_edit.setEnabled(False)
            self.manage_keys_btn.setEnabled(False)
            self.test_api_btn.setEnabled(False)
            self.api_base_label.setVisible(False)
            self.api_base_edit.setVisible(False)

            # 自动加载 Edge TTS 音色
            logger.info(f"当前语言列表数量: {self.language_combo.count()}")
            if self.language_combo.count() == 0:
                logger.info("语言列表为空，开始加载...")
                self._load_languages()
            else:
                logger.info("语言列表已存在，按当前语言刷新 Edge 音色")
                lang_idx = self.language_combo.currentIndex()
                if lang_idx < 0 and self.language_combo.count() > 0:
                    lang_idx = 0
                if lang_idx >= 0:
                    self._on_language_changed(lang_idx)

            resolved = resolve_dubbing_voice("edge", cfg.dubbing_voice.value)
            if resolved != (cfg.dubbing_voice.value or "").strip():
                cfg.dubbing_voice.value = resolved
                cfg.save()
                self._restore_voice_selection(resolved)

        elif provider == "elevenlabs":
            # ElevenLabs：需要 API Key，点击测试按钮获取音色
            self.language_combo.setVisible(False)
            self.voice_combo.setVisible(True)
            self.preview_btn.setVisible(True)  # ElevenLabs 试听
            self.model_label.setVisible(True)  # 显示模型选择
            self.model_combo.setVisible(True)
            self.quota_label.setVisible(True)  # 显示配额
            self.reset_date_label.setVisible(True)
            self.hint_label.setText("💡 点击「管理密钥」后测试获取音色列表")
            self.api_key_edit.setEnabled(False)
            self.manage_keys_btn.setEnabled(True)
            self.test_api_btn.setEnabled(True)
            self.api_base_label.setVisible(False)
            self.api_base_edit.setVisible(False)

            # 尝试从缓存加载音色列表
            cached_voices = self._load_voice_cache(provider)
            if cached_voices:
                self.voice_combo.clear()
                for voice in cached_voices:
                    name = voice.get("name", "Unknown")
                    voice_id = voice.get("voice_id", "")
                    if voice_id:
                        self.voice_combo.addItem(f"{name}", userData=voice_id)
                logger.info(f"已从缓存加载 {len(cached_voices)} 个 ElevenLabs 音色")
                saved = (cfg.dubbing_voice.value or "").strip()
                if saved and not saved.endswith("Neural"):
                    for i in range(self.voice_combo.count()):
                        if self.voice_combo.itemData(i) == saved:
                            self.voice_combo.setCurrentIndex(i)
                            break
                elif self.voice_combo.count() > 0:
                    self.voice_combo.setCurrentIndex(0)
            else:
                saved = (cfg.dubbing_voice.value or "").strip()
                if saved.endswith("Neural"):
                    cfg.dubbing_voice.value = ""
                    cfg.save()
                self.voice_combo.clear()

            # 如果有 API Key，自动查询配额
            if self._primary_api_key():
                self._query_elevenlabs_quota()
            else:
                self.quota_label.setText("配额: 未查询")
                self.reset_date_label.setText("")

            if not self._primary_api_key():
                InfoBar.warning(
                    title="需要 API Key",
                    content="ElevenLabs 需要配置 API Key",
                    duration=INFOBAR_DURATION_WARNING,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )

        elif provider == "openai":
            # OpenAI TTS：需要 API Key 和 Base URL
            self.language_combo.setVisible(False)
            self.voice_combo.setVisible(True)
            self.preview_btn.setVisible(True)  # OpenAI 试听
            self.model_label.setVisible(False)  # 隐藏模型选择
            self.model_combo.setVisible(False)
            self.quota_label.setVisible(False)  # 隐藏配额
            self.reset_date_label.setVisible(False)
            self.hint_label.setText("💡 选择预设音色或输入自定义音色 ID")
            self.api_key_edit.setEnabled(False)
            self.manage_keys_btn.setEnabled(True)
            self.test_api_btn.setEnabled(False)
            self.api_base_label.setVisible(True)
            self.api_base_edit.setVisible(True)

            # 从配置加载 base URL
            if not self.api_base_edit.text():
                self.api_base_edit.setText(cfg.dubbing_api_base.value)

            # OpenAI TTS 预定义音色
            openai_voices = [
                ("Alloy - 中性", "alloy"),
                ("Echo - 男性", "echo"),
                ("Fable - 英式男性", "fable"),
                ("Onyx - 深沉男性", "onyx"),
                ("Nova - 女性", "nova"),
                ("Shimmer - 女性", "shimmer"),
            ]
            self.voice_combo.clear()
            for name, voice_id in openai_voices:
                self.voice_combo.addItem(name, userData=voice_id)
            resolved = resolve_dubbing_voice("openai", cfg.dubbing_voice.value)
            for i in range(self.voice_combo.count()):
                if self.voice_combo.itemData(i) == resolved:
                    self.voice_combo.setCurrentIndex(i)
                    break

        elif provider in ("dots", "voxcpm"):
            self.language_combo.setVisible(False)
            self.voice_combo.setVisible(False)
            self.preview_btn.setVisible(False)
            self.model_label.setVisible(False)
            self.model_combo.setVisible(False)
            self.quota_label.setVisible(False)
            self.reset_date_label.setVisible(False)
            self.hint_label.setText("本地克隆引擎使用参考音频和参考文本，不使用预设音色。")
            self.api_key_edit.setEnabled(False)
            self.manage_keys_btn.setEnabled(False)
            self.test_api_btn.setEnabled(False)
            self.api_base_label.setVisible(False)
            self.api_base_edit.setVisible(False)
            self._load_local_provider_fields(provider)
            self._set_local_controls_visible(True, provider)

        else:
            # 其他引擎
            self.language_combo.setVisible(False)
            self.voice_combo.setVisible(True)
            self.preview_btn.setVisible(True)  # 其他引擎试听
            self.model_label.setVisible(False)  # 隐藏模型选择
            self.model_combo.setVisible(False)
            self.quota_label.setVisible(False)  # 隐藏配额
            self.reset_date_label.setVisible(False)
            self.hint_label.setText("💡 输入音色名称或 ID")
            self.api_key_edit.setEnabled(False)
            self.manage_keys_btn.setEnabled(True)
            self.test_api_btn.setEnabled(False)
            self.api_base_label.setVisible(False)
            self.api_base_edit.setVisible(False)

        self._persist_dubbing_settings()

    def _package_url_for_provider(self, provider: str) -> str:
        if provider == "dots":
            saved = (cfg.dubbing_dots_package_url.value or "").strip()
        elif provider == "voxcpm":
            saved = (cfg.dubbing_voxcpm_package_url.value or "").strip()
        else:
            saved = ""
        if saved:
            return saved
        legacy = (cfg.dubbing_local_package_url.value or "").strip()
        if legacy:
            return legacy
        if provider == "dots":
            return DEFAULT_DOTS_PACKAGE_URL
        if provider == "voxcpm":
            return DEFAULT_VOXCPM_PACKAGE_URL
        return ""

    def _load_local_provider_fields(self, provider: str):
        self.local_url_edit.blockSignals(True)
        self.start_script_edit.blockSignals(True)
        self.voxcpm_version_combo.blockSignals(True)
        self.package_url_edit.blockSignals(True)
        if provider == "dots":
            self.local_url_edit.setText(cfg.dubbing_dots_url.value or "http://127.0.0.1:7860")
            self.start_script_edit.setText(cfg.dubbing_dots_start_script.value or "")
        elif provider == "voxcpm":
            self.local_url_edit.setText(cfg.dubbing_voxcpm_url.value or "http://127.0.0.1:9880")
            self.start_script_edit.setText(cfg.dubbing_voxcpm_start_script.value or "")
            version = cfg.dubbing_voxcpm_version.value or "v2"
            for i in range(self.voxcpm_version_combo.count()):
                if self.voxcpm_version_combo.itemText(i) == version:
                    self.voxcpm_version_combo.setCurrentIndex(i)
                    break
        self.package_url_edit.setText(self._package_url_for_provider(provider))
        self.local_url_edit.blockSignals(False)
        self.start_script_edit.blockSignals(False)
        self.voxcpm_version_combo.blockSignals(False)
        self.package_url_edit.blockSignals(False)

    def _set_local_controls_visible(self, visible: bool, provider: str = ""):
        for widget in (
            self.local_url_label,
            self.local_url_edit,
            self.start_script_label,
            self.start_script_edit,
            self.start_script_btn,
            self.package_url_label,
            self.package_url_edit,
            self.download_package_btn,
            self.local_service_hint,
            self.clone_audio_label,
            self.clone_audio_edit,
            self.clone_btn,
            self.clone_summary,
            self.clone_text_label,
            self.clone_text_edit,
            self.clone_hint_label,
        ):
            widget.setVisible(visible)
        self.voxcpm_version_label.setVisible(visible and provider == "voxcpm")
        self.voxcpm_version_combo.setVisible(visible and provider == "voxcpm")
        if visible:
            self._refresh_clone_summary()
            if provider == "dots":
                self.local_service_hint.setText(
                    f"Dots-TTS 需本地 Gradio 服务。项目地址：{DOTS_TTS_PROJECT_URL} "
                    f"（无官方环境包 zip，请克隆仓库后配置启动脚本；可参考 pyvideotrans：{PYVIDEOTRANS_F5TTS_TUTORIAL_URL}）"
                )
            elif provider == "voxcpm":
                hint = (
                    f"VoxCPM 需本地 Gradio（默认 WebUI 常为 http://127.0.0.1:7860，与 pyvideotrans 一致）。"
                    f"项目：{VOXCPM_PROJECT_URL}；部署说明：{PYVIDEOTRANS_F5TTS_TUTORIAL_URL}"
                )
                if PYVIDEOTRANS_F5_TTS_BUNDLE_URL:
                    hint += (
                        f"。同页提供的 Windows 整合包示例（F5-TTS）：{PYVIDEOTRANS_F5_TTS_BUNDLE_URL}"
                    )
                self.local_service_hint.setText(hint)
            else:
                self.local_service_hint.setText(
                    "本地引擎需先启动 Gradio 服务；可配置启动脚本自动拉起，或填写环境包 URL 快速下载。"
                )

    def _on_clone_audio_changed(self, text: str):
        self.clone_audio_path = text.strip()
        self._refresh_clone_summary()

    def _select_clone_audio(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择参考音频",
            "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*.*)",
        )
        if file_path:
            self.clone_audio_edit.setText(file_path)

    def _refresh_clone_summary(self):
        path = self.clone_audio_edit.text().strip()
        if path:
            exists = Path(path).is_file()
            prefix = "✓" if exists else "!"
            self.clone_summary.setText(f"{prefix} {Path(path).name if path else ''}")
            self.clone_summary.setStyleSheet(
                "color: #4caf50; font-size: 12px;" if exists else "color: #ff9800; font-size: 12px;"
            )
        else:
            self.clone_summary.setText("未选择参考音频")
            self.clone_summary.setStyleSheet("color: #888; font-size: 12px;")
        self.clone_hint_label.setText("Dots-TTS / VoxCPM 需要参考音频；建议 3-10 秒、发音清晰，并填写对应参考文本。")

    def _on_local_url_changed(self, text: str):
        self._persist_dubbing_settings()

    def _on_start_script_changed(self, text: str):
        self._persist_dubbing_settings()

    def _select_start_script(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择启动脚本",
            "",
            "脚本文件 (*.ps1 *.bat *.cmd);;所有文件 (*.*)",
        )
        if file_path:
            self.start_script_edit.setText(file_path)

    def _on_package_url_changed(self, text: str):
        self._persist_dubbing_settings()

    def _download_local_package(self):
        url = self.package_url_edit.text().strip()
        if not url:
            InfoBar.warning(
                title="缺少下载地址",
                content="请先填写 Dots-TTS 或 VoxCPM 环境包 zip 下载地址。",
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        parsed = urlparse(url)
        filename = Path(parsed.path).name or "local_tts_package.zip"
        save_path = CACHE_PATH / "local_tts" / filename
        self.download_package_btn.setEnabled(False)
        self.local_service_hint.setText("正在下载本地 TTS 环境包...")
        self.local_package_thread = LocalPackageDownloadThread(url, str(save_path), str(BIN_PATH / "local-tts"))
        self.local_package_thread.progress.connect(self._on_local_package_progress)
        self.local_package_thread.finished.connect(self._on_local_package_finished)
        self.local_package_thread.error.connect(self._on_local_package_error)
        self.local_package_thread.start()

    def _on_local_package_progress(self, value: float, message: str):
        self.local_service_hint.setText(f"下载环境包 {int(value)}%：{message}")

    def _on_local_package_finished(self, target_dir: str):
        self.download_package_btn.setEnabled(True)
        self.local_service_hint.setText(f"环境包已解压到：{target_dir}")
        InfoBar.success(
            title="下载完成",
            content="本地 TTS 环境包已下载并解压，请按包内说明配置启动脚本。",
            duration=INFOBAR_DURATION_SUCCESS,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_local_package_error(self, error_msg: str):
        self.download_package_btn.setEnabled(True)
        self.local_service_hint.setText("环境包下载失败")
        InfoBar.error(
            title="下载失败",
            content=error_msg,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _browse_output(self):
        """浏览输出路径"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存配音文件", "", "音频文件 (*.mp3);;所有文件 (*.*)"
        )
        if file_path:
            self.output_edit.setText(file_path)

    def _load_languages(self):
        """加载语言列表"""
        import logging
        logger = logging.getLogger(__name__)

        logger.info("开始加载语言列表...")
        languages = get_all_languages()
        logger.info(f"获取到 {len(languages)} 种语言")

        self.language_combo.blockSignals(True)
        self.language_combo.clear()

        for code, name in languages:
            self.language_combo.addItem(f"{name} ({code})", userData=code)

        self.language_combo.blockSignals(False)
        logger.info(f"语言列表已加载到界面，ComboBox count: {self.language_combo.count()}")

        # 设置默认选中第一项并触发音色加载
        if self.language_combo.count() > 0:
            self.language_combo.setCurrentIndex(0)
            logger.info("已设置默认语言为第一项")
            self._on_language_changed(0)

    def _on_language_changed(self, index):
        """语言切换时加载对应音色"""
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"语言切换事件触发，index: {index}")

        if index < 0:
            logger.warning("index < 0, 跳过")
            return

        language_code = self.language_combo.currentData()
        if not language_code:
            language_code = self.language_combo.itemData(index)
        logger.info(f"当前选中的语言代码: {language_code}, index: {index}, count: {self.language_combo.count()}")

        if not language_code:
            logger.warning("语言代码为空，跳过")
            return

        # 清空音色列表
        self.voice_combo.clear()

        # 加载该语言的音色
        logger.info(f"开始加载 {language_code} 的音色...")
        voices = get_voices_by_language(language_code)
        logger.info(f"获取到 {len(voices)} 个音色")

        for display_name, voice_id in voices:
            self.voice_combo.addItem(display_name, userData=voice_id)

        logger.info(f"音色列表已加载到界面，ComboBox count: {self.voice_combo.count()}")

        # 如果有音色，默认选中第一个
        if voices:
            self.voice_combo.setCurrentIndex(0)
            logger.info(f"默认选中第一个音色: {voices[0][0]}")
            self._persist_dubbing_settings()
        else:
            logger.warning("没有可用音色")

    def _restore_voice_selection(self, voice_id: str):
        """从保存的音色ID恢复选择"""
        # 遍历所有语言，找到对应的音色
        languages = get_all_languages()

        for lang_code, _ in languages:
            voices = get_voices_by_language(lang_code)
            for idx, (display_name, vid) in enumerate(voices):
                if vid == voice_id:
                    # 找到了，设置语言
                    for i in range(self.language_combo.count()):
                        if self.language_combo.itemData(i) == lang_code:
                            self.language_combo.setCurrentIndex(i)
                            # 等待音色列表加载后再设置
                            self.voice_combo.setCurrentIndex(idx)
                            return

    def _preview_voice(self):
        """试听音色 - 支持播放/暂停切换"""
        # 如果正在播放，则暂停
        if self.is_playing:
            self.media_player.pause()
            self.preview_btn.setIcon(FIF.PLAY_SOLID)
            self.preview_btn.setToolTip("播放")
            self.is_playing = False
            return

        # 如果已经有音频文件且播放器已准备好，直接恢复播放
        if self.media_player.state() == QMediaPlayer.PausedState:
            self.media_player.play()
            self.preview_btn.setIcon(FIF.PAUSE)
            self.preview_btn.setToolTip("暂停")
            self.is_playing = True
            return

        # 否则，生成新的试听音频
        voice_id = self.voice_combo.currentData()
        if not voice_id:
            InfoBar.warning(
                title="请先选择音色",
                content="请先选择一个音色后再试听",
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        # 获取当前 provider
        provider_text = self.provider_combo.currentText()
        provider = provider_text.split(" - ")[0].lower() if " - " in provider_text else provider_text.lower()

        # 获取 API Key（如果需要）
        api_key = self._primary_api_key() if provider != "edge" else None
        api_base = self.api_base_edit.text().strip() if provider == "openai" else None

        # 获取 ElevenLabs 模型（如果是 ElevenLabs）
        model_id = None
        if provider == "elevenlabs":
            model_text = self.model_combo.currentText()
            model_id = model_text.split(" - ")[0] if " - " in model_text else "eleven_flash_v2_5"

        # 禁用试听按钮
        self.preview_btn.setEnabled(False)

        # 显示提示
        InfoBar.info(
            title="正在生成试听音频",
            content="请稍候...",
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

        # 创建试听线程
        self.preview_thread = VoicePreviewThread(
            voice_id=voice_id,
            provider=provider,
            api_key=api_key,
            api_base=api_base,
            model_id=model_id
        )
        self.preview_thread.finished.connect(self._on_preview_finished)
        self.preview_thread.error.connect(self._on_preview_error)
        self.preview_thread.start()

    def _on_preview_finished(self, audio_path: str):
        """试听完成"""
        self.preview_btn.setEnabled(True)

        # 使用内置播放器播放音频
        if audio_path and Path(audio_path).exists():
            # 确保使用绝对路径
            abs_path = str(Path(audio_path).resolve())
            url = QUrl.fromLocalFile(abs_path)
            self.media_player.setMedia(QMediaContent(url))

            # 开始播放并更新按钮状态
            self.media_player.play()
            self.preview_btn.setIcon(FIF.PAUSE)
            self.preview_btn.setToolTip("暂停")
            self.is_playing = True

            InfoBar.success(
                title="试听成功",
                content="正在播放音频",
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            InfoBar.error(
                title="试听失败",
                content="音频文件不存在",
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _on_preview_error(self, error_msg: str):
        """试听失败"""
        self.preview_btn.setEnabled(True)

        InfoBar.error(
            title="试听失败",
            content=error_msg,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_player_state_changed(self, state):
        """播放器状态变化"""
        if state == QMediaPlayer.StoppedState:
            # 播放结束，恢复播放图标
            self.preview_btn.setIcon(FIF.PLAY_SOLID)
            self.preview_btn.setToolTip("试听音色")
            self.is_playing = False
        elif state == QMediaPlayer.PlayingState:
            # 正在播放，显示暂停图标
            self.preview_btn.setIcon(FIF.PAUSE)
            self.preview_btn.setToolTip("暂停")
            self.is_playing = True
        elif state == QMediaPlayer.PausedState:
            # 已暂停，显示播放图标
            self.preview_btn.setIcon(FIF.PLAY_SOLID)
            self.preview_btn.setToolTip("播放")
            self.is_playing = False

    def _test_api(self):
        """测试 API 并获取音色列表"""
        provider_text = self.provider_combo.currentText()
        provider = provider_text.split(" - ")[0].lower() if " - " in provider_text else provider_text.lower()

        api_key = self._primary_api_key()
        if not api_key:
            InfoBar.warning(
                title="请输入 API Key",
                content="请先通过「管理密钥」添加 API Key",
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        # 禁用测试按钮
        self.test_api_btn.setEnabled(False)

        # 显示加载提示
        InfoBar.info(
            title="测试中",
            content="正在测试 API 连接并获取音色列表...",
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

        # 根据不同引擎测试
        if provider == "elevenlabs":
            self._test_elevenlabs_api(api_key)
        else:
            self.test_api_btn.setEnabled(True)
            InfoBar.warning(
                title="不支持",
                content="当前引擎不支持 API 测试",
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _test_elevenlabs_api(self, api_key: str):
        """测试 ElevenLabs API 并获取音色"""
        # 创建测试线程
        self.api_test_thread = ElevenLabsAPITestThread(api_key)
        self.api_test_thread.finished.connect(self._on_api_test_finished)
        self.api_test_thread.error.connect(self._on_api_test_error)
        self.api_test_thread.start()

    def _on_api_test_finished(self, voices: list):
        """API 测试成功"""
        self.test_api_btn.setEnabled(True)

        # 清空音色列表
        self.voice_combo.clear()

        # 加载音色
        for voice in voices:
            name = voice.get("name", "Unknown")
            voice_id = voice.get("voice_id", "")
            if voice_id:
                self.voice_combo.addItem(f"{name}", userData=voice_id)

        # 保存音色列表到缓存
        provider_text = self.provider_combo.currentText()
        provider = provider_text.split(" - ")[0].lower() if " - " in provider_text else provider_text.lower()
        self._save_voice_cache(provider, voices)

        if self.voice_combo.count() > 0:
            self.voice_combo.setCurrentIndex(0)
        self._persist_dubbing_settings()

        self._query_elevenlabs_quota()

        InfoBar.success(
            title="测试成功",
            content=f"已获取 {len(voices)} 个音色",
            duration=INFOBAR_DURATION_SUCCESS,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_api_test_error(self, error_msg: str):
        """API 测试失败"""
        self.test_api_btn.setEnabled(True)

        InfoBar.error(
            title="测试失败",
            content=error_msg,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _start_dubbing(self):
        """开始配音"""
        # 保存配置
        self.save_config()

        # 验证输入
        provider = self._provider_id()
        if provider in ("dots", "voxcpm"):
            clone_audio = self.clone_audio_edit.text().strip()
            if not clone_audio or not Path(clone_audio).is_file():
                InfoBar.warning(
                    title="请选择参考音频",
                    content="Dots-TTS / VoxCPM 需要有效的参考音频文件。",
                    duration=INFOBAR_DURATION_WARNING,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            if not self.clone_text_edit.toPlainText().strip():
                InfoBar.warning(
                    title="请输入参考文本",
                    content="请填写参考音频对应的文字内容，以便本地克隆引擎复刻音色。",
                    duration=INFOBAR_DURATION_WARNING,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return

        if self.mode_subtitle.isChecked():
            subtitle_path = self.subtitle_input.get_file_path()
            if not subtitle_path:
                InfoBar.warning(
                    title="请选择字幕文件",
                    content="请先选择一个字幕文件",
                    duration=INFOBAR_DURATION_WARNING,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            input_mode = "subtitle"
            input_data = subtitle_path
        else:
            user_text = self.text_input.get_text()
            if not user_text:
                InfoBar.warning(
                    title="请输入文案",
                    content="请先输入需要配音的文案",
                    duration=INFOBAR_DURATION_WARNING,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            input_mode = "text"
            input_data = user_text

        # 禁用控件
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setVisible(True)
        self.status_label.setText("准备中...")

        # 创建工作线程
        self.worker_thread = DubbingInterfaceThread(
            input_mode=input_mode,
            input_data=input_data,
            output_path=self.output_edit.text() or None,
        )

        # 连接信号
        self.worker_thread.progress.connect(self._on_progress)
        self.worker_thread.error.connect(self._on_error)
        self.worker_thread.finished.connect(self._on_finished)

        # 启动线程
        self.worker_thread.start()

    def _on_progress(self, percent: int, message: str):
        """进度更新"""
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_error(self, error_msg: str):
        """处理错误"""
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)

        InfoBar.error(
            title="配音失败",
            content=error_msg,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_finished(self, output_path: str):
        """配音完成"""
        self.start_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("配音完成！")

        InfoBar.success(
            title="配音成功",
            content=f"已保存到: {Path(output_path).name}",
            duration=INFOBAR_DURATION_SUCCESS,
            position=InfoBarPosition.TOP,
            parent=self,
        )

        self.finished.emit(output_path)

    def cleanup_preview_files(self):
        """清理试听临时文件"""
        try:
            from ...config import TEMP_PATH
            import shutil
            preview_dir = TEMP_PATH / "voice_preview"
            if preview_dir.exists():
                shutil.rmtree(preview_dir)
                print(f"已清理试听文件夹: {preview_dir}")
        except Exception as e:
            print(f"清理试听文件失败: {e}")

    def closeEvent(self, event):
        """窗口关闭时清理和保存"""
        self.cleanup_preview_files()
        self._stop_quota_polling()  # 停止配额轮询
        self.save_config()  # 保存配置
        super().closeEvent(event)


class LocalPackageDownloadThread(QThread):
    """Download and extract a local TTS environment package."""

    progress = pyqtSignal(float, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, url: str, save_path: str, target_dir: str):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.target_dir = target_dir
        self.download_thread = None

    def run(self):
        try:
            from zipfile import ZipFile

            save_path = Path(self.save_path)
            downloader_cls = Aria2Downloader if Aria2Downloader.is_available() else RequestsDownloader
            downloader = downloader_cls(self.url, save_path, self.progress.emit)
            if not downloader.download():
                self.error.emit("下载失败")
                return
            target = Path(self.target_dir).resolve()
            target.mkdir(parents=True, exist_ok=True)
            self.progress.emit(99, "正在解压...")
            with ZipFile(save_path) as zf:
                for member in zf.infolist():
                    member_path = (target / member.filename).resolve()
                    if target != member_path and target not in member_path.parents:
                        raise ValueError(f"压缩包包含不安全路径: {member.filename}")
                zf.extractall(target)
            self.finished.emit(str(target))
        except Exception as e:
            self.error.emit(str(e))


class ElevenLabsAPITestThread(QThread):
    """ElevenLabs API 测试线程"""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    def run(self):
        """测试 API 并获取音色列表"""
        try:
            # 使用官方 elevenlabs 库
            from elevenlabs import ElevenLabs

            # 创建客户端
            client = ElevenLabs(api_key=self.api_key)

            # 获取音色列表
            voiceslist = client.voices.get_all()

            # 转换为列表格式
            voices = []
            for voice in voiceslist.voices:
                voices.append({
                    "name": voice.name,
                    "voice_id": voice.voice_id
                })

            self.finished.emit(voices)

        except ImportError:
            self.error.emit("缺少 elevenlabs 库，请运行: pip install elevenlabs")
        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "Unauthorized" in error_msg:
                self.error.emit("API Key 无效，请检查后重试")
            elif "403" in error_msg or "Forbidden" in error_msg:
                self.error.emit("API Key 没有权限")
            else:
                self.error.emit(f"测试失败: {error_msg}")


class VoicePreviewThread(QThread):
    """音色试听线程 - 支持多种 TTS 引擎"""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, voice_id: str, provider: str = "edge", api_key: str = None, api_base: str = None, model_id: str = None):
        super().__init__()
        self.voice_id = voice_id
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base
        self.model_id = model_id  # ElevenLabs 模型 ID

    def run(self):
        """执行试听"""
        try:
            # 试听文本（根据语言自动选择）
            preview_texts = {
                "zh": "你好，这是音色试听，希望你喜欢这个声音。",
                "en": "Hello, this is a voice preview. I hope you like this sound.",
                "ja": "こんにちは、これは音声プレビューです。この声が気に入っていただければ幸いです。",
                "ko": "안녕하세요, 이것은 음성 미리보기입니다. 이 소리가 마음에 드셨으면 좋겠습니다.",
                "es": "Hola, esta es una vista previa de voz. Espero que te guste este sonido.",
                "fr": "Bonjour, ceci est un aperçu vocal. J'espère que vous aimez ce son.",
                "de": "Hallo, dies ist eine Sprachvorschau. Ich hoffe, dir gefällt dieser Sound.",
                "it": "Ciao, questa è un'anteprima vocale. Spero che ti piaccia questo suono.",
                "pt": "Olá, esta é uma prévia de voz. Espero que você goste deste som.",
                "ru": "Привет, это предварительный просмотр голоса. Надеюсь, вам понравится этот звук.",
            }

            # 从 voice_id 提取语言代码
            lang_code = self.voice_id.split("-")[0] if "-" in self.voice_id else "en"
            text = preview_texts.get(lang_code, preview_texts["en"])

            # 生成临时文件到配置的临时目录
            import os
            from ...config import TEMP_PATH
            preview_dir = TEMP_PATH / "voice_preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            output_file = str(preview_dir / f"voice_preview_{os.getpid()}_{id(self)}.mp3")

            # 根据不同引擎生成音频
            if self.provider == "edge":
                self._generate_edge_tts(text, output_file)
            elif self.provider == "elevenlabs":
                self._generate_elevenlabs(text, output_file)
            elif self.provider == "openai":
                self._generate_openai(text, output_file)
            else:
                self.error.emit(f"暂不支持 {self.provider} 引擎的试听功能")
                return

            # 发送音频文件路径信号
            if os.path.exists(output_file):
                self.finished.emit(output_file)
            else:
                self.error.emit("音频文件生成失败")

        except ImportError as e:
            self.error.emit(f"缺少必要的库: {str(e)}")
        except Exception as e:
            self.error.emit(f"试听失败: {str(e)}")

    def _generate_edge_tts(self, text: str, output_file: str):
        """使用 Edge TTS 生成音频"""
        import edge_tts
        import asyncio

        async def generate():
            communicate = edge_tts.Communicate(text, self.voice_id)
            await communicate.save(output_file)

        asyncio.run(generate())

    def _generate_elevenlabs(self, text: str, output_file: str):
        """使用 ElevenLabs 生成音频"""
        if not self.api_key:
            raise ValueError("ElevenLabs 需要 API Key")

        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=self.api_key)

        # 使用用户选择的模型，默认 eleven_flash_v2_5
        model_id = self.model_id if self.model_id else "eleven_flash_v2_5"

        response = client.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id=model_id,
            output_format="mp3_44100_128"
        )

        # 保存音频流
        with open(output_file, "wb") as f:
            for chunk in response:
                if chunk:
                    f.write(chunk)

    def _generate_openai(self, text: str, output_file: str):
        """使用 OpenAI TTS 生成音频"""
        if not self.api_key:
            raise ValueError("OpenAI 需要 API Key")

        from openai import OpenAI
        from videocaptioner.core.llm.request_logger import create_http_client
        client = OpenAI(
            api_key=self.api_key,
            base_url=self.api_base if self.api_base else None,
            http_client=create_http_client(),
        )

        response = client.audio.speech.create(
            model="tts-1",
            voice=self.voice_id,
            input=text
        )

        response.stream_to_file(output_file)


class ElevenLabsQuotaThread(QThread):
    """ElevenLabs 配额查询线程"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    def run(self):
        """查询配额"""
        try:
            from elevenlabs import ElevenLabs
            client = ElevenLabs(api_key=self.api_key)

            # 调用正确的 API：user.subscription.get()
            subscription = client.user.subscription.get()

            # 提取配额信息
            quota_info = {
                "character_count": subscription.character_count,
                "character_limit": subscription.character_limit,
                "next_character_count_reset_unix": subscription.next_character_count_reset_unix,
            }

            # 转换时间戳为可读日期
            if subscription.next_character_count_reset_unix:
                from datetime import datetime
                reset_time = datetime.fromtimestamp(subscription.next_character_count_reset_unix)
                quota_info["reset_date"] = reset_time.strftime("%Y-%m-%d")
            else:
                quota_info["reset_date"] = "未知"

            self.finished.emit(quota_info)

        except Exception as e:
            self.error.emit(str(e))

