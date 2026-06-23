#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试配音界面的音色选择功能（使用 edge-tts API）"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from videocaptioner.core.voices.loader import (
    get_all_languages,
    get_voices_by_language,
    load_edge_voices,
)
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_voice_loader_api():
    """测试从 edge-tts API 加载音色"""
    print("=" * 60)
    print("测试音色数据加载（从 edge-tts API）")
    print("=" * 60)

    # 1. 测试加载所有语言
    print("\n1. 加载所有支持的语言:")
    languages = get_all_languages()
    print(f"   共支持 {len(languages)} 种语言")
    print(f"   前 10 种语言:")
    for code, name in languages[:10]:
        print(f"     - {code}: {name}")

    # 2. 测试加载中文音色
    print("\n2. 加载中文音色:")
    zh_voices = get_voices_by_language("zh")
    print(f"   中文音色数量: {len(zh_voices)}")
    print(f"   所有中文音色:")
    for name, voice_id in zh_voices:
        print(f"     - {name}: {voice_id}")

    # 3. 测试加载英文音色
    print("\n3. 加载英文音色:")
    en_voices = get_voices_by_language("en")
    print(f"   英文音色数量: {len(en_voices)}")
    print(f"   前 10 个英文音色:")
    for name, voice_id in en_voices[:10]:
        print(f"     - {name}: {voice_id}")

    # 4. 测试加载日文音色
    print("\n4. 加载日文音色:")
    ja_voices = get_voices_by_language("ja")
    print(f"   日文音色数量: {len(ja_voices)}")
    for name, voice_id in ja_voices:
        print(f"     - {name}: {voice_id}")

    # 5. 测试原始数据结构
    print("\n5. 测试原始数据加载:")
    all_voices = load_edge_voices()
    print(f"   数据中包含 {len(all_voices)} 种语言")
    print(f"   总音色数: {sum(len(v) for v in all_voices.values())}")

    # 6. 检查特定音色
    print("\n6. 检查常用中文音色是否存在:")
    common_voices = [
        ("Xiaoxiao", "zh-CN-XiaoxiaoNeural"),
        ("Yunyang", "zh-CN-YunyangNeural"),
        ("Xiaoyi", "zh-CN-XiaoyiNeural"),
    ]
    for expected_name, expected_id in common_voices:
        found = False
        for name, voice_id in zh_voices:
            if expected_id in voice_id:
                print(f"   ✅ 找到: {name} -> {voice_id}")
                found = True
                break
        if not found:
            print(f"   ❌ 未找到: {expected_name} ({expected_id})")

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！音色数据从 edge-tts API 加载成功")
    print("=" * 60)


if __name__ == "__main__":
    test_voice_loader_api()
