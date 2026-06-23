#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""无窗口模式验证配音界面"""

import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent))

from PyQt5.QtWidgets import QApplication
from videocaptioner.ui.view.dubbing_interface import DubbingInterface

logger = logging.getLogger(__name__)


def main():
    """主函数"""
    app = QApplication(sys.argv)

    logger.info("创建配音界面...")
    window = DubbingInterface()

    logger.info("=" * 60)
    logger.info("初始状态检查:")
    logger.info("=" * 60)

    provider = window.provider_combo.currentText()
    logger.info(f"Provider: {provider}")
    logger.info(f"语言选择框可见: {window.language_combo.isVisible()}")
    logger.info(f"语言列表数量: {window.language_combo.count()}")

    if window.language_combo.count() > 0:
        logger.info(f"前3个语言: {[window.language_combo.itemText(i) for i in range(min(3, window.language_combo.count()))]}")
    else:
        logger.error("❌ 语言列表为空！")
        return 1

    logger.info(f"音色选择框可见: {window.voice_combo.isVisible()}")
    logger.info(f"初始音色数量: {window.voice_combo.count()}")

    # 测试选择第一个语言
    logger.info("\n" + "=" * 60)
    logger.info("选择第一个语言 (中文):")
    logger.info("=" * 60)

    window.language_combo.setCurrentIndex(0)
    selected_lang = window.language_combo.itemData(0)
    logger.info(f"选中语言: {window.language_combo.currentText()}")
    logger.info(f"语言代码: {selected_lang}")

    # 处理事件队列
    app.processEvents()

    logger.info(f"音色列表数量: {window.voice_combo.count()}")

    if window.voice_combo.count() > 0:
        logger.info(f"前5个音色: {[window.voice_combo.itemText(i) for i in range(min(5, window.voice_combo.count()))]}")
        logger.info("\n✅ 测试通过！配音界面音色加载正常。")
        return 0
    else:
        logger.error("\n❌ 测试失败！选择语言后音色列表仍为空。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
