# Windows 安装包构建

目标：生成 **不含 Faster-Whisper 程序与 whisper 模型** 的安装包；用户安装后可用 Edge/必剪/云端转录等，需要本地 Faster-Whisper 时在软件内下载。

## 1. 准备精简资源

```powershell
.\packaging\scripts\prepare_slim_resource.ps1
```

将 `resource/assets`、`subtitle_style`、`translations` 复制到 `packaging/slim_resource/`。

可选：把 `ffmpeg.exe` 放到 `packaging/slim_resource/bin/ffmpeg/`（从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) essentials 包解压）。未捆绑时，用户需自行安装 ffmpeg 或放入 `%LOCALAPPDATA%\字幕助手\bin\`。

## 2. PyInstaller 目录版

```powershell
.\packaging\scripts\build_pyinstaller.ps1
```

输出：`dist\字幕助手\`（含 `字幕助手.exe` 与依赖）。

首次请先：

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .
```

## 3. Inno Setup 安装程序

1. 安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)  
2. 用 Inno 打开 `packaging\installer\subtitle_assistant.iss`  
3. 编译 → 得到 `packaging\installer\output\SubtitleAssistant-1.0.0-setup.exe`

修改仓库 URL：编辑 `.iss` 顶部 `#define MyAppURL`。

## 4. 不要打进安装包的内容

| 路径 | 原因 |
|------|------|
| `resource/bin/Faster-Whisper-XXL/` | 体积巨大，应用内下载 |
| `AppData/models/` | 用户本机模型 |
| `.venv/`、`test_outputs/` | 开发产物 |

## 5. 冻结版运行数据目录

打包后（`sys.frozen`）用户数据在：

- Windows：`%LOCALAPPDATA%\字幕助手\`（设置、缓存、模型、bin 下载目录）

与 [`videocaptioner/config.py`](../videocaptioner/config.py) 一致。

## 6. 提交 GitHub 前

见 [docs/RELEASE_AND_GITHUB.md](../docs/RELEASE_AND_GITHUB.md)。