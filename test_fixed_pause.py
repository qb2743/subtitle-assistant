"""测试固定停顿配置"""
import sys
import os
from pathlib import Path

# 配置 ffmpeg 路径
project_root = Path(__file__).parent
os.environ['PATH'] = str(project_root) + os.pathsep + os.environ.get('PATH', '')

sys.path.insert(0, '.')

from videocaptioner.core.dubbing.pipeline import DubbingPipeline, DubbingConfig

# 配置（启用固定停顿）
config = DubbingConfig(
    provider="edge",
    api_key="",
    base_url="",
    model="",
    voice="zh-CN-XiaoxiaoNeural",
    tts_workers=2,
    fixed_line_pause=True,      # 启用固定停顿
    fixed_line_pause_ms=1000,   # 1秒停顿
    speed=1.0,                  # 正常速度
)

pipeline = DubbingPipeline(config)

subtitle_path = "D:/搬运/原字幕/01.srt"
output_path = "D:/搬运/test_fixed_pause.mp3"

print(f"\n配音配置:")
print(f"  固定停顿: {config.fixed_line_pause}")
print(f"  停顿时长: {config.fixed_line_pause_ms} ms")
print(f"  语速: {config.speed}")
print(f"\n开始配音: {subtitle_path}")
print(f"输出: {output_path}")
print("-" * 60)

try:
    result = pipeline.run(
        subtitle_path=subtitle_path,
        output_audio_path=output_path,
        callback=lambda p, m: print(f"  {p:3d}% - {m}"),
    )

    print("-" * 60)
    print(f"配音成功!")
    print(f"  输出文件: {result.output_audio_path}")
    print(f"  处理段数: {len(result.segments)}")

    # 检查是否真的使用了固定停顿模式
    if config.fixed_line_pause:
        print(f"\n固定停顿模式已启用，所有语音段之间有 {config.fixed_line_pause_ms}ms 停顿")

    sys.exit(0)

except Exception as e:
    print(f"\n配音失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
