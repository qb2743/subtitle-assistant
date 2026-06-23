#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试配音界面是否能正常显示音色"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from videocaptioner.ui.view.dubbing_interface import DubbingInterface


def test_dubbing_interface():
    """测试配音界面"""
    app = QApplication(sys.argv)

    # 创建界面
    interface = DubbingInterface()

    # 检查语言下拉框
    print(f"语言下拉框项数: {interface.language_combo.count()}")
    if interface.language_combo.count() > 0:
        print(f"第一个语言: {interface.language_combo.itemText(0)}")
        print(f"第一个语言代码: {interface.language_combo.itemData(0)}")

        # 选择第一个语言（应该是中文）
        interface.language_combo.setCurrentIndex(0)

        # 等待加载
        app.processEvents()

        # 检查音色下拉框
        print(f"\n音色下拉框项数: {interface.voice_combo.count()}")
        if interface.voice_combo.count() > 0:
            print(f"前5个音色:")
            for i in range(min(5, interface.voice_combo.count())):
                print(f"  {i+1}. {interface.voice_combo.itemText(i)} -> {interface.voice_combo.itemData(i)}")
            print(f"\n✅ 音色加载成功！共 {interface.voice_combo.count()} 个音色")
        else:
            print(f"\n❌ 音色未加载")
    else:
        print("❌ 语言未加载")

    # 显示界面（可选）
    # interface.show()
    # sys.exit(app.exec_())


if __name__ == "__main__":
    test_dubbing_interface()
