#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""综合测试配音界面修复"""

import sys
import io
from pathlib import Path

# 设置输出编码为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("测试 1: 音色加载器（底层）")
print("=" * 60)

from videocaptioner.core.voices.loader import (
    load_edge_voices,
    get_all_languages,
    get_voices_by_language
)

voices = load_edge_voices()
print(f"✓ 加载音色数据: {len(voices)} 种语言")

languages = get_all_languages()
print(f"✓ 获取语言列表: {len(languages)} 种语言")
print(f"  前3个: {languages[:3]}")

zh_voices = get_voices_by_language("zh")
print(f"✓ 中文音色: {len(zh_voices)} 个")
print(f"  前3个: {[v[0] for v in zh_voices[:3]]}")

print("\n" + "=" * 60)
print("测试 2: UI 类定义检查")
print("=" * 60)

try:
    from videocaptioner.ui.view.dubbing_interface import (
        DubbingInterface,
        ElevenLabsAPITestThread,
        VoicePreviewThread
    )
    print("✓ DubbingInterface 类导入成功")
    print("✓ ElevenLabsAPITestThread 类导入成功")
    print("✓ VoicePreviewThread 类导入成功")
except ImportError as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("测试 3: UI 初始化（无显示）")
print("=" * 60)

try:
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = DubbingInterface()

    print(f"✓ 界面创建成功")
    print(f"  Provider: {window.provider_combo.currentText()}")
    print(f"  语言框可见: {window.language_combo.isVisible()}")
    print(f"  语言数量: {window.language_combo.count()}")
    print(f"  音色框可见: {window.voice_combo.isVisible()}")
    print(f"  音色数量: {window.voice_combo.count()}")

    # 模拟选择语言
    if window.language_combo.count() > 0:
        window.language_combo.setCurrentIndex(0)
        app.processEvents()
        print(f"\n✓ 选择第一个语言")
        print(f"  语言: {window.language_combo.currentText()}")
        print(f"  音色数量: {window.voice_combo.count()}")

        if window.voice_combo.count() > 0:
            print(f"  前3个音色: {[window.voice_combo.itemText(i) for i in range(min(3, window.voice_combo.count()))]}")

    # 结果判断
    success = True
    if window.language_combo.count() == 0:
        print("\n✗ 失败: 语言列表为空")
        success = False
    elif not window.language_combo.isVisible():
        print("\n✗ 失败: 语言选择框不可见")
        success = False
    elif window.voice_combo.count() == 0:
        print("\n✗ 失败: 选择语言后音色列表为空")
        success = False
    else:
        print("\n✓ 所有测试通过！")

    sys.exit(0 if success else 1)

except Exception as e:
    print(f"\n✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
