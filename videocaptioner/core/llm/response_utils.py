# -*- coding: utf-8 -*-
"""LLM 响应解析工具 —— 兼容非标准 OpenAI 代理的响应格式。

部分 OpenAI 兼容代理（如 grok.469733.xyz、sub.19960426.xyz）在未设置
stream=True 时仍返回 SSE 流式数据，导致 OpenAI SDK 无法解析成标准
ChatCompletion 对象。本模块提供 SSE 解析和响应内容提取的共享逻辑。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Optional, Tuple


def parse_sse_string(text: str) -> Tuple[bool, Optional[str]]:
    """从 SSE 流式字符串中提取拼接内容或错误信息。

    可能包含：
    - 正常内容 chunk：data: {"choices":[{"delta":{"content":"Hello"}}]}
    - 错误事件：event: error / data: {"error":{"message":"...", ...}}
    - 心跳注释：: heartbeat
    - 结束标记：data: [DONE]

    返回：
    - (True, content)  成功提取到有效内容
    - (False, message) 识别为 SSE 但包含错误 / 无有效内容
    - (False, None)    不是 SSE 格式字符串
    """
    if "data:" not in text and "event:" not in text:
        return False, None
    if "chat.completion.chunk" not in text and "event: error" not in text:
        return False, None

    contents: list[str] = []
    errors: list[str] = []
    current_event = None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip().lower()
            continue
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if current_event == "error" or isinstance(data, dict) and "error" in data:
                error_obj = data.get("error", data)
                if isinstance(error_obj, dict):
                    msg = error_obj.get("message", str(error_obj))
                    err_type = error_obj.get("type", "unknown")
                    err_code = error_obj.get("code", "")
                    parts = [p for p in (err_type, err_code, msg) if p]
                    errors.append(": ".join(parts))
                else:
                    errors.append(str(error_obj))
                current_event = None
                continue

            for choice in data.get("choices", []):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta", {})
                if not isinstance(delta, dict):
                    continue
                content = delta.get("content")
                if content:
                    contents.append(str(content))
            current_event = None

    if errors:
        return False, "SSE error: " + "; ".join(errors)
    if contents:
        return True, "".join(contents)

    return False, "SSE stream returned no usable content"


def extract_content_from_response(response) -> Optional[str]:
    """从 LLM 响应中提取文本内容，兼容标准和非标准格式。

    按优先级尝试：
    1. 标准 ChatCompletion 对象（response.choices[0].message.content）
    2. 原始 dict 格式
    3. 纯字符串（直接返回或 SSE 解析）

    返回提取到的内容字符串；无法提取时返回 None。
    对于 SSE 错误响应，返回 None（调用方可通过 get_sse_error 获取错误信息）。
    """
    # 1. 标准 ChatCompletion 对象
    if (
        response
        and hasattr(response, "choices")
        and response.choices
        and len(response.choices) > 0
        and hasattr(response.choices[0], "message")
        and response.choices[0].message
        and response.choices[0].message.content
    ):
        return response.choices[0].message.content

    # 2. 原始 dict 格式
    if isinstance(response, dict):
        choices = response.get("choices")
        if choices and len(choices) > 0:
            message = (
                choices[0].get("message", {})
                if isinstance(choices[0], dict)
                else getattr(choices[0], "message", {})
            )
            if isinstance(message, dict):
                content = message.get("content")
            else:
                content = getattr(message, "content", None)
            if content:
                return str(content).strip()

    # 3. 纯字符串响应
    if isinstance(response, str):
        is_sse, sse_result = parse_sse_string(response)
        if is_sse:
            return sse_result
        if sse_result is not None:
            # SSE 格式正确但包含错误 / 无内容
            return None
        # 非 SSE 字符串，直接返回
        return response.strip()

    # 4. 尝试从响应的字符串表示中解析 SSE 流式数据
    # 某些代理在非流式请求下返回 SSE，SDK 无法解析成标准对象，
    # 但 model_dump() / str() 会包含原始 SSE 数据。
    for text in _response_to_strings(response):
        is_sse, sse_result = parse_sse_string(text)
        if is_sse:
            return sse_result

    return None


def get_sse_error(response) -> Optional[str]:
    """检查响应中是否包含 SSE 错误，返回错误消息或 None。"""
    for text in _response_to_strings(response):
        if isinstance(response, str):
            text = response
        is_sse, sse_result = parse_sse_string(text)
        if not is_sse and sse_result and "SSE error" in sse_result:
            return sse_result
    # 也检查纯字符串 response
    if isinstance(response, str):
        is_sse, sse_result = parse_sse_string(response)
        if not is_sse and sse_result and "SSE error" in sse_result:
            return sse_result
    return None


def _response_to_strings(response) -> list[str]:
    """把 response 转成可能包含 SSE 数据的字符串列表（多种尝试）。"""
    texts: list[str] = []
    # model_dump() 可能返回 dict 或 str
    if hasattr(response, "model_dump"):
        try:
            dump = response.model_dump()
            if isinstance(dump, str):
                texts.append(dump)
            elif isinstance(dump, dict):
                # dict 里的值可能包含 SSE 字符串
                for v in dump.values():
                    if isinstance(v, str) and "data:" in v:
                        texts.append(v)
        except Exception:
            pass
    # str() 兜底
    try:
        s = str(response)
        if s and s != "None":
            texts.append(s)
    except Exception:
        pass
    return texts


def make_pseudo_completion(content: str):
    """构造一个伪 ChatCompletion 对象，兼容下游 response.choices[0].message.content 访问。"""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, index=0, finish_reason="stop")
    return SimpleNamespace(choices=[choice], id="", model="", object="chat.completion")
