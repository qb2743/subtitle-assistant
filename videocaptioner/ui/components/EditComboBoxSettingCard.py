from typing import List, Optional, Union

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QCompleter
from qfluentwidgets import CheckableMenu, EditableComboBox, SettingCard
from qfluentwidgets.common.config import ConfigItem, qconfig


def _selection_values(value: str) -> List[str]:
    parts = (value or "").replace("，", ",").split(",")
    return list(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _toggle_selection(value: str, selected: str) -> str:
    values = _selection_values(value)
    selected = selected.strip()
    if not selected:
        return ", ".join(values)

    if selected in values and len(values) > 1:
        values.remove(selected)
    elif selected not in values:
        values.append(selected)
    return ", ".join(values)


class _MultiSelectComboBoxMenu(CheckableMenu):
    """Checkable menu that reflects the current comma-separated value."""

    def __init__(self, selected: List[str], parent=None):
        super().__init__(parent=parent)
        self._selected = set(selected)

    def addAction(self, action):
        action.setCheckable(True)
        action.setChecked(action.text() in self._selected)
        return super().addAction(action)

    def _onItemClicked(self, item):
        action = item.data(Qt.UserRole)
        if action not in self.menuActions() or not action.isEnabled():
            return

        action.trigger()
        selected = set(_selection_values(self.parent().currentText()))
        action.setChecked(action.text() in selected)
        self.view.viewport().update()


class MultiSelectEditableComboBox(EditableComboBox):
    """Editable combo box that toggles items in an ordered value list."""

    def _createComboMenu(self):
        return _MultiSelectComboBoxMenu(_selection_values(self.currentText()), self)

    def _onItemClicked(self, index):
        if not 0 <= index < self.count():
            return

        selected = self.itemText(index)
        self.setText(_toggle_selection(self.currentText(), selected))
        self.activated.emit(index)
        self.textActivated.emit(selected)

    def _onReturnPressed(self):
        self.setText(", ".join(_selection_values(self.currentText())))


def _combo_box_class(multiSelect: bool):
    return MultiSelectEditableComboBox if multiSelect else EditableComboBox


class EditComboBoxSettingCard(SettingCard):
    """可编辑的下拉框设置卡片"""

    currentTextChanged = pyqtSignal(str)

    def __init__(
        self,
        configItem: ConfigItem,
        icon: Union[str, QIcon],
        title: str,
        content: Optional[str] = None,
        items: Optional[List[str]] = None,
        parent=None,
        *,
        multiSelect: bool = False,
    ):
        super().__init__(icon, title, content, parent)

        self.configItem = configItem
        self.items = items or []
        self.multiSelect = multiSelect
        self._updatingItems = False

        # 创建可编辑的组合框
        comboBoxClass = _combo_box_class(multiSelect)
        self.comboBox = comboBoxClass(self)
        for item in self.items:
            self.comboBox.addItem(item)

        # 设置搜索功能
        self._setupCompleter()

        # 设置布局
        self.hBoxLayout.addWidget(self.comboBox, 1, Qt.AlignRight)  # type: ignore
        self.hBoxLayout.addSpacing(16)

        # 设置最小宽度
        self.comboBox.setMinimumWidth(280)

        # 设置初始值
        self.setValue(qconfig.get(configItem))

        # 连接信号
        self.comboBox.currentTextChanged.connect(self.__onTextChanged)
        configItem.valueChanged.connect(self.setValue)

    def _setupCompleter(self):
        """设置搜索自动完成功能"""
        if self.multiSelect or not self.items:
            # EditableComboBox completion replaces the entire model chain.
            self.comboBox.setCompleter(None)
            return

        completer = QCompleter(self.items, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)  # type: ignore # 不区分大小写
        completer.setFilterMode(Qt.MatchContains)  # type: ignore # 包含匹配
        self.comboBox.setCompleter(completer)

    def __onTextChanged(self, text: str):
        """当文本改变时触发"""
        if self._updatingItems:
            return

        self.setValue(text)
        self.currentTextChanged.emit(text)

    def setValue(self, value: str):
        """设置值"""
        qconfig.set(self.configItem, value)
        self.comboBox.setText(value)

    def addItems(self, items: List[str]):
        """添加选项"""
        for item in items:
            self.comboBox.addItem(item)
        self.items.extend(items)
        self._setupCompleter()

    def setItems(self, items: List[str]):
        """重新设置选项列表"""
        value = self.comboBox.currentText()
        self._updatingItems = True
        try:
            self.comboBox.clear()
            fetchedItems = [item.strip() for item in items if item.strip()]
            selectedItems = _selection_values(value) if self.multiSelect else []
            self.items = list(dict.fromkeys([*selectedItems, *fetchedItems]))
            for item in self.items:
                self.comboBox.addItem(item)
            self.comboBox.setText(value)
        finally:
            self._updatingItems = False
        self._setupCompleter()
