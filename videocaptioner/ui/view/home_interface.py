from typing import Optional

from PyQt5.QtWidgets import QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import SegmentedWidget

from videocaptioner.core.llm.context import generate_task_id
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.view.dubbing_interface import DubbingInterface
from videocaptioner.ui.view.subtitle_interface import SubtitleInterface
from videocaptioner.ui.view.task_creation_interface import TaskCreationInterface
from videocaptioner.ui.view.text_matching_interface import TextMatchingInterface
from videocaptioner.ui.view.transcription_interface import TranscriptionInterface
from videocaptioner.ui.view.video_alignment_interface import VideoAlignmentInterface


class HomeInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_task_id: Optional[str] = None  # 当前流程的任务 ID

        # 设置对象名称和样式
        self.setObjectName("HomeInterface")
        self.setStyleSheet(
            """
            HomeInterface {
                background-color: transparent;
            }
        """
        )

        # 创建分段控件和堆叠控件
        self.pivot = SegmentedWidget(self)
        self.pivot.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout = QVBoxLayout(self)

        # 添加子界面
        self.task_creation_interface = TaskCreationInterface(self)
        self.transcription_interface = TranscriptionInterface(self)
        self.subtitle_optimization_interface = SubtitleInterface(self)
        self.video_alignment_interface = VideoAlignmentInterface(self)
        self.dubbing_interface = DubbingInterface(self)
        self.text_matching_interface = TextMatchingInterface(self)

        self.addSubInterface(
            self.task_creation_interface, "TaskCreationInterface", self.tr("任务创建")
        )
        self.addSubInterface(
            self.transcription_interface, "TranscriptionInterface", self.tr("语音转录")
        )
        self.addSubInterface(
            self.subtitle_optimization_interface,
            "SubtitleInterface",
            self.tr("字幕优化与翻译"),
        )
        self.addSubInterface(
            self.dubbing_interface, "DubbingInterface", self.tr("配音")
        )
        self.addSubInterface(
            self.video_alignment_interface,
            "VideoAlignmentInterface",
            self.tr("视频对齐"),
        )
        self.addSubInterface(
            self.text_matching_interface, "TextMatchingInterface", self.tr("文稿匹配")
        )

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)

        self.stackedWidget.currentChanged.connect(self.onCurrentIndexChanged)
        self.stackedWidget.setCurrentWidget(self.task_creation_interface)
        self.pivot.setCurrentItem("TaskCreationInterface")

        self.task_creation_interface.finished.connect(self.switch_to_transcription)
        self.transcription_interface.finished.connect(
            self.switch_to_subtitle_optimization
        )

    def switch_to_transcription(self, file_path):
        # 流程开始，生成新的 task_id
        self._current_task_id = generate_task_id()

        transcribe_task = TaskFactory.create_transcribe_task(
            file_path, need_next_task=True, task_id=self._current_task_id
        )
        self.transcription_interface.set_task(transcribe_task)
        self.transcription_interface.process()
        self.stackedWidget.setCurrentWidget(self.transcription_interface)
        self.pivot.setCurrentItem("TranscriptionInterface")

    def switch_to_subtitle_optimization(self, file_path, video_path):
        # 继续使用同一个 task_id
        subtitle_task = TaskFactory.create_subtitle_task(
            file_path, video_path, need_next_task=True, task_id=self._current_task_id
        )
        self.subtitle_optimization_interface.set_task(subtitle_task)
        self.subtitle_optimization_interface.process()
        self.stackedWidget.setCurrentWidget(self.subtitle_optimization_interface)
        self.pivot.setCurrentItem("SubtitleInterface")

    def switch_to_video_synthesis(self, video_path, subtitle_path):
        # 继续使用同一个 task_id，流程结束后清空
        self._current_task_id = None  # 流程结束
        # 旧版流程曾经使用独立的视频合成页；当前流程统一由视频对齐页处理。
        if video_path:
            self.video_alignment_interface.video_input.set_file(video_path)
        self.stackedWidget.setCurrentWidget(self.video_alignment_interface)
        self.pivot.setCurrentItem("VideoAlignmentInterface")

    def addSubInterface(self, widget, objectName, text):
        # 添加子界面到堆叠控件和分段控件
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(
            routeKey=objectName,
            text=text,
            onClick=lambda: self.stackedWidget.setCurrentWidget(widget),
        )

    def onCurrentIndexChanged(self, index):
        # 当堆叠控件的当前索引改变时，更新分段控件的当前项
        widget = self.stackedWidget.widget(index)
        if widget:
            if widget is self.dubbing_interface:
                widget.load_config()
            elif widget is self.video_alignment_interface:
                widget._config_loading = True
                try:
                    widget._load_config()
                    widget._refresh_tts_models()
                    widget._refresh_tts_voices()
                finally:
                    widget._config_loading = False
            self.pivot.setCurrentItem(widget.objectName())

    def closeEvent(self, event):
        # 关闭事件，关闭所有子界面
        self.task_creation_interface.close()
        self.transcription_interface.close()
        self.subtitle_optimization_interface.close()
        self.video_alignment_interface.close()
        super().closeEvent(event)
