"""解说字幕删除明细的 LLM 二级复核(port of pyVideoTrans ``narrator_llm_judge.py``)。

从「解说员过滤」删掉的字幕里,用 LLM 复核哪些其实是解说员误删,返回要恢复的
(dropped 列表)下标。pyVideoTrans 参照点:``videotrans/process/narrator_llm_judge.py``
(``SYSTEM_PROMPT`` / ``build_judge_user_prompt`` / ``parse_judge_response`` /
 ``pick_restore_indices``)。

数据模型适配:
- 入参为 ``DubbingSegment`` 列表,时间戳 ``start_ms/end_ms`` 单位为**毫秒**,展示时
  转为 ``mm:ss.cc``(如 83450ms -> "01:23.45";非法/缺失显示 "?")。
- LLM 通道复用 ``core/llm/client.call_llm``(项目统一 LLM 通道);prompt 走
  ``core/prompts.get_prompt("review/narrator_restore")`` 模板机制。
- LLM 配置(api_key/api_base/model)由调用方经 ``llm_fields`` 传入(与配音改写
  ``rewriter.py`` 复用同一组字段,复用 ``DubbingConfig.llm_api_key/llm_api_base/llm_model``)。
  因 ``call_llm`` 走 env-var 单例 client,调用前按 ``llm_fields`` 临时设置环境变量。
- JSON 解析 + 校验失败重试 1 次,仍失败返回空列表(不阻塞主流程)。
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable, List, Optional

from videocaptioner.core.llm.client import call_llm
from videocaptioner.core.prompts import get_prompt
from videocaptioner.core.utils.logger import setup_logger

from .models import DubbingSegment

logger = setup_logger("narrator_llm_judge")

_LABEL_WHITELIST = frozenset({"narrator", "dialogue", "unsure"})

_STRUCTURED_TEMPERATURE = 0.2

# 常见推理模型的思考块包裹格式
_THINKING_BLOCKS = (
    re.compile(r"<thinking>.*?</thinking>", re.S | re.I),
    re.compile(r"thinking\b.*?/thinking", re.S | re.I),
)


def _fmt_ms(value) -> str:
    """毫秒时间戳 → 'mm:ss.cc'(如 83450 -> '01:23.45')。非法/缺失 → '?'。"""
    if isinstance(value, bool):
        return "?"
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return "?"
    if ms < 0:
        return "?"
    total_cs = int(round(ms / 10))          # 1/100 秒
    minutes, rem = divmod(total_cs, 6000)   # 每分 6000 厘秒
    secs, centis = divmod(rem, 100)
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"


def build_judge_user_prompt(
    items: list[dict],
    *,
    narrator_hint: Optional[str] = None,
    style_samples: Optional[list[str]] = None,
) -> str:
    """把待复核字幕列表拼成发给 LLM 的 user 消息。

    items: [{i, start, end, speaker_id, text}],start/end 单位**毫秒**,展示时转为
            `mm:ss.cc`(如 83450ms -> "01:23.45";非法/缺失显示 "?")。
    输出结构(\n 连接):
    - narrator_hint 非空 → 首行「主说话人(时长最长,仅供参考): {narrator_hint}」
    - style_samples 非空 → 一行「已判定为解说的样例(风格参考):」+ 每条「  · {text}」
      (最多取前 8 条)
    - 空行
    - 「待判定字幕(按序号):」
    - 每条一行:「[{i}] t={start}-{end} speaker={speaker_id或?} | {text}」
      (text 内换行替换为空格、strip)
    - 空行 + 「请输出 JSON 数组。」
    """
    lines: list[str] = []
    if narrator_hint:
        lines.append(f"主说话人(时长最长,仅供参考): {narrator_hint}")
    if style_samples:
        lines.append("已判定为解说的样例(风格参考):")
        for t in list(style_samples)[:8]:
            lines.append(f"  · {str(t).strip()}")
    lines.append("")
    lines.append("待判定字幕(按序号):")
    for it in items:
        i = it.get("i")
        start = _fmt_ms(it.get("start"))
        end = _fmt_ms(it.get("end"))
        sid = it.get("speaker_id")
        if sid is None or (isinstance(sid, str) and not sid.strip()):
            speaker = "?"
        else:
            speaker = str(sid).strip() or "?"
        text = str(it.get("text") or "").strip().replace("\n", " ").replace("\r", " ")
        lines.append(f"[{i}] t={start}-{end} speaker={speaker} | {text}")
    lines.append("")
    lines.append("请输出 JSON 数组。")
    return "\n".join(lines)


def parse_judge_response(raw: str, expected_ids: List[int]) -> dict[int, dict]:
    """容错解析模型输出 → {i: {"label": "narrator"|"dialogue"|"unsure", "reason": str}}。

    容错规则(按序):
    - raw 为 None/空串/纯空白 → {}
    - 先移除 thinking... 响应段(re.S|re.I):兼容 <thinking>...</thinking>、
      [thinking]...[/thinking]、thinking ... /thinking 等常见思考块包裹
    - 移除 ```json / ``` 代码围栏
    - 截取首个 '[' 到末个 ']' 之间的子串再 json.loads;解析失败 → {}
    - 数组元素非 dict、缺 i、i 不可转 int、i 不在 expected_ids → 跳过该条
    - label 不在 {'narrator','dialogue','unsure'}(先 lower strip)→ 'unsure'
    - reason 缺失/非 str → ''
    """
    if raw is None:
        return {}
    text = str(raw)
    if not text.strip():
        return {}

    # 移除思考块
    for pat in _THINKING_BLOCKS:
        text = pat.sub("", text)
    # 移除 ```json / ``` 代码围栏
    text = re.sub(r"```(?:json)?", "", text, flags=re.I)
    # 截取首个 '[' 到末个 ']' 之间的子串
    first = text.find("[")
    last = text.rfind("]")
    if first < 0 or last < 0 or last <= first:
        return {}
    body = text[first : last + 1]
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}

    expected = set(expected_ids)
    result: dict[int, dict] = {}
    for elem in data:
        if not isinstance(elem, dict):
            continue
        k = elem.get("i")
        if k is None or isinstance(k, bool):
            continue
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        if i not in expected:
            continue
        label = str(elem.get("label") or "").strip().lower()
        if label not in _LABEL_WHITELIST:
            label = "unsure"
        reason = elem.get("reason")
        if not isinstance(reason, str):
            reason = ""
        result[i] = {"label": label, "reason": reason}
    return result


def pick_restore_indices(
    judged: dict[int, dict], *, restore_unsure: bool = False
) -> List[int]:
    """从复核结果中挑出要恢复的条目下标(升序)。

    label == 'narrator' → 恢复;restore_unsure=True 时 'unsure' 一并恢复。
    """
    restore = []
    for i, item in judged.items():
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().lower()
        if label == "narrator" or (restore_unsure and label == "unsure"):
            restore.append(i)
    return sorted(restore)


def judge_dropped(
    kept_segments: List[DubbingSegment],
    dropped_segments: List[DubbingSegment],
    llm_fields: tuple[str, str, str],
    progress: Optional[Callable[[int, str], None]] = None,
    details_callback: Optional[Callable[[dict[int, dict]], None]] = None,
) -> List[int]:
    """LLM 复核被删字幕,返回要恢复的 dropped 列表下标(升序)。

    Args:
        kept_segments: 解说员过滤后保留的字幕(用作风格样例与主说话人提示)。
        dropped_segments: 被删的字幕,复核对它逐条判定。
        llm_fields: ``(api_key, api_base, model)``,复用配音改写(rewriter)的同一组
            LLM 字段(DubbingConfig.llm_api_key/llm_api_base/llm_model)。
        progress: 可选的 ``(percent, message)`` 进度回调。
        details_callback: 可选回调，接收每条字幕的 AI 标签与原因，供人工复核表展示。

    Returns:
        要恢复的 dropped 下标(升序)。LLM 调用/解析失败时返回空列表,不抛错
        (不阻塞主流程)。
    """
    cb = progress or (lambda _p, _s: None)
    if not dropped_segments:
        return []
    if not (llm_fields and llm_fields[0] and llm_fields[1] and llm_fields[2]):
        logger.warning("LLM 复核未配置 api_key/api_base/model,跳过")
        return []

    api_key, api_base, model = llm_fields

    # 构造 items(下标为 dropped 列表下标)。
    items = [
        {
            "i": idx,
            "start": seg.start_ms,
            "end": seg.end_ms,
            # 说话人标签仅作参考;若为默认/空则留空,由 prompt 显示为 "?"。
            "speaker_id": seg.speaker if seg.speaker and seg.speaker != "default" else None,
            "text": seg.text,
        }
        for idx, seg in enumerate(dropped_segments)
    ]

    narrator_hint = "；".join(seg.text for seg in kept_segments[:3]) or None
    style_samples = [seg.text for seg in kept_segments]

    user_prompt = build_judge_user_prompt(
        items, narrator_hint=narrator_hint, style_samples=style_samples
    )
    system_prompt = get_prompt("review/narrator_restore")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # call_llm 走 env-var 单例,调用前临时按 llm_fields 设置环境变量。
    saved = {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
    }
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = api_base
    try:
        expected_ids = [it["i"] for it in items]
        for attempt in range(2):  # 解析失败重试 1 次
            cb(0, f"LLM 复核被删字幕(尝试 {attempt + 1}/2)...")
            try:
                response = call_llm(
                    messages=messages,
                    model=model,
                    temperature=_STRUCTURED_TEMPERATURE,
                )
                content = response.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 复核调用失败(第 %d 次): %s", attempt + 1, exc)
                if attempt == 1:
                    return []
                continue

            judged = parse_judge_response(content, expected_ids)
            if not judged:
                # 解析失败/无有效条目 → 重试一次(带纠错提示)。
                if attempt == 1:
                    return []
                messages = messages + [
                    {
                        "role": "assistant",
                        "content": content or "{}",
                    },
                    {
                        "role": "user",
                        "content": (
                            "错误:无法解析你的输出。请严格输出覆盖每个 i 的 JSON 数组,"
                            "格式 [{\"i\":0,\"label\":\"narrator\",\"reason\":\"...\"}, ...]。"
                        ),
                    },
                ]
                continue
            if details_callback:
                details_callback(judged)
            cb(100, "LLM 复核完成")
            return pick_restore_indices(judged)
    finally:
        # 恢复环境变量(避免污染并发的其它 LLM 调用)。
        for var, val in saved.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val

    return []
