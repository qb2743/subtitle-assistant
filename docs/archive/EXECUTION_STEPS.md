# 执行步骤指南

**推荐使用 Plan Mode 执行，分 3 个阶段**

---

## 🎯 阶段一：ElevenLabs TTS（配音专用）⭐ 优先

### 预计时间：0.5-1 天
### 目标：让用户能在配音中使用 ElevenLabs

### 启动命令：
```
/plan 在 VideoCaptioner 的 core/speech/providers.py 中添加 ElevenLabsSpeechSynthesizer，
使用 elevenlabs 官方 SDK，支持音色选择和参数配置
```

### 详细任务：
1. 安装依赖：`elevenlabs>=1.0.0`
2. 查看现有 providers 的实现模式
3. 实现 `ElevenLabsSpeechSynthesizer` 类
4. 在 `create_speech_synthesizer` 中注册
5. 编写单元测试
6. 测试配音管线集成

### 验收标准：
- [ ] 能在配音管线中选择 ElevenLabs
- [ ] 支持 API Key 配置
- [ ] 支持 Voice ID 选择
- [ ] 音频输出正常

---

## 🎯 阶段二：DTW 文稿匹配

### 预计时间：1.5-2 天
### 目标：用户能上传视频+文稿，生成时间戳准确的字幕

### 启动命令：
```
/plan 从 txt2srt 项目移植 DTW 文稿匹配算法到 VideoCaptioner，
新建 core/alignment/ 模块，实现 align_text_to_asr 函数
```

### 详细任务：
1. 安装依赖：`dtw-python`, `jieba`
2. 新建 `core/alignment/dtw_aligner.py`
3. 移植 `match_user_text_to_timestamps` 函数
4. 实现 `align_text_to_asr` 适配器（ASRData ↔ txt2srt 格式）
5. 编写单元测试（测试数据：已知视频+文稿）
6. UI 界面（可选，或下个阶段做）

### 验收标准：
- [ ] 对齐准确率 >85%（人工抽查）
- [ ] 处理速度：5 分钟视频 <30 秒
- [ ] 支持中英文

---

## 🎯 阶段三：本地 TTS（可选）

### 预计时间：3-4 天
### 目标：支持 Dots-TTS 和 VoxCPM 本地服务

### 启动命令：
```
/plan 在 VideoCaptioner 的 core/tts/ 中实现 GradioBaseTTS 基类，
然后实现 DotsTTS 和 VoxCPMTTS，支持本地服务自动启动和音色克隆
```

### 详细任务：
1. 移植 pyvideotrans 的 `GradioBase` 逻辑
2. 新建 `core/tts/gradio_base.py`
3. 实现 `DotsTTS`（服务启动 + gradio_client）
4. 实现 `VoxCPMTTS`（音色克隆）
5. UI 配置（服务路径、启动脚本）
6. 集成测试

### 验收标准：
- [ ] 服务能自动启动（或显示清晰错误）
- [ ] 首次下载成功率 >95%
- [ ] VoxCPM 音色克隆功能正常

---

## 🚀 快速启动（复制粘贴）

### 如果只想快速看到效果：
```
/plan 实现 ElevenLabs TTS（配音专用），
在 VideoCaptioner 的 core/speech/providers.py 中添加 ElevenLabsSpeechSynthesizer
```

### 如果想完整实现：
```
/plan 按照 implementation_plan_optimized.md 执行完整计划，
分 3 个阶段：ElevenLabs → DTW 文稿匹配 → 本地 TTS
```

---

## ⚠️ 重要提示

### 执行前准备：
1. ✅ 确认 VideoCaptioner 项目路径正确
2. ✅ 准备测试素材（视频 + 文稿）
3. ✅ 确认 Python 环境（>=3.10）

### 测试素材准备：
```
测试文件清单：
- test_video.mp4（5-10 分钟中文视频）
- test_transcript.txt（对应的正确文稿）
- （可选）test_video_en.mp4 + test_transcript_en.txt
```

### 关键决策点：
- [ ] 是否需要本地 TTS？（如果只用云端 API，可跳过阶段三）
- [ ] UI 界面优先级？（核心逻辑先行，UI 可以后补）

---

## 📞 遇到问题？

### 常见问题：
1. **依赖安装失败** → 检查 Python 版本和网络
2. **服务启动失败** → 查看错误日志，检查端口占用
3. **DTW 准确率低** → 检查 ASR 质量，调整匹配参数

### 调试建议：
- 每个阶段完成后立即测试
- 保存测试日志
- 发现问题及时反馈
