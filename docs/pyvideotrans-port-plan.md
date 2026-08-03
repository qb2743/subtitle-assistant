# pyVideoTrans 视频对齐功能移植改造方案

> 日期:2026-08-03 · 方案/审阅:Opus · 实施:Haiku 子 agent
> 对标项目:`D:\pyvideotrans`(pyVideoTrans v4.08)
> 目标:将其主界面圈选的"视频对齐"相关功能移植到本项目配音流水线。

---

## 0. 圈选功能清单(来自截图)

| # | 圈选区域 | 功能 |
|---|---------|------|
| A | 右上 | 识别说话人(+数量下拉)、仅保留解说员字幕、LLM复核被删字幕 |
| B | 对齐控制行 | 配音加速、视频变速、随机镜像画面、随机调色、统一画布、嵌入硬字幕、语音间隔(毫秒) |
| C | 背景音行 | 分离人声背景声、重新嵌入背景声、背景音短时循环、背景音量、添加额外背景音频 |
| D | 右侧按钮 | 修改硬字幕样式 |
| E | 顶部(可能圈选) | 输出到..(自定义输出目录) |

---

## 1. 与本项目现状对照(探测结论)

| 功能 | pyVideoTrans 实现 | 本项目现状 | 结论 |
|------|------------------|-----------|------|
| 配音加速 | `task/_rate.py` SpeedRate:atempo/rubberband 逐段加速 | ✅ 已有:时间策略 combo → `fit_mode="tempo"` + `max_speed`(`dubbing_config_builder.py:87-97`),`core/dubbing/audio.py:42` `change_tempo` | **不移植**,仅 UI 语义确认 |
| 视频变速 | 逐段 `setpts` 减速 + 多进程裁切拼接,音频超长时拉长视频 | ❌ 无 setpts 相关代码 | **移植(核心)** |
| 语音间隔(毫秒) | 每条配音后插静音,时间轴顺延 | ⚠️ 有"固定停顿"(`pipeline.py:271-283`),但语义不同:它会**忽略 SRT 时间轴**整段重排 | **新增** `subtitle_gap_ms`(保留时间轴的间隔) |
| 嵌入硬字幕 | `subtitles=...:force_style=...` | ✅ core 已有 `add_subtitles` / `add_subtitles_with_style`(`core/utils/video_utils.py:173,528`),配音输出未接线 | **接线**(小) |
| 随机镜像画面 | 场景切点检测 + `hflip=enable='gte(t,a)*lt(t,b)'` | ❌ | **移植**(场景检测用 ffmpeg showinfo,不引 cv2) |
| 随机调色 | 随机 `eq=brightness:contrast:saturation` | ❌ | **移植** |
| 统一画布 | `scale→crop→pad→setsar` | ❌ | **移植**(小) |
| 分离人声背景声 | sherpa-onnx `OfflineSourceSeparation` + UVR onnx 模型按需下载 | ❌(`entities.py:574` 仅有占位字段) | **移植** |
| 重新嵌入背景声 | `amix=inputs=2` + `volume=` | ⚠️ `audio.py:81` `mux_dubbed_audio` 有 amix 混原音,无"纯背景回嵌" | **移植** |
| 背景音短时循环 | concat 循环 / rubberband 拉长 | ❌ | **移植**(简化为 loop) |
| 背景音量 / 额外背景音频 | `volume=0.8` / 额外 BGM amix | ❌ | 随回嵌一并做 |
| 识别说话人 | sherpa-onnx 内置(zh/en)/ ali_CAM / pyannote 三档 | ❌ | **移植(内置 sherpa-onnx 方案)** |
| 仅保留解说员字幕 | `process/narrator_filter.py:255-386` 纯 Python 算法 | ❌ | **移植**(纯算法,直接可测) |
| LLM复核被删字幕 | `process/narrator_llm_judge.py`,openai SDK | ❌,但 LLM 通道完备(`core/llm/client.py:126` `call_llm` + `core/prompts/` 模板机制) | **移植**(复用现有 LLM 通道) |
| 修改硬字幕样式 | 样式对话框 + force_style 引擎 | ✅ 已有 `SubtitleStyleInterface`(`ui/view/subtitle_style_interface.py:127`,主窗口已注册) | **核对打通**配音输出使用样式配置 |
| 输出到.. | `target_dir` 贯穿全流水线 | ⚠️ 配音输出固定写到 `WORK_PATH/dubbing/` 或视频同级 | **新增**输出目录选择(小) |

### 关键基建(可直接复用)

- 进度回调全链路统一:`ProgressCallback = Callable[[int, str], None]`
- 模型按需下载:`core/utils/model_downloader.py` `ModelDownloader`(HF 失败自动回退 hf-mirror)+ `ui/thread/modelscope_download_thread.py` 模板;模型缓存目录 `MODEL_PATH`
- 配置:`qfluentwidgets QConfig` → `AppData/settings.json`,`ui/common/config.py` 加 `ConfigItem` 即持久化
- LLM prompt:`core/prompts/**/*.md` + `get_prompt()`,新增 `.md` 自动被打包 `_datas()` 收集
- ffmpeg/ffprobe:仓库根自带 `ffmpeg.exe`/`ffprobe.exe`,`core/utils/video_utils.py` 有封装惯例
- 配音线程已支持可选 `video_path`(`ui/thread/dubbing_thread.py:24-61`,批量流程自动探测同名视频在用)

### 环境约束(重要)

- **dev venv 无 PySide6**:UI 代码只能 import + 语法检查 + 静态审查,无法实例化冒烟;所有核心逻辑必须 pytest 覆盖,UI 层尽量薄
- 打包 `packaging/app.spec:77` **显式 excludes torch/tensorflow** → 说话人识别/人声分离**禁止引入 torch**(排除 pyannote 方案)
- 新增 pip 依赖需同步:`pyproject.toml` dependencies + `app.spec` hiddenimports
- 新增 `.md` prompt 放 `core/prompts/` 下即可被 spec 自动收集

---

## 2. 关键架构决策

| 决策点 | 选择 | 理由 |
|-------|------|------|
| 说话人识别引擎 | **sherpa-onnx 内置方案**(segmentation + 3dspeaker eres2net(zh)/ nemo titanet(en) onnx,FastClustering) | 纯 ONNX 无 torch,打包友好;pyannote 需 torch+HF token 被否。限制:内置模型仅支持中/英文,文档中标注 |
| 人声分离引擎 | **sherpa-onnx UVR-MDX-NET**(如 `UVR-MDX-NET-Inst_HQ_4.onnx`,~170MB,按需下载到 `MODEL_PATH`) | 与说话人识别共用 sherpa-onnx 运行时,一次引入两处受益 |
| 场景切点检测 | **ffmpeg `select='gt(scene,0.3)',showinfo` 解析日志** | pyVideoTrans 同样支持该路径;不引入 cv2/PySceneDetect |
| 说话人数据格式 | 与字幕平行的 speaker 数组 + sidecar JSON(仿 pyVideoTrans `speaker.json`),**不改动 `ASRDataSeg`** | 避免动字幕核心数据模型 |
| 视频变速音频策略 | 不引入 rubberband;音频侧维持现有 atempo(`change_tempo`),视频侧 setpts 减速兜底 | 减少系统依赖,质量可接受 |
| 语音间隔语义 | 每条配音结束后插入 gap,后续字幕**整体顺延**,导出调整后字幕供烧录/回写,保证音画同步 | 与 pyVideoTrans 一致,避免音画漂移 |
| 功能暴露顺序 | 先做 GUI 配音面板;CLI 参数后置(方案末尾列 TODO) | 控制单阶段范围 |

---

## 3. 总体设计

### 3.1 流水线扩展(在 `DubbingPipeline._run_inner` 前后挂钩)

```
[前置阶段·新]  diarize(可选):  媒体音频 → sherpa-onnx 说话人分离 → speaker.json
[前置阶段·新]  narrator_filter(可选): ASRData + speaker 数组 → 保留解说员 → (可选)LLM 复核恢复误删
─────────────────────────────────────────────────────────────
现有           load_dubbing_segments → _apply_speakers → rewrite → 并行 TTS
[增强]         create_timeline_audio: 支持 subtitle_gap_ms(顺延语义) → 输出调整后 ASRData
[增强]         mux_dubbed_audio: 支持背景音回嵌(instrument+volume+loop)、额外 BGM
─────────────────────────────────────────────────────────────
[后置阶段·新]  video_post(可选,需 video_path):
               1) video_autorate: 逐段 setpts 减速 + 裁切拼接(音频超槽时)
               2) 画面滤镜链: 统一画布 → 随机镜像(场景级)→ 随机调色
               3) 嵌入硬字幕: add_subtitles(+SubtitleStyleInterface 样式配置)
[输出]         支持自定义输出目录
```

进度百分比重映射(现有 2→8→10→88→94→100,插入新阶段后统一调整,UI 不变)。

### 3.2 新增模块清单

| 文件 | 职责 | 阶段 |
|------|------|------|
| `core/dubbing/video_rate.py` | 逐段视频变速:`compute_rate_plan(segments, audio_durations) -> RatePlan`、`apply_video_rate(video, plan, out)`(ffmpeg 裁切 + setpts + concat + tpad 兜底) | 1 |
| `core/dubbing/timeline.py`(或扩展 `audio.py`) | `subtitle_gap_ms` 顺延时间轴 + 返回调整后 ASRData | 1 |
| `core/separation/__init__.py` `core/separation/vocal_separator.py` | sherpa-onnx UVR 人声/背景分离;`separate(audio, work_dir) -> (vocal, instrument)`;模型按需下载 | 2 |
| `core/dubbing/background_mix.py` | 背景回嵌:`mix_background(dubbed, instrument, volume, loop, extra_bgm) -> wav`(ffmpeg amix/volume/aloop) | 2 |
| `core/diarization/__init__.py` `core/diarization/speaker_diarizer.py` | sherpa-onnx 内置说话人分离:`diarize(audio, max_speakers) -> List[DiarSegment]`;模型按需下载 | 3 |
| `core/diarization/assign.py` | `_assign_speakers` 移植:字幕↔说话人区间重叠扫描线 → 平行 speaker 数组 + speaker.json | 3 |
| `core/dubbing/narrator_filter.py` | 解说员判定与过滤(移植 pyVideoTrans `process/narrator_filter.py` 算法,输入改 ASRData+speaker 数组) | 3 |
| `core/dubbing/narrator_llm_judge.py` | LLM 复核误删恢复;复用 `core/llm/client.py` `call_llm` | 3 |
| `core/prompts/review/narrator_restore.md` | 复核 prompt(结构化 JSON 输出 + 校验,仿 `llm_translator._agent_loop`) | 3 |
| `core/utils/video_filters.py` | 滤镜构造器:`build_canvas_filter`、`build_random_mirror_filter(scene_cuts)`、`build_random_color_filter`、`detect_scene_cuts_ffmpeg` | 4 |
| `core/utils/model_urls.py` | 模型 URL 表(移植自 pyVideoTrans `configure/contants.py`,HF + hf-mirror 双源) | 2/3 |

### 3.3 配置项(`ui/common/config.py`,全走 QConfig)

```
"Dubbing" 组: video_autorate(bool,默认False)、subtitle_gap_ms(int 0-2000,默认0)、
              embed_subtitle(OptionsConfigItem: none/hard,默认none)、output_dir(str,默认空=自动)
"BGM" 组:    separate_vocal(bool)、embed_bgm(bool)、bgm_loop(bool,默认True)、
              bgm_volume(RangeConfigItem 0.0-1.0,默认0.8)、extra_bgm_path(str)
"Speaker" 组: enable_diarization(bool)、speaker_count(OptionsConfigItem: 不限/2..6,默认不限)、
              narrator_only(bool)、narrator_llm_review(bool)
"Video" 组:  random_mirror(bool)、random_color(bool)、
              canvas(OptionsConfigItem: off/1080x1920/1920x1080,默认off)
```

### 3.4 UI 变更(`ui/view/dubbing_interface.py`,全部仿现有 speed_layout 模式)

- `params_card` 内新增三个分组行:**对齐控制**(视频变速 switch、语音间隔 spin、嵌入硬字幕 combo)、**背景音**(分离/回嵌/循环 switch + 音量 slider + 额外音频选择)、**说话人**(识别 switch + 数量 combo + 仅解说员 switch + LLM复核 switch)
- 字幕模式卡片增加**可选视频输入**(`DubbingThread` 已支持 `video_path`,主界面目前未暴露)
- 输出目录选择(按钮 + 标签,空=默认)
- 联动:仅解说员依赖识别说话人;LLM复核依赖仅解说员;回嵌依赖分离;硬字幕/视频变速依赖视频输入
- 控件 → `_persist_dubbing_settings` → `dubbing_config_builder.py` 透传 `DubbingConfig`(对应字段扩展 `core/dubbing/models.py`)

---

## 4. 分期实施(每期:Haiku 写码+测试 → Opus 审阅 → 通过后合入)

### 阶段 1 — 对齐控制核心(纯 ffmpeg,无新依赖)
- 任务 1.1:`video_rate.py` 逐段变速 + 单测(rate plan 计算纯函数;ffmpeg 冒烟用仓库根 ffmpeg.exe)
- 任务 1.2:`subtitle_gap_ms` 时间轴顺延 + 调整后 ASRData 导出 + 单测
- 任务 1.3:UI 对齐控制分组 + 视频输入 + 硬字幕 combo 接线 + 配置持久化
- 验收:`pytest tests/test_dubbing/` 全绿;新增 `test_video_rate.py`、`test_timeline_gap.py`

### 阶段 2 — 背景音分离与回嵌
- 任务 2.1:`core/separation/` + sherpa-onnx 接入 + UVR 模型按需下载(`ModelDownloader` 复用)+ `model_urls.py`
- 任务 2.2:`background_mix.py`(volume/loop/额外BGM)+ 集成测试(合成短音频验证时长与音量)
- 任务 2.3:UI 背景音分组 + 配置;`pyproject.toml` 加 `sherpa-onnx`;`app.spec` hiddenimports
- 验收:单测+集成测试绿;分离流程在有模型时端到端可跑(无模型走下载分支,mock 测试)

### 阶段 3 — 说话人识别 + 解说员过滤 + LLM 复核
- 任务 3.1:`core/diarization/` sherpa-onnx 内置模型 + 下载 + `assign.py` 扫描线分配(单测:构造区间验证分配)
- 任务 3.2:`narrator_filter.py` 移植(单测:多说话人/占比边界/语种补救)
- 任务 3.3:`narrator_llm_judge.py` + prompt(mock LLM 测试解析与恢复逻辑)
- 任务 3.4:UI 说话人分组 + 配置 + pipeline 前置阶段挂钩
- 验收:`tests/test_diarization/`、`test_narrator_filter.py`、`test_narrator_llm_judge.py` 绿

### 阶段 4 — 画面滤镜 + 收尾
- 任务 4.1:`video_filters.py`(画布/镜像/调色 + ffmpeg 场景检测)+ 单测(滤镜字符串构造、场景日志解析)
- 任务 4.2:硬字幕样式打通核对(`SubtitleStyleInterface` 配置 → 配音硬字幕输出)
- 任务 4.3:输出目录选择
- 任务 4.4:`app.spec` 最终核对 + 文档(README/使用说明)
- 验收:全量 `uv run pytest` 绿

### 后置 TODO(不在本期)
- CLI 暴露新参数(`cli/commands/dub.py`)
- 更多分离模型/spleeter 备选、pyannote 可选接入(若未来接受 torch)
- 场景检测可选 cv2 加速

---

## 5. 风险与缓解

| 风险 | 缓解 |
|------|------|
| sherpa-onnx API 版本漂移 | `pyproject.toml` 锁定版本;严格照 pyVideoTrans `process/_audio_speakers.py`、`process/_audio_separate.py` 的调用方式移植 |
| UI 无法在 dev 环境冒烟 | UI 层保持薄(仅控件+配置读写);全部逻辑下沉 core 并 pytest 覆盖;交付时注明需真机手验 |
| 模型下载源在国内不可用 | 复用 `ModelDownloader` 的 hf-mirror 回退;URL 表双源 |
| 视频变速后音画同步 | rate plan 与音频时间轴同一数据源;tpad 补帧兜底;集成测试校验总时长差 <50ms |
| 打包体积增长 | sherpa-onnx 约 +60~100MB;模型全部按需下载不入包;torch 继续 excludes |
| 中文路径 | 模型/临时文件一律走 `MODEL_PATH`/`CACHE_PATH`/`WORK_PATH`,已有先例 |

## 6. 工作约定

- 分支:当前 `codex/subtitle-translation-dubbing-alignment-fixes` 有未提交改动;每阶段开独立分支 `feat/align-video-rate`、`feat/bgm-separation`、`feat/speaker-diarization`、`feat/video-filters`,阶段内由 Haiku agent 提交,Opus 审阅后合回
- 每个 Haiku agent 的 prompt 必须包含:本方案对应章节 + 涉及的 文件:行 锚点 + 测试要求 + "dev venv 无 Qt,禁止实例化 UI 控件"约束
- 每个阶段完成定义:测试绿 + Opus 审阅意见闭环 + 配置/文档同步
