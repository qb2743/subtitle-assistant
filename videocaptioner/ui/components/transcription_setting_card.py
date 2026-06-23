from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, MessageBoxBase, SingleDirectionScrollArea
from qfluentwidgets.common.config import isDarkTheme

from videocaptioner.core.entities import (
    TranscribeModelEnum,
)
from videocaptioner.core.utils.platform_utils import is_macos

from .FasterWhisperSettingWidget import FasterWhisperSettingWidget
from .transcription_settings_style import (
    TRANSCRIPTION_EMBED_PANEL_QSS,
    TRANSCRIPTION_SETTINGS_TRANSPARENT_QSS,
)
from .WhisperAPISettingWidget import WhisperAPISettingWidget
from .WhisperCppSettingWidget import WhisperCppSettingWidget

_TRANSPARENT_PANEL = TRANSCRIPTION_EMBED_PANEL_QSS.strip()


class TranscriptionSettingCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_TRANSPARENT_PANEL)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.stacked_widget = QStackedWidget(self)
        self.stacked_widget.setStyleSheet(_TRANSPARENT_PANEL)

        self.empty_widget = QWidget(self)
        self.empty_widget.setStyleSheet(_TRANSPARENT_PANEL)
        self.whisper_cpp_widget = WhisperCppSettingWidget(self)
        self.whisper_api_widget = WhisperAPISettingWidget(self)

        self.faster_whisper_widget: Optional[FasterWhisperSettingWidget] = None
        if not is_macos():
            self.faster_whisper_widget = FasterWhisperSettingWidget(self)

        self.stacked_widget.addWidget(self.empty_widget)
        self.stacked_widget.addWidget(self.whisper_cpp_widget)
        self.stacked_widget.addWidget(self.whisper_api_widget)
        if self.faster_whisper_widget is not None:
            self.stacked_widget.addWidget(self.faster_whisper_widget)

        self.main_layout.addWidget(self.stacked_widget)

    def on_model_changed(self, value):
        if value == TranscribeModelEnum.WHISPER_CPP.value:
            self.stacked_widget.setCurrentWidget(self.whisper_cpp_widget)
        elif value == TranscribeModelEnum.WHISPER_API.value:
            self.stacked_widget.setCurrentWidget(self.whisper_api_widget)
        elif value == TranscribeModelEnum.FASTER_WHISPER.value:
            if self.faster_whisper_widget is not None:
                self.stacked_widget.setCurrentWidget(self.faster_whisper_widget)
            else:
                self.stacked_widget.setCurrentWidget(self.empty_widget)
        else:
            self.stacked_widget.setCurrentWidget(self.empty_widget)


class TranscriptionModelSettingsDialog(MessageBoxBase):
    """在独立窗口中配置当前识别模型（Faster Whisper / Whisper API 等）。"""

    def __init__(self, model_display_name: str, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr("识别模型详细设置"), self)
        subtitle = BodyLabel(
            self.tr(f"当前模型：{model_display_name}（与「语音转录」「文稿匹配」共用配置）"),
            self,
        )
        if isDarkTheme():
            subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.55); font-size: 12px;")
        else:
            subtitle.setStyleSheet("color: rgba(0, 0, 0, 0.55); font-size: 12px;")

        self.setting_card = TranscriptionSettingCard(self)

        self.scroll_area = SingleDirectionScrollArea(orient=Qt.Vertical, parent=self)
        self.scroll_area.setStyleSheet(TRANSCRIPTION_SETTINGS_TRANSPARENT_QSS)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(420)
        self.scroll_area.setWidget(self.setting_card)
        self.scroll_area.viewport().setStyleSheet("background-color: transparent;")

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(subtitle)
        self.viewLayout.addWidget(self.scroll_area)
        self.viewLayout.setSpacing(12)

        self.widget.setMinimumWidth(620)
        self.widget.setMinimumHeight(520)

        self.yesButton.setText(self.tr("完成"))
        self.cancelButton.setText(self.tr("取消"))

        self.setting_card.on_model_changed(model_display_name)