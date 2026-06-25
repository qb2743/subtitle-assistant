# 不用 gh，推送到 GitHub（qb2743）

## 第一步：网页建空仓库

1. 打开：<https://github.com/new>
2. **Repository name** 填：`subtitle-assistant`
3. 选 **Public**
4. **不要**勾选 “Add a README file” / “Add .gitignore” / “Choose a license”
5. 点 **Create repository**

## 第二步：推送代码

在 PowerShell（项目根目录 `D:\音视频综合助手`）：

```powershell
cd D:\音视频综合助手
.\packaging\scripts\push_github.ps1
```

若已提交过，脚本会直接 `git push`。

## 第三步：登录失败时（没有 gh 很正常）

GitHub **不再支持账号密码推送**，需要 **Personal Access Token (PAT)**：

1. 登录 GitHub → 右上角头像 → **Settings**
2. 左侧最下方 **Developer settings** → **Personal access tokens** → **Tokens (classic)**
3. **Generate new token (classic)**，勾选 **repo**
4. 生成后复制 token（只显示一次）

再执行 `git push -u origin main`，提示时：

- **Username**：`qb2743`
- **Password**：粘贴 **token**（不是 GitHub 登录密码）

可选：安装 [Git Credential Manager](https://github.com/git-ecosystem/git-scm-v2-scalar)（装 Git for Windows 时一般已带），会记住 token。

## 第四步：上传安装包到 Releases

1. 先打安装包（见 [packaging/README.md](../packaging/README.md)）
2. 打开：<https://github.com/qb2743/subtitle-assistant/releases/new>
3. **Tag**：`v1.0.0`
4. **Title**：`字幕助手 1.0.0`
5. 上传文件：`packaging\installer\output\SubtitleAssistant-1.0.0-setup.exe`
6. **Publish release**

## 可选：以后想装 gh

```powershell
winget install GitHub.cli
# 安装后重新打开 PowerShell
gh auth login
```

不装 gh 也可以完成上面全部步骤。