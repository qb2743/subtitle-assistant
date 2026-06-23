# 补充需求：配音功能增强

**更新日期**：2026-06-21

---

## 🎯 新增需求概述

基于 pyvideotrans 的实现，为 VideoCaptioner 的配音功能添加两个重要特性：

### 1️⃣ 字幕行间停顿控制
允许用户在每行字幕配音之间添加固定的停顿时间

### 2️⃣ ElevenLabs API Key 轮询
支持配置多个 API Key，自动轮询使用（避免单个 Key 配额耗尽）

---

## 📋 需求 1：字幕行间停顿控制

### 功能描述
在配音时，忽略 SRT 文件的原始时间轴，为每行配音后自动添加固定时长的停顿。

### 使用场景
- 用户制作有声书、教程视频
- 希望每句话之间有明确的停顿
- 不关心与原视频的精确同步

### pyvideotrans 的实现

#### UI 界面：
```python
# videotrans/ui/peiyin.py
self.fixed_line_pause = QtWidgets.QCheckBox()
self.fixed_line_pause.setText("固定停顿")
self.fixed_line_pause.setToolTip("忽略SRT时间轴，每行配音后追加固定停顿")

self.fixed_line_pause_ms = QtWidgets.QComboBox()
self.fixed_line_pause_ms.addItems(["0.5s", "1s", "2s"])
self.fixed_line_pause_ms.setToolTip("每行配音后的固定停顿时长")
```

#### 配置存储：
```python
# videotrans/configure/config.py
{
    "fixed_line_pause": False,          # 是否启用固定停顿
    "fixed_line_pause_ms": 1000,        # 停顿时长（毫秒）
}
```

#### 核心逻辑：
```python
# videotrans/task/_rate.py
def _run_no_rate_change_mode(self):
    if self.fixed_line_pause:
        self._run_fixed_line_pause_mode()
        return
    # 正常模式...

def _run_fixed_line_pause_mode(self):
    """固定停顿模式：忽略时间轴，顺序拼接音频"""
    audio_concat_list = []
    current_timeline = 0
    
    for i, item in enumerate(self.queue_tts):
        audio_file = item['filename']
        dubb_len = tools.get_audio_duration_ms(audio_file)
        
        audio_concat_list.append(audio_file)
        current_timeline += dubb_len
        
        # 在每行音频后添加停顿（静音）
        if self.fixed_line_pause_ms > 0:
            silence_file = self._create_silen_file(f"pause_{i}", self.fixed_line_pause_ms)
            audio_concat_list.append(silence_file)
            current_timeline += self.fixed_line_pause_ms
    
    # 拼接所有音频（包括停顿）
    self._exec_concat_audio(audio_concat_list)
```

#### 静音生成：
```python
def _create_silen_file(self, name: str, duration_ms: int) -> str:
    """生成指定时长的静音文件"""
    silence_file = Path(self.cache_folder) / f"{name}.wav"
    # 使用 ffmpeg 生成静音
    # ffmpeg -f lavfi -i anullsrc=r=44100:cl=stereo -t {duration_sec} {output}
    return str(silence_file)
```

---

### 需要在 VideoCaptioner 中实现

#### 1. 数据模型扩展
```python
# videocaptioner/core/dubbing/models.py
@dataclass
class DubbingConfig:
    # ... 现有字段 ...
    
    # 新增字段
    fixed_line_pause: bool = False           # 是否启用固定停顿
    fixed_line_pause_ms: int = 1000          # 停顿时长（毫秒）
```

#### 2. 核心逻辑实现
```python
# videocaptioner/core/dubbing/pipeline.py
class DubbingPipeline:
    def _create_timeline(self, segments: List[DubbingSegment]) -> List[Tuple[str, int]]:
        """创建音频时间线"""
        if self.config.fixed_line_pause:
            return self._create_fixed_pause_timeline(segments)
        else:
            return self._create_normal_timeline(segments)
    
    def _create_fixed_pause_timeline(self, segments: List[DubbingSegment]) -> List[Tuple[str, int]]:
        """固定停顿模式：忽略原时间轴"""
        timeline = []
        current_time = 0
        
        for i, seg in enumerate(segments):
            # 添加音频
            duration_ms = get_audio_duration_ms(seg.audio_path)
            timeline.append((seg.audio_path, current_time))
            current_time += duration_ms
            
            # 添加停顿（除了最后一行）
            if i < len(segments) - 1 and self.config.fixed_line_pause_ms > 0:
                silence_path = self._create_silence(f"pause_{i}", self.config.fixed_line_pause_ms)
                timeline.append((silence_path, current_time))
                current_time += self.config.fixed_line_pause_ms
        
        return timeline
    
    def _create_silence(self, name: str, duration_ms: int) -> str:
        """生成静音文件"""
        # 使用 pydub 生成静音
        from pydub import AudioSegment
        silence = AudioSegment.silent(duration=duration_ms)
        output_path = self.work_dir / f"{name}.wav"
        silence.export(output_path, format="wav")
        return str(output_path)
```

#### 3. UI 配置
```python
# videocaptioner/ui/view/dubbing_settings.py
# 在配音设置中添加复选框和下拉框

self.fixed_line_pause = QCheckBox("固定停顿")
self.fixed_line_pause.setToolTip("忽略SRT时间轴，每行配音后追加固定停顿")

self.fixed_line_pause_duration = QComboBox()
self.fixed_line_pause_duration.addItems(["0.5秒", "1秒", "2秒", "3秒"])
self.fixed_line_pause_duration.setEnabled(False)  # 初始禁用

# 绑定事件
self.fixed_line_pause.stateChanged.connect(
    lambda state: self.fixed_line_pause_duration.setEnabled(state == Qt.Checked)
)
```

---

## 📋 需求 2：ElevenLabs API Key 轮询

### 功能描述
允许用户配置多个 ElevenLabs API Key（用逗号或分号分隔），系统自动轮询使用。

### 使用场景
- 用户有多个 ElevenLabs 账号
- 避免单个 Key 配额耗尽导致任务中断
- 提高并发处理能力

### pyvideotrans 的实现

#### 配置格式：
```python
# 用户输入（支持多种分隔符）
elevenlabs_api_key = "key1, key2; key3，key4"
```

#### 核心机制：

##### 1. 解析多个 Key
```python
# videotrans/configure/config.py
def get_elevenlabs_api_keys(key_string: str = None) -> List[str]:
    """解析 API Key 字符串，返回 Key 列表"""
    if not key_string:
        key_string = params.get('elevenlabstts_key', '')
    
    # 支持多种分隔符：空格、逗号、分号（中英文）
    keys = re.split(r'[\s,;，；]+', key_string)
    return [k.strip() for k in keys if k.strip()]
```

##### 2. 轮询选择 Key（Round-Robin）
```python
# 全局状态
_elevenlabs_key_index = 0
_elevenlabs_key_lock = threading.Lock()

def get_elevenlabs_api_key_candidates(key_string: str = None) -> List[str]:
    """
    返回按轮询顺序排列的 Key 列表
    每次调用会将游标前进 1 位
    """
    global _elevenlabs_key_index
    
    keys = get_elevenlabs_api_keys(key_string)
    if not keys:
        return []
    
    with _elevenlabs_key_lock:
        idx = _elevenlabs_key_index % len(keys)
        _elevenlabs_key_index += 1
    
    # 返回从当前位置开始的 Key 列表（作为 fallback）
    # 例如：keys = [A, B, C], idx = 1 → 返回 [B, C, A]
    return keys[idx:] + keys[:idx]
```

##### 3. TTS 中使用轮询
```python
# videotrans/tts/_elevenlabs.py
def _run(self, data_item: Dict) -> None:
    keys = get_elevenlabs_api_key_candidates()  # 获取轮询后的 Key 列表
    if not keys:
        keys = ['']
    
    last_error = None
    for key_index, api_key in enumerate(keys):
        try:
            client = ElevenLabs(api_key=api_key)
            response = client.text_to_speech.convert(...)
            # 成功则返回
            return
        
        except Exception as e:
            last_error = e
            
            # 判断是否应该尝试下一个 Key
            if key_index < len(keys) - 1 and self._should_try_next_key(e):
                logger.warning(f'ElevenLabs key failed, trying next key: {e}')
                continue  # 尝试下一个 Key
            
            # 所有 Key 都失败，或遇到不可重试的错误
            raise
    
    # 所有 Key 都失败
    if last_error:
        raise last_error

@staticmethod
def _should_try_next_key(error: Exception) -> bool:
    """判断错误是否应该尝试下一个 Key"""
    if isinstance(error, UnauthorizedError):
        return True  # 未授权 → 换 Key
    
    if isinstance(error, ElevenLabsApiError):
        status_code = getattr(error, 'status_code', None)
        if status_code in (401, 402, 403, 404, 429):
            return True  # 配额/权限问题 → 换 Key
        
        body = str(getattr(error, 'body', '')).lower()
        if any(word in body for word in ('quota', 'rate', 'limit', 'unauthorized', 'permission')):
            return True  # 错误信息包含配额关键词 → 换 Key
    
    return False  # 其他错误（网络、服务器）→ 不换 Key
```

---

### 需要在 VideoCaptioner 中实现

#### 1. 配置管理
```python
# videocaptioner/core/config.py
import re
import threading
from typing import List

_elevenlabs_key_index = 0
_elevenlabs_key_lock = threading.Lock()

def parse_api_keys(key_string: str) -> List[str]:
    """解析 API Key 字符串（支持多种分隔符）"""
    if not key_string:
        return []
    keys = re.split(r'[\s,;，；]+', key_string)
    return [k.strip() for k in keys if k.strip()]

def get_next_elevenlabs_key(keys: List[str]) -> List[str]:
    """
    轮询获取下一个 Key（Round-Robin）
    返回从当前位置开始的列表（用于 fallback）
    """
    global _elevenlabs_key_index
    
    if not keys:
        return []
    
    with _elevenlabs_key_lock:
        idx = _elevenlabs_key_index % len(keys)
        _elevenlabs_key_index += 1
    
    return keys[idx:] + keys[:idx]
```

#### 2. Speech Provider 扩展
```python
# videocaptioner/core/speech/providers.py
class ElevenLabsSpeechSynthesizer:
    def __init__(self, config: SpeechProviderConfig):
        self.config = config
        # 解析 API Keys（支持多个）
        self.api_keys = parse_api_keys(config.api_key)
        if not self.api_keys:
            raise ValueError("At least one ElevenLabs API key is required")
    
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        # 获取轮询后的 Key 列表
        keys_to_try = get_next_elevenlabs_key(self.api_keys)
        
        last_error = None
        for key_index, api_key in enumerate(keys_to_try):
            try:
                client = ElevenLabs(api_key=api_key)
                response = client.text_to_speech.convert(
                    text=request.text,
                    voice_id=request.voice or self.config.default_voice,
                    model_id=self.config.model,
                    output_format="mp3_44100_128",
                    voice_settings=VoiceSettings(
                        speed=self.config.speed,
                        stability=0.8,
                        similarity_boost=1,
                    )
                )
                
                # 写入文件
                output_path = Path(request.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    for chunk in response:
                        if chunk:
                            f.write(chunk)
                
                return SynthesisResult(
                    output_path=str(output_path),
                    voice=request.voice or self.config.default_voice,
                    format="mp3",
                    provider_metadata={"api_key_index": key_index}
                )
            
            except Exception as e:
                last_error = e
                logger.warning(f"ElevenLabs API key {key_index + 1} failed: {e}")
                
                # 判断是否应该尝试下一个 Key
                if key_index < len(keys_to_try) - 1 and self._should_retry_with_next_key(e):
                    continue
                else:
                    raise
        
        raise RuntimeError(f"All {len(keys_to_try)} ElevenLabs API keys failed: {last_error}")
    
    @staticmethod
    def _should_retry_with_next_key(error: Exception) -> bool:
        """判断错误是否应该尝试下一个 Key"""
        from elevenlabs import UnauthorizedError
        from elevenlabs.core import ApiError as ElevenLabsApiError
        
        if isinstance(error, UnauthorizedError):
            return True
        
        if isinstance(error, ElevenLabsApiError):
            status_code = getattr(error, 'status_code', None)
            if status_code in (401, 402, 403, 404, 429):
                return True
            
            body = str(getattr(error, 'body', '')).lower()
            return any(word in body for word in ('quota', 'rate', 'limit', 'unauthorized'))
        
        return False
```

#### 3. UI 配置
```python
# videocaptioner/ui/view/tts_settings.py
# API Key 输入框的 tooltip
api_key_card = LineEditSettingCard(
    FIF.KEY,
    "ElevenLabs API Key",
    "支持多个 Key（用逗号或分号分隔），系统将自动轮询使用\n例如：key1, key2, key3",
    cfg.elevenlabs_api_key
)
```

---

## 🎯 实施优先级

### 高优先级：ElevenLabs 轮询 ⭐⭐⭐
**原因**：
- 直接影响用户体验（避免配额耗尽导致任务失败）
- 实现相对简单（主要是逻辑修改）
- 可以在实现 ElevenLabs 基础功能时一并完成

**工作量**：+0.5 天（在原有 1 天基础上增加）

### 中优先级：固定停顿 ⭐⭐
**原因**：
- 是一个独立的功能增强
- 不影响现有配音流程
- 适合在配音功能完整后添加

**工作量**：+1 天

---

## 📝 修订后的工作量估算

| 任务 | 原估算 | 增加 | 新估算 |
|------|--------|------|--------|
| ElevenLabs TTS（基础） | 1 天 | +0.5 天 | **1.5 天** |
| 固定停顿功能 | - | +1 天 | **1 天** |
| **总计增加** | - | - | **+1.5 天** |

**总工期**：8-10 天 → **9.5-11.5 天**

---

## ✅ 验收标准

### ElevenLabs 轮询
- [ ] 支持配置多个 API Key（逗号/分号分隔）
- [ ] 自动轮询使用（Round-Robin）
- [ ] Key 失败时自动切换到下一个
- [ ] 配额/权限错误能触发切换
- [ ] 所有 Key 失败时给出清晰错误提示

### 固定停顿
- [ ] 配音设置中有停顿开关
- [ ] 支持选择停顿时长（0.5s/1s/2s/3s）
- [ ] 启用后生成的音频在每行之间有明确停顿
- [ ] 停顿时长准确（±50ms）
- [ ] 与正常模式可正常切换

---

## 📚 参考代码位置

### pyvideotrans 中的实现：
- **固定停顿 UI**：`videotrans/ui/peiyin.py` (L159-L165)
- **固定停顿逻辑**：`videotrans/task/_rate.py` (_run_fixed_line_pause_mode)
- **API Key 轮询**：`videotrans/configure/config.py` (get_elevenlabs_api_key_candidates)
- **ElevenLabs 集成**：`videotrans/tts/_elevenlabs.py`

---

## 🚀 建议的执行顺序

1. **先实现 ElevenLabs 基础功能**（1 天）
   - 使用官方 SDK
   - 支持音色选择

2. **然后添加 API Key 轮询**（0.5 天）
   - 扩展配置解析
   - 实现轮询逻辑
   - 添加错误判断

3. **最后添加固定停顿**（1 天）
   - 修改 DubbingPipeline
   - 添加静音生成
   - UI 配置

---

**准备好了我们就开始实施！** 🚀
