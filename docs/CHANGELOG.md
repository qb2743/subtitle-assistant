# 更新日志

## 1.0.0（字幕助手）

- 产品定名 **字幕助手**，版本 **1.0**；界面与关于文案统一  
- 基于 VideoCaptioner + pyvideotrans + txt2srt 思路整合：配音多引擎、文稿 DTW 对齐、Anthropic/配音提示词等  
- 配音：Edge 切回自动刷新音色；本地 Dots/VoxCPM 项目地址与环境包配置项  
- LLM：写入任务前统一 `resolve_llm_base_url`（OpenAI 兼容可省略 `/v1`）  
- 文档：合并至 `docs/PROJECT.md`、`docs/DEVELOPMENT.md`  

上游 VideoCaptioner 版本线见原仓库 Release。