#!/usr/bin/env python
"""
配音功能批量测试脚本
用法：python test_dubbing_batch.py
"""
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 配置 ffmpeg 路径
os.environ['PATH'] = str(project_root) + os.pathsep + os.environ.get('PATH', '')

from videocaptioner.core.dubbing.pipeline import DubbingPipeline, DubbingConfig


# ==================== 测试配置 ====================

# 测试用例定义
TEST_CASES = [
    {
        "name": "Edge TTS - 中文 - 正常速度",
        "config": {
            "provider": "edge",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speed": 1.0,
            "fixed_line_pause": False,
        },
        "subtitle_file": "D:/搬运/原字幕/01.srt",
    },
    {
        "name": "Edge TTS - 中文 - 固定停顿",
        "config": {
            "provider": "edge",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speed": 1.0,
            "fixed_line_pause": True,
            "fixed_line_pause_ms": 1000,
        },
        "subtitle_file": "D:/搬运/原字幕/01.srt",
    },
    {
        "name": "Edge TTS - 中文 - 加速1.5x",
        "config": {
            "provider": "edge",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speed": 1.5,
            "fixed_line_pause": False,
        },
        "subtitle_file": "D:/搬运/原字幕/01.srt",
    },
    {
        "name": "Edge TTS - 英文",
        "config": {
            "provider": "edge",
            "voice": "en-US-JennyNeural",
            "speed": 1.0,
            "fixed_line_pause": False,
        },
        "subtitle_file": "D:/搬运/6.16/1.English - 副本.srt",
    },
]

# 输出目录
OUTPUT_DIR = Path("D:/搬运/batch_test_results")


# ==================== 测试函数 ====================

def run_single_test(test_case: dict, test_index: int) -> dict:
    """运行单个测试用例"""
    name = test_case["name"]
    config_dict = test_case["config"]
    subtitle_file = test_case["subtitle_file"]

    print(f"\n{'='*60}")
    print(f"测试 {test_index}: {name}")
    print(f"{'='*60}")
    print(f"字幕文件: {subtitle_file}")
    print(f"配置: {config_dict}")

    # 检查字幕文件是否存在
    if not Path(subtitle_file).exists():
        print(f"❌ 字幕文件不存在，跳过: {subtitle_file}")
        return {
            "name": name,
            "status": "skipped",
            "reason": "字幕文件不存在",
            "error": None,
            "output_file": None,
            "duration": 0,
        }

    # 创建输出文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"test_{test_index}_{timestamp}.mp3"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 创建配音配置
    config = DubbingConfig(**config_dict)
    pipeline = DubbingPipeline(config)

    # 进度回调
    def progress_callback(progress: int, message: str):
        print(f"  [{progress:3d}%] {message}")

    # 运行配音
    start_time = datetime.now()
    try:
        result = pipeline.run(
            subtitle_path=subtitle_file,
            output_audio_path=str(output_file),
            callback=progress_callback,
        )

        duration = (datetime.now() - start_time).total_seconds()
        file_size = output_file.stat().st_size / 1024 / 1024  # MB

        print(f"\n✅ 测试通过")
        print(f"  输出: {result.audio_path}")
        print(f"  大小: {file_size:.2f} MB")
        print(f"  耗时: {duration:.1f} 秒")
        print(f"  段数: {len(result.segments)}")

        return {
            "name": name,
            "status": "success",
            "reason": None,
            "error": None,
            "output_file": str(result.audio_path),
            "file_size_mb": file_size,
            "duration_sec": duration,
            "segments_count": len(result.segments),
        }

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        print(f"\n❌ 测试失败: {e}")

        return {
            "name": name,
            "status": "failed",
            "reason": str(e),
            "error": str(e),
            "output_file": None,
            "duration_sec": duration,
        }


def run_batch_tests():
    """运行所有测试用例"""
    print(f"\n{'#'*60}")
    print(f"配音功能批量测试")
    print(f"{'#'*60}")
    print(f"测试用例数: {len(TEST_CASES)}")
    print(f"输出目录: {OUTPUT_DIR}")

    results = []
    for i, test_case in enumerate(TEST_CASES, 1):
        result = run_single_test(test_case, i)
        results.append(result)

    # 打印总结
    print(f"\n{'='*60}")
    print(f"测试总结")
    print(f"{'='*60}")

    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")

    print(f"\n总计: {len(results)} 个测试")
    print(f"  ✅ 成功: {success_count}")
    print(f"  ❌ 失败: {failed_count}")
    print(f"  ⊘  跳过: {skipped_count}")

    # 详细结果
    print(f"\n详细结果:")
    for i, result in enumerate(results, 1):
        status_icon = {
            "success": "✅",
            "failed": "❌",
            "skipped": "⊘",
        }.get(result["status"], "?")

        print(f"\n{i}. {status_icon} {result['name']}")
        if result["status"] == "success":
            print(f"   输出: {result['output_file']}")
            print(f"   大小: {result['file_size_mb']:.2f} MB")
            print(f"   耗时: {result['duration_sec']:.1f} 秒")
            print(f"   段数: {result['segments_count']}")
        elif result["status"] == "failed":
            print(f"   错误: {result['error']}")
            print(f"   耗时: {result['duration_sec']:.1f} 秒")
        elif result["status"] == "skipped":
            print(f"   原因: {result['reason']}")

    # 保存结果到文件
    import json
    result_file = OUTPUT_DIR / f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存到: {result_file}")

    # 返回状态码
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = run_batch_tests()
    sys.exit(exit_code)
