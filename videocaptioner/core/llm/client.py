"""Unified LLM client for the application."""

import os
import threading
from typing import Any, List, Optional
from urllib.parse import urlparse, urlunparse

import openai
from openai import OpenAI
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from videocaptioner.core.utils.cache import get_llm_cache, memoize
from videocaptioner.core.utils.logger import setup_logger

from .request_logger import create_logging_http_client, log_llm_response
from .response_utils import extract_content_from_response, make_pseudo_completion

_global_client: Optional[OpenAI] = None
_client_lock = threading.Lock()

logger = setup_logger("llm_client")


def normalize_base_url(base_url: str) -> str:
    """Normalize API base URL by ensuring /v1 suffix when path is empty.

    OpenAI SDK appends paths like ``/chat/completions`` to ``base_url``. If you
    only provide ``http://host:port`` (no path), we append ``/v1`` so requests
    hit ``/v1/chat/completions``. URLs that already include a path (e.g.
    ``.../v1``, ``.../api/paas/v4``, Anthropic gateways) are left unchanged.
    """
    url = base_url.strip()
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if not path:
        path = "/v1"

    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    return normalized


def resolve_llm_base_url(base_url: str) -> str:
    """Return base URL safe for OpenAI-compatible clients (applies normalize)."""
    if not (base_url or "").strip():
        return ""
    return normalize_base_url(base_url)


def get_llm_client() -> OpenAI:
    """Get global LLM client instance (thread-safe singleton)."""
    global _global_client

    if _global_client is None:
        with _client_lock:
            if _global_client is None:
                base_url = os.getenv("OPENAI_BASE_URL", "").strip()
                base_url = normalize_base_url(base_url)
                api_key = os.getenv("OPENAI_API_KEY", "").strip()

                if not base_url or not api_key:
                    raise ValueError(
                        "OPENAI_BASE_URL and OPENAI_API_KEY environment variables must be set"
                    )

                _global_client = OpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    http_client=create_logging_http_client(),
                )

    return _global_client


def before_sleep_log(retry_state: RetryCallState) -> None:
    logger.warning(
        "Rate Limit Error, sleeping and retrying... Please lower your thread concurrency or use better OpenAI API."
    )


@retry(
    stop=stop_after_attempt(10),
    wait=wait_random_exponential(multiplier=1, min=5, max=60),
    retry=retry_if_exception_type(openai.RateLimitError),
    before_sleep=before_sleep_log,
)
def _call_llm_api(
    messages: List[dict],
    model: str,
    temperature: float = 1,
    **kwargs: Any,
) -> Any:
    """实际调用 LLM API（带重试）"""
    client = get_llm_client()

    response = client.chat.completions.create(
        model=model,
        messages=messages,  # pyright: ignore[reportArgumentType]
        temperature=temperature,
        **kwargs,
    )

    # 记录响应内容
    log_llm_response(response)

    return response


@memoize(get_llm_cache(), expire=3600, typed=True)
def call_llm(
    messages: List[dict],
    model: str,
    temperature: float = 1,
    **kwargs: Any,
) -> Any:
    """Call LLM API with automatic caching.

    兼容非标准 OpenAI 代理：当 SDK 解析出的标准 choices 为空时，
    尝试从响应原始数据中提取 SSE 流式内容并构造伪 ChatCompletion。
    """
    response = _call_llm_api(messages, model, temperature, **kwargs)

    # 标准解析：choices[0].message.content 非空
    if (
        response
        and hasattr(response, "choices")
        and response.choices
        and len(response.choices) > 0
        and hasattr(response.choices[0], "message")
        and response.choices[0].message
        and response.choices[0].message.content
    ):
        return response

    # SSE fallback：某些代理在非流式请求下返回 SSE 流式数据，
    # SDK 无法解析成标准 ChatCompletion，但原始数据里有内容。
    content = extract_content_from_response(response)
    if content:
        logger.info(
            f"Standard ChatCompletion parse failed, extracted content via SSE fallback "
            f"({len(content)} chars)"
        )
        return make_pseudo_completion(content)

    # 真正的空响应，抛错并附带诊断信息
    try:
        dump = response.model_dump() if hasattr(response, "model_dump") else str(response)
        if not isinstance(dump, str):
            import json as _json
            dump = _json.dumps(dump, ensure_ascii=False, default=str)
    except Exception:
        dump = str(response)
    logger.error(f"Invalid OpenAI API response: empty choices or content. Raw: {dump[:500]}")
    raise ValueError(
        f"Invalid OpenAI API response: empty choices or content. "
        f"The endpoint returned 200 but no parseable completion. "
        f"Raw response (truncated): {dump[:300]}"
    )
