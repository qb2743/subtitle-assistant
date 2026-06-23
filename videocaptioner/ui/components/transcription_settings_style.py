# -*- coding: utf-8 -*-
"""转录模型设置区域背景：与 FluentWindow 主界面一致，避免 Qt 默认白底。"""

# 滚动区 + viewport + 内层容器（弹窗与嵌入页共用）
TRANSCRIPTION_SETTINGS_TRANSPARENT_QSS = """
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QAbstractScrollArea::viewport {
    background-color: transparent;
}
"""

TRANSCRIPTION_EMBED_PANEL_QSS = """
background-color: transparent;
"""

# 语音转录 / 文稿匹配 子页：与设置页 ScrollArea 一致
TRANSCRIPTION_PAGE_QSS = """
TranscriptionInterface,
TextMatchingInterface,
#transcriptionSettingHost {
    background-color: transparent;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QAbstractScrollArea::viewport {
    background-color: transparent;
}
"""