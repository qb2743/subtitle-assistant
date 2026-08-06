"""Unified LLM client for the application."""

import hashlib
import os
import threading
from typing import Any, Callable, List, Optional, TypeVar
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
_model_lock = threading.Lock()
_preferred_models: dict[tuple[str, ...], str] = {}

logger = setup_logger("llm_client")
T = TypeVar("T")


def parse_model_candidates(model: str) -> list[str]:
    """Parse a comma-separated model failover chain, preserving order."""
    parts = (model or "").replace("，", ",").split(",")
    return list(dict.fromkeys(part.strip() for part in parts if part.strip()))


def call_with_model_fallback(
    model: str, request: Callable[[str], T], *, scope: str = ""
) -> tuple[T, str]:
    """Run a model request with sticky, ordered fallback."""
    candidates = parse_model_candidates(model)
    if not candidates:
        raise ValueError("At least one LLM model must be configured")

    chain = (scope, *candidates)
    with _model_lock:
        preferred = _preferred_models.get(chain)
    if preferred in candidates:
        candidates.remove(preferred)
        candidates.insert(0, preferred)

    last_error: Optional[Exception] = None
    rate_limit_error: Optional[openai.RateLimitError] = None
    for index, candidate in enumerate(candidates):
        try:
            result = request(candidate)
        except Exception as exc:
            last_error = exc
            if isinstance(exc, openai.RateLimitError):
                rate_limit_error = exc
            if index + 1 < len(candidates):
                logger.warning(
                    "LLM model %s failed; switching to %s: %s",
                    candidate,
                    candidates[index + 1],
                    exc,
                )
            continue

        with _model_lock:
            _preferred_models[chain] = candidate
        return result, candidate

    assert last_error is not None
    raise rate_limit_error or last_error


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


def model_fallback_scope(base_url: str, api_key: str) -> str:
    """Identify one endpoint/account without retaining the API key."""
    key = (api_key or "").strip()
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
    return f"{resolve_llm_base_url(base_url)}|{fingerprint}"


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


def _normalize_llm_response(response: Any) -> Any:
    """Return a usable completion, including non-standard SSE responses."""
    if (
        response
        and hasattr(response, "choices")
        and response.choices
        and hasattr(response.choices[0], "message")
        and response.choices[0].message
        and response.choices[0].message.content
    ):
        return response

    content = extract_content_from_response(response)
    if content:
        logger.info(
            "Standard ChatCompletion parse failed, extracted content via SSE fallback "
            "(%s chars)",
            len(content),
        )
        return make_pseudo_completion(content)

    try:
        dump = response.model_dump() if hasattr(response, "model_dump") else str(response)
        if not isinstance(dump, str):
            import json as _json

            dump = _json.dumps(dump, ensure_ascii=False, default=str)
    except Exception:
        dump = str(response)
    logger.error(
        "Invalid OpenAI API response: empty choices or content. Raw: %s", dump[:500]
    )
    raise ValueError(
        "Invalid OpenAI API response: empty choices or content. "
        "The endpoint returned 200 but no parseable completion. "
        f"Raw response (truncated): {dump[:300]}"
    )


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

    def request(candidate: str) -> Any:
        response = client.chat.completions.create(
            model=candidate,
            messages=messages,  # pyright: ignore[reportArgumentType]
            temperature=temperature,
            **kwargs,
        )
        log_llm_response(response)
        return _normalize_llm_response(response)

    response, _ = call_with_model_fallback(
        model,
        request,
        scope=model_fallback_scope(
            str(getattr(client, "base_url", "")),
            str(getattr(client, "api_key", "") or ""),
        ),
    )
    return response


@memoize(get_llm_cache(), expire=3600, typed=True)
def call_llm(
    messages: List[dict],
    model: str,
    temperature: float = 1,
    **kwargs: Any,
) -> Any:
    """Call LLM API with automatic caching.

    ``model`` accepts a comma-separated failover chain in priority order.
    兼容非标准 OpenAI 代理：当 SDK 解析出的标准 choices 为空时，
    尝试从响应原始数据中提取 SSE 流式内容并构造伪 ChatCompletion。
    """
    return _normalize_llm_response(
        _call_llm_api(messages, model, temperature, **kwargs)
    )
