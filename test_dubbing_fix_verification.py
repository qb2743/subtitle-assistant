#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证配音界面修复"""

import sys
import logging
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(name)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from videocaptioner.ui.view.dubbing_interface import DubbingInterface

logger = logging.getLogger(__name__)


def check_interface_state(window):
    """检查界面状态"""
    logger.info("=" * 60)
    logger.info("配音界面状态检查:")
    logger.info("=" * 60)

    logger.info(f"Provider: {window.provider_combo.currentText()}")
    logger.info(f"语言选择框可见: {window.language_combo.isVisible()}")
    logger.info(f"语言列表数量: {window.language_combo.count()}")

    if window.language_combo.count() > 0:
        logger.info(f"第一个语言: {window.language_combo.itemText(0)}")
        logger.info(f"第一个语言代码: {window.language_combo.itemData(0)}")

    logger.info(f"音色选择框可见: {window.voice_combo.isVisible()}")
    logger.info(f"音色列表数量: {window.voice_combo.count()}")

    if window.voice_combo.count() > 0:
        logger.info(f"第一个音色: {window.voice_combo.itemText(0)}")

    logger.info("=" * 60)

    # 检查结果
    success = True
    errors = []

    if not window.language_combo.isVisible():
        errors.append("❌ 语言选择框不可见")
        success = False

    if window.language_combo.count() == 0:
        errors.append("❌ 语言列表为空")
        success = False

    # 对于默认的 Edge TTS，初始时音色列表可能为空（需要选择语言）
    # 所以我们手动选择第一个语言
    if window.language_combo.count() > 0:
        logger.info("\n尝试选择第一个语言...")
        window.language_combo.setCurrentIndex(0)

        # 给一点时间让事件处理
        QTimer.singleShot(100, lambda: check_voice_loading(window, errors, success))
        return

    if errors:
        logger.error("\n测试失败:")
        for error in errors:
            logger.error(f"  {error}")
    else:
        logger.info("\n✅ 基本检查通过！")

    # 退出应用
    QTimer.singleShot(500, app.quit)


def check_voice_loading(window, errors, success):
    """检查音色加载"""
    logger.info(f"\n选择语言后的音色数量: {window.voice_combo.count()}")

    if window.voice_combo.count() == 0:
        errors.append("❌ 选择语言后音色列表仍为空")
        success = False
    else:
        logger.info(f"前3个音色: {[window.voice_combo.itemText(i) for i in range(min(3, window.voice_combo.count()))]}")

    if errors:
        logger.error("\n测试失败:")
        for error in errors:
            logger.error(f"  {error}")
        sys.exit(1)
    else:
        logger.info("\n✅ 所有检查通过！配音界面工作正常。")
        sys.exit(0)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = DubbingInterface()
    window.setWindowTitle("配音界面验证测试")
    window.resize(1200, 800)
    window.show()

    # 延迟检查，给界面时间完成初始化
    QTimer.singleShot(500, lambda: check_interface_state(window))

    sys.exit(app.exec_())
