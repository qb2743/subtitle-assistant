<div align="center">

  <h1>字幕助手</h1>
  <p><strong>版本 1.0</strong></p>
  <p>语音识别 · 字幕优化与翻译 · 文稿对齐 · 多引擎配音 · 视频合成</p>

</div>

---

## 项目说明

**字幕助手** 是在以下项目基础上整合改造而成的桌面工具（感谢原作者与社区）：

- **[VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner)** — 主程序架构、转录/字幕/合成与 LLM 能力  
- **[pyvideotrans](https://github.com/jianchang512/pyvideotrans)** — 多 TTS 与配音流程参考  
- **txt2srt-main** — 文稿与时间轴对齐（DTW）思路  

维护者：**qb2743** · 仓库：[GitHub](https://github.com/qb2743/subtitle-assistant)

更多背景见 [docs/PROJECT.md](docs/PROJECT.md)。

---

## 安装

```bash
pip install -e ".[gui]"    # 源码目录下
# 或
pip install videocaptioner
```

免费能力（如必剪转录、必应/谷歌翻译）多数**无需 API Key**。

---

## 桌面版（GUI）

```bash
videocaptioner-gui
# 或
python -m videocaptioner.ui.main
```

窗口标题：**字幕助手 v1.0**。

---

## 命令行（CLI）

```bash
# 转录
videocaptioner transcribe video.mp4 --asr bijian

# 字幕翻译
videocaptioner subtitle input.srt --translator bing --target-language en

# 配音
videocaptioner dub subtitle.srt --provider edge

# 全流程
videocaptioner process video.mp4 --target-language ja

# 配置
videocaptioner config show
```

LLM 优化/大模型翻译需配置 API（OpenAI 兼容 Base URL 可只填主机，程序会自动补 `/v1`）：

```bash
videocaptioner config set llm.api_key <your-key>
videocaptioner config set llm.api_base https://api.openai.com/v1
videocaptioner config set llm.model gpt-4o-mini
```

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/PROJECT.md](docs/PROJECT.md) | 来源、功能、文档索引 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发环境与架构 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 1.0 更新说明 |
| [AGENTS.md](AGENTS.md) | 自动化协作 / 测试约定 |

| [docs/RELEASE_AND_GITHUB.md](docs/RELEASE_AND_GITHUB.md) | 推送到 GitHub、打安装包 |
| [packaging/README.md](packaging/README.md) | Windows exe 安装包构建 |

---

## 许可

GPL-3.0（与上游 VideoCaptioner 一致）。使用与二次分发请遵守许可证条款。
