# 更新日志

## 1.4.0

- **新增云端转录渠道 ElevenLabs Scribe（scribe_v2）**：参考 buxuku/SmartSub 的实现重写，支持
  90+ 语种与词级时间戳；由于 Scribe 只返回 `text` + `words`，程序按停顿/标点/长度自动成句。
- **多 API Key 轮询**：与配音面板 ElevenLabs 同一套语义（round-robin 起始游标、429 同 Key 退避、
  其它错误立即换 Key、全部失败才报错）；转录专设 Key 留空时自动复用「配音 → ElevenLabs」的 Key。
- 渠道接入位置：「语音转录」「文稿匹配（DTW 对齐）」「视频对齐」三个面板、全局设置页、
  转录设置弹窗（含「测试连接」）与 CLI（`--asr elevenlabs`、`elevenlabs.api_key/model/api_base`）。
- 云端渠道不再触发 FasterWhisper 的 CUDA 探测与「降级 CPU」提示。
- **版本号统一为单一来源**：窗口标题改为读取 `config.VERSION`，README / docs / 安装脚本同步到 1.4.0
  （此前 `_version.py` 1.3.3、界面标题 v1.0、README 1.0 三处不一致）。

## 1.0.0（字幕助手）

- 产品定名 **字幕助手**，版本 **1.0**；界面与关于文案统一  
- 基于 VideoCaptioner + pyvideotrans + txt2srt 思路整合：配音多引擎、文稿 DTW 对齐、Anthropic/配音提示词等  
- 配音：Edge 切回自动刷新音色；本地 Dots/VoxCPM 项目地址与环境包配置项  
- LLM：写入任务前统一 `resolve_llm_base_url`（OpenAI 兼容可省略 `/v1`）  
- 文档：合并至 `docs/PROJECT.md`、`docs/DEVELOPMENT.md`  

上游 VideoCaptioner 版本线见原仓库 Release。