# -*- coding: utf-8 -*-
"""文稿匹配界面 - 使用 DTW 算法将正确文稿对齐到 ASR 时间轴"""

import os
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SubtitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from videocaptioner.core.constant import (
    INFOBAR_DURATION_ERROR,
    INFOBAR_DURATION_SUCCESS,
    INFOBAR_DURATION_WARNING,
)
from videocaptioner.core.entities import (
    SupportedAudioFormats,
    SupportedVideoFormats,
    TranscribeModelEnum,
)
from videocaptioner.core.utils.platform_utils import get_available_transcribe_models, open_folder
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.components.transcription_settings_style import TRANSCRIPTION_PAGE_QSS
from videocaptioner.ui.components.transcription_setting_card import (
    TranscriptionModelSettingsDialog,
)
from videocaptioner.ui.thread.text_matching_thread import TextMatchingThread


class MediaInputCard(CardWidget):
    """媒体文件输入卡片"""

    fileSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_path = None
        self.setup_ui()

    def setup_ui(self):
        self.setAcceptDrops(True)
        self.setMinimumHeight(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 标题
        title = BodyLabel("媒体文件", self)
        layout.addWidget(title)

        # 拖拽提示区域
        self.drop_hint = QLabel(
            "拖拽视频或音频到此处\n支持常见音视频格式", self
        )
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setWordWrap(True)
        self.drop_hint.setMinimumHeight(88)
        self.drop_hint.setStyleSheet(
            "QLabel { border: 2px dashed #666; border-radius: 8px; "
            "padding: 12px 10px; color: #888; font-size: 14px; }"
        )
        layout.addWidget(self.drop_hint, 1)

        # 选择按钮
        self.select_btn = PushButton(FIF.FOLDER, "选择文件", self)
        self.select_btn.clicked.connect(self._select_file)
        layout.addWidget(self.select_btn, 0, Qt.AlignCenter)

        # 文件名显示
        self.file_label = BodyLabel("", self)
        self.file_label.setVisible(False)
        layout.addWidget(self.file_label)

    def _select_file(self):
        """选择文件对话框"""
        valid_formats = [f"*.{fmt.value}" for fmt in SupportedAudioFormats] + [
            f"*.{fmt.value}" for fmt in SupportedVideoFormats
        ]
        filters = f"媒体文件 ({' '.join(valid_formats)});;所有文件 (*.*)"

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择媒体文件", "", filters
        )

        if file_path:
            self._set_file(file_path)

    def _set_file(self, file_path: str):
        """设置选择的文件"""
        self.file_path = file_path
        file_name = os.path.basename(file_path)

        self.drop_hint.setText(f"✓ {file_name}")
        self.drop_hint.setStyleSheet(
            "QLabel { border: 2px solid #0078d4; border-radius: 8px; "
            "padding: 12px 10px; color: #0078d4; font-size: 14px; }"
        )
        self.drop_hint.setWordWrap(True)
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


class TranscriptInputCard(CardWidget):
    """文稿输入卡片"""

    textChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        self.setAcceptDrops(True)

        # 标题栏
        header_layout = QHBoxLayout()
        title = SubtitleLabel("正确文稿", self)
        header_layout.addWidget(title)
        header_layout.addStretch()

        # 字数统计
        self.char_count_label = BodyLabel("0 字符", self)
        self.char_count_label.setStyleSheet("color: #888;")
        header_layout.addWidget(self.char_count_label)

        layout.addLayout(header_layout)

        # 文本输入框
        self.text_edit = PlainTextEdit(self)
        self.text_edit.setPlaceholderText(
            "在这里粘贴或输入正确的文稿文本，也可拖拽 txt / srt 文件到此...\n\n"
            "支持中英文，会自动检测语言。\n"
            "拖入 txt：直接读取文本；拖入 srt/ass/vtt：自动去除序号与时间轴，仅取纯文本。\n"
            "文稿将通过 DTW 算法对齐到 ASR 识别的时间轴上。"
        )
        self.text_edit.setMinimumHeight(300)
        self.text_edit.setAcceptDrops(False)  # 由卡片接管拖拽，避免 PlainTextEdit 自带的文件拖入行为
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        # 按钮栏
        btn_layout = QHBoxLayout()
        self.import_btn = PushButton(FIF.DOCUMENT, "导入 TXT / 字幕", self)
        self.import_btn.clicked.connect(self._import_file)
        self.clear_btn = ToolButton(FIF.DELETE, self)
        self.clear_btn.clicked.connect(self.text_edit.clear)
        self.clear_btn.setToolTip("清空文本")

        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    def _on_text_changed(self):
        """文本改变时更新字数统计"""
        text = self.text_edit.toPlainText()
        char_count = len(text)
        self.char_count_label.setText(f"{char_count} 字符")
        self.textChanged.emit()

    def _import_file(self):
        """导入文本文件（txt/md 直读，字幕文件去时间轴取纯文本）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文本文件", "",
            "文本与字幕 (*.txt *.md *.srt *.ass *.vtt);;所有文件 (*.*)",
        )
        if file_path:
            self._load_text_file(file_path)

    def _load_text_file(self, file_path: str):
        """读取文件并填入文本框；字幕格式自动剥离序号与时间轴。"""
        try:
            text = _extract_text_from_file(file_path)
            if text is None:
                InfoBar.error(
                    title="导入失败",
                    content="无法识别的文件类型，支持 txt/md/srt/ass/vtt。",
                    duration=INFOBAR_DURATION_ERROR,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            self.text_edit.setPlainText(text)
        except Exception as e:
            InfoBar.error(
                title="导入失败",
                content=f"无法读取文件: {str(e)}",
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if p and _is_supported_text_file(p):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and _is_supported_text_file(p):
                self._load_text_file(p)
                event.acceptProposedAction()
                return

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()


# 支持拖拽 / 导入的纯文本与字幕扩展名。
_TEXT_EXTS = {".txt", ".md"}
_SUBTITLE_EXTS = {".srt", ".ass", ".vtt", ".ssa", ".sub"}


def _is_supported_text_file(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in _TEXT_EXTS or suffix in _SUBTITLE_EXTS


def _extract_text_from_file(path: str) -> Optional[str]:
    """读取文件为纯文本。txt/md 直接读；字幕格式剥离序号与时间轴。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _TEXT_EXTS:
        return p.read_text(encoding="utf-8")
    if suffix in _SUBTITLE_EXTS:
        from videocaptioner.core.asr.asr_data import ASRData

        asr = ASRData.from_subtitle_file(str(p))
        return asr.to_txt() if asr.has_data() else ""
    return None


class TextMatchingInterface(QWidget):
    """文稿匹配主界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TextMatchingInterface")
        self.setStyleSheet(TRANSCRIPTION_PAGE_QSS)
        self.worker_thread = None
        self.setup_ui()

    def setup_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 说明文本
        desc = BodyLabel(
            "使用 DTW 算法将正确的文稿对齐到 ASR 识别的时间轴，生成准确的时间戳字幕。",
            self,
        )
        desc.setStyleSheet("color: #888;")
        main_layout.addWidget(desc)

        # 左右分栏容器
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        # 左侧：媒体输入 + 参数设置
        left_layout = QVBoxLayout()
        left_layout.setSpacing(16)

        # 媒体输入卡片
        self.media_card = MediaInputCard(self)
        left_layout.addWidget(self.media_card)

        # 参数设置卡片
        param_card = CardWidget(self)
        param_layout = QVBoxLayout(param_card)
        param_layout.setContentsMargins(20, 20, 20, 20)
        param_layout.setSpacing(12)

        param_title = BodyLabel("参数设置", self)
        param_layout.addWidget(param_title)

        # 识别模型（与语音转录、全局设置共用 cfg.transcribe_model）
        model_layout = QHBoxLayout()
        model_layout.addWidget(BodyLabel("识别模型:", self))
        self.model_combo = ComboBox(self)
        self._available_models = get_available_transcribe_models()
        for model in self._available_models:
            self.model_combo.addItem(model.value, userData=model)
        self.model_combo.currentIndexChanged.connect(self._on_transcribe_model_changed)
        model_layout.addWidget(self.model_combo, 1)

        self.model_settings_btn = PushButton(FIF.SETTING, "模型详细设置", self)
        self.model_settings_btn.clicked.connect(self._open_model_settings_dialog)
        model_layout.addWidget(self.model_settings_btn)
        model_layout.addStretch()
        param_layout.addLayout(model_layout)

        model_hint = BodyLabel(
            "💡 Faster Whisper 等参数较多，请点击「模型详细设置」在弹窗中配置",
            self,
        )
        model_hint.setStyleSheet("color: #666; font-size: 11px;")
        param_layout.addWidget(model_hint)

        # 语言选择
        lang_layout = QHBoxLayout()
        lang_label = BodyLabel("识别语言:", self)
        self.language_combo = ComboBox(self)
        self.language_combo.addItems([
            "auto - 自动检测（推荐）",
            "zh - 中文",
            "en - English",
            "ja - 日本語",
            "ko - 한국어",
            "es - Español",
            "fr - Français",
            "de - Deutsch",
            "ru - Русский",
            "ar - العربية",
            "pt - Português",
            "it - Italiano",
            "th - ไทย",
            "vi - Tiếng Việt",
            "tr - Türkçe",
        ])
        self.language_combo.setCurrentIndex(0)
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.language_combo)
        lang_layout.addStretch()
        param_layout.addLayout(lang_layout)

        lang_hint = BodyLabel("💡 Whisper 支持 99 种语言", self)
        lang_hint.setStyleSheet("color: #666; font-size: 11px;")
        param_layout.addWidget(lang_hint)

        param_layout.addStretch()
        left_layout.addWidget(param_card)

        # 开始按钮
        self.start_btn = PrimaryPushButton(FIF.PLAY, "开始匹配", self)
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self._start_matching)
        left_layout.addWidget(self.start_btn)

        # 进度显示
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)

        self.status_label = BodyLabel("", self)
        self.status_label.setVisible(False)
        left_layout.addWidget(self.status_label)

        left_layout.addStretch()

        # 右侧：文稿输入
        right_layout = QVBoxLayout()
        self.transcript_card = TranscriptInputCard(self)
        right_layout.addWidget(self.transcript_card)

        # 添加左右布局
        content_layout.addLayout(left_layout, 1)
        content_layout.addLayout(right_layout, 1)

        main_layout.addLayout(content_layout)

        self._sync_transcribe_model_from_cfg()

    def _sync_transcribe_model_from_cfg(self):
        """从全局配置恢复识别模型选择。"""
        current = cfg.transcribe_model.value
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == current:
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(i)
                self.model_combo.blockSignals(False)
                return

    def _open_model_settings_dialog(self):
        model_name = self.model_combo.currentText()
        dialog = TranscriptionModelSettingsDialog(model_name, self.window())
        dialog.exec()

    def _on_transcribe_model_changed(self, index: int):
        if index < 0:
            return
        model = self.model_combo.itemData(index)
        if model is None:
            return
        cfg.set(cfg.transcribe_model, model)
        cfg.save()

    def _start_matching(self):
        """开始匹配"""
        # 参数校验
        media_path = self.media_card.get_file_path()
        if not media_path:
            InfoBar.warning(
                title="请选择媒体文件",
                content="请先拖拽或选择一个视频/音频文件",
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        user_text = self.transcript_card.get_text()
        if not user_text:
            InfoBar.warning(
                title="请输入文稿",
                content="请先输入或导入正确的文稿文本",
                duration=INFOBAR_DURATION_WARNING,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        # 禁用控件
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setVisible(True)
        self.status_label.setText("准备中...")

        # 创建工作线程
        # 提取语言代码
        language_text = self.language_combo.currentText()
        language = language_text.split(" - ")[0]  # 提取 "auto", "zh", "en" 等

        self.worker_thread = TextMatchingThread(
            media_path=media_path,
            user_text=user_text,
            language=language,
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
            title="匹配失败",
            content=error_msg,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_finished(self, output_path: str):
        """匹配完成"""
        self.start_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("匹配完成！")

        folder = Path(output_path).parent
        open_btn = PushButton(FIF.FOLDER, "打开文件夹", self)
        open_btn.clicked.connect(lambda: open_folder(folder))

        bar = InfoBar.success(
            title="匹配成功",
            content=f"已保存到: {os.path.basename(output_path)}",
            duration=INFOBAR_DURATION_SUCCESS,
            position=InfoBarPosition.TOP,
            parent=self,
        )
        bar.addWidget(open_btn)
