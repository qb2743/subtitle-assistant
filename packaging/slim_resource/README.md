# 安装包用精简资源（不含 Faster-Whisper / 模型）

将以下内容复制到安装目录的 `resource/`（或由 PyInstaller 打入 `_MEIPASS/resource`）：

| 目录 | 说明 |
|------|------|
| `assets/` | 图标、默认背景、界面资源 |
| `subtitle_style/` | 字幕样式 JSON |
| `translations/` | 界面翻译 `.qm` |

**不要**放入：

- `resource/bin/Faster-Whisper-XXL/`（约 1GB+，用户在软件内按提示下载）
- `AppData/models/` 下任何 whisper 模型

## FFmpeg

安装包**不**捆绑 Faster-Whisper。音视频处理仍需要 **ffmpeg** 在系统 PATH 中，或用户自行将 `ffmpeg.exe` 放到：

`%LOCALAPPDATA%\字幕助手\bin\`（与程序首次运行创建的目录一致）

构建脚本可从 [gyan.dev ffmpeg builds](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip` 中的 `bin/ffmpeg.exe` 放入 `packaging/slim_resource/bin/ffmpeg/`（可选，约 80MB）。