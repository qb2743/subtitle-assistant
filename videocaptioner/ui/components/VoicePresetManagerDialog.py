# -*- coding: utf-8 -*-
"""音色管理面板 —— 管理参考音频克隆音色库。

Fish Audio 与 dots/voxcpm 共用一份 voice_presets.json，按渠道过滤展示。
支持新建 / 编辑 / 改名 / 删除 / 试听 / 应用到当前配音。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    MessageBox,
    MessageBoxBase,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

# 渠道显示名映射
_PROVIDER_LABELS = {
    "fishaudio": "Fish Audio",
    "dots": "Dots-TTS",
    "voxcpm": "VoxCPM",
    "": "通用",
}


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider or "通用")


def load_presets(presets_file: Path) -> list:
    """从文件读取音色预设列表。"""
    try:
        if presets_file.exists():
            with open(presets_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_presets(presets_file: Path, presets: list) -> None:
    """写入音色预设列表到文件。"""
    presets_file.parent.mkdir(parents=True, exist_ok=True)
    with open(presets_file, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)


class _PresetItemWidget(QWidget):
    """列表项的自定义控件：名称 + 渠道标签 + 音频文件 + 参考文本预览。"""

    def __init__(self, preset: dict, parent=None):
        super().__init__(parent)
        self._preset = preset
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # 第一行：名称 + 渠道标签
        top = QHBoxLayout()
        top.setSpacing(8)
        name_label = StrongBodyLabel(preset.get("name", "未命名"), self)
        top.addWidget(name_label)
        top.addStretch(1)
        provider = preset.get("provider", "")
        tag = BodyLabel(_provider_label(provider), self)
        tag.setStyleSheet(
            "color: #fff; background: #5b8def; border-radius: 8px; "
            "padding: 1px 8px; font-size: 11px;"
        )
        top.addWidget(tag)
        layout.addLayout(top)

        # 第二行：音频文件
        audio_path = preset.get("audio_path", "")
        audio_name = Path(audio_path).name if audio_path else "（未设置音频）"
        audio_exists = bool(audio_path) and Path(audio_path).is_file()
        color = "#4caf50" if audio_exists else "#ff9800"
        audio_label = BodyLabel(f"🎵 {audio_name}", self)
        audio_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        layout.addWidget(audio_label)

        # 第三行：参考文本预览
        text = (preset.get("audio_text", "") or "").strip()
        preview = text if len(text) <= 60 else text[:60] + "…"
        if preview:
            text_label = BodyLabel(f"💬 {preview}", self)
            text_label.setStyleSheet("color: #888; font-size: 12px;")
            text_label.setWordWrap(True)
            layout.addWidget(text_label)


class VoicePresetEditDialog(MessageBoxBase):
    """新建 / 编辑单个音色预设的子对话框。"""

    def __init__(
        self,
        preset: Optional[dict] = None,
        current_provider: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._preset = preset or {}
        self._current_provider = current_provider

        self.titleLabel = StrongBodyLabel("编辑音色" if preset else "新建音色", self)
        self.viewLayout.addWidget(self.titleLabel)

        # 名称
        self.name_label = BodyLabel("名称", self)
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("给这个音色起个名字，例如「温柔女声」")
        self.name_edit.setText(self._preset.get("name", ""))
        self.viewLayout.addWidget(self.name_label)
        self.viewLayout.addWidget(self.name_edit)

        # 渠道
        self.provider_label = BodyLabel("适用渠道", self)
        self.provider_combo = ComboBox(self)
        self.provider_combo.addItems(["Fish Audio", "Dots-TTS", "VoxCPM", "通用"])
        prov = self._preset.get("provider", current_provider)
        prov_map = {"fishaudio": "Fish Audio", "dots": "Dots-TTS", "voxcpm": "VoxCPM", "": "通用"}
        target = prov_map.get(prov, "通用")
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemText(i) == target:
                self.provider_combo.setCurrentIndex(i)
                break
        self.viewLayout.addWidget(self.provider_label)
        self.viewLayout.addWidget(self.provider_combo)

        # 参考音频
        self.audio_label = BodyLabel("参考音频", self)
        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        self.audio_edit = LineEdit(self)
        self.audio_edit.setPlaceholderText("wav / mp3 / flac 参考音频路径")
        self.audio_edit.setText(self._preset.get("audio_path", ""))
        self.audio_btn = ToolButton(FIF.FOLDER, self)
        self.audio_btn.setToolTip("选择参考音频")
        self.audio_btn.clicked.connect(self._browse_audio)
        audio_row.addWidget(self.audio_edit, 1)
        audio_row.addWidget(self.audio_btn)
        self.viewLayout.addWidget(self.audio_label)
        self.viewLayout.addLayout(audio_row)

        # 参考文本
        self.text_label = BodyLabel("参考文本（音频对应的文字）", self)
        self.text_edit = PlainTextEdit(self)
        self.text_edit.setPlaceholderText("输入参考音频对应的文字内容")
        self.text_edit.setPlainText(self._preset.get("audio_text", ""))
        self.text_edit.setMinimumHeight(100)
        self.viewLayout.addWidget(self.text_label)
        self.viewLayout.addWidget(self.text_edit)

        hint = BodyLabel("建议 3-10 秒、发音清晰的参考音频。", self)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        self.viewLayout.addWidget(hint)

        self.viewLayout.setSpacing(10)
        self.widget.setMinimumWidth(500)

        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def _browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择参考音频", "", "音频文件 (*.wav *.mp3 *.flac *.ogg *.aac)"
        )
        if path:
            self.audio_edit.setText(path)

    def _provider_value(self) -> str:
        text = self.provider_combo.currentText()
        rev = {"Fish Audio": "fishaudio", "Dots-TTS": "dots", "VoxCPM": "voxcpm", "通用": ""}
        return rev.get(text, "")

    def get_preset(self) -> dict:
        base = dict(self._preset)
        base["name"] = self.name_edit.text().strip()
        base["provider"] = self._provider_value()
        base["audio_path"] = self.audio_edit.text().strip()
        base["audio_text"] = self.text_edit.toPlainText().strip()
        if not base.get("created"):
            base["created"] = datetime.now().isoformat()
        return base


class VoicePresetManagerDialog(MessageBoxBase):
    """音色管理主面板。

    列表展示所有预设（按渠道过滤），支持新建 / 编辑 / 删除 / 试听 / 应用。
    保存动作直接写回 presets 文件；「应用此音色」会发出 applied 信号。

    继承自 MessageBoxBase，使面板自动跟随 qfluentwidgets 暗色/亮色主题。
    """

    applied = pyqtSignal(str, str)  # (audio_path, audio_text)

    def __init__(
        self,
        presets_file: Path,
        current_provider: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._presets_file = presets_file
        self._current_provider = current_provider
        self._presets: list = load_presets(presets_file)
        self._player: Optional[QMediaPlayer] = None

        # 标题
        self.titleLabel = StrongBodyLabel("🎙 参考音色管理", self)
        self.viewLayout.addWidget(self.titleLabel)

        subtitle = BodyLabel(
            "管理参考音频克隆音色库；Fish Audio 与 dots/voxcpm 共用，按渠道过滤。",
            self,
        )
        subtitle.setStyleSheet("color: #888; font-size: 12px;")
        subtitle.setWordWrap(True)
        self.viewLayout.addWidget(subtitle)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.new_btn = PrimaryPushButton(FIF.ADD, "新建", self)
        self.new_btn.clicked.connect(self._on_new)
        self.edit_btn = PushButton(FIF.EDIT, "编辑", self)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn = PushButton(FIF.DELETE, "删除", self)
        self.delete_btn.clicked.connect(self._on_delete)
        self.preview_btn = PushButton(FIF.PLAY, "试听", self)
        self.preview_btn.clicked.connect(self._on_preview)
        toolbar.addWidget(self.new_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addWidget(self.preview_btn)
        toolbar.addStretch(1)
        # 渠道过滤：默认「全部渠道」——参考音频是跨渠道通用资产，
        # 用户在 dots 存的音色在 Fish Audio 下也应可见可应用。
        toolbar.addWidget(BodyLabel("筛选:", self))
        self.filter_combo = ComboBox(self)
        self.filter_combo.blockSignals(True)
        self.filter_combo.addItems(["当前渠道", "全部渠道", "Fish Audio", "Dots-TTS", "VoxCPM"])
        self.filter_combo.setCurrentIndex(1)  # 默认全部渠道
        self.filter_combo.blockSignals(False)
        self.filter_combo.currentIndexChanged.connect(self._reload_list)
        toolbar.addWidget(self.filter_combo)
        self.viewLayout.addLayout(toolbar)

        # 列表
        self.list_widget = ListWidget(self)
        self.list_widget.setSpacing(2)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.viewLayout.addWidget(self.list_widget, 1)

        # 空状态提示
        self.empty_label = BodyLabel("暂无音色，点击「新建」添加第一个参考音色。", self)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #aaa; font-size: 13px; padding: 24px;")
        self.viewLayout.addWidget(self.empty_label)

        self.viewLayout.setSpacing(10)
        self.widget.setMinimumSize(560, 480)
        self.widget.setMaximumSize(960, 720)

        # 底部按钮：应用此音色 / 关闭
        self.yesButton.setText("应用此音色")
        self.cancelButton.setText("关闭")
        # 重连 yesButton 到我们的应用逻辑
        try:
            self.yesButton.clicked.disconnect()
        except TypeError:
            pass
        self.yesButton.clicked.connect(self._on_apply)
        self.yesButton.setEnabled(False)

        self._reload_list()
        self._on_selection_changed()

    # ---- 列表渲染 ----
    def _filter_value(self) -> str:
        text = self.filter_combo.currentText()
        if text == "当前渠道":
            return self._current_provider
        if text == "全部渠道":
            return "__all__"
        rev = {"Fish Audio": "fishaudio", "Dots-TTS": "dots", "VoxCPM": "voxcpm"}
        return rev.get(text, "__all__")

    def _filtered_presets(self) -> list:
        f = self._filter_value()
        if f == "__all__":
            return list(self._presets)
        return [p for p in self._presets if p.get("provider", "") in ("", f)]

    def _reload_list(self):
        self.list_widget.clear()
        for preset in self._filtered_presets():
            item = QListWidgetItem(self.list_widget)
            item.setData(Qt.UserRole, preset)
            widget = _PresetItemWidget(preset)
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
        self.empty_label.setVisible(self.list_widget.count() == 0)
        self.list_widget.setVisible(self.list_widget.count() > 0)
        self._on_selection_changed()

    def _current_preset(self) -> Optional[dict]:
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self):
        has = self.list_widget.currentItem() is not None
        self.edit_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        self.preview_btn.setEnabled(has)
        self.yesButton.setEnabled(has)

    def _on_item_double_clicked(self, item):
        self._on_apply()

    # ---- CRUD ----
    def _persist(self):
        save_presets(self._presets_file, self._presets)

    def _on_new(self):
        dlg = VoicePresetEditDialog(preset=None, current_provider=self._current_provider, parent=self)
        if dlg.exec_():
            preset = dlg.get_preset()
            if not preset["name"]:
                InfoBar.warning(
                    title="缺少名称", content="请填写音色名称。",
                    duration=2500, position=InfoBarPosition.TOP, parent=self,
                )
                return
            if not preset["audio_path"]:
                InfoBar.warning(
                    title="缺少参考音频", content="请选择参考音频文件。",
                    duration=2500, position=InfoBarPosition.TOP, parent=self,
                )
                return
            self._presets = [p for p in self._presets if p.get("name") != preset["name"]]
            self._presets.append(preset)
            self._persist()
            self._reload_list()
            self._select_by_name(preset["name"])
            InfoBar.success(
                title="已新建", content=f"音色「{preset['name']}」已保存。",
                duration=2500, position=InfoBarPosition.TOP, parent=self,
            )

    def _on_edit(self):
        preset = self._current_preset()
        if not preset:
            return
        dlg = VoicePresetEditDialog(preset=dict(preset), current_provider=self._current_provider, parent=self)
        if dlg.exec_():
            new_preset = dlg.get_preset()
            if not new_preset["name"]:
                return
            old_name = preset.get("name", "")
            if new_preset["name"] != old_name:
                self._presets = [p for p in self._presets if p.get("name") not in (old_name, new_preset["name"])]
            else:
                self._presets = [p for p in self._presets if p.get("name") != old_name]
            self._presets.append(new_preset)
            self._persist()
            self._reload_list()
            self._select_by_name(new_preset["name"])
            InfoBar.success(
                title="已更新", content=f"音色「{new_preset['name']}」已更新。",
                duration=2500, position=InfoBarPosition.TOP, parent=self,
            )

    def _on_delete(self):
        preset = self._current_preset()
        if not preset:
            return
        name = preset.get("name", "")

        if not MessageBox("删除音色", f"确定删除音色「{name}」？此操作不可撤销。", self).exec_():
            return
        self._presets = [p for p in self._presets if p.get("name") != name]
        self._persist()
        self._reload_list()
        InfoBar.success(
            title="已删除", content=f"音色「{name}」已删除。",
            duration=2500, position=InfoBarPosition.TOP, parent=self,
        )

    def _select_by_name(self, name: str):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole).get("name") == name:
                self.list_widget.setCurrentRow(i)
                break

    # ---- 试听 ----
    def _on_preview(self):
        preset = self._current_preset()
        if not preset:
            return
        audio_path = preset.get("audio_path", "")
        if not audio_path or not Path(audio_path).is_file():
            InfoBar.warning(
                title="无法试听", content="参考音频文件不存在，请先编辑并选择有效音频。",
                duration=3000, position=InfoBarPosition.TOP, parent=self,
            )
            return
        if self._player and self._player.state() == QMediaPlayer.PlayingState:
            self._player.stop()
            self.preview_btn.setText("试听")
            return
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._player.stateChanged.connect(self._on_player_state)
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(str(Path(audio_path).resolve()))))
        self._player.play()

    def _on_player_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.preview_btn.setText("停止")
        else:
            self.preview_btn.setText("试听")

    # ---- 应用 ----
    def _on_apply(self):
        preset = self._current_preset()
        if not preset:
            return
        audio_path = preset.get("audio_path", "")
        audio_text = preset.get("audio_text", "")
        if not audio_path:
            InfoBar.warning(
                title="无法应用", content="该音色未设置参考音频。",
                duration=2500, position=InfoBarPosition.TOP, parent=self,
            )
            return
        self.applied.emit(audio_path, audio_text)
        self.accept()
