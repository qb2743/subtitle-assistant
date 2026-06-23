# VideoCaptioner 两套 TTS 架构对比分析

**分析结论**：两套架构各有用途，**不冲突**，应该保留两者。

---

## 📊 架构对比总览

| 维度 | `core/tts/` | `core/speech/` |
|------|-------------|----------------|
| **设计目的** | 通用 TTS 框架（批量处理） | 配音管线专用（单次合成） |
| **数据模型** | `TTSData` + `TTSDataSeg`（列表） | `SynthesisRequest`（单个） |
| **处理模式** | 批量（遍历 segments） | 单次（per utterance） |
| **缓存机制** | ✅ 内置（BaseTTS） | ❌ 无（由调用者管理） |
| **进度回调** | ✅ 内置（统一接口） | ❌ 无 |
| **当前使用者** | ❌ 无（可能是新架构） | ✅ `core/dubbing/pipeline.py` |
| **实现的引擎** | OpenAI, SiliconFlow, OpenAI.fm | EdgeTTS, SiliconFlow, Gemini |
| **文件数** | 7 个文件 | 3 个文件 |
| **代码量** | ~500 行 | ~400 行 |

---

## 🔍 详细分析

### 1. `core/tts/` - 通用批量处理框架

**设计理念**：
- 处理**一批文本**，统一管理缓存、进度、错误处理
- 适合需要合成大量音频的场景（如批量字幕配音）

**核心接口**：
```python
class BaseTTS(ABC):
    def synthesize(
        self, 
        tts_data: TTSData,  # 包含多个 TTSDataSeg 的容器
        output_dir: str,
        callback: Optional[Callable[[int, str], None]] = None
    ) -> TTSData:
        """批量合成，返回填充了 audio_path 的 TTSData"""
        for segment in tts_data.segments:
            self._synthesize_segment(segment, output_path)  # 带缓存
        return tts_data
    
    @abstractmethod
    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        """子类实现：合成单个 segment"""
        pass
```

**数据结构**：
```python
@dataclass
class TTSDataSeg:
    text: str
    start_time: float = 0.0
    end_time: float = 0.0
    audio_path: str = ""              # 填充后的路径
    audio_duration: float = 0.0
    voice: Optional[str] = None
    clone_audio_path: Optional[str] = None  # 声音克隆
    clone_audio_text: Optional[str] = None

class TTSData:
    segments: List[TTSDataSeg]
    
    @classmethod
    def from_texts(cls, texts: List[str]) -> "TTSData":
        """从文本列表快速创建"""
```

**特点**：
- ✅ **内置缓存**：自动管理二进制音频缓存
- ✅ **批量优化**：统一的进度管理、错误处理
- ✅ **声音克隆**：内置支持参考音频
- ✅ **类型安全**：完整的类型标注

**使用场景**：
- 批量字幕配音
- 大规模文本转语音
- 需要缓存的场景

**已实现的引擎**：
- `openai_tts.py` - OpenAI TTS（58 行）
- `siliconflow.py` - SiliconFlow CosyVoice（210 行）
- `openai_fm.py` - OpenAI Fish Models（未详查）

---

### 2. `core/speech/` - 配音管线专用

**设计理念**：
- 处理**单个发音请求**，轻量级、灵活
- 适合配音管线（DubbingPipeline）逐条合成字幕

**核心接口**：
```python
class SpeechSynthesizer(Protocol):
    """Provider-neutral synthesis interface"""
    
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """合成单个 utterance"""
        pass

def create_speech_synthesizer(config: SpeechProviderConfig) -> SpeechSynthesizer:
    """工厂函数"""
    if config.provider == "siliconflow":
        return SiliconFlowSpeechSynthesizer(config)
    if config.provider == "gemini":
        return GeminiSpeechSynthesizer(config)
    if config.provider == "edge":
        return EdgeTTSSpeechSynthesizer(config)
```

**数据结构**：
```python
@dataclass
class SynthesisRequest:
    """单个发音请求"""
    text: str
    output_path: str
    voice: Optional[str] = None
    style_prompt: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None

@dataclass
class SynthesisResult:
    """合成结果"""
    output_path: str
    voice: str
    format: AudioFormat
    provider_metadata: dict  # 提供商特定的元数据
```

**特点**：
- ✅ **轻量级**：单次请求，无额外开销
- ✅ **灵活性**：每个请求可以独立配置
- ✅ **并行友好**：由调用者（DubbingPipeline）管理并发
- ❌ **无缓存**：调用者自己决定是否缓存

**使用场景**：
- `core/dubbing/pipeline.py` 配音管线
- 需要逐条控制的场景
- 并行合成（ThreadPoolExecutor）

**已实现的引擎**：
- `EdgeTTSSpeechSynthesizer` - 微软 Edge TTS（免费）
- `SiliconFlowSpeechSynthesizer` - SiliconFlow（支持声音克隆）
- `GeminiSpeechSynthesizer` - Google Gemini 原生语音

---

## 🎯 为什么有两套架构？

### 历史推测：

1. **`core/speech/` 是初始设计**（简单、直接）
   - 专门为 `dubbing` 模块设计
   - 轻量级，满足配音需求

2. **`core/tts/` 是后来的重构**（通用、完善）
   - 意识到 TTS 可以用于更多场景（不只是配音）
   - 添加了缓存、批量处理等企业级特性
   - 设计更通用，方便扩展

3. **两者并存是合理的**
   - `core/speech/` 保留给配音管线（已稳定运行）
   - `core/tts/` 用于新功能（如批量字幕翻译+配音）

---

## 📋 实际使用情况

### ✅ `core/speech/` 被使用
```python
# videocaptioner/core/dubbing/pipeline.py
from videocaptioner.core.speech import (
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)

class DubbingPipeline:
    def __init__(self, config: DubbingConfig):
        speech_config = SpeechProviderConfig(...)
        self.synthesizer = create_speech_synthesizer(speech_config)
    
    def _process_segment(self, segment: DubbingSegment, work_dir: Path):
        request = SynthesisRequest(
            text=segment.text,
            output_path=str(audio_path),
            voice=segment.speaker.voice,
            ...
        )
        result = self.synthesizer.synthesize(request)
```

### ❌ `core/tts/` 暂未被使用
- 只有内部互相导入（base.py, openai_tts.py, siliconflow.py）
- 没有找到 CLI、UI、或其他业务模块使用它

**推测**：可能是为未来功能预留的架构

---

## 🚀 我们应该怎么办？

### 建议：**两者都保留，新增功能基于场景选择**

#### 场景 1：为配音管线添加新引擎（如 ElevenLabs）
**使用 `core/speech/`**

**原因**：
- 配音管线已经使用 `core/speech/`
- 不需要破坏现有稳定代码
- 单次合成模式更适合配音（逐条并行）

**实现**：
```python
# videocaptioner/core/speech/providers.py
class ElevenLabsSpeechSynthesizer:
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        from elevenlabs import ElevenLabs, VoiceSettings
        client = ElevenLabs(api_key=self.config.api_key)
        response = client.text_to_speech.convert(
            text=request.text,
            voice_id=request.voice or self.config.default_voice,
            ...
        )
        # 写入 request.output_path
        return SynthesisResult(...)

# 在 create_speech_synthesizer 中注册
def create_speech_synthesizer(config: SpeechProviderConfig):
    if config.provider == "elevenlabs":
        return ElevenLabsSpeechSynthesizer(config)
    # ...
```

**工作量**：0.5-1 天

---

#### 场景 2：批量字幕配音（新功能）
**使用 `core/tts/`**

**原因**：
- 需要批量处理（一次性处理几百条字幕）
- 需要缓存（避免重复合成）
- 需要统一的进度管理

**实现**：
```python
# 新增引擎
class ElevenLabsTTS(BaseTTS):
    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        # 实现单个 segment 的合成
        pass

# 业务代码
tts = ElevenLabsTTS(config)
tts_data = TTSData.from_texts(subtitle_texts)
result = tts.synthesize(tts_data, output_dir="./audio/", callback=progress_callback)
# result.segments 中所有 audio_path 已填充
```

**工作量**：1-1.5 天

---

#### 场景 3：本地 TTS（Dots-TTS、VoxCPM）
**两者都可以，建议用 `core/tts/`**

**原因**：
- 本地服务启动慢，批量处理更高效（启动一次服务合成多条）
- 缓存对本地 TTS 更重要（避免重启服务）
- 可以先在 `core/tts/` 实现，再包装一个 `core/speech/` 的 adapter

**实现策略**：
```python
# 1. 在 core/tts/ 实现核心逻辑
class DotsTTS(GradioBaseTTS):
    def _synthesize(self, segment: TTSDataSeg, output_path: str):
        # 服务管理 + gradio_client 调用
        pass

# 2. （可选）在 core/speech/ 提供 adapter
class DotsTTSSpeechSynthesizer:
    def __init__(self, config: SpeechProviderConfig):
        # 内部使用 core/tts/DotsTTS
        self.tts = DotsTTS(convert_to_tts_config(config))
    
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        # 单次请求转换为 TTSDataSeg
        segment = TTSDataSeg(text=request.text, ...)
        self.tts._synthesize(segment, request.output_path)
        return SynthesisResult(...)
```

**工作量**：2-3 天

---

## 🎯 最终建议

### 优先级排序

#### 阶段一：快速支持云端 TTS（配音管线）
**目标**：让用户能在配音中使用 ElevenLabs

**实现**：在 `core/speech/providers.py` 中添加 `ElevenLabsSpeechSynthesizer`

**工作量**：0.5-1 天

**优势**：
- 最小改动
- 立即可用
- 不破坏现有架构

---

#### 阶段二：实现批量 TTS 框架（未来功能）
**目标**：支持批量字幕配音、文本转语音等新功能

**实现**：完善 `core/tts/` 架构，添加更多引擎

**工作量**：2-3 天

**优势**：
- 为未来功能打基础
- 提供更强大的 TTS 能力

---

#### 阶段三：本地 TTS（高级功能）
**目标**：支持 Dots-TTS、VoxCPM 等本地服务

**实现**：在 `core/tts/` 实现 `GradioBaseTTS`，然后选择性添加到 `core/speech/`

**工作量**：3-4 天

**优势**：
- 免费、私有化部署
- 音色克隆

---

## 📊 总结对比表

| 特性 | core/tts/ | core/speech/ | 建议选择 |
|------|-----------|--------------|----------|
| **配音管线集成** | ❌ 需要 adapter | ✅ 原生支持 | `core/speech/` |
| **批量处理** | ✅ 内置 | ❌ 需要自己实现 | `core/tts/` |
| **缓存机制** | ✅ 自动 | ❌ 手动 | `core/tts/` |
| **进度回调** | ✅ 统一接口 | ❌ 自己管理 | `core/tts/` |
| **代码量** | 多（完善） | 少（简洁） | 看场景 |
| **学习曲线** | 陡（复杂） | 平（简单） | 看场景 |
| **扩展性** | 高 | 中 | `core/tts/` |
| **性能优化** | ✅ 内置 | ❌ 手动 | `core/tts/` |

---

## 🎯 最终执行方案

### 第 1 天：ElevenLabs（配音专用）
```python
# videocaptioner/core/speech/providers.py 中添加
class ElevenLabsSpeechSynthesizer:
    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        # 使用 elevenlabs SDK
        pass

# create_speech_synthesizer 中注册
if config.provider == "elevenlabs":
    return ElevenLabsSpeechSynthesizer(config)
```

### 第 2-3 天：完善 core/tts/ 框架
- 添加工厂函数（类似 `create_speech_synthesizer`）
- 完善文档和示例
- 测试现有的 OpenAI TTS、SiliconFlow

### 第 4-5 天：本地 TTS（基于 core/tts/）
- 实现 `GradioBaseTTS`
- 实现 `DotsTTS`、`VoxCPMTTS`
- （可选）添加到 `core/speech/` 的 adapter

---

## ✅ 结论

**两套架构都应该保留**：
- `core/speech/` - 配音管线专用，轻量、稳定
- `core/tts/` - 通用框架，批量、缓存、完善

**新增功能的选择**：
- 如果是为**配音管线**添加引擎 → 用 `core/speech/`
- 如果是**新的批量处理功能** → 用 `core/tts/`
- 如果是**本地 TTS** → 优先 `core/tts/`，可选 adapter 到 `core/speech/`

**实施计划不需要大改**，只需在每个阶段明确使用哪个架构！
