#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试配音界面的音色加载功能"""

import sys
import logging
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from PyQt5.QtWidgets import QApplication
from videocaptioner.ui.view.dubbing_interface import DubbingInterface


def main():
    """主函数"""
    app = QApplication(sys.argv)

    # 创建配音界面
    window = DubbingInterface()
    window.setWindowTitle("配音界面调试")
    window.resize(1200, 800)
    window.show()

    # 检查初始状态
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("界面初始化完成，开始检查状态...")
    logger.info(f"语言列表数量: {window.language_combo.count()}")
    logger.info(f"音色列表数量: {window.voice_combo.count()}")
    logger.info(f"语言下拉框可见: {window.language_combo.isVisible()}")
    logger.info(f"音色下拉框可见: {window.voice_combo.isVisible()}")
    logger.info(f"当前 Provider: {window.provider_combo.currentText()}")
    logger.info("=" * 60)

    # 如果语言列表有内容，选择第一个语言
    if window.language_combo.count() > 0:
        logger.info("测试：手动选择第一个语言...")
        window.language_combo.setCurrentIndex(0)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
