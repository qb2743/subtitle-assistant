# 字幕助手 — 协作与测试约定

**产品**：字幕助手 1.0 · **包名**：`videocaptioner`

## 运行

```bash
.venv/Scripts/python -m videocaptioner.ui.main   # GUI
.venv/Scripts/python -m pytest tests/ -q           # 测试
```

## 配置

- 用户数据：`AppData/settings.json`
- GitHub 链接：`videocaptioner/config.py` → `GITHUB_OWNER` / `GITHUB_REPO`

## 文档

- [README.md](README.md) — 用户说明  
- [docs/PROJECT.md](docs/PROJECT.md) — 项目来源与结构  
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — 开发说明  