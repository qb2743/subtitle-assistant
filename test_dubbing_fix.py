"""测试配音功能修复 - 不启动 GUI"""
import sys
import os
from pathlib import Path

# 配置 ffmpeg/ffprobe 路径
project_root = Path(__file__).parent
os.environ['PATH'] = str(project_root) + os.pathsep + os.environ.get('PATH', '')

sys.path.insert(0, '.')

from videocaptioner.core.dubbing.pipeline import DubbingPipeline, DubbingConfig

# 模拟进度回调
progress_log = []

def mock_callback(progress: int, message: str):
    """模拟 UI 进度回调"""
    progress_log.append((progress, message))
    print(f"Progress: {progress}% - {message}")

# 配置
config = DubbingConfig(
    provider="edge",
    api_key="",  # Edge TTS 不需要 key
    base_url="",
    model="",
    voice="zh-CN-XiaoxiaoNeural",
    tts_workers=2,
)

# 创建 pipeline
pipeline = DubbingPipeline(config)

# 测试字幕文件路径
subtitle_path = "D:/搬运/原字幕/01.srt"
output_path = "D:/搬运/test_output.mp3"

print(f"\n开始配音测试: {subtitle_path}")
print(f"输出路径: {output_path}")
print("-" * 60)

try:
    result = pipeline.run(
        subtitle_path=subtitle_path,
        output_audio_path=output_path,
        callback=mock_callback,
    )

    print("-" * 60)
    print(f"✓ 配音成功!")
    print(f"  输出文件: {result.output_audio_path}")
    print(f"  处理段数: {len(result.segments)}")
    print(f"  总时长: {result.segments[-1].end_ms / 1000:.2f}s" if result.segments else "N/A")

    if result.warnings:
        print(f"\n警告信息:")
        for w in result.warnings[:5]:
            print(f"  - {w}")
        if len(result.warnings) > 5:
            print(f"  ... 共 {len(result.warnings)} 条警告")

    print(f"\n进度回调记录 ({len(progress_log)} 次):")
    for prog, msg in progress_log[:10]:
        print(f"  {prog:3d}% - {msg}")
    if len(progress_log) > 10:
        print(f"  ... 共 {len(progress_log)} 次回调")

    sys.exit(0)

except Exception as e:
    print("-" * 60)
    print(f"✗ 配音失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
