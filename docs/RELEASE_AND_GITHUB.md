# 发布到 GitHub 与安装包分发

## 你需要提供的信息

在把源码推到 GitHub 并发布安装包前，请确认或发给我以下内容（可逐项回复）：

| 项 | 说明 | 当前占位 |
|----|------|----------|
| **GitHub 用户名** | 已用 `qb2743` | `qb2743` |
| **仓库名** | 远程仓库 URL 最后一段 | `subtitle-assistant`（可改） |
| **仓库是否已创建** | 空仓库即可，本地再 `git remote add` | 需你确认 |
| **安装包 exe 放哪** | 建议 **GitHub Releases** 附件，不进 git | — |
| **GPL-3.0** | 上游 VideoCaptioner 同许可证，保留 `LICENSE` | 需保留版权声明 |
| **作者/署名** | 关于页与 README | `qb2743` |
| **logo.ico** | 由 `packaging/scripts/make_logo_ico.py` 从原项目 `logo.png` 生成 | 已接入 spec / Inno |
| **ffmpeg** | 安装包捆绑 | `prepare_slim_resource.ps1` 从 FW 自带或 gyan.dev 下载 |

若仓库名不是 `subtitle-assistant`，请改这三处一致：

- `videocaptioner/config.py` → `GITHUB_REPO`
- `pyproject.toml` → `[project.urls]`
- `packaging/installer/subtitle_assistant.iss` → `MyAppURL`

## 建议的仓库目录（提交到 GitHub）

```
字幕助手/
├── videocaptioner/          # 源码
├── resource/                # 仅 assets、subtitle_style、translations、fonts（无 Faster-Whisper-XXL）
├── packaging/               # spec、脚本、Inno Setup
├── docs/
├── tests/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── LICENSE                  # GPL-3.0（从上游复制或保留）
└── .gitignore
```

**不要提交**：`.venv/`、`AppData/`、`dist/`、`build/`、`resource/bin/Faster-Whisper-XXL/`、`packaging/output/*.exe`。

## 推送源码（**不需要 gh**）

详见 **[docs/PUSH_WITHOUT_GH.md](PUSH_WITHOUT_GH.md)**（网页建仓库 + `push_github.ps1` + PAT）。

```powershell
# 1. 浏览器打开 https://github.com/new 创建空仓库 subtitle-assistant
# 2. 项目根目录执行：
.\packaging\scripts\push_github.ps1
```

可选：安装 `winget install GitHub.cli` 后可用 `gh auth login`，非必须。

## 本地首次推送到 GitHub（手动）

```bash
git init
git add .
git status   # 确认无 AppData、.venv、大体积 bin
git commit -m "字幕助手 1.0.0 初始发布"
git branch -M main
git remote add origin https://github.com/qb2743/subtitle-assistant.git
git push -u origin main
```

（将 URL 换成你的实际仓库。）

## 构建安装包（在 Windows 开发机）

1. `.\packaging\scripts\build_pyinstaller.ps1`
2. 用 Inno Setup 编译 `packaging\installer\subtitle_assistant.iss`
3. 得到 `packaging\installer\output\SubtitleAssistant-1.0.0-setup.exe`
4. 在 GitHub → **Releases** → New release → 标签 `v1.0.0` → 上传该 exe

## 用户安装后缺什么？

- **Faster-Whisper**：转录设置里下载（ModelScope 链接已在应用内）。
- **ffmpeg**：已打入安装包（`resource/bin/ffmpeg`）；无需用户单独安装。
- **Dots/VoxCPM**：可选，见配音页说明与 GitHub 项目地址。

## 文件夹整理说明

- 根目录历史 `DUBBING_*`、`UI_*` 等已归档到 `docs/archive/`。
- 用户数据仍在本地 `AppData/`（已 gitignore），不随仓库分发。