# -*- coding: utf-8 -*-
"""多 API Key 编辑对话框（明文，换行或逗号分隔）"""

from qfluentwidgets import BodyLabel, MessageBoxBase, PlainTextEdit

from videocaptioner.core.speech.api_keys import parse_api_keys


class ApiKeysEditorDialog(MessageBoxBase):
    """在独立窗口中编辑 API Key 列表。"""

    def __init__(self, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr("API Key 管理"), self)
        self.hintLabel = BodyLabel(
            self.tr(
                "每行一个 Key，也可用英文逗号分隔多个 Key。\n"
                "保存后用于配音与配额查询（多 Key 时按顺序轮询）。"
            ),
            self,
        )
        self.hintLabel.setStyleSheet("color: #888; font-size: 12px;")

        self.text_edit = PlainTextEdit(self)
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setMinimumHeight(220)
        self.text_edit.setPlaceholderText(
            "sk_xxxxxxxx\nsk_yyyyyyyy"
        )

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.hintLabel)
        self.viewLayout.addWidget(self.text_edit)
        self.viewLayout.setSpacing(10)

        self.widget.setMinimumWidth(480)
        self.yesButton.setText(self.tr("保存"))
        self.cancelButton.setText(self.tr("取消"))

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()

    def key_count(self) -> int:
        return len(parse_api_keys(self.get_text()))