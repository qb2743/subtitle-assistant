#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接测试音色加载逻辑（无GUI）"""

import sys
import logging
from pathlib import Path

# 设置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def test_voice_loader():
    """测试音色加载器"""
    logger.info("=" * 60)
    logger.info("测试1: 直接调用 loader 函数")
    logger.info("=" * 60)

    from videocaptioner.core.voices.loader import (
        load_edge_voices,
        get_all_languages,
        get_voices_by_language
    )

    # 测试1: 加载所有音色
    logger.info("加载音色数据...")
    voices = load_edge_voices()
    logger.info(f"成功！共 {len(voices)} 种语言")
    logger.info(f"语言代码: {list(voices.keys())[:10]}")

    # 测试2: 获取语言列表
    logger.info("\n获取语言列表...")
    languages = get_all_languages()
    logger.info(f"成功！共 {len(languages)} 种语言")
    logger.info(f"前5个语言: {languages[:5]}")

    # 测试3: 获取中文音色
    logger.info("\n获取中文音色...")
    zh_voices = get_voices_by_language("zh")
    logger.info(f"成功！共 {len(zh_voices)} 个中文音色")
    logger.info(f"前3个中文音色: {zh_voices[:3]}")

    logger.info("\n" + "=" * 60)
    logger.info("测试2: 模拟 UI 组件调用")
    logger.info("=" * 60)

    # 模拟 ComboBox 数据结构
    class MockComboBox:
        def __init__(self):
            self.items = []
            self.data = []

        def clear(self):
            self.items = []
            self.data = []

        def addItem(self, text, user_data=None):
            self.items.append(text)
            self.data.append(user_data)

        def count(self):
            return len(self.items)

        def itemText(self, index):
            return self.items[index] if 0 <= index < len(self.items) else ""

        def itemData(self, index):
            return self.data[index] if 0 <= index < len(self.data) else None

        def currentData(self):
            return self.data[0] if self.data else None

    # 模拟加载语言到 ComboBox
    logger.info("模拟语言 ComboBox...")
    language_combo = MockComboBox()
    languages = get_all_languages()
    for code, name in languages:
        language_combo.addItem(f"{name} ({code})", code)

    logger.info(f"语言 ComboBox 项数: {language_combo.count()}")
    logger.info(f"前3项: {[language_combo.itemText(i) for i in range(min(3, language_combo.count()))]}")

    # 模拟切换到中文并加载音色
    logger.info("\n模拟切换到中文...")
    voice_combo = MockComboBox()
    zh_code = "zh"
    zh_voices = get_voices_by_language(zh_code)
    for display_name, voice_id in zh_voices:
        voice_combo.addItem(display_name, voice_id)

    logger.info(f"音色 ComboBox 项数: {voice_combo.count()}")
    logger.info(f"前5个音色: {[voice_combo.itemText(i) for i in range(min(5, voice_combo.count()))]}")

    logger.info("\n" + "=" * 60)
    logger.info("所有测试完成！")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        test_voice_loader()
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        sys.exit(1)
