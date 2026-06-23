# 配音界面问题修复方案

**问题分析日期**: 2026-06-21  
**参考项目**: pyvideotrans-src

---

## 🎯 发现的问题

### 问题 1: Edge TTS 音色未自动加载
**现状**: 语言和音色下拉框都是空的  
**原因**: `_load_languages()` 被调用了，但 `load_edge_voices()` 返回了空数据  
**根本原因**: 缓存变量 `_edge_voices_cache` 可能在初始化时就失败了

### 问题 2: ElevenLabs 测试失败  
**错误**: `Invalid voice 'sk_86cdbd366d0b77d469a22ea379c1fc4cea9bac49def87794'`  
**原因**: 传递的是 API Key 而不是 voice_id  
**根本原因**: 音色下拉框没有数据，`voice_combo.currentData()` 返回了 None

### 问题 3: OpenAI TTS 缺少 base_url 配置
**现状**: 无法配置自定义的 TTS 端点  
**需求**: 添加 base_url 输入框

---

## 📚 从 pyvideotrans-src 学到的实现

### 1. Edge TTS 实现（`_edgetts.py`）
```python
# 直接使用 edge_tts 库
from edge_tts import Communicate

communicate = Communicate(
    text=item['text'], 
    voice=item['role'],  # 直接使用 voice ID
    rate=self.rate,
    volume=self.volume, 
    proxy=self.useproxy, 
    pitch=self.pitch
)
await communicate.save(filename)
```

**关键点**:
- 不需要额外的音色列表 API
- 直接使用预定义的 voice ID（如 `zh-CN-XiaoxiaoNeural`）
- 音色列表存储在 `videotrans/voicejson/edge_tts.json`

### 2. ElevenLabs 实现（`_elevenlabs.py` + `help_role.py`）
```python
# 获取音色列表
from elevenlabs import ElevenLabs

client = ElevenLabs(api_key=api_key)
voiceslist = client.voices.get_all()

result = {}
for it in voiceslist.voices:
    result[role_name] = {
        "name": role_name, 
        "voice_id": it.voice_id
    }

# 保存到 JSON
with open('videotrans/voicejson/elevenlabs.json', 'w') as f:
    f.write(json.dumps(result))
```

**关键点**:
- 使用 `elevenlabs` 官方库（不是 requests）
- 调用 `client.voices.get_all()`
- 音色数据格式: `{"角色名": {"name": "...", "voice_id": "..."}}`
- 保存到 JSON 文件供后续使用

### 3. OpenAI TTS 实现（`_openaitts.py`）
```python
from openai import OpenAI

client = OpenAI(
    api_key=params.get('openaitts_key', ''), 
    base_url=self.api_url  # ← 支持自定义 base_url
)

with client.audio.speech.with_streaming_response.create(
    model=params.get('openaitts_model', ''),
    voice=data_item['role'],
    input=data_item['text'],
    speed=self.speed,
    response_format="wav",
    instructions=params.get('openaitts_instructions', '')
) as response:
    with open(filename, 'wb') as f:
        for chunk in response.iter_bytes():
            f.write(chunk)
```

**关键点**:
- 支持 `base_url` 参数
- 支持 `instructions` 参数
- UI 中有 `openaitts_api` 输入框用于设置 base_url

---

## 🔧 需要的修复

### 修复 1: Edge TTS 音色加载

**问题定位**:
```python
# 当前实现（有问题）
def load_edge_voices_from_api():
    voices = asyncio.run(edge_tts.list_voices())  # ← 可能失败
    ...
```

**解决方案**:
1. 添加详细的错误日志
2. 确保在UI线程外调用异步函数
3. 添加重试机制
4. 提供降级方案（使用静态 JSON）

**修复代码**:
```python
def load_edge_voices() -> Dict[str, Dict[str, str]]:
    """加载 Edge TTS 音色（优先 API，失败则用 JSON）"""
    global _edge_voices_cache
    
    if _edge_voices_cache is not None:
        return _edge_voices_cache
    
    try:
        # 尝试从 API 加载
        _edge_voices_cache = load_edge_voices_from_api()
        if _edge_voices_cache:
            return _edge_voices_cache
    except Exception as e:
        logger.error(f"从 API 加载音色失败: {e}")
    
    # 回退到 JSON
    _edge_voices_cache = load_edge_voices_from_json()
    return _edge_voices_cache
```

### 修复 2: ElevenLabs API 测试

**问题定位**:
```python
# 当前实现（使用 requests，有问题）
response = requests.get(
    "https://api.elevenlabs.io/v1/voices",
    headers={"xi-api-key": self.api_key}
)
```

**解决方案**:
使用官方 `elevenlabs` 库：
```python
def _test_elevenlabs_api(self, api_key: str):
    try:
        from elevenlabs import ElevenLabs
        
        client = ElevenLabs(api_key=api_key)
        voiceslist = client.voices.get_all()
        
        voices = []
        for voice in voiceslist.voices:
            voices.append({
                "name": voice.name,
                "voice_id": voice.voice_id
            })
        
        self.finished.emit(voices)
    except Exception as e:
        self.error.emit(str(e))
```

### 修复 3: OpenAI TTS Base URL

**添加配置项** (`videocaptioner/ui/common/config.py`):
```python
# OpenAI TTS
openai_tts_api_base = ConfigItem(
    "dubbing",
    "openai_tts_api_base",
    "https://api.openai.com/v1",
    Restart
)
openai_tts_model = ConfigItem(
    "dubbing",
    "openai_tts_model",
    "tts-1",
    Restart
)
```

**UI 界面添加输入框** (`dubbing_interface.py`):
```python
# API 配置卡片
api_layout.addWidget(BodyLabel("API Base URL:", self))
self.api_base_edit = LineEdit(self)
self.api_base_edit.setPlaceholderText("https://api.openai.com/v1")
api_layout.addWidget(self.api_base_edit)

api_layout.addWidget(BodyLabel("API Key:", self))
self.api_key_edit = LineEdit(self)
...
```

**根据引擎显示/隐藏**:
```python
def _on_provider_changed(self, text):
    provider = text.split(" - ")[0].lower()
    
    if provider == "openai":
        self.api_base_edit.setVisible(True)
        self.api_base_edit.setText(cfg.openai_tts_api_base.value)
    else:
        self.api_base_edit.setVisible(False)
```

---

## 📋 实施步骤

### 步骤 1: 修复 Edge TTS 音色加载器
- [ ] 在 `loader.py` 中添加详细错误日志
- [ ] 确保异步调用正确执行
- [ ] 测试音色是否能成功加载

### 步骤 2: 修复 ElevenLabs API 测试
- [ ] 安装 `elevenlabs` 库：`pip install elevenlabs`
- [ ] 修改 `ElevenLabsAPITestThread` 使用官方库
- [ ] 测试 API 是否能获取音色列表

### 步骤 3: 添加 OpenAI TTS Base URL
- [ ] 在 `config.py` 添加配置项
- [ ] 在 UI 添加输入框
- [ ] 根据引擎动态显示/隐藏
- [ ] 保存和恢复配置

### 步骤 4: 测试完整流程
- [ ] Edge TTS: 选择语言 → 显示音色 → 试听 → 配音
- [ ] ElevenLabs: 输入 Key → 测试 → 显示音色 → 配音
- [ ] OpenAI TTS: 输入 Base URL + Key → 配音

---

## 🔍 调试建议

### 1. 检查 Edge TTS 音色加载
```python
# 添加到 loader.py 的 load_edge_voices_from_api
try:
    voices = asyncio.run(edge_tts.list_voices())
    print(f"✅ 成功获取 {len(voices)} 个音色")
    return grouped_voices
except Exception as e:
    print(f"❌ 加载失败: {e}")
    import traceback
    traceback.print_exc()
```

### 2. 检查 ElevenLabs API
```python
# 测试脚本
from elevenlabs import ElevenLabs

api_key = "your_api_key_here"
client = ElevenLabs(api_key=api_key)
voices = client.voices.get_all()

print(f"获取到 {len(voices.voices)} 个音色:")
for v in voices.voices[:5]:
    print(f"  - {v.name}: {v.voice_id}")
```

### 3. 检查音色下拉框
```python
# 在 _on_language_changed 中添加
print(f"语言代码: {language_code}")
voices = get_voices_by_language(language_code)
print(f"获取到 {len(voices)} 个音色")
for name, vid in voices[:5]:
    print(f"  - {name}: {vid}")
```

---

## ⚠️ 注意事项

1. **依赖安装**:
   ```bash
   pip install elevenlabs edge-tts requests
   ```

2. **API Key 格式**:
   - ElevenLabs: `sk_xxx`
   - OpenAI: `sk-xxx`

3. **网络问题**:
   - edge-tts 需要访问 Microsoft API
   - ElevenLabs 需要访问 elevenlabs.io
   - 确保网络可达

4. **错误处理**:
   - 所有 API 调用都应有 try-except
   - 失败时应显示友好的错误信息
   - 提供降级方案（使用缓存/静态数据）

---

**总结**: 主要问题是音色加载失败和 API 调用方式不正确。参考 pyvideotrans-src 的实现，需要使用官方库并正确处理异步调用。
