"""Voice data loader for dubbing engines."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

# 设置日志
logger = logging.getLogger(__name__)

# 数据目录
VOICES_DIR = Path(__file__).parent.parent.parent / "data" / "voices"

# 缓存变量
_edge_voices_cache = None


def load_edge_voices_from_api() -> Dict[str, Dict[str, str]]:
    """从 edge-tts API 动态获取音色数据

    Returns:
        {
            "zh": {
                "Xiaoxiao(Female/CN)": "zh-CN-XiaoxiaoNeural",
                ...
            }
        }
    """
    global _edge_voices_cache

    # 如果已经缓存，直接返回
    if _edge_voices_cache is not None:
        logger.info("使用缓存的音色数据")
        return _edge_voices_cache

    try:
        import edge_tts

        logger.info("开始从 edge-tts API 获取音色列表...")

        # 异步获取音色列表
        voices = asyncio.run(edge_tts.list_voices())

        logger.info(f"成功获取 {len(voices)} 个音色")

        # 组织成按语言分组的格式
        grouped_voices = {}

        for voice in voices:
            # 提取信息
            short_name = voice.get("ShortName", "")
            locale = voice.get("Locale", "")
            gender = voice.get("Gender", "Unknown")

            if not short_name or not locale:
                continue

            # 提取语言代码（例如 zh-CN -> zh）
            lang_code = locale.split("-")[0] if "-" in locale else locale

            # 提取音色名称和地区
            # 例如: zh-CN-XiaoxiaoNeural -> Xiaoxiao
            name_parts = short_name.split("-")
            if len(name_parts) >= 3:
                voice_name = name_parts[2].replace("Neural", "")
                region = name_parts[1]  # CN, US, GB 等
            else:
                voice_name = short_name
                region = ""

            # 构建显示名称
            display_name = f"{voice_name}({gender}/{region})"

            # 添加到分组
            if lang_code not in grouped_voices:
                grouped_voices[lang_code] = {}

            grouped_voices[lang_code][display_name] = short_name

        # 缓存结果
        _edge_voices_cache = grouped_voices

        logger.info(f"音色数据已缓存，共 {len(grouped_voices)} 种语言")

        return grouped_voices

    except ImportError as e:
        # 如果没有安装 edge-tts，回退到静态 JSON 文件
        logger.warning(f"未安装 edge-tts 库: {e}")
        return load_edge_voices_from_json()
    except Exception as e:
        # 如果 API 调用失败，回退到静态 JSON 文件
        logger.error(f"从 edge-tts API 加载音色失败: {e}", exc_info=True)
        return load_edge_voices_from_json()


def load_edge_voices_from_json() -> Dict[str, Dict[str, str]]:
    """从静态 JSON 文件加载音色数据（回退方案）

    Returns:
        {
            "zh": {
                "Yunyang(Male/CN)": "zh-CN-YunyangNeural",
                ...
            }
        }
    """
    json_file = VOICES_DIR / "edge_tts.json"

    logger.info(f"尝试从 JSON 文件加载音色: {json_file}")

    if not json_file.exists():
        logger.error(f"JSON 文件不存在: {json_file}")
        return {}

    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.info(f"从 JSON 文件成功加载 {len(data)} 种语言的音色")
            return data
    except Exception as e:
        logger.error(f"读取 JSON 文件失败: {e}", exc_info=True)
        return {}


def load_edge_voices() -> Dict[str, Dict[str, str]]:
    """加载 Edge TTS 音色数据（优先从 API，回退到 JSON）

    Returns:
        {
            "zh": {
                "晓晓(Female/CN)": "zh-CN-XiaoxiaoNeural",
                ...
            }
        }
    """
    return load_edge_voices_from_api()


def get_voices_by_language(language_code: str) -> List[tuple]:
    """根据语言代码获取音色列表

    Args:
        language_code: 语言代码，如 "zh", "en", "ja"

    Returns:
        [(display_name, voice_id), ...]
        例如: [("晓晓(Female/CN)", "zh-CN-XiaoxiaoNeural"), ...]
    """
    voices = load_edge_voices()

    logger.debug(f"获取语言 '{language_code}' 的音色")

    if language_code not in voices:
        logger.warning(f"未找到语言代码 '{language_code}' 的音色")
        return []

    lang_voices = voices[language_code]
    logger.debug(f"语言 '{language_code}' 有 {len(lang_voices)} 个音色")

    return [(name, voice_id) for name, voice_id in lang_voices.items()]


def get_all_languages() -> List[tuple]:
    """获取所有支持的语言

    Returns:
        [(code, name), ...]
        例如: [("zh", "中文"), ("en", "English"), ...]
    """
    # 常用语言映射（中文显示）
    LANGUAGE_NAMES = {
        "zh": "中文",
        "en": "英语",
        "ja": "日语",
        "ko": "韩语",
        "es": "西班牙语",
        "fr": "法语",
        "de": "德语",
        "it": "意大利语",
        "pt": "葡萄牙语",
        "ru": "俄语",
        "ar": "阿拉伯语",
        "th": "泰语",
        "vi": "越南语",
        "id": "印尼语",
        "ms": "马来语",
        "tr": "土耳其语",
        "pl": "波兰语",
        "nl": "荷兰语",
        "sv": "瑞典语",
        "da": "丹麦语",
        "fi": "芬兰语",
        "no": "挪威语",
        "cs": "捷克语",
        "sk": "斯洛伐克语",
        "hu": "匈牙利语",
        "ro": "罗马尼亚语",
        "bg": "保加利亚语",
        "hr": "克罗地亚语",
        "sr": "塞尔维亚语",
        "uk": "乌克兰语",
        "el": "希腊语",
        "he": "希伯来语",
        "hi": "印地语",
        "bn": "孟加拉语",
        "ta": "泰米尔语",
        "te": "泰卢固语",
        "mr": "马拉地语",
        "ur": "乌尔都语",
        "fa": "波斯语",
        "sw": "斯瓦希里语",
        "af": "南非荷兰语",
        "sq": "阿尔巴尼亚语",
        "am": "阿姆哈拉语",
        "az": "阿塞拜疆语",
        "eu": "巴斯克语",
        "be": "白俄罗斯语",
        "bs": "波斯尼亚语",
        "ca": "加泰罗尼亚语",
        "cy": "威尔士语",
        "et": "爱沙尼亚语",
        "fil": "菲律宾语",
        "gl": "加利西亚语",
        "gu": "古吉拉特语",
        "is": "冰岛语",
        "jv": "爪哇语",
        "kn": "卡纳达语",
        "kk": "哈萨克语",
        "km": "高棉语",
        "lo": "老挝语",
        "lv": "拉脱维亚语",
        "lt": "立陶宛语",
        "mk": "马其顿语",
        "ml": "马拉雅拉姆语",
        "mn": "蒙古语",
        "my": "缅甸语",
        "ne": "尼泊尔语",
        "ps": "普什图语",
        "si": "僧伽罗语",
        "sl": "斯洛文尼亚语",
        "so": "索马里语",
        "su": "巽他语",
        "uz": "乌兹别克语",
        "zu": "祖鲁语",
    }

    voices = load_edge_voices()
    languages = []

    for code in voices.keys():
        name = LANGUAGE_NAMES.get(code, code.upper())
        languages.append((code, name))

    # 常用语言置顶：中文、英语、法语、德语
    priority_langs = ["zh", "en", "fr", "de"]

    def sort_key(x):
        code = x[0]
        if code in priority_langs:
            return (0, priority_langs.index(code))  # 优先级语言按指定顺序
        else:
            return (1, x[1])  # 其他语言按名称排序

    languages.sort(key=sort_key)

    return languages


def search_voices(keyword: str, language_code: Optional[str] = None) -> List[tuple]:
    """搜索音色

    Args:
        keyword: 搜索关键词
        language_code: 限定语言

    Returns:
        [(display_name, voice_id), ...]
    """
    voices = load_edge_voices()
    results = []

    for lang_code, lang_voices in voices.items():
        if language_code and lang_code != language_code:
            continue

        for name, voice_id in lang_voices.items():
            if keyword.lower() in name.lower() or keyword.lower() in voice_id.lower():
                results.append((name, voice_id))

    return results
