"""GUI 启动测试脚本"""

import sys
from PyQt5.QtWidgets import QApplication

# 测试导入
print("正在测试 GUI 组件导入...")

from videocaptioner.ui.view.text_matching_interface import TextMatchingInterface
print("[OK] TextMatchingInterface")

from videocaptioner.ui.thread.text_matching_thread import TextMatchingThread
print("[OK] TextMatchingThread")

from videocaptioner.ui.view.main_window import MainWindow
print("[OK] MainWindow")

from videocaptioner.ui.view.batch_process_interface import BatchProcessInterface
print("[OK] BatchProcessInterface")

from videocaptioner.ui.thread.dubbing_thread import DubbingThread
print("[OK] DubbingThread")

from videocaptioner.core.entities import BatchTaskType
print("[OK] BatchTaskType")
print(f"    枚举值: {[t.value for t in BatchTaskType]}")

print("\n=== 所有组件导入成功 ===")
print("\n可以启动 GUI 应用:")
print("  python -m videocaptioner.ui.main")
print("或")
print("  videocaptioner gui")
