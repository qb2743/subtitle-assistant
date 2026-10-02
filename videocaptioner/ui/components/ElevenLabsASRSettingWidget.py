from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    InfoBar,
    InfoBarPosition,
    PushSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
)
from qfluentwidgets import FluentIcon as FIF

from videocaptioner.core.asr.elevenlabs_asr import (
    SCRIBE_MODELS,
    check_elevenlabs_asr_connection,
)
from videocaptioner.core.constant import INFOBAR_DURATION_ERROR, INFOBAR_DURATION_SUCCESS
from videocaptioner.core.entities import TranscribeLanguageEnum

from ..common.config import cfg, resolve_elevenlabs_asr_api_key
from .EditComboBoxSettingCard import EditComboBoxSettingCard
from .LineEditSettingCard import LineEditSettingCard
from .transcription_settings_style import TRANSCRIPTION_SETTINGS_TRANSPARENT_QSS


class ElevenLabsASRSettingWidget(QWidget):
    """ElevenLabs Scribe 云端转录设置（与「语音转录」「文稿匹配」共用配置）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.setStyleSheet("background-color: transparent;")

        self.scrollArea = SingleDirectionScrollArea(orient=Qt.Vertical, parent=self)  # type: ignore
        self.scrollArea.setStyleSheet(TRANSCRIPTION_SETTINGS_TRANSPARENT_QSS)
        self.scrollArea.viewport().setStyleSheet("background-color: transparent;")

        self.container = QWidget(self)
        self.container.setStyleSheet("background-color: transparent;")
        self.containerLayout = QVBoxLayout(self.container)

        self.setting_group = SettingCardGroup(self.tr("ElevenLabs Scribe 设置"), self)

        self.api_key_card = LineEditSettingCard(
            cfg.elevenlabs_asr_api_key,
            FIF.FINGERPRINT,
            self.tr("API Key"),
            self.tr(
                "多个 Key 用逗号/分号分隔，逐个轮询；留空则复用「配音 → ElevenLabs」已填的 Key"
            ),
            self.tr("xi-... 或 key1,key2,key3"),
            self.setting_group,
        )

        self.base_url_card = LineEditSettingCard(
            cfg.elevenlabs_asr_base_url,
            FIF.LINK,
            self.tr("API Base URL"),
            self.tr("留空使用官方端点 https://api.elevenlabs.io"),
            "https://api.elevenlabs.io",
            self.setting_group,
        )

        self.model_card = EditComboBoxSettingCard(
            cfg.elevenlabs_asr_model,
            FIF.ROBOT,  # type: ignore
            self.tr("Scribe 模型"),
            self.tr("scribe_v2 支持 90+ 语种与词级时间戳；scribe_v1 已被官方废弃"),
            list(SCRIBE_MODELS),
            self.setting_group,
        )

        self.language_card = ComboBoxSettingCard(
            cfg.transcribe_language,
            FIF.LANGUAGE,
            self.tr("源语言"),
            self.tr("音视频中说话的语言，默认自动识别"),
            [lang.value for lang in TranscribeLanguageEnum],
            self.setting_group,
        )

        self.check_connection_card = PushSettingCard(
            self.tr("测试连接"),
            FIF.CONNECT,
            self.tr("测试 ElevenLabs 转录连接"),
            self.tr("用内置示例音频真实调用一次 Scribe（会消耗少量额度）"),
            self.setting_group,
        )

        self.api_key_card.lineEdit.setMinimumWidth(240)
        self.base_url_card.lineEdit.setMinimumWidth(240)
        self.model_card.comboBox.setMinimumWidth(200)
        self.language_card.comboBox.setMinimumWidth(200)

        self.setting_group.addSettingCard(self.api_key_card)
        self.setting_group.addSettingCard(self.base_url_card)
        self.setting_group.addSettingCard(self.model_card)
        self.setting_group.addSettingCard(self.language_card)
        self.setting_group.addSettingCard(self.check_connection_card)

        self.check_connection_card.clicked.connect(self.on_check_connection)

        self.containerLayout.addWidget(self.setting_group)
        self.containerLayout.addStretch(1)

        self.scrollArea.setWidget(self.container)
        self.scrollArea.setWidgetResizable(True)
        self.main_layout.addWidget(self.scrollArea)

    def on_check_connection(self):
        """真实调用一次 Scribe，验证 Key / Base URL / 模型是否可用。"""
        api_key = resolve_elevenlabs_asr_api_key()
        base_url = (self.base_url_card.lineEdit.text() or "").strip()
        model = (self.model_card.comboBox.currentText() or "").strip()

        if not api_key:
            InfoBar.warning(
                self.tr("配置不完整"),
                self.tr(
                    "请填写 ElevenLabs API Key（或在「配音 → ElevenLabs」里配置后留空此项）"
                ),
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
            return

        self.check_connection_card.button.setEnabled(False)
        self.check_connection_card.button.setText(self.tr("正在测试..."))

        self.connection_thread = ElevenLabsASRConnectionThread(api_key, base_url, model)
        self.connection_thread.finished.connect(self.on_connection_check_finished)
        self.connection_thread.error.connect(self.on_connection_check_error)
        self.connection_thread.start()

    def on_connection_check_finished(self, success, result):
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))

        if success:
            InfoBar.success(
                self.tr("连接成功"),
                self.tr("ElevenLabs Scribe 转录成功！\n转录结果：") + result,
                duration=INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
        else:
            InfoBar.error(
                self.tr("连接失败"),
                self.tr("ElevenLabs Scribe 转录失败！\n") + result,
                duration=INFOBAR_DURATION_ERROR,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )

    def on_connection_check_error(self, message):
        self.check_connection_card.button.setEnabled(True)
        self.check_connection_card.button.setText(self.tr("测试连接"))
        InfoBar.error(
            self.tr("测试错误"),
            message,
            duration=INFOBAR_DURATION_ERROR,
            position=InfoBarPosition.BOTTOM,
            parent=self.window(),
        )


class ElevenLabsASRConnectionThread(QThread):
    """ElevenLabs Scribe 连接测试线程。"""

    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, api_key, base_url, model):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self):
        try:
            success, result = check_elevenlabs_asr_connection(
                self.api_key, self.base_url, self.model
            )
            self.finished.emit(success, result)
        except Exception as e:
            self.error.emit(str(e))
