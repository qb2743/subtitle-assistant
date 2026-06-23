# 配音服务批量处理现状分析

**分析日期**：2026-06-21  
**分析范围**：CLI + GUI 批量处理能力对比

---

## 📊 现状总结

### ✅ CLI 支持情况

**配音命令（`videocaptioner dub`）**：
- ✅ 支持单文件处理
- ❌ **不支持批量处理**（没有 batch 参数）
- 输入：单个字幕文件 `.srt/.ass/.vtt/.json`
- 输出：单个音频/视频文件

**实际用法**：
```bash
# 只能这样单个处理
videocaptioner dub input.srt --preset elevenlabs-multilingual-female
videocaptioner dub subtitle2.srt --preset edge-cn-male

# ❌ 没有批量模式
videocaptioner dub *.srt  # 不支持
```

---

### ✅ GUI 批量处理现状

**现有批量处理页面**（`batch_process_interface.py`）：

#### 支持的任务类型（`BatchTaskType`）
```python
class BatchTaskType(Enum):
    TRANSCRIBE = "批量转录"          # ✅ 支持
    SUBTITLE = "批量字幕"            # ✅ 支持（翻译/优化）
    TRANS_SUB = "转录+字幕"          # ✅ 支持
    FULL_PROCESS = "全流程处理"      # ✅ 支持（转录→字幕→合成视频）
```

#### ❌ **配音不在批量任务类型中**

**证据：**
1. `BatchTaskType` 枚举中没有 `DUBBING` / `DUB` 相关选项
2. `BatchProcessThread` 的任务处理函数只有：
   - `_handle_transcribe_task()`
   - `_handle_subtitle_task()`
   - `_handle_trans_sub_task()`
   - `_handle_full_process_task()`
   - **没有** `_handle_dubbing_task()`

3. UI 任务类型下拉框只显示 4 种任务类型

---

## 🔍 详细对比分析

### 转录（Transcribe）批量能力
| 功能 | CLI | GUI 批量 |
|------|-----|----------|
| 单文件 | ✅ `transcribe video.mp4` | ✅ |
| 多文件 | ❌ 需循环 | ✅ 拖拽多个文件 |
| 进度显示 | ✅ 文本输出 | ✅ 每个文件独立进度条 |
| 并发处理 | ❌ | ✅ 可设置并发数（默认 1） |

### 字幕处理（Subtitle）批量能力
| 功能 | CLI | GUI 批量 |
|------|-----|----------|
| 单文件 | ✅ `subtitle input.srt` | ✅ |
| 多文件 | ❌ 需循环 | ✅ 拖拽多个 SRT |
| 翻译 | ✅ | ✅ |
| 优化 | ✅ | ✅ |

### 配音（Dubbing）批量能力
| 功能 | CLI | GUI 批量 |
|------|-----|----------|
| 单文件 | ✅ `dub input.srt` | ❓ 无独立页面 |
| 多文件 | ❌ **不支持** | ❌ **不支持** |
| 进度显示 | ✅ 文本输出 | - |
| Provider 选择 | ✅ `--preset` | - |

---

## 🎯 缺失功能清单

### 1. CLI 批量配音命令
**不存在：** `videocaptioner dub --batch` 或类似机制

**期望用法**：
```bash
# 方案 A：批量标志
videocaptioner dub --batch folder/*.srt --preset elevenlabs-multilingual-female

# 方案 B：输入目录
videocaptioner dub --input-dir ./subtitles/ --output-dir ./dubbed/
```

### 2. GUI 批量配音界面
**不存在：** 批量处理页面中的"批量配音"任务类型

**期望功能**：
- 任务类型下拉框增加 `DUBBING = "批量配音"`
- 支持拖拽多个 `.srt/.ass/.vtt` 文件
- 统一配置 provider / voice / timing
- 每个文件独立进度条
- 输出 `.mp3` 或 `.mp4`（如果有视频输入）

---

## 🛠️ 技术实现路径

### 方案 A：扩展 GUI 批量处理（推荐）

#### 1. 添加批量配音任务类型
```python
# videocaptioner/core/entities.py
class BatchTaskType(Enum):
    TRANSCRIBE = "批量转录"
    SUBTITLE = "批量字幕"
    TRANS_SUB = "转录+字幕"
    FULL_PROCESS = "全流程处理"
    DUBBING = "批量配音"  # ← 新增
```

#### 2. 实现批量配音线程
```python
# videocaptioner/ui/thread/dubbing_thread.py (新建)
from PyQt5.QtCore import QThread, pyqtSignal
from videocaptioner.core.dubbing import DubbingPipeline, DubbingConfig

class DubbingThread(QThread):
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)
    finished = pyqtSignal(str)  # 输出文件路径
    
    def __init__(self, subtitle_path: str, config: DubbingConfig):
        super().__init__()
        self.subtitle_path = subtitle_path
        self.config = config
    
    def run(self):
        try:
            pipeline = DubbingPipeline(self.config)
            
            # 配音处理
            output = pipeline.run(
                subtitle_path=self.subtitle_path,
                progress_callback=self._on_progress
            )
            
            self.finished.emit(output)
        except Exception as e:
            self.error.emit(str(e))
    
    def _on_progress(self, current, total):
        percent = int((current / total) * 100)
        self.progress.emit(percent, f"配音中 {current}/{total}")
```

#### 3. 在 BatchProcessThread 中添加处理函数
```python
# videocaptioner/ui/thread/batch_process_thread.py
def _process_task(self, batch_task: BatchTask):
    # ... 现有代码 ...
    elif batch_task.task_type == BatchTaskType.DUBBING:
        self._handle_dubbing_task(batch_task)

def _handle_dubbing_task(self, batch_task: BatchTask):
    """处理配音任务"""
    config = self.factory.create_dubbing_config()
    thread = DubbingThread(batch_task.file_path, config)
    batch_task.current_thread = thread
    
    self.threads.append(thread)
    
    thread.progress.connect(
        partial(self._on_progress_wrapper, batch_task)
    )
    thread.error.connect(
        partial(self._on_error_wrapper, batch_task)
    )
    thread.finished.connect(
        partial(self._on_finished_wrapper, batch_task)
    )
    
    thread.start()
```

#### 4. UI 适配
```python
# videocaptioner/ui/view/batch_process_interface.py
def init_ui(self):
    # 任务类型选择
    self.task_type_combo.addItems([
        str(BatchTaskType.TRANSCRIBE),
        str(BatchTaskType.SUBTITLE),
        str(BatchTaskType.DUBBING),  # ← 新增
        str(BatchTaskType.TRANS_SUB),
        str(BatchTaskType.FULL_PROCESS),
    ])
    
    # 任务类型说明
    self.task_type_descriptions[str(BatchTaskType.DUBBING)] = \
        self.tr("为字幕文件生成配音音轨")

def filter_files(self, file_paths, task_type: BatchTaskType):
    # ... 现有代码 ...
    elif task_type == BatchTaskType.DUBBING:
        valid_extensions = {f".{fmt.value}" for fmt in SupportedSubtitleFormats}
    # ...
```

**工作量**：**1-1.5 天**

---

### 方案 B：添加 CLI 批量配音命令（次选）

#### 1. 新建批量命令
```python
# videocaptioner/cli/commands/batch_dub.py (新建)
def run(args: Namespace, config: dict) -> int:
    input_paths = args.inputs  # List[Path]
    output_dir = Path(args.output_dir) if args.output_dir else None
    
    for subtitle_path in input_paths:
        output.info(f"Processing {subtitle_path.name}...")
        
        # 复用单文件 dub 逻辑
        result = dub.run_single(subtitle_path, config, output_dir)
        
        if result != EXIT.SUCCESS:
            output.error(f"Failed: {subtitle_path.name}")
            continue
    
    output.success("All done!")
    return EXIT.SUCCESS
```

#### 2. 注册命令
```python
# videocaptioner/cli/main.py
def _build_batch_dub_parser(subparsers):
    parser = subparsers.add_parser(
        "batch-dub",
        help="Batch dubbing from multiple subtitle files"
    )
    parser.add_argument("inputs", nargs="+", help="Subtitle files")
    parser.add_argument("--output-dir", help="Output directory")
    # ... 复用 dub 的参数 ...
```

**工作量**：**0.5-1 天**

---

## 📋 推荐实现方案

### 优先级排序

1. **🔴 最高优先级：GUI 批量配音**
   - 原因：用户已有批量处理习惯（转录、字幕都在这里）
   - 工作量：1-1.5 天
   - 价值：与现有 UI 一致，学习成本低

2. **🟡 中优先级：配音设置页面**
   - 原因：批量配音需要统一配置 provider
   - 工作量：0.75 天（见 UI_IMPLEMENTATION_PLAN.md）
   - 价值：可视化配置，避免命令行输入

3. **🟢 低优先级：CLI 批量命令**
   - 原因：高级用户可以用 shell 脚本循环
   - 工作量：0.5-1 天
   - 价值：自动化场景

---

## 🚀 实现计划（最小可交付版本）

### 阶段 1：核心功能（1 天）
- [ ] 添加 `BatchTaskType.DUBBING`
- [ ] 创建 `DubbingThread`
- [ ] 实现 `_handle_dubbing_task()`
- [ ] UI 下拉框添加"批量配音"
- [ ] 测试：拖拽 3 个 SRT，配音成功

### 阶段 2：配置增强（0.5 天）
- [ ] 批量配音配置面板（provider/voice 选择）
- [ ] 复用设置页面的配音配置
- [ ] 测试：切换 provider 生效

### 阶段 3：用户体验（0.5 天）
- [ ] 错误提示优化
- [ ] 进度显示细化（当前段/总段数）
- [ ] 输出文件位置提示

**总计：2 天**

---

## ✅ 验收标准

### 功能验收
- [ ] 能拖拽 10+ 个 SRT 到批量处理界面
- [ ] 选择"批量配音"任务类型
- [ ] 每个文件独立进度条显示
- [ ] 配音完成后文件保存在正确位置
- [ ] 支持所有 7 个 provider（edge/gemini/siliconflow/elevenlabs/dots/voxcpm/openai）

### 性能验收
- [ ] 10 个短字幕文件（<50 行）批量配音 <5 分钟（使用 edge）
- [ ] UI 不卡顿
- [ ] 可随时取消任务

### 用户体验验收
- [ ] 任务失败后有明确错误提示
- [ ] 配音参数可批量应用（不用每个文件单独配置）
- [ ] 输出文件命名清晰（`input.srt` → `input.dubbed.mp3`）

---

## 📚 参考实现

### 已有批量任务实现
```
videocaptioner/ui/thread/
├── transcript_thread.py        # 转录任务线程
├── subtitle_thread.py          # 字幕任务线程
└── batch_process_thread.py     # 批量调度器
```

### 配音核心逻辑
```
videocaptioner/core/dubbing/
├── pipeline.py                 # DubbingPipeline 类
├── models.py                   # DubbingConfig
└── presets.py                  # Voice 预设
```

### CLI 单文件配音
```
videocaptioner/cli/commands/dub.py  # 完整实现参考
```

---

## 🎯 总结

### 现状
- ✅ CLI 支持单文件配音（7 个 provider 全可用）
- ✅ GUI 支持批量转录、批量字幕处理
- ❌ **CLI 不支持批量配音**
- ❌ **GUI 不支持批量配音**

### 建议
**优先实现 GUI 批量配音**，因为：
1. 用户已习惯在批量处理页面操作
2. 技术路径清晰（复用现有架构）
3. 工作量可控（1-2 天）
4. 与现有功能一致性好

### 下一步
如果你确认需要批量配音功能，我可以立即开始实现：
1. 修改 `BatchTaskType` 枚举
2. 创建 `DubbingThread`
3. 扩展批量处理界面

需要我现在开始实现吗？
