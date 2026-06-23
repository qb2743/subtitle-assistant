# 字幕助手 — 项目说明与开发文档

**软件名称**：字幕助手  
**版本**：1.0.0  
**包名**（Python）：`videocaptioner`（沿用上游模块名，便于合并与测试）

---

## 项目由来

本仓库是在以下开源项目基础上整合、改造而成的**桌面字幕与配音工具**：

| 来源 | 作用 |
|------|------|
| **[VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)** | 主架构：PyQt5 界面、转录/字幕/合成流水线、LLM 翻译与优化、CLI |
| **[pyvideotrans](https://github.com/jianchang512/pyvideotrans)** | 多 TTS 渠道（ElevenLabs、OpenAI TTS、Dots-TTS、VoxCPM 等）、配音节奏与 API Key 轮询等思路 |
| **txt2srt-main** | 文稿与时间轴对齐（DTW 等算法思路，已接入 `core/alignment`） |

感谢上述作者与社区。本发行版由 **qb2743** 维护，产品名定为 **「字幕助手」1.0**。

---

## 功能概览（1.0）

- **转录**：Faster Whisper、Whisper API、必剪/剪映等  
- **字幕**：断句、LLM 优化与翻译（含配音向提示词）、批量处理  
- **文稿匹配**：用户文稿 + ASR 时间轴 DTW 对齐  
- **配音**：Edge / ElevenLabs / OpenAI / 本地 Dots-TTS、VoxCPM（克隆参考音频）  
- **合成**：软/硬字幕、样式与圆角背景等  

详细使用见根目录 [README.md](../README.md)。

---

## 仓库文档结构

| 路径 | 说明 |
|------|------|
| [README.md](../README.md) | 用户向：安装、CLI、GUI、配置 |
| [AGENTS.md](../AGENTS.md) | 给 AI/协作者的运行与测试约定 |
| [docs/DEVELOPMENT.md](DEVELOPMENT.md) | 开发环境、阶段计划、架构备注 |
| [docs/CHANGELOG.md](CHANGELOG.md) | 1.0 相对上游的主要改动摘要 |
| [docs/PACKAGING.md](PACKAGING.md) | Windows 安装包构建 |
| [docs/RELEASE_AND_GITHUB.md](RELEASE_AND_GITHUB.md) | 推 GitHub、Release、需你提供的信息 |

根目录下大量 `DUBBING_*`、`UI_*` 等 `.md` 已迁入 `docs/archive/`，避免重复维护。

---

## GitHub

请在 [`videocaptioner/config.py`](../videocaptioner/config.py) 中修改：

- `GITHUB_OWNER` / `GITHUB_REPO`  
- 对应 `HELP_URL`、`RELEASE_URL`、`FEEDBACK_URL`

当前：`https://github.com/qb2743/subtitle-assistant`

---

## 许可

继承上游 **GPL-3.0**（见 `pyproject.toml`）。分发与修改请遵守许可证及上游版权声明。