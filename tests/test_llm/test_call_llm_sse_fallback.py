"""LLM call_llm SSE fallback 测试。

验证当 OpenAI SDK 无法将 SSE 响应解析为标准 ChatCompletion 时，
call_llm 能从原始响应数据中提取 SSE 内容并返回伪 ChatCompletion。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from videocaptioner.core.llm.response_utils import (
    extract_content_from_response,
    parse_sse_string,
    make_pseudo_completion,
)


SSE_RESPONSE_WITH_CONTENT = """\
: heartbeat

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"Thinking about your request\\n"}}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","content":"他说"}}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","content":"","finish_reason":"stop"}}]}

data: [DONE]
"""


class FakeEmptyResponse:
    """模拟 SDK 解析 SSE 失败后返回的空 ChatCompletion 对象。

    model_dump() 返回包含原始 SSE 数据的 dict（某些 SDK 版本会这样）。
    choices 存在但 message.content 为空。
    """
    def __init__(self, raw_sse: str):
        self.choices = [SimpleNamespace(
            index=0,
            message=SimpleNamespace(content="", role="assistant"),
            finish_reason=None,
        )]
        self.id = ""
        self.model = "grok-4.3-fast"
        self._raw = raw_sse

    def model_dump(self):
        return {"raw": self._raw}


def test_extract_content_from_sse_response():
    """从 SDK 无法解析的 SSE 响应中提取内容。"""
    response = FakeEmptyResponse(SSE_RESPONSE_WITH_CONTENT)
    content = extract_content_from_response(response)
    assert content == "他说"


def test_make_pseudo_completion_has_correct_shape():
    """伪 ChatCompletion 应兼容 choices[0].message.content 访问。"""
    pseudo = make_pseudo_completion("你好")
    assert pseudo.choices[0].message.content == "你好"
    assert pseudo.choices[0].finish_reason == "stop"


def test_call_llm_sse_fallback(monkeypatch):
    """call_llm 在标准解析失败时应通过 SSE fallback 提取内容。"""
    # 禁用缓存
    monkeypatch.setattr(
        "videocaptioner.core.llm.client.get_llm_cache",
        lambda: None,
    )
    # 重新 import 以使缓存 mock 生效
    import importlib
    import videocaptioner.core.llm.client as client_mod
    importlib.reload(client_mod)

    fake_response = FakeEmptyResponse(SSE_RESPONSE_WITH_CONTENT)
    monkeypatch.setattr(
        client_mod, "_call_llm_api",
        lambda *args, **kwargs: fake_response,
    )

    response = client_mod.call_llm(
        messages=[{"role": "user", "content": "hi"}],
        model="grok-4.3-fast",
    )
    assert response.choices[0].message.content == "他说"


def test_call_llm_real_empty_response_raises(monkeypatch):
    """真正空响应（无 SSE 数据）应抛 ValueError。"""
    import importlib
    import videocaptioner.core.llm.client as client_mod
    importlib.reload(client_mod)

    monkeypatch.setattr(
        client_mod, "_call_llm_api",
        lambda *args, **kwargs: SimpleNamespace(choices=[], model_dump=lambda: {}),
    )

    with pytest.raises(ValueError, match="empty choices or content"):
        client_mod.call_llm(
            messages=[{"role": "user", "content": "hi"}],
            model="fake",
        )
