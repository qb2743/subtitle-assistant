# 大模型渠道和翻译提示词对比分析

**分析日期**：2026-06-21  

---

## 📊 **支持的大模型渠道对比**

### 当前项目（音视频综合助手）
```python
class LLMServiceEnum(Enum):
    OPENAI = "OpenAI 兼容"        ✅
    SILICON_CLOUD = "SiliconCloud" ✅
    DEEPSEEK = "DeepSeek"          ✅
    OLLAMA = "Ollama"              ✅
    LM_STUDIO = "LM Studio"        ✅
    GEMINI = "Gemini"              ✅
    CHATGLM = "ChatGLM"            ✅
    
    ❌ 缺少：Anthropic (Claude)
```

### pyvideotrans 项目
```python
# 支持的翻译渠道（通过查看 translator 目录）
- ChatGPT (OpenAI)              ✅
- DeepSeek                      ✅
- Gemini                        ✅
- Azure OpenAI                  ✅
- SiliconFlow                   ✅
- LocalLLM                      ✅
- Minimax                       ✅
- OpenRouter                    ✅
- Huoshan (火山引擎)            ✅
- Xiaomi                        ✅
- ZhipuAI                       ✅
- AI302                         ✅
- OpenAI Compatible             ✅

❌ 也缺少：Anthropic (Claude)
```

**结论**：两个项目都没有内置 Anthropic Claude 支持。

---

## 📝 **翻译提示词对比**

### pyvideotrans 的提示词（chatgpt.txt）

**特点**：
- ✅ 非常详细（88 行）
- ✅ 针对配音场景优化（dubbing-safe pacing）
- ✅ 考虑 TTS 语速问题
- ✅ 多语言特定指南（CJK、RTL、Abugida 脚本）
- ✅ 严格的 1-to-1 block 映射
- ✅ 椭圆号（...）衔接规则
- ✅ XML 标签输出格式 `<TRANSLATE_TEXT>`

**核心原则**：
1. **DUBBING-SAFE PACING**：压缩文本，避免配音超时
2. **ZERO-SHIFT RULE**：不合并、不移动语义元素
3. **ELLIPSIS BRIDGING**：用 `...` 连接分段句子
4. **SPOKEN REGISTER**：口语化、会话风格

**提示词片段**：
```
# ROLE
You are an expert "Multilingual Dubbing Script Adapter" and "SRT Formatter".
Your exact objective is to translate ONLY the SRT subtitles...

# CRITICAL PRINCIPLES
## 1. DUBBING-SAFE PACING & CONCISENESS
- Aggressive Compression: Prioritize core meaning using shortest expression
- Language-Specific Density Guidelines:
  - CJK scripts: 2.5–3.5 syllables per second
  - Alphabetic scripts: contractions and short synonyms

## 2. ABSOLUTE 1-TO-1 BLOCK MAPPING
- Local Semantic Equivalence
- No Word Shifting
- Ellipsis Bridging (...)

## 3. SPOKEN REGISTER & LOCALIZATION
- Everyday, colloquial register
- Match tone (casual/formal)
```

---

### 当前项目的提示词（standard.md）

**特点**：
- ✅ 简洁（22 行）
- ✅ JSON 输出格式
- ✅ 基础翻译规则
- ❌ 没有配音优化
- ❌ 没有语言特定指南
- ❌ 没有椭圆号规则

**提示词内容**：
```markdown
You are a professional subtitle translator specializing in ${target_language}.

<guidelines>
- Translations must be natural, fluent, and easy to understand
- Keep proper nouns or technical terms original
- Use culturally appropriate expressions
- Maintain one-to-one correspondence of subtitle numbering
- If incomplete, do not add ellipsis
</guidelines>

<output_format>
{
  "0": "Translated Subtitle 1",
  "1": "Translated Subtitle 2"
}
</output_format>
```

---

## 🆚 **提示词效果对比**

| 特性 | pyvideotrans | 当前项目 |
|------|-------------|---------|
| **详细程度** | ⭐⭐⭐⭐⭐ (88 行) | ⭐⭐ (22 行) |
| **配音优化** | ✅ 专门优化 TTS 语速 | ❌ 无 |
| **语言特定规则** | ✅ CJK/RTL/Abugida | ❌ 通用规则 |
| **1-to-1 映射** | ✅ 非常严格 | ✅ 有提及 |
| **椭圆号衔接** | ✅ 详细规则 | ❌ 相反（不加省略号） |
| **压缩策略** | ✅ 激进压缩 | ❌ 无 |
| **示例说明** | ✅ 正确/错误示例 | ❌ 无 |
| **自我验证** | ✅ 要求模型自查 | ❌ 无 |
| **输出格式** | XML 标签 | JSON |

---

## 💡 **关键区别分析**

### 1. 配音场景优化
**pyvideotrans**：
```
The translated text will be used for TTS voiceover. 
If too long, audio will play too fast, causing desync.
- CJK scripts: 2.5–3.5 pronounced syllables per second
- Alphabetic scripts: Use contractions
```

**当前项目**：无此优化

### 2. 椭圆号处理
**pyvideotrans**：
```
Block 1: "I think I'm gonna..."
Block 2: "...go to the hospital."
```
用 `...` 连接跨 block 的句子

**当前项目**：
```
If the last sentence is incomplete, do not add ellipsis
```
相反策略！

### 3. 语言密度指南
**pyvideotrans**：
```
- CJK: Target 2.5–3.5 syllables per second
- Thai/Khmer: Avoid long compound words
- RTL: High semantic density
```

**当前项目**：无语言特定规则

---

## 🎯 **推荐改进方案**

### 方案 A：直接采用 pyvideotrans 提示词
**优点**：
- ✅ 配音效果更好
- ✅ 已验证有效
- ✅ 细节完善

**缺点**：
- ⚠️ 需要调整输出格式（XML → JSON）
- ⚠️ 更长的提示词 = 更多 token 消耗

### 方案 B：融合两者优点
**建议**：
1. 保留当前项目的 JSON 输出格式
2. 添加 pyvideotrans 的配音优化规则
3. 添加语言特定密度指南
4. 添加椭圆号衔接规则

### 方案 C：创建两个提示词模式
- `translate/standard.md` - 通用翻译
- `translate/dubbing.md` - 配音优化（采用 pyvideotrans 风格）

---

## 🔧 **添加 Anthropic Claude 支持**

### 需要修改的文件

#### 1. `videocaptioner/core/entities.py`
```python
class LLMServiceEnum(Enum):
    OPENAI = "OpenAI 兼容"
    SILICON_CLOUD = "SiliconCloud"
    DEEPSEEK = "DeepSeek"
    OLLAMA = "Ollama"
    LM_STUDIO = "LM Studio"
    GEMINI = "Gemini"
    CHATGLM = "ChatGLM"
    ANTHROPIC = "Anthropic (Claude)"  # 新增
```

#### 2. `videocaptioner/ui/common/config.py`
```python
# 添加 Anthropic 配置项
anthropic_model = ConfigItem("LLM", "Anthropic_Model", "claude-3-5-sonnet-20241022")
anthropic_api_key = ConfigItem("LLM", "Anthropic_API_Key", "")
anthropic_api_base = ConfigItem("LLM", "Anthropic_API_Base", "https://api.anthropic.com")
```

#### 3. `videocaptioner/core/llm/client.py`
需要检查是否已经支持 Anthropic API 调用。

---

## 📌 **总结与建议**

### 提示词方面
**pyvideotrans 的翻译提示词确实更优秀**，特别是：
1. ✅ 针对配音场景优化
2. ✅ 多语言特定规则
3. ✅ 严格的分段映射
4. ✅ 自我验证机制

**建议**：
- 为配音功能创建专用提示词 `translate/dubbing.md`
- 采用 pyvideotrans 的核心原则，但保持 JSON 输出格式

### Anthropic 支持方面
**两个项目都没有 Anthropic 支持**

**建议添加**：
1. 在 `LLMServiceEnum` 添加 ANTHROPIC 选项
2. 添加配置项
3. 实现 Anthropic API 调用（如果 client.py 尚未支持）

---

**需要我帮你实现这些改进吗？**
1. 添加 Anthropic Claude 支持
2. 创建配音优化的翻译提示词
3. 或两者都做
