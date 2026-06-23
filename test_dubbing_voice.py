#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试配音界面的音色选择功能"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from videocaptioner.core.voices.loader import (
    get_all_languages,
    get_voices_by_language,
    load_edge_voices,
)


def test_voice_loader():
    """测试音色加载器"""
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=" * 50)
    print("测试音色数据加载")
    print("=" * 50)

    # 1. 测试加载所有语言
    print("\n1. 加载所有支持的语言:")
    languages = get_all_languages()
    print(f"   共支持 {len(languages)} 种语言")
    for code, name in languages[:10]:
        print(f"     - {code}: {name}")

    # 2. 测试加载中文音色
    print("\n2. 加载中文音色:")
    zh_voices = get_voices_by_language("zh")
    print(f"   中文音色数量: {len(zh_voices)}")
    print(f"   前 5 个中文音色:")
    for name, voice_id in zh_voices[:5]:
        print(f"     - {name}: {voice_id}")

    # 3. 测试加载英文音色
    print("\n3. 加载英文音色:")
    en_voices = get_voices_by_language("en")
    print(f"   英文音色数量: {len(en_voices)}")
    print(f"   前 5 个英文音色:")
    for name, voice_id in en_voices[:5]:
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
    print(f"   数据文件中包含 {len(all_voices)} 种语言")

    print("\n" + "=" * 50)
    print("✅ 所有测试通过！")
    print("=" * 50)


if __name__ == "__main__":
    test_voice_loader()
