# 快速开始指南

**最后更新**：2026-06-21

---

## ✅ 你现在拥有的文档

| 文档 | 用途 | 优先级 |
|------|------|--------|
| [README.md](./README.md) | 总览和导航 | ⭐⭐⭐ 必读 |
| [ADDITIONAL_REQUIREMENTS.md](./ADDITIONAL_REQUIREMENTS.md) | 补充需求（停顿+轮询） | ⭐⭐⭐ 必读 |
| [EXECUTION_STEPS.md](./EXECUTION_STEPS.md) | 执行步骤（分阶段） | ⭐⭐⭐ 必读 |
| [tts_architecture_comparison.md](./tts_architecture_comparison.md) | TTS 架构对比 | ⭐⭐ 推荐 |
| [code_based_optimization.md](./code_based_optimization.md) | 代码分析和优化 | ⭐⭐ 推荐 |
| [implementation_plan_optimized.md](./implementation_plan_optimized.md) | 详细实施计划 | ⭐ 参考 |

---

## 🎯 核心功能清单

### 已明确的需求：

#### 1. TTS 引擎集成
- ✅ ElevenLabs（云端）+ API Key 轮询 ⭐⭐⭐
- ✅ OpenAI TTS（已有，需暴露到 UI）
- ⚪ Dots-TTS（本地，可选）
- ⚪ VoxCPM（本地，可选）

#### 2. 文稿匹配（DTW）
- ✅ 核心算法移植
- ✅ UI 界面
- ✅ 支持中英文

#### 3. 配音增强功能
- ✅ 固定停顿控制 ⭐⭐

---

## 📊 工作量总览

| 功能 | 工作量 | 累计 |
|------|--------|------|
| ElevenLabs + API 轮询 | 1.5 天 | 1.5 天 |
| 固定停顿功能 | 1 天 | 2.5 天 |
| DTW 文稿匹配 | 1.5-2 天 | 4-4.5 天 |
| 本地 TTS（可选） | 3-4 天 | 7-8.5 天 |
| 集成测试 | 2 天 | 9-10.5 天 |
| **总计** | - | **9.5-11.5 天** |

---

## 🚀 立即开始

### 方式一：完整执行（推荐）

```bash
# 复制以下命令到对话框
/plan 实现 VideoCaptioner 的 ElevenLabs TTS 集成，包括：
1. 使用 elevenlabs 官方 SDK
2. 支持多个 API Key 轮询（Round-Robin）
3. 支持音色选择和参数配置
4. 在 core/speech/providers.py 中实现 ElevenLabsSpeechSynthesizer
```

### 方式二：分步执行

#### 第 1 步：ElevenLabs TTS
```bash
/plan 在 VideoCaptioner 的 core/speech/providers.py 中添加 ElevenLabsSpeechSynthesizer，
使用 elevenlabs SDK，支持 API Key 轮询和音色选择
```

#### 第 2 步：固定停顿
```bash
/plan 为 VideoCaptioner 的配音功能添加固定停顿控制，
参考 pyvideotrans 的实现，在 core/dubbing/pipeline.py 中添加逻辑
```

#### 第 3 步：DTW 文稿匹配
```bash
/plan 从 txt2srt 移植 DTW 文稿匹配算法到 VideoCaptioner，
新建 core/alignment/ 模块，实现 align_text_to_asr 函数
```

---

## ⚠️ 执行前检查清单

- [ ] 已阅读 README.md 了解全貌
- [ ] 已阅读 ADDITIONAL_REQUIREMENTS.md 了解新需求
- [ ] 已确认三个项目路径可访问：
  - D:\VideoCaptioner-src
  - D:\pyvideotrans-src
  - D:\txt2srt-main
- [ ] 准备好测试素材（可选）：
  - 5-10 分钟视频 + 对应文稿
- [ ] 确认 Python 环境 >=3.10

---

## 📞 关键决策点

### 在开始前需要确认：

#### 1. 功能优先级
**问题**：是否需要本地 TTS（Dots-TTS、VoxCPM）？

- [ ] **只做云端**（ElevenLabs + OpenAI）- 4.5 天
- [ ] **全部做**（含本地 TTS）- 9.5-11.5 天

**建议**：先做云端，测试通过后再考虑本地 TTS

---

#### 2. UI 优先级
**问题**：UI 界面何时做？

- [ ] **核心逻辑优先**（先实现功能，UI 后补）
- [ ] **同步开发**（逻辑+UI 一起做）

**建议**：核心逻辑优先，确保功能可用

---

#### 3. 测试数据
**问题**：是否有现成的测试素材？

- [ ] **有**（视频 + 文稿）→ 可以立即测试 DTW
- [ ] **没有**（后续准备）→ 先做 TTS，DTW 暂缓

---

## 🎯 推荐的执行路径

### 路径 A：快速验证（4.5 天）
```
Day 1-1.5: ElevenLabs + API 轮询
Day 2.5-3: 固定停顿功能
Day 3.5-4: DTW 文稿匹配（如果有测试数据）
Day 4.5: 集成测试
```

### 路径 B：完整实现（9.5-11.5 天）
```
Day 1-1.5: ElevenLabs + API 轮询
Day 2.5-3: 固定停顿功能
Day 3.5-5: DTW 文稿匹配 + UI
Day 5-8.5: 本地 TTS（Dots-TTS + VoxCPM）
Day 8.5-10.5: 集成测试 + 文档
```

---

## 📝 开始执行

### 准备好了就说：

```
我准备好了，我们从 ElevenLabs TTS 开始
```

或者直接复制命令：

```
/plan 实现 VideoCaptioner 的 ElevenLabs TTS，
包括 API Key 轮询、音色选择，在 core/speech/providers.py 中实现
```

---

**祝顺利！有任何问题随时提出** 🚀
