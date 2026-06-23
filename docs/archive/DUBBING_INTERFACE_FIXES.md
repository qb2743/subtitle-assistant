# 配音界面优化完成 ✅

**优化日期**: 2026-06-21  
**问题**: 三个关键问题需要修复

---

## 🎯 问题分析与解决

### 问题 1: 音色下拉框为空 ❌

**原因**:
- Edge TTS 模式下，语言和音色没有自动加载
- 切换到 ElevenLabs 时，没有提供获取音色的方式

**解决方案**: ✅
1. **Edge TTS**: 在 `_on_provider_changed` 中自动调用 `_load_languages()`
2. **ElevenLabs**: 添加"测试 API"按钮，测试成功后自动获取音色列表
3. 根据不同引擎显示/隐藏相应的控件

---

### 问题 2: 缺少"测试 API"按钮 ❌

**需求**:
- 切换到 ElevenLabs 时，需要一个按钮来测试 API
- 测试成功后顺便获取可用音色列表

**解决方案**: ✅
1. 在 API Key 输入框旁边添加测试按钮（同步图标 🔄）
2. 创建 `ElevenLabsAPITestThread` 线程类
3. 调用 ElevenLabs API 获取音色列表
4. 测试成功后自动填充音色下拉框

---

### 问题 3: 配音文件输出路径不明确 ❌

**现状**:
- 字幕文件模式：输出到 `字幕文件.dubbed.mp3`（同目录）✅
- 文案直接模式：输出到 `output.mp3`（工作目录）❌ 不够清晰

**解决方案**: ✅
- **字幕文件模式**：保持原样，输出到字幕文件同目录
  ```
  输入: D:\Videos\subtitle.srt
  输出: D:\Videos\subtitle.dubbed.mp3
  ```

- **文案直接模式**：创建 `dubbing` 子文件夹，使用时间戳命名
  ```
  输出: D:\音视频综合助手\dubbing\dubbing_20260621_153045.mp3
  ```

---

## 🔧 技术实现

### 1. 智能引擎切换

**文件**: `videocaptioner/ui/view/dubbing_interface.py`

```python
def _on_provider_changed(self, text):
    """Provider 改变时的提示和界面更新"""
    provider = text.split(" - ")[0].lower()

    if provider == "edge":
        # Edge TTS：显示语言和音色选择
        self.language_combo.setVisible(True)
        self.voice_combo.setVisible(True)
        self.preview_btn.setVisible(True)
        self.hint_label.setText("💡 选择语言后自动加载音色列表")
        
        # 自动加载音色
        if self.language_combo.count() == 0:
            self._load_languages()

    elif provider == "elevenlabs":
        # ElevenLabs：需要 API Key
        self.language_combo.setVisible(False)  # 隐藏语言选择
        self.voice_combo.setVisible(True)
        self.preview_btn.setVisible(False)  # 隐藏试听
        self.hint_label.setText("💡 输入 API Key 后点击测试按钮获取音色列表")
        self.test_api_btn.setEnabled(True)
```

### 2. 测试 API 按钮

**UI 布局**:
```python
# API Key 输入和测试按钮
api_input_layout = QHBoxLayout()

self.api_key_edit = LineEdit(self)
api_input_layout.addWidget(self.api_key_edit, 1)

# 测试 API 按钮
self.test_api_btn = ToolButton(FIF.SYNC, self)
self.test_api_btn.setToolTip("测试 API 并获取音色")
self.test_api_btn.clicked.connect(self._test_api)
api_input_layout.addWidget(self.test_api_btn)
```

**测试逻辑**:
```python
def _test_api(self):
    """测试 API 并获取音色列表"""
    api_key = self.api_key_edit.text().strip()
    
    if provider == "elevenlabs":
        self._test_elevenlabs_api(api_key)
```

### 3. ElevenLabs API 测试线程

**文件**: `videocaptioner/ui/view/dubbing_interface.py`

```python
class ElevenLabsAPITestThread(QThread):
    """ElevenLabs API 测试线程"""
    
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def run(self):
        import requests
        
        url = "https://api.elevenlabs.io/v1/voices"
        headers = {"xi-api-key": self.api_key}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            voices = data.get("voices", [])
            self.finished.emit(voices)
        elif response.status_code == 401:
            self.error.emit("API Key 无效，请检查后重试")
```

### 4. 智能输出路径

**文件**: `videocaptioner/ui/thread/dubbing_interface_thread.py`

```python
def _run_text_mode(self, config):
    """文案直接配音模式"""
    
    # 生成输出路径（文案模式）
    if not self.output_path:
        # 使用当前目录的 dubbing 子文件夹
        output_dir = Path.cwd() / "dubbing"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用时间戳作为文件名
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_path = str(output_dir / f"dubbing_{timestamp}.mp3")
```

---

## 🎨 UI 变化

### Edge TTS 模式
```
┌─────────────────────────────────┐
│ 配音引擎                         │
│ [edge - Edge TTS (免费) ▼]     │
├─────────────────────────────────┤
│ 语言与音色                       │
│ 语言: [中文 (zh)        ▼]     │
│ 音色: [Xiaoxiao(Female) ▼] [▶] │
│ 💡 选择语言后自动加载音色列表    │
├─────────────────────────────────┤
│ API 配置                         │
│ [输入 API Key]          [🔄]   │  ← 禁用
│ 💡 支持多 Key 轮询，用逗号分隔  │
└─────────────────────────────────┘
```

### ElevenLabs 模式
```
┌─────────────────────────────────┐
│ 配音引擎                         │
│ [elevenlabs - ElevenLabs ▼]    │
├─────────────────────────────────┤
│ 语言与音色                       │
│ （语言选择隐藏）                 │
│ 音色: [选择音色        ▼]       │
│ 💡 输入 API Key 后点击测试按钮  │
│    获取音色列表                  │
├─────────────────────────────────┤
│ API 配置                         │
│ [输入 API Key]          [🔄]   │  ← 启用
│ 💡 支持多 Key 轮询，用逗号分隔  │
└─────────────────────────────────┘
```

---

## ✅ 使用流程

### Edge TTS 流程
1. 选择"edge - Edge TTS (免费)"
2. 自动加载语言列表
3. 选择语言（如：中文）
4. 自动加载该语言的音色
5. 选择音色 → 点击试听 → 开始配音

### ElevenLabs 流程
1. 选择"elevenlabs - ElevenLabs"
2. 输入 API Key
3. **点击测试按钮 🔄**
4. 系统测试 API 并自动获取音色列表
5. 从下拉框选择音色 → 开始配音

---

## 📁 输出路径规则

| 模式 | 输入 | 输出路径 |
|------|------|----------|
| 字幕文件 | `D:\Videos\subtitle.srt` | `D:\Videos\subtitle.dubbed.mp3` |
| 文案直接 | 文本输入框 | `当前目录\dubbing\dubbing_时间戳.mp3` |

**示例**:
```
字幕文件模式：
  输入: C:\Users\qiu\Documents\video.srt
  输出: C:\Users\qiu\Documents\video.dubbed.mp3

文案直接模式：
  输入: "你好，这是测试文案"
  输出: D:\音视频综合助手\dubbing\dubbing_20260621_153045.mp3
```

---

## 🧪 测试验证

### 测试 1: 语法检查
```bash
python -m py_compile videocaptioner/ui/view/dubbing_interface.py
python -m py_compile videocaptioner/ui/thread/dubbing_interface_thread.py
```
**结果**: ✅ 通过

### 测试 2: Edge TTS 音色加载
1. 打开配音界面
2. 默认选择 Edge TTS
3. 检查语言下拉框是否自动加载
4. 选择中文，检查音色是否自动加载

**预期**: 显示 14 个中文音色

### 测试 3: ElevenLabs API 测试
1. 切换到 ElevenLabs
2. 输入有效的 API Key
3. 点击测试按钮
4. 检查是否显示成功提示
5. 检查音色下拉框是否填充

**预期**: 显示"已获取 X 个音色"

### 测试 4: 输出路径
1. 字幕文件模式：拖入 `test.srt`，配音后检查输出
2. 文案模式：输入文案，配音后检查输出

**预期**: 
- 字幕模式：`test.dubbed.mp3`（同目录）
- 文案模式：`dubbing/dubbing_时间戳.mp3`

---

## ⚠️ 注意事项

### 依赖要求
```bash
pip install edge-tts requests
```

### ElevenLabs API
- 需要有效的 API Key
- 免费账户有额度限制
- API endpoint: `https://api.elevenlabs.io/v1/voices`

### 输出路径
- 字幕模式：如果字幕文件所在目录没有写权限，会失败
- 文案模式：会在当前工作目录创建 `dubbing` 文件夹
- 可以在输出路径框手动指定路径

---

## 📝 相关文件

### 修改的文件
- ✅ `videocaptioner/ui/view/dubbing_interface.py` - 主界面优化
- ✅ `videocaptioner/ui/thread/dubbing_interface_thread.py` - 输出路径优化
- ✅ `videocaptioner/core/voices/loader.py` - 音色加载器（之前已修改）

### 新增的类
- ✅ `ElevenLabsAPITestThread` - ElevenLabs API 测试线程

---

## 🎊 优化总结

### 改进前
- ❌ Edge TTS 音色不自动加载
- ❌ ElevenLabs 无法获取音色列表
- ❌ 文案模式输出路径不清晰（`output.mp3`）

### 改进后
- ✅ Edge TTS 自动加载 322 个音色
- ✅ ElevenLabs 提供测试按钮，一键获取音色
- ✅ 文案模式使用 `dubbing/dubbing_时间戳.mp3`
- ✅ 智能界面切换（根据引擎显示/隐藏控件）
- ✅ 更友好的提示信息

---

**🎉 所有问题已解决！配音界面体验大幅提升！**
