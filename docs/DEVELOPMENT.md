# 开发说明

## 环境

```bash
cd D:/音视频综合助手   # 或你的克隆路径
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[gui]"
```

运行 GUI：`.venv/Scripts/python -m videocaptioner.ui.main` 或 `videocaptioner-gui`  
测试：`.venv/Scripts/python -m pytest tests/ -q`

详见 [AGENTS.md](../AGENTS.md)。

## 推荐实施顺序（自整合计划）

1. **文稿匹配（DTW）** — `core/alignment`，界面「文稿匹配」  
2. **云端 TTS / 配音** — ElevenLabs、OpenAI、Edge；批量配音  
3. **本地 TTS** — Dots-TTS、VoxCPM（Gradio + 可选环境包下载）  

## 架构要点

- **业务**：`videocaptioner/core/`（asr、translate、dubbing、tts、alignment）  
- **界面**：`videocaptioner/ui/`（qfluentwidgets）  
- **配置**：`AppData/settings.json` + `ui/common/config.py`  
- **TTS**：`BaseTTS` / `GradioBaseTTS`；本地引擎见 `local_tts_defaults.py`  
- **LLM Base URL**：`normalize_base_url` — 仅当 path 为空时补 `/v1`  

## 品牌与版本

- 显示名：**字幕助手 v1.0**（`APP_NAME`、`main_window` 标题）  
- 版本号：`videocaptioner/_version.py` → `1.0.0`  