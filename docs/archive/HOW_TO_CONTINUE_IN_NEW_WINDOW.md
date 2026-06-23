# 如何在新窗口继续工作

## 🎯 快速开始提示词模板

```
我在继续开发"音视频综合助手"项目。

项目路径：D:\音视频综合助手
虚拟环境：.venv\Scripts\python.exe

今天（2026-06-21）已完成21个任务：
- 批量配音系统
- 主页配音面板（左右分栏，两种模式）
- 文稿匹配功能（DTW算法，99语言）
- Anthropic Claude 支持
- 配音优化翻译提示词
- 界面布局调整和优化

现在要实现剩余的3个功能（任务19-21）：
1. 音色自动获取 - 将音色输入框改为下拉选择
2. 音色试听功能 - 添加试听按钮
3. 配音语言选择 - 添加语言下拉框

准备工作已完成：
- 音色数据：videocaptioner/data/voices/edge_tts.json（478行，76语言）
- 加载器：videocaptioner/core/voices/loader.py
- 目标文件：videocaptioner/ui/view/dubbing_interface.py

请帮我实现这三个功能。
```

---

## 📋 详细说明（可选）

如果需要更多上下文，可以补充：

```
详细背景：
- 配音界面在主页第4个标签页（home_interface.py）
- 当前音色是 LineEdit 手动输入
- 需要改成 ComboBox 自动加载
- Edge TTS 有150+音色，需要按语言筛选

技术栈：
- PyQt5 + QFluentWidgets
- 配音引擎：7种（Edge TTS 免费，其他需要API）
- 音色数据结构：{"zh": {"晓晓(Female/CN)": "zh-CN-XiaoxiaoNeural"}}

具体需求：
1. 添加"配音语言"ComboBox（76种语言，中文排第一）
2. 将"音色"改为ComboBox，根据语言和引擎动态加载
3. 添加"试听"按钮，使用Edge TTS生成示例音频播放
```

---

## 🔑 关键信息

### 必须知道的
- **项目路径**：`D:\音视频综合助手`
- **虚拟环境**：`.venv\Scripts\python.exe`
- **待修改文件**：`videocaptioner/ui/view/dubbing_interface.py`
- **数据已准备**：`videocaptioner/data/voices/edge_tts.json` 和 `videocaptioner/core/voices/loader.py`

### 当前状态
- ✅ 21个任务已完成
- ✅ 所有核心功能已实现
- ✅ 界面已优化完成
- 🔄 3个音色相关功能待实现（数据已准备好）

### 任务编号
- Task #19：音色自动获取和选择
- Task #20：添加音色试听功能
- Task #21：添加配音语言选择

---

## 💡 最佳实践提示词

**最简洁版本**（推荐）：
```
继续"音视频综合助手"项目（D:\音视频综合助手）。

今天完成了21个任务，现在要实现任务19-21：
1. 音色自动获取（改LineEdit为ComboBox）
2. 音色试听功能（添加试听按钮）
3. 配音语言选择（添加语言下拉框）

数据已准备：
- videocaptioner/core/voices/loader.py（加载器）
- videocaptioner/data/voices/edge_tts.json（76语言，150+音色）

目标文件：videocaptioner/ui/view/dubbing_interface.py

请实现这三个功能。
```

---

## 🎨 如果需要查看界面

可以说：
```
先让我看看当前的配音界面代码和布局，然后再实现音色功能。
```

---

## ⚡ 快速验证命令

新窗口可以先运行这些命令验证环境：

```bash
cd "D:\音视频综合助手"
.venv\Scripts\python.exe -c "from videocaptioner.core.voices.loader import load_edge_voices; print('Voices loaded:', len(load_edge_voices()), 'languages')"
```

---

## 📚 记忆文件位置

新窗口会自动加载这些记忆：
- `C:\Users\qiu\.claude\projects\D---------\memory\MEMORY.md` - 索引
- `C:\Users\qiu\.claude\projects\D---------\memory\av-assistant-implementation-summary.md` - 详细总结

你只需要说"继续音视频助手项目"，我就能从记忆中了解所有上下文。

---

## ✅ 验证清单

新窗口开始前确认：
- [ ] 记忆文件已更新（av-assistant-implementation-summary.md）
- [ ] 音色数据已复制（edge_tts.json）
- [ ] 加载器已创建（loader.py）
- [ ] 当前代码可正常运行

**所有准备工作已完成！随时可以新开窗口继续。** 🎉
