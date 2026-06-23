# 音色动态加载功能升级 ✅

**升级日期**: 2026-06-21  
**问题**: 音色下拉框没有显示音色  
**原因**: 之前使用静态 JSON 文件，现在改为从 edge-tts API 动态获取

---

## 🎯 问题分析

### 之前的方案
- 使用静态 JSON 文件 `videocaptioner/data/voices/edge_tts.json`
- 需要手动维护音色列表
- 音色数据可能过时

### 现在的方案
- 从 edge-tts API 动态获取音色列表
- 自动获取最新的音色数据
- 支持 **322 个音色**，**75 种语言**

---

## 🔧 技术实现

### 关键改动

**文件**: `videocaptioner/core/voices/loader.py`

```python
def load_edge_voices_from_api() -> Dict[str, Dict[str, str]]:
    """从 edge-tts API 动态获取音色数据"""
    import edge_tts
    
    # 异步获取音色列表
    voices = asyncio.run(edge_tts.list_voices())
    
    # 组织成按语言分组的格式
    grouped_voices = 
    
    for voice in voices:
        short_name = voice.get("ShortName", "")
        locale = voice.get("Locale", "")
        gender = voice.get("Gender", "Unknown")
        
        # 提取语言代码（例如 zh-CN -> zh）
        lang_code = locale.split("-")[0]
        
        # 构建显示名称：Xiaoxiao(Female/CN)
        display_name = f"{voice_name}({gender}/{region})"
        
        grouped_voices[lang_code][display_name] = short_name
    
    return grouped_voices
```

### 回退机制

如果 API 调用失败，会自动回退到静态 JSON 文件：

```python
def load_edge_voices() -> Dict[str, Dict[str, str]]:
    """优先从 API 加载，失败则回退到 JSON"""
    try:
        return load_edge_voices_from_api()
    except Exception:
        return load_edge_voices_from_json()
```

---

## 📊 数据对比

### edge-tts API 返回格式
```python
{
    'Name': 'Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)',
    'ShortName': 'zh-CN-XiaoxiaoNeural',
    'Gender': 'Female',
    'Locale': 'zh-CN',
    'FriendlyName': 'Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)',
    'Status': 'GA',
    'VoiceTag': {...}
}
```

### 转换后的格式
```python
{
    "zh": {
        "Xiaoxiao(Female/CN)": "zh-CN-XiaoxiaoNeural",
        "Yunyang(Male/CN)": "zh-CN-YunyangNeural",
        ...
    },
    "en": {
        "Emma(Female/US)": "en-US-EmmaNeural",
        ...
    }
}
```

---

## ✅ 测试验证

### 测试1: 基础功能测试
```bash
python -c "from videocaptioner.core.voices.loader import get_voices_by_language; ..."
```

**结果**:
- ✅ 加载 75 种语言
- ✅ 中文音色: 14 个
- ✅ 英文音色: 47 个
- ✅ 总音色数: 322 个

### 测试2: 完整测试脚本
```bash
python test_dubbing_voice_api.py
```

**结果**:
```
✅ 所有测试通过！音色数据从 edge-tts API 加载成功

中文音色数量: 14
所有中文音色:
  - HiuGaai(Female/HK): zh-HK-HiuGaaiNeural
  - HiuMaan(Female/HK): zh-HK-HiuMaanNeural
  - WanLung(Male/HK): zh-HK-WanLungNeural
  - Xiaoxiao(Female/CN): zh-CN-XiaoxiaoNeural
  - Xiaoyi(Female/CN): zh-CN-XiaoyiNeural
  - Yunjian(Male/CN): zh-CN-YunjianNeural
  - Yunxi(Male/CN): zh-CN-YunxiNeural
  - Yunxia(Male/CN): zh-CN-YunxiaNeural
  - Yunyang(Male/CN): zh-CN-YunyangNeural
  - liaoning(Female/CN): zh-CN-liaoning-XiaobeiNeural
  - HsiaoChen(Female/TW): zh-TW-HsiaoChenNeural
  - YunJhe(Male/TW): zh-TW-YunJheNeural
  - HsiaoYu(Female/TW): zh-TW-HsiaoYuNeural
  - shaanxi(Female/CN): zh-CN-shaanxi-XiaoniNeural
```

---

## 🎨 UI 界面显示

### 语言选择
下拉框显示:
```
中文 (zh)
English (en)
日本語 (ja)
한국어 (ko)
...（共75种语言）
```

### 音色选择（选择中文后）
下拉框显示:
```
Xiaoxiao(Female/CN)
Yunyang(Male/CN)
Xiaoyi(Female/CN)
...（共14个中文音色）
```

---

## 🚀 用户使用流程

1. 打开配音界面
2. **选择语言**（如：中文）
3. 系统**自动从 edge-tts API 加载**该语言的所有音色
4. **选择音色**（如：Xiaoxiao(Female/CN)）
5. **点击试听按钮** 🔊 预览音色效果
6. 开始配音

---

## 🔄 与 edge-tts 项目的关系

### edge-tts 项目
- 链接: https://github.com/rany2/edge-tts/
- 功能: Microsoft Edge 的免费 TTS 服务
- API: `edge_tts.list_voices()` - 获取所有可用音色

### 本项目使用
- 通过 `edge_tts.list_voices()` 动态获取音色
- 自动解析和分组音色数据
- 提供友好的 UI 界面展示

### 优势
- ✅ 始终使用最新的音色列表
- ✅ 无需手动维护音色数据
- ✅ 自动获取新增的音色
- ✅ 与 edge-tts 项目保持同步

---

## 📝 性能优化

### 缓存机制
```python
# 全局缓存变量
_edge_voices_cache = None

def load_edge_voices_from_api():
    global _edge_voices_cache
    
    # 如果已经缓存，直接返回
    if _edge_voices_cache is not None:
        return _edge_voices_cache
    
    # 首次调用时获取并缓存
    voices = asyncio.run(edge_tts.list_voices())
    _edge_voices_cache = grouped_voices
    
    return _edge_voices_cache
```

### 性能表现
- 首次加载: ~1-2 秒（需要 API 调用）
- 后续加载: 即时（使用缓存）
- 内存占用: 极小（仅存储音色映射）

---

## ⚠️ 注意事项

### 依赖要求
```bash
pip install edge-tts
```

### 网络要求
- 首次启动需要网络连接（调用 edge-tts API）
- 如果网络不可用，会自动回退到静态 JSON 文件

### 错误处理
```python
try:
    return load_edge_voices_from_api()
except ImportError:
    # 未安装 edge-tts
    return load_edge_voices_from_json()
except Exception as e:
    # API 调用失败
    print(f"Failed to load voices from edge-tts API: {e}")
    return load_edge_voices_from_json()
```

---

## 📚 相关文件

### 核心文件
- `videocaptioner/core/voices/loader.py` - 音色加载器（已升级）
- `videocaptioner/ui/view/dubbing_interface.py` - 配音界面

### 测试文件
- `test_dubbing_voice_api.py` - API 加载测试
- `test_dubbing_ui.py` - UI 界面测试

### 文档
- `VOICE_SELECTION_IMPLEMENTATION.md` - 音色选择功能文档
- `EDGE_TTS_API_UPGRADE.md` - 本文档

---

## 🎊 总结

### 改进前
- ❌ 使用静态 JSON 文件
- ❌ 需要手动维护
- ❌ 音色数据可能过时
- ❌ 音色下拉框可能为空

### 改进后
- ✅ 从 edge-tts API 动态获取
- ✅ 自动同步最新音色
- ✅ 322 个音色，75 种语言
- ✅ 音色下拉框正常显示
- ✅ 支持缓存，性能优秀
- ✅ 自动回退机制，容错性强

---

**🎉 升级完成！现在音色下拉框可以正常显示所有可用音色了！**
