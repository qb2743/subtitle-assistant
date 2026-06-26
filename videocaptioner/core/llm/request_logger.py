import json
import threading
import time
from datetime import datetime
from typing import Any, Dict

import httpx

from videocaptioner.config import LOG_PATH
from videocaptioner.core.llm.context import get_task_context

LLM_LOG_FILE = LOG_PATH / "llm_requests.jsonl"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB


_log_lock = threading.Lock()
_pending_requests: Dict[int, Dict[str, Any]] = {}  # 暂存请求信息，等待响应后合并


# ==================== 日志写入 ====================


def _rotate_if_needed() -> None:
    """日志文件过大时轮转"""
    if not LLM_LOG_FILE.exists():
        return
    if LLM_LOG_FILE.stat().st_size < MAX_LOG_SIZE:
        return

    backup = LLM_LOG_FILE.with_suffix(".jsonl.old")
    if backup.exists():
        backup.unlink()
    LLM_LOG_FILE.rename(backup)


def _write_log(entry: Dict[str, Any]) -> None:
    """写入日志"""
    try:
        LOG_PATH.mkdir(parents=True, exist_ok=True)
        with _log_lock:
            _rotate_if_needed()
            with open(LLM_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _disguise_request(request: httpx.Request) -> None:
    """移除 SDK 机器人标识头，避免被 Cloudflare 拦截"""
    keys_to_remove = [
        k for k in request.headers
        if k.lower().startswith(("x-stainless", "x-fern"))
    ]
    for k in keys_to_remove:
        del request.headers[k]
    request.headers["user-agent"] = _BROWSER_UA


def create_http_client(timeout: float = 240) -> httpx.Client:
    """创建不含 SDK 机器人标识的 HTTPX 客户端（用于非日志场景）"""
    return httpx.Client(event_hooks={"request": [_disguise_request]}, timeout=timeout)


def _patch_elevenlabs_headers() -> None:
    """Strip SDK headers before httpx sees ElevenLabs requests."""
    try:
        from elevenlabs.core.client_wrapper import SyncClientWrapper

        if getattr(SyncClientWrapper.get_headers, "_cf_patched", False):
            return

        _orig = SyncClientWrapper.get_headers

        def _patched(self):
            headers = _orig(self)
            headers["User-Agent"] = _BROWSER_UA
            for k in ("X-Fern-Language", "X-Fern-SDK-Name",
                       "X-Fern-SDK-Version"):
                headers.pop(k, None)
            return headers

        _patched._cf_patched = True
        SyncClientWrapper.get_headers = _patched
    except Exception:
        pass


_patch_elevenlabs_headers()


# ==================== HTTPX Hooks ====================


def _on_request(request: httpx.Request) -> None:
    """请求发送前: 暂存请求信息"""
    if "/chat/completions" not in str(request.url):
        return

    try:
        request_body = json.loads(request.content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        request_body = {"raw": request.content.decode("utf-8", errors="replace")}

    _pending_requests[id(request)] = {
        "start_time": time.time(),
        "url": str(request.url),
        "request": request_body,
    }


def _on_response(response: httpx.Response) -> None:
    """响应接收后: 记录状态码和耗时"""
    request = response.request
    pending = _pending_requests.get(id(request))
    if not pending:
        return

    pending["status"] = response.status_code
    pending["duration_ms"] = int((time.time() - pending["start_time"]) * 1000)
    pending["completed"] = True  # 标记响应已完成


# ==================== 公开 API ====================


def create_logging_http_client() -> httpx.Client:
    """创建带日志记录 + 反 Cloudflare 拦截的 HTTPX 客户端"""
    return httpx.Client(
        event_hooks={
            "request": [_disguise_request, _on_request],
            "response": [_on_response],
        },
    )


def log_llm_response(response: Any) -> None:
    """记录完整的请求+响应（在 SDK 解析响应后调用）"""
    if not _pending_requests:
        return

    # 优先选择已完成响应的请求（有 duration_ms）
    completed_key = None
    for key, pending in _pending_requests.items():
        if pending.get("completed"):
            completed_key = key
            break

    # 如果没有已完成的，取第一个
    key = completed_key if completed_key else next(iter(_pending_requests))
    pending = _pending_requests.pop(key)

    # 序列化完整响应体
    response_data = {}
    if response and hasattr(response, "model_dump"):
        response_data = response.model_dump()

    # 获取任务上下文
    ctx = get_task_context()

    log_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": ctx.task_id if ctx else "",
        "file_name": ctx.file_name if ctx else "",
        "stage": ctx.stage if ctx else "",
        "url": pending.get("url", ""),
        "status": pending.get("status", 0),
        "duration_ms": pending.get("duration_ms", 0),
        "request": pending.get("request", {}),
        "response": response_data,
    }

    _write_log(log_entry)
