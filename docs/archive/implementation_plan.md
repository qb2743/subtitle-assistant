# 字幕与配音集成软件实现计划 (基于 VideoCaptioner)

## 总体目标
在 `VideoCaptioner-src` 现有的三层架构基础上，移植 `pyvideotrans` 的特定 TTS 渠道（ElevenLabs、OpenAI TTS、Dots-TTS、VoxCPMv2），实现本地模型的延迟下载机制（类似 Faster Whisper），并从 `txt2srt` 提取基于 DTW 的文稿匹配算法，复用现有的 ASR 模型提取时间戳。

---

## 阶段一：云端 TTS 渠道移植

### 1. OpenAI TTS 适配与暴露
- **分析**：VideoCaptioner `core/tts/` 下其实已经有 `openai_tts.py` 的初步实现。
- **任务**：
  - 检查并完善 `core/tts/openai_tts.py`，确保其继承自 `BaseTTS` 并正确实现了 `_synthesize` 方法。
  - 在 `core/entities.py` 的 TTS 枚举中注册 OpenAI TTS。
  - 在 UI 层（`ui/view/`）添加 OpenAI TTS 的 API Key 配置卡片。

### 2. ElevenLabs TTS 移植
- **分析**：将 `pyvideotrans/tts/_elevenlabs.py` 适配到 VideoCaptioner 的架构中。
- **任务**：
  - 新建 `core/tts/elevenlabs.py`，继承 `BaseTTS`。
  - 使用 `requests` 实现 ElevenLabs 的 HTTP API 调用，包含 Voice ID 选择。
  - 在 `core/entities.py` 注册 ElevenLabs。
  - 在 UI 层添加 ElevenLabs 的设置界面（API Key 和音色选择）。

---

## 阶段二：本地 TTS 渠道与延迟下载机制

> [!TIP]
> **设计模式思路**：复用 VideoCaptioner `FasterWhisperSettingWidget` 的逻辑。通过在配置文件中保留本地服务的安装路径，当用户选择该 TTS 且路径下无程序时，触发下载窗口。

### 3. Dots-TTS 移植与按需下载
- **分析**：`pyvideotrans` 中的 Dots-TTS (`_dotstts.py`) 实际上是调用一个本地启动的 Gradio 服务。
- **任务**：
  - **核心逻辑**：新建 `core/tts/dots_tts.py`。其逻辑为：检查本地 Dots-TTS 服务是否就绪 $\rightarrow$ 未就绪则运行本地启动脚本 $\rightarrow$ 发送 HTTP 请求进行合成。
  - **UI 与按需下载**：在 UI 设置中添加 `Dots-TTS 引擎路径`。实现一个 `DotsTTSSettingWidget`，如果检测到本地未安装（或路径为空），提供一个【下载环境/模型】的按钮，类似 Faster Whisper 的下载弹窗。下载完成后解压到指定目录。

### 4. VoxCPMv2 移植与按需下载
- **分析**：`pyvideotrans` 的 `_voxcpm.py` 同样继承自 `GradioBase`，调用本地或远程的 `/generate` API。
- **任务**：
  - **核心逻辑**：新建 `core/tts/voxcpm.py`，处理 v2 版本的请求参数（`text`, `ref_wav`, `dit_steps` 等）。
  - **音色克隆适配**：VoxCPM 支持参考音频（克隆），需对接 `BaseTTS` 的 `segment.clone_audio_path`。
  - **按需下载**：与 Dots-TTS 类似，实现 `VoxCPMSettingWidget`，支持环境和模型的懒加载下载。

---

## 阶段三：文稿匹配 (DTW) 集成

> [!IMPORTANT]
> **资源复用**：文稿匹配完全可以复用 VideoCaptioner 现有的 `FasterWhisperASR` 引擎！流程变为：使用现成的 ASR 跑出带时间戳的粗糙结果 $\rightarrow$ 用 DTW 将用户提供的正确文稿强制对齐到这些时间戳上。

### 5. 核心 DTW 算法移植
- **任务**：
  - 在项目中添加轻量级依赖 `dtw-python`。
  - 新建 `core/split/alignment.py`（或类似模块）。
  - 将 `txt2srt.py` 中的 `match_user_text_to_timestamps` 核心算法提取过来。
  - 编写适配器：将 VideoCaptioner 的 `ASRDataSeg` 对象列表转换为算法需要的 `List[Dict]`，对齐后再转回 `ASRData` 格式。

### 6. 文稿匹配业务管线 (Pipeline)
- **任务**：
  - 在 `core/` 下建立一个新的任务管线（例如 `TextMatchingTask`）。
  - 步骤：
    1. 接收视频/音频文件和纯文本文稿。
    2. 调用现有的 `transcribe()` 工厂函数（例如选用本地的 Faster Whisper）获取初始时间戳。
    3. 调用 DTW 算法进行对齐，覆盖原识别文本，保留原时间戳。
    4. 修正时间戳重叠并优化字幕显示时长（移植 `txt2srt` 的后处理函数）。
    5. 生成最终的 SRT 字幕文件。

### 7. 文稿匹配 UI 界面
- **任务**：
  - 在主界面侧边栏新增一个【文稿匹配】Tab。
  - 界面左侧：音视频文件导入卡片 + 现有的 ASR 引擎选择卡片（复用转录的 UI，让用户选择 Faster Whisper 等）。
  - 界面右侧：文本框用于粘贴或导入正确的 txt 文稿。
  - 底部：【开始匹配】按钮及进度条。

---

## 阶段四：联调与测试

### 8. 整体串联测试
- **任务**：
  - 测试文稿匹配模块生成字幕的准确性。
  - 测试将文稿匹配生成的字幕直接发送到翻译/配音管线（打通业务流）。
  - 验证本地 TTS 模型下载的断点续传/解压逻辑。
  - 测试配音模块的音轨合成效果。

## 优先级与执行顺序建议

1. **先做核心业务逻辑**：阶段三的文稿匹配（由于依赖现有的 ASR，能快速出成果且逻辑最独立）。
2. **再做云端 TTS**：阶段一（API 接入相对简单，能快速跑通配音的基础管线）。
3. **最后做本地 TTS 懒加载**：阶段二（涉及多线程下载、解压、本地服务启停，UI 和逻辑都最复杂）。

## 用户确认

这套实现计划是否符合您的期望？如果确认无误，我们可以直接从**阶段三（文稿匹配核心算法移植）**开始执行第一步！
