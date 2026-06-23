# 配音界面改进方案

**完成日期**：2026-06-21  
**状态**：📋 规划中

---

## 📋 **改进需求**

### 1. 音色自动获取（下拉选择）
**当前问题**：
- 需要手动输入音色名称
- 容易输错
- 不知道有哪些可用音色

**改进方案**：
- 将 `LineEdit` 改为 `ComboBox`
- 根据选择的引擎自动加载音色列表
- 支持搜索和筛选

### 2. 试听音色功能
**当前问题**：
- 无法试听音色
- 不知道音色效果如何

**改进方案**：
- 添加"试听"按钮
- 点击后播放示例音频
- 使用 Edge TTS API 实时生成示例

### 3. 配音语言选择
**当前问题**：
- 没有语言选择
- 容易选错语言的音色
- 配音效果不理想

**改进方案**：
- 添加语言下拉框
- 根据语言筛选音色
- 减少配音错误

---

## 🎯 **实现方案**

### 音色数据来源

#### pyvideotrans 音色文件
```
videotrans/voicejson/
├── edge_tts.json        (478 lines - Edge TTS 音色)
├── elevenlabs.json      (0 lines - 需要 API)
├── azure_voice_list.json (785 lines - Azure)
└── ...其他引擎
```

#### 数据结构（edge_tts.json）
```json
{
  "language_code": {
    "language_name": "语言名称",
    "voices": [
      {
        "name": "zh-CN-XiaoxiaoNeural",
        "gender": "Female",
        "language": "zh-CN"
      }
    ]
  }
}
```

---

## 📐 **UI 设计**

### 改进后的布局

```
┌─────────────────────────────────┐
│ 配音引擎                         │
│ [edge - Edge TTS (免费) ▼]      │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│ 配音语言                    ✨新增│
│ [简体中文 (zh-CN) ▼]            │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│ 音色                        改进│
│ [zh-CN-XiaoxiaoNeural ▼] [试听]│
│ 💡 晓晓 - 女声 - 中文           │
└─────────────────────────────────┘
```

---

## 🔧 **技术实现**

### 1. 复制音色 JSON 文件

```bash
cp D:\pyvideotrans-src\videotrans\voicejson\edge_tts.json \
   D:\音视频综合助手\videocaptioner\data\voices\
```

### 2. 创建音色加载器

```python
# videocaptioner/core/voices/loader.py

def load_voices(engine: str, language: str = None):
    """加载指定引擎的音色列表"""
    json_file = f"data/voices/{engine}.json"
    with open(json_file) as f:
        data = json.load(f)
    
    if language:
        return filter_by_language(data, language)
    return data
```

### 3. 修改界面组件

```python
# 语言选择
self.language_combo = ComboBox(self)
self.language_combo.addItems([
    "zh-CN - 简体中文",
    "zh-TW - 繁体中文",
    "en-US - 英语(美国)",
    "ja-JP - 日语",
    # ...
])
self.language_combo.currentTextChanged.connect(self._on_language_changed)

# 音色选择
self.voice_combo = ComboBox(self)
self.voice_combo.setPlaceholderText("选择音色")
# 根据语言动态加载

# 试听按钮
self.preview_btn = PushButton(FIF.PLAY, "试听", self)
self.preview_btn.clicked.connect(self._preview_voice)
```

### 4. 音色试听实现

```python
def _preview_voice(self):
    """试听音色"""
    voice = self.voice_combo.currentText().split(" ")[0]
    
    # 生成示例音频
    sample_text = "你好，这是音色试听。"
    
    # 调用 Edge TTS
    import edge_tts
    asyncio.run(self._generate_preview(voice, sample_text))
    
    # 播放音频
    import pygame
    pygame.mixer.init()
    pygame.mixer.music.load("preview.mp3")
    pygame.mixer.music.play()
```

---

## 📊 **数据准备**

### 需要复制的文件

1. **Edge TTS**
   - `edge_tts.json` (478行)
   - 免费，最常用

2. **ElevenLabs**
   - 需要 API，动态获取

3. **其他引擎**
   - 按需添加

---

## ⏱️ **实现步骤**

1. ✅ 创建数据目录和音色加载器
2. ✅ 添加语言选择下拉框
3. ✅ 将音色输入框改为下拉框
4. ✅ 实现音色筛选逻辑
5. ✅ 添加试听按钮和功能
6. ✅ 测试各个引擎

---

## 🎉 **预期效果**

### 用户体验改进

**改进前**：
1. 选择引擎
2. 手动输入音色名称（容易错）
3. 无法试听
4. 不知道效果

**改进后**：
1. 选择引擎
2. 选择语言（自动筛选）
3. 下拉选择音色（清晰明了）
4. 点击试听（即刻体验）
5. 开始配音（信心满满）

---

## 💡 **技术考虑**

### Edge TTS 音色数量
- 478行 JSON ≈ 150+ 音色
- 支持 50+ 语言
- 需要语言筛选

### 性能优化
- 懒加载音色列表
- 缓存已加载的数据
- 异步加载试听音频

### 兼容性
- 保持配置格式兼容
- 只保存音色 ID
- 向后兼容手动输入

---

**准备开始实现！** 🚀
