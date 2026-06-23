#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ElevenLabs API 真实测试脚本

使用真实的 API 密钥测试 ElevenLabs 的各项功能：
1. 连接测试
2. 获取可用音色列表
3. 文本转语音（TTS）
4. 测试不同语言和音色
5. 测试语音参数调节

使用方法：
    python test_elevenlabs_real_api.py

配置：
    在运行前请设置环境变量 ELEVENLABS_API_KEY 或直接修改脚本中的 API_KEY
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from videocaptioner.core.speech import (
    ElevenLabsSpeechSynthesizer,
    SpeechProviderConfig,
    SynthesisRequest,
    list_elevenlabs_voices,
)


# ===== 配置区域 =====
# 方式1: 从环境变量读取（推荐）
API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# 方式2: 直接填写（不推荐提交到 git）
if not API_KEY:
    API_KEY = "sk_786cd83b9f8eb2995ea17393fe2ef1f52c37664f78d0597d"  # 请替换为你的真实 API 密钥

# 测试输出目录
OUTPUT_DIR = Path(__file__).parent / "test_outputs" / "elevenlabs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def print_section(title):
    """打印带分隔线的标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_api_connection():
    """测试 1: API 连接和密钥验证"""
    print_section("测试 1: API 连接和密钥验证")

    if not API_KEY or API_KEY == "sk-xxx":
        print("[错误] 请先设置 ELEVENLABS_API_KEY 环境变量或修改脚本中的 API_KEY")
        print("\n设置环境变量方法:")
        print("  Windows: set ELEVENLABS_API_KEY=your_api_key")
        print("  Linux/Mac: export ELEVENLABS_API_KEY=your_api_key")
        return False

    print(f"[OK] API 密钥已配置: {API_KEY[:10]}...{API_KEY[-4:]}")
    print("[OK] 连接测试准备就绪")
    return True


def test_list_voices():
    """测试 2: 获取可用音色列表"""
    print_section("测试 2: 获取可用音色列表")

    try:
        print("正在获取音色列表...")
        voices = list_elevenlabs_voices(API_KEY)

        print(f"\n[成功] 成功获取 {len(voices)} 个音色")

        # 分类统计
        categories = {}
        for voice in voices:
            cat = voice.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        print("\n音色分类统计:")
        for cat, count in categories.items():
            print(f"  - {cat}: {count} 个")

        # 显示前 10 个音色
        print("\n前 10 个可用音色:")
        for i, voice in enumerate(voices[:10], 1):
            labels = voice.get("labels", {})
            gender = labels.get("gender", "unknown")
            accent = labels.get("accent", "")
            print(f"  {i}. {voice['name']}")
            print(f"     ID: {voice['voice_id']}")
            print(f"     类别: {voice['category']} | 性别: {gender} | 口音: {accent}")

        return voices

    except Exception as e:
        print(f"\n[失败] 获取音色列表失败: {e}")
        return []


def test_basic_synthesis(voices):
    """测试 3: 基本文本转语音"""
    print_section("测试 3: 基本文本转语音")

    if not voices:
        print("[警告] 跳过测试：没有可用音色")
        return

    # 使用 Rachel 或第一个可用音色
    test_voice = None
    for v in voices:
        if "Rachel" in v["name"]:
            test_voice = v
            break
    if not test_voice:
        test_voice = voices[0]

    print(f"\n使用音色: {test_voice['name']} ({test_voice['voice_id']})")

    # 创建配置
    config = SpeechProviderConfig(
        provider="elevenlabs",
        api_key=API_KEY,
        model="eleven_multilingual_v2",
        default_voice=test_voice["voice_id"],
    )

    synthesizer = ElevenLabsSpeechSynthesizer(config)

    # 测试文本
    test_cases = [
        ("英文", "Hello! This is a test of ElevenLabs text to speech."),
        ("中文", "你好！这是 ElevenLabs 语音合成的测试。"),
        ("日文", "こんにちは！これは ElevenLabs のテストです。"),
    ]

    print("\n开始合成测试:")
    for lang, text in test_cases:
        output_file = OUTPUT_DIR / f"test_basic_{lang}.mp3"

        try:
            print(f"\n  [{lang}] {text}")
            print(f"  输出: {output_file}")

            result = synthesizer.synthesize(
                SynthesisRequest(
                    text=text,
                    output_path=str(output_file),
                )
            )

            file_size = Path(result.output_path).stat().st_size
            print(f"  [成功] 成功! 文件大小: {file_size / 1024:.1f} KB")
            print(f"     音色: {result.voice}")
            print(f"     格式: {result.format}")

        except Exception as e:
            print(f"  [失败] 失败: {e}")


def test_voice_settings():
    """测试 4: 语音参数调节"""
    print_section("测试 4: 语音参数调节")

    # 测试不同的参数组合
    test_configs = [
        {
            "name": "默认设置",
            "extra": {},
            "speed": 1.0,
        },
        {
            "name": "高稳定性",
            "extra": {"stability": 0.8, "similarity_boost": 0.5},
            "speed": 1.0,
        },
        {
            "name": "高表现力",
            "extra": {"stability": 0.3, "similarity_boost": 0.9, "style": 0.5},
            "speed": 1.0,
        },
        {
            "name": "快速语速",
            "extra": {},
            "speed": 1.5,
        },
        {
            "name": "慢速语速",
            "extra": {},
            "speed": 0.75,
        },
    ]

    test_text = "The quick brown fox jumps over the lazy dog."

    print(f"\n测试文本: {test_text}")
    print("\n开始参数测试:")

    for test_config in test_configs:
        output_file = OUTPUT_DIR / f"test_settings_{test_config['name'].replace(' ', '_')}.mp3"

        try:
            config = SpeechProviderConfig(
                provider="elevenlabs",
                api_key=API_KEY,
                model="eleven_multilingual_v2",
                default_voice="21m00Tcm4TlvDq8ikWAM",  # Rachel
                speed=test_config["speed"],
                extra=test_config["extra"],
            )

            synthesizer = ElevenLabsSpeechSynthesizer(config)

            print(f"\n  [{test_config['name']}]")
            print(f"    语速: {test_config['speed']}")
            if test_config['extra']:
                print(f"    参数: {test_config['extra']}")

            result = synthesizer.synthesize(
                SynthesisRequest(
                    text=test_text,
                    output_path=str(output_file),
                )
            )

            file_size = Path(result.output_path).stat().st_size
            print(f"    [成功] 成功! 文件: {output_file.name} ({file_size / 1024:.1f} KB)")

        except Exception as e:
            print(f"    [失败] 失败: {e}")


def test_multiple_voices():
    """测试 5: 测试多个不同音色"""
    print_section("测试 5: 测试多个不同音色")

    try:
        voices = list_elevenlabs_voices(API_KEY)

        # 选择几个不同类型的音色
        test_voices = []

        # 尝试找到不同类型的音色
        categories_needed = {"premade", "cloned", "professional"}
        for voice in voices:
            if voice["category"] in categories_needed and len(test_voices) < 5:
                test_voices.append(voice)
                categories_needed.discard(voice["category"])

        # 如果没找够，补充前几个
        if len(test_voices) < 3:
            test_voices = voices[:3]

        test_text = "Hello, this is a voice comparison test."

        print(f"\n将使用 {len(test_voices)} 个音色进行测试")
        print(f"测试文本: {test_text}\n")

        for i, voice in enumerate(test_voices, 1):
            output_file = OUTPUT_DIR / f"test_voice_{i}_{voice['name'].replace(' ', '_')}.mp3"

            try:
                config = SpeechProviderConfig(
                    provider="elevenlabs",
                    api_key=API_KEY,
                    model="eleven_multilingual_v2",
                    default_voice=voice["voice_id"],
                )

                synthesizer = ElevenLabsSpeechSynthesizer(config)

                print(f"  {i}. {voice['name']} ({voice['category']})")
                print(f"     ID: {voice['voice_id']}")

                result = synthesizer.synthesize(
                    SynthesisRequest(
                        text=test_text,
                        output_path=str(output_file),
                    )
                )

                file_size = Path(result.output_path).stat().st_size
                print(f"     [成功] 成功! {file_size / 1024:.1f} KB\n")

            except Exception as e:
                print(f"     [失败] 失败: {e}\n")

    except Exception as e:
        print(f"\n[失败] 测试失败: {e}")


def test_long_text():
    """测试 6: 长文本合成"""
    print_section("测试 6: 长文本合成")

    long_text = """
    Artificial intelligence is transforming the world in profound ways.
    From healthcare to transportation, from education to entertainment,
    AI is reshaping how we live, work, and interact with technology.
    Machine learning algorithms can now recognize patterns, make predictions,
    and even create original content. As we continue to advance in this field,
    it's crucial that we develop AI responsibly, ensuring it benefits all of humanity
    while addressing potential challenges and ethical considerations.
    """

    output_file = OUTPUT_DIR / "test_long_text.mp3"

    print(f"\n文本长度: {len(long_text)} 字符")
    print(f"输出文件: {output_file}")

    try:
        config = SpeechProviderConfig(
            provider="elevenlabs",
            api_key=API_KEY,
            model="eleven_multilingual_v2",
            default_voice="21m00Tcm4TlvDq8ikWAM",
        )

        synthesizer = ElevenLabsSpeechSynthesizer(config)

        print("\n开始合成...")
        result = synthesizer.synthesize(
            SynthesisRequest(
                text=long_text.strip(),
                output_path=str(output_file),
            )
        )

        file_size = Path(result.output_path).stat().st_size
        print(f"[成功] 成功! 文件大小: {file_size / 1024:.1f} KB")

    except Exception as e:
        print(f"[失败] 失败: {e}")


def print_summary():
    """打印测试总结"""
    print_section("测试完成")

    output_files = list(OUTPUT_DIR.glob("*.mp3"))

    if output_files:
        print(f"\n[成功] 成功生成 {len(output_files)} 个音频文件")
        print(f"\n输出目录: {OUTPUT_DIR}")
        print("\n生成的文件:")

        total_size = 0
        for f in sorted(output_files):
            size = f.stat().st_size
            total_size += size
            print(f"  - {f.name} ({size / 1024:.1f} KB)")

        print(f"\n总大小: {total_size / 1024:.1f} KB")
    else:
        print("\n[警告] 没有生成任何音频文件")

    print("\n" + "=" * 70)


def main():
    """主测试流程"""
    print("\n" + "=" * 70)
    print("  ElevenLabs API 真实测试")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

    # 测试 1: 连接测试
    if not test_api_connection():
        return

    # 测试 2: 获取音色列表
    voices = test_list_voices()

    # 测试 3: 基本合成
    test_basic_synthesis(voices)

    # 测试 4: 参数调节
    test_voice_settings()

    # 测试 5: 多音色测试
    test_multiple_voices()

    # 测试 6: 长文本
    test_long_text()

    # 打印总结
    print_summary()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[警告] 测试被用户中断")
    except Exception as e:
        print(f"\n\n[失败] 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
