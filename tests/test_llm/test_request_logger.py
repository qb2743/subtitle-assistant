"""request_logger 并发请求/响应配对测试。

并发翻译时多个线程同时挂起请求，log_llm_response 必须把响应配对到
本线程发出的请求上，而不是"全局第一个已完成"的请求。
"""

import httpx
import pytest

from videocaptioner.core.llm import request_logger as rl


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """隔离日志文件与共享状态，避免污染真实日志。"""
    monkeypatch.setattr(rl, "LLM_LOG_FILE", tmp_path / "llm_requests.jsonl")
    rl._pending_requests.clear()
    yield
    rl._pending_requests.clear()


def _fake_response(content: str = "{}"):
    class _Resp:
        def model_dump(self):
            return {"choices": [{"message": {"content": content}}]}

    return _Resp()


def _send_request(url: str, text: str) -> int:
    """模拟一个线程发出请求，返回暂存条目的 key。"""
    request = httpx.Request(
        "POST",
        url,
        json={"messages": [{"role": "user", "content": text}]},
    )
    rl._on_request(request)
    return getattr(rl._request_ctx, "key")


def _complete(key_owner_request: httpx.Request):
    response = httpx.Response(200, request=key_owner_request)
    rl._on_response(response)


def test_log_pairs_response_with_same_thread_request(tmp_path):
    """两个并发请求交错完成时，各自线程写各自的日志。"""
    request_a = httpx.Request(
        "POST", "https://x/v1/chat/completions", json={"messages": [{"role": "user", "content": "A"}]}
    )
    request_b = httpx.Request(
        "POST", "https://x/v1/chat/completions", json={"messages": [{"role": "user", "content": "B"}]}
    )

    # 线程 A、B 先后发出请求（各自设置自己的 thread-local key）
    rl._on_request(request_a)
    key_a = getattr(rl._request_ctx, "key")
    rl._on_request(request_b)
    key_b = getattr(rl._request_ctx, "key")
    assert key_a != key_b

    # B 先完成并写日志：必须记录 B 的请求，而不是先发出的 A
    _complete(request_b)
    rl.log_llm_response(_fake_response())
    entries = (tmp_path / "llm_requests.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(entries) == 1
    logged = __import__("json").loads(entries[0])
    assert logged["request"]["messages"][0]["content"] == "B"

    # A 完成后写日志：记录 A 的请求
    assert key_b not in rl._pending_requests
    _complete(request_a)
    rl.log_llm_response(_fake_response())
    entries = (tmp_path / "llm_requests.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(entries) == 2
    logged = __import__("json").loads(entries[-1])
    assert logged["request"]["messages"][0]["content"] == "A"
    assert key_a not in rl._pending_requests


def test_expired_pending_entries_are_pruned():
    """异常失败的请求残留条目超过 TTL 后应被清理，不再干扰后续配对。"""
    import time

    stale_request = httpx.Request("POST", "https://x/v1/chat/completions", json={})
    rl._on_request(stale_request)
    key = getattr(rl._request_ctx, "key")
    rl._pending_requests[key]["start_time"] = time.time() - 3600

    fresh_request = httpx.Request("POST", "https://x/v1/chat/completions", json={})
    rl._on_request(fresh_request)

    assert key not in rl._pending_requests
