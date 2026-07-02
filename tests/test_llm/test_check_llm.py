"""LLM 连接测试单元测试。"""

from types import SimpleNamespace

import pytest

from videocaptioner.core.llm.check_llm import check_llm_connection, _extract_response_content, _parse_sse_string


class FakeChatCompletions:
    """返回指定 response 的 mock chat.completions.create"""

    def __init__(self, response):
        self._response = response

    def create(self, **kwargs):
        return self._response


class FakeOpenAIClient:
    """mock openai.OpenAI 返回 FakeChatCompletions"""

    def __init__(self, response):
        self.chat = SimpleNamespace(completions=FakeChatCompletions(response))


class FakeChoice:
    def __init__(self, content):
        self.message = SimpleNamespace(content=content)


class FakeChatCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


@pytest.mark.parametrize("response", [
    FakeChatCompletion("Hello"),
    {"choices": [{"message": {"content": "Hello"}}]},
    "Hello",
    "  Hello  ",
])
def test_check_llm_connection_accepts_various_response_formats(monkeypatch, response):
    """连接测试应兼容标准 ChatCompletion、dict、字符串等多种返回格式。"""
    monkeypatch.setattr(
        "videocaptioner.core.llm.check_llm.openai.OpenAI",
        lambda *args, **kwargs: FakeOpenAIClient(response),
    )
    ok, msg = check_llm_connection("http://fake/v1", "sk-fake", "gpt-4")
    assert ok is True
    assert msg == "Hello"


def test_check_llm_connection_rejects_empty_response(monkeypatch):
    """无法提取内容时应返回失败而不是抛异常。"""
    monkeypatch.setattr(
        "videocaptioner.core.llm.check_llm.openai.OpenAI",
        lambda *args, **kwargs: FakeOpenAIClient({}),
    )
    ok, msg = check_llm_connection("http://fake/v1", "sk-fake", "gpt-4")
    assert ok is False
    assert "Invalid API response" in msg


def test_extract_response_content_raises_on_unsupported():
    """无法识别的响应类型抛出 ValueError。"""
    with pytest.raises(ValueError):
        _extract_response_content(123)


SSE_RESPONSE = """\
: heartbeat

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"Thinking about your request\\n"}}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"}}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"grok-4.3-fast","choices":[{"index":0,"delta":{"role":"assistant","content":"","finish_reason":"stop"}}]}

data: [DONE]
"""


def test_parse_sse_string_extracts_concatenated_content():
    """SSE 流式字符串应被解析并拼接 delta.content。"""
    ok, content = _parse_sse_string(SSE_RESPONSE)
    assert ok is True
    assert content == "Hello"


SSE_ERROR_RESPONSE = """\
: heartbeat

: heartbeat

event: error
data: {"error":{"message":"Console API returned 429","type":"upstream_error","code":"upstream_error"}}

data: [DONE]
"""


def test_parse_sse_string_detects_error_event():
    """SSE 中的 error 事件应被识别并返回错误信息。"""
    ok, content = _parse_sse_string(SSE_ERROR_RESPONSE)
    assert ok is False
    assert "429" in content


def test_check_llm_connection_accepts_sse_stream_response(monkeypatch):
    """连接测试应能处理默认返回的 SSE 流式字符串。"""
    monkeypatch.setattr(
        "videocaptioner.core.llm.check_llm.openai.OpenAI",
        lambda *args, **kwargs: FakeOpenAIClient(SSE_RESPONSE),
    )
    ok, msg = check_llm_connection("http://fake/v1", "sk-fake", "grok-4.3-fast")
    assert ok is True
    assert msg == "Hello"


def test_check_llm_connection_rejects_sse_error_response(monkeypatch):
    """SSE 流式错误响应应被识别为失败。"""
    monkeypatch.setattr(
        "videocaptioner.core.llm.check_llm.openai.OpenAI",
        lambda *args, **kwargs: FakeOpenAIClient(SSE_ERROR_RESPONSE),
    )
    ok, msg = check_llm_connection("http://fake/v1", "sk-fake", "grok-4.3-fast")
    assert ok is False
    assert "429" in msg
