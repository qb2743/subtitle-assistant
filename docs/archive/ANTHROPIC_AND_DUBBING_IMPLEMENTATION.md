# Anthropic Claude 和配音提示词实现总结

**完成日期**：2026-06-21  
**状态**：✅ 已完成两项功能

---

## ✅ **已完成的工作**

### 1️⃣ **添加 Anthropic Claude 支持**

#### 修改的文件

**`videocaptioner/core/entities.py`**
```python
class LLMServiceEnum(Enum):
    OPENAI = "OpenAI 兼容"
    SILICON_CLOUD = "SiliconCloud"
    DEEPSEEK = "DeepSeek"
    OLLAMA = "Ollama"
    LM_STUDIO = "LM Studio"
    GEMINI = "Gemini"
    CHATGLM = "ChatGLM"
    ANTHROPIC = "Anthropic (Claude)"  # ✅ 新增
```

**`videocaptioner/ui/common/config.py`**
```python
# 添加 Anthropic 配置项
anthropic_model = ConfigItem("LLM", "Anthropic_Model", "claude-3-5-sonnet-20241022")
anthropic_api_key = ConfigItem("LLM", "Anthropic_API_Key", "")
anthropic_api_base = ConfigItem("LLM", "Anthropic_API_Base", "https://api.anthropic.com")
```

#### 测试结果 ✅
```
LLM Services: ['OpenAI 兼容', 'SiliconCloud', 'DeepSeek', 'Ollama', 
               'LM Studio', 'Gemini', 'ChatGLM', 'Anthropic (Claude)']
Anthropic Model: claude-3-5-sonnet-20241022
Anthropic API Base: https://api.anthropic.com
```

---

### 2️⃣ **创建配音优化翻译提示词**

#### 新文件

**`videocaptioner/core/prompts/translate/dubbing.md`**

**特点**：
- ✅ 融合 pyvideotrans 的配音优化规则
- ✅ 保持当前项目的 JSON 输出格式
- ✅ 89 行详细提示词
- ✅ 语言特定密度指南
- ✅ 严格 1-to-1 映射规则
- ✅ 椭圆号衔接规则

**核心原则**：

1. **DUBBING-SAFE PACING（配音安全节奏）**
   - 激进压缩文本
   - 语言特定密度：
     - CJK: 2.5-3.5 音节/秒
     - 英文：使用缩写
     - 泰文/越南文：避免长复合词
     - RTL（阿拉伯语）：高语义密度

2. **1-TO-1 BLOCK MAPPING（严格映射）**
   - 不合并块
   - 不移动语义元素
   - 保持分段结构

3. **ELLIPSIS BRIDGING（椭圆号衔接）**
   ```
   Block 0: "I think I'm gonna..."
   Block 1: "...go to the hospital."
   ```

4. **SPOKEN REGISTER（口语风格）**
   - 会话风格
   - 使用缩写
   - 中文：成语/俗语/网络用语

**示例**：
```json
输入：
{
  "0": "I think I'm gona",
  "1": "go to the hospital right now."
}

输出（中文）：
{
  "0": "我觉得我要...",
  "1": "...现在就去医院。"
}
```

---

## 📋 **提示词对比**

| 特性 | standard.md | dubbing.md |
|------|------------|-----------|
| 行数 | 22 | 89 |
| 配音优化 | ❌ | ✅ |
| 语言密度规则 | ❌ | ✅ |
| 椭圆号衔接 | ❌ (不加) | ✅ (详细规则) |
| 1-to-1 映射 | ✅ | ✅ (更严格) |
| 压缩策略 | ❌ | ✅ |
| 示例 | ❌ | ✅ |
| 自我验证 | ❌ | ✅ |
| 输出格式 | JSON | JSON |

---

## 🔧 **使用方法**

### 使用标准翻译提示词
```python
from videocaptioner.core.prompts import get_prompt

prompt = get_prompt(
    "translate/standard",
    target_language="简体中文",
    custom_prompt="保持专业术语"
)
```

### 使用配音优化提示词
```python
from videocaptioner.core.prompts import get_prompt

prompt = get_prompt(
    "translate/dubbing",  # ✅ 新增
    target_language="简体中文",
    custom_prompt="保持专业术语"
)
```

### 使用 Anthropic Claude
```python
from videocaptioner.ui.common.config import cfg
from videocaptioner.core.entities import LLMServiceEnum

# 配置 Anthropic
cfg.llm_service.value = LLMServiceEnum.ANTHROPIC
cfg.anthropic_api_key.value = "sk-ant-..."
cfg.anthropic_model.value = "claude-3-5-sonnet-20241022"
cfg.save()
```

---

## ⚠️ **注意事项**

### Anthropic API 调用

**当前状态**：
- ✅ 枚举已添加
- ✅ 配置项已添加
- ⚠️ `client.py` 使用 OpenAI SDK

**Anthropic API 差异**：
1. **不同的 SDK**：需要 `anthropic` 包，不是 `openai`
2. **不同的调用方式**：
   ```python
   # OpenAI
   client.chat.completions.create(...)
   
   # Anthropic
   client.messages.create(...)
   ```
3. **不同的消息格式**：
   - OpenAI: `[{"role": "system", "content": "..."}, ...]`
   - Anthropic: `system="..."`, `messages=[{"role": "user", ...}]`

### 解决方案

**方案 1**：使用 OpenAI 兼容的 Anthropic 端点
- 无需修改代码
- 通过代理服务将 Anthropic API 转换为 OpenAI 格式

**方案 2**：修改 `client.py` 支持多种 SDK
- 检测 LLM service 类型
- 根据类型使用不同的 SDK

**方案 3**：使用 LiteLLM 统一接口
- 安装 `litellm` 包
- 统一多种 LLM API

---

## 🎉 **已完成功能总结**

### Anthropic Claude 支持
- ✅ 枚举定义（LLMServiceEnum.ANTHROPIC）
- ✅ 配置项（model, api_key, api_base）
- ✅ UI 可选择 Anthropic
- ⚠️ API 调用需要进一步集成（见注意事项）

### 配音优化翻译提示词
- ✅ 创建 `translate/dubbing.md`
- ✅ 配音安全节奏规则
- ✅ 语言特定密度指南
- ✅ 椭圆号衔接规则
- ✅ 严格 1-to-1 映射
- ✅ 口语化风格
- ✅ JSON 输出格式
- ✅ 正确/错误示例

---

## 📊 **效果对比预期**

### 使用 standard.md
```json
输入: "I think I'm gonna go to the hospital right now."
输出: {"0": "我认为我现在要去医院。"}
```
- ⚠️ 可能过长
- ⚠️ 单个块，不适合配音

### 使用 dubbing.md
```json
输入: 
{
  "0": "I think I'm gonna",
  "1": "go to the hospital right now."
}

输出:
{
  "0": "我觉得我要...",
  "1": "...现在就去医院。"
}
```
- ✅ 压缩简洁
- ✅ 椭圆号衔接
- ✅ 适合 TTS 语速

---

## 🚀 **下一步（可选）**

### 完善 Anthropic API 调用
如果需要真正调用 Anthropic API（而不是通过 OpenAI 兼容代理），需要：

1. 安装 `anthropic` SDK
2. 修改 `videocaptioner/core/llm/client.py`
3. 添加 Anthropic 特定的调用逻辑

**是否需要我实现完整的 Anthropic API 集成？**
