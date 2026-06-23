# 下次会话启动说明

## 📋 问题概述

配音界面有两个关键问题未解决：

1. **Edge TTS 音色列表为空** - 语言选择"中文 (zh)"后，音色下拉框显示"选择音色"但没有任何选项
2. **ElevenLabs API 测试失败** - 错误显示 `Invalid voice 'sk_86cdbd...'`，传递了 API Key 而不是 voice_id

## 🎯 下次会话目标

**调试并修复配音界面的音色加载问题**

## 📂 项目信息

- **项目路径**: `D:\音视频综合助手`
- **参考项目**: `D:\pyvideotrans-src` (正常工作的版本)
- **虚拟环境**: `.venv/Scripts/python.exe`

## 🔍 已完成的修改

虽然修改了以下文件，但实际运行时问题仍然存在：

1. `videocaptioner/core/voices/loader.py` - 添加日志，优化错误处理
2. `videocaptioner/ui/view/dubbing_interface.py` - 修改 ElevenLabs API，添加 OpenAI Base URL
3. `videocaptioner/ui/common/config.py` - 添加配置项

**重要**: 代码修改后需要重启应用才能生效

## 🐛 需要调试的关键点

### 调试点 1: Edge TTS 音色加载流程

检查以下函数是否被正确调用：

```python
# 在 dubbing_interface.py 中添加调试日志
def _load_languages(self):
    print("DEBUG: _load_languages() 被调用")
    languages = get_all_languages()
    print(f"DEBUG: 获取到 {len(languages)} 种语言")
    ...

def _on_language_changed(self, index):
    print(f"DEBUG: _on_language_changed({index}) 被调用")
    language_code = self.language_combo.currentData()
    print(f"DEBUG: language_code = {language_code}")
    voices = get_voices_by_language(language_code)
    print(f"DEBUG: 获取到 {len(voices)} 个音色")
    for name, vid in voices[:3]:
        print(f"DEBUG:   - {name}: {vid}")
```

### 调试点 2: 信号连接

确认以下信号是否正确连接：

```python
# 在 __init__ 方法中
self.language_combo.currentIndexChanged.connect(self._on_language_changed)
```

### 调试点 3: 手动测试加载器

在 Python 交互式环境中测试：

```bash
cd "D:\音视频综合助手"
.venv/Scripts/python.exe

>>> from videocaptioner.core.voices.loader import get_all_languages, get_voices_by_language
>>> langs = get_all_languages()
>>> print(f"Languages: {len(langs)}")
>>> zh_voices = get_voices_by_language("zh")
>>> print(f"Chinese voices: {len(zh_voices)}")
>>> for name, vid in zh_voices[:5]:
...     print(f"  - {name}: {vid}")
```

## 📝 建议的调试步骤

1. **先测试加载器本身是否工作**
   ```bash
   python test_dubbing_voice_api.py
   ```
   如果这个通过，说明问题在 UI 层

2. **添加 UI 层调试日志**
   在 `dubbing_interface.py` 的关键函数添加 print 语句

3. **重启应用并查看日志**
   关闭应用，重新启动，观察控制台输出

4. **参考 pyvideotrans-src**
   对比 `D:\pyvideotrans-src` 中的实现，看有什么不同

## 🔗 相关文件位置

### 主要文件
- 配音界面: `videocaptioner/ui/view/dubbing_interface.py`
- 音色加载: `videocaptioner/core/voices/loader.py`
- 配置: `videocaptioner/ui/common/config.py`

### 测试文件
- `test_dubbing_voice_api.py` - 测试音色加载器
- `test_dubbing_fixes.py` - 综合测试

### 参考项目
- EdgeTTS: `D:\pyvideotrans-src\videotrans\tts\_edgetts.py`
- ElevenLabs: `D:\pyvideotrans-src\videotrans\tts\_elevenlabs.py`
- 音色获取: `D:\pyvideotrans-src\videotrans\util\help_role.py`

## ⚠️ 重要提示

1. **修改代码后必须重启应用** - Python 会缓存模块
2. **可能需要清除 .pyc 缓存** - 删除 `__pycache__` 目录
3. **使用虚拟环境** - 确保用 `.venv/Scripts/python.exe`

## 💡 快速启动命令

```bash
# 切换到项目目录
cd "D:\音视频综合助手"

# 测试加载器
.venv/Scripts/python.exe test_dubbing_voice_api.py

# 如果加载器测试通过，问题在 UI 层
# 需要添加调试日志并重启应用查看
```

## 📋 下次会话开场白

**向我说**:

> 继续调试"音视频综合助手"项目的配音界面问题。
> 
> **问题**: Edge TTS 音色列表为空，ElevenLabs API 测试失败
> 
> **项目路径**: D:\音视频综合助手
> 
> 请先测试 `videocaptioner/core/voices/loader.py` 是否能正常加载音色，然后在 UI 层添加调试日志定位问题。

---

**记忆文件**: 已保存到 `C:\Users\qiu\.claude\projects\D---------\memory\dubbing-interface-issues.md`
