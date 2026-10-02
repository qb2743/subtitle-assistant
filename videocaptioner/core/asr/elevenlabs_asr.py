"""ElevenLabs Scribe 云端转录（云端听写渠道）。

移植自 buxuku/SmartSub 的 ElevenLabs ASR 实现（``main/service/asr/elevenlabs.ts``
与 ``elevenlabsUtils.ts``），并按本项目既有约定重写：

- **端点**：``POST {base}/v1/speech-to-text``，multipart 上传音频，始终请求词级
  时间戳（``timestamps_granularity=word``）与 ``tag_audio_events=false``。
- **词间距**：Scribe 用 ``spacing`` 条目表达词间空白，没有语音时间语义。这里把
  连续空白折叠为下一个有效词的前导空格；若上游完全没给 spacing（或给了 CJK
  之外的混排），再按「ASCII 字母数字边界」补一个空格，避免英文/阿拉伯文被拼成
  一整串。
- **成句**：Scribe 只返回 ``text`` + ``words``，没有句子级段落。因此当调用方
  不需要词级时间戳时，用停顿/标点/长度三种边界把词聚合成字幕行（``group_words_into_lines``），
  而不是把逐词结果直接当字幕。
- **多 API Key 轮询**：与 ``core/speech/providers.py::ElevenLabsSpeechSynthesizer``
  保持同一套语义 —— round-robin 起始游标、单 key 上仅对 429 做退避重试、其它
  错误（401/402/5xx/超时/网络）立刻换下一个 key、全部 key 失败才抛错。
  差别是游标放在模块级：``ChunkedASR`` 会为每个分块新建实例，实例级游标会让
  每个分块都从第 1 个 key 开始，轮询失效。
"""

import time
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Union

import requests

from videocaptioner.core.speech.api_keys import parse_api_keys

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("elevenlabs_asr")

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
SPEECH_TO_TEXT_PATH = "/v1/speech-to-text"
DEFAULT_MODEL = "scribe_v2"
# scribe_v1 已被官方废弃，仅作为历史配置的兼容项保留。
SCRIBE_MODELS = ("scribe_v2", "scribe_v1")

DEFAULT_TIMEOUT_SEC = 300
MAX_SAME_KEY_RETRIES = 3

# 成句参数（仅在调用方不需要词级时间戳时生效）
SENTENCE_GAP_MS = 500
SENTENCE_MAX_CHARS = 36
SENTENCE_MAX_WORDS = 20
_STRONG_END = tuple("。！？!?…；;")
_SOFT_END = tuple("，,、：:")
_ASCII_PUNCT = ",.;:!?)]}\"'"

# 模块级轮询游标：key 组合 -> 下一个起始下标。ChunkedASR 并发分块共享同一游标，
# 使多个分块真正分散到不同 API Key 上。
_key_cursors: dict[tuple[str, ...], int] = {}
_key_cursor_lock = threading.Lock()

_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


class ElevenLabsASRError(RuntimeError):
    """携带 HTTP 语义的 ElevenLabs 转录错误，供轮询逻辑分类处理。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retriable: bool = False,
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retriable = retriable
        self.retry_after = retry_after


def normalize_base_url(raw: Optional[str]) -> str:
    """规范化 Base URL：空/非法回落官方端点，去掉误粘的 ``/v1`` 或端点后缀。

    与 Whisper API 不同，ElevenLabs 的 base 不是必填项：留空即用官方端点。
    """
    trimmed = (raw or "").strip().rstrip("/")
    if not trimmed:
        return DEFAULT_BASE_URL
    if not trimmed.lower().startswith(("http://", "https://")):
        return DEFAULT_BASE_URL

    for suffix in ("/speech-to-text", "/v1/speech-to-text"):
        if trimmed.lower().endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
            break
    if trimmed.lower().endswith("/v1"):
        trimmed = trimmed[:-3]

    return trimmed.rstrip("/") or DEFAULT_BASE_URL


def build_speech_to_text_url(base_url: str) -> str:
    """拼接 Scribe 转写端点：``{base}/v1/speech-to-text``。"""
    return f"{normalize_base_url(base_url)}{SPEECH_TO_TEXT_PATH}"


def normalize_language(raw: Optional[str]) -> str:
    """把 UI/CLI 的语言代码规整为 Scribe 可接受的 ``language_code``。

    空值或明显不是语言代码的值返回空串（交给 ElevenLabs 自动识别）。
    """
    code = (raw or "").strip().lower().replace("_", "-")
    if not code or code in {"auto", "automatic", "none"}:
        return ""
    if "-" in code:
        code = code.split("-", 1)[0]
    if not code.isalpha() or not 2 <= len(code) <= 3:
        return ""
    return code


def map_elevenlabs_words(raw: Any) -> List[dict]:
    """把 Scribe 的 ``words`` 映射为 ``{word, start, end}``（秒）。

    移植自 SmartSub ``mapElevenLabsWords``：``spacing`` 不单独成词，其空白前导到
    紧随其后的那个词；``audio_event`` 丢弃；缺 type 时按「有文本 + 有时间」保留。
    """
    if not isinstance(raw, list):
        return []

    out: List[dict] = []
    has_pending_spacing = False
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "spacing":
            spacing = str(item.get("text") or "")
            if any(char.isspace() for char in spacing):
                has_pending_spacing = True
            continue
        if isinstance(item_type, str) and item_type != "word":
            continue

        word = str(item.get("text") or "").strip()
        if not word:
            continue

        leading_space = " " if has_pending_spacing else ""
        # spacing 属于紧随其后的词；该词时间非法被丢弃时不能泄漏到更后面的词。
        has_pending_spacing = False

        start = _to_float(item.get("start"))
        end = _to_float(item.get("end"))
        if start is None or end is None:
            continue
        out.append({"word": leading_space + word, "start": start, "end": end})

    return add_inferred_spacing(out)


def add_inferred_spacing(words: List[dict]) -> List[dict]:
    """为未携带空白信息的相邻词补一个空格。

    仅当上一个词的结尾与下一个词的开头都是 ASCII 字母数字/ASCII 标点时补空格，
    因此中文、日文等不需要空格的文本不会被拆开。
    """
    normalized: List[dict] = []
    previous_text = ""
    for word in words:
        text = word["word"]
        if (
            normalized
            and not text.startswith(" ")
            and _needs_ascii_space(previous_text, text)
        ):
            text = " " + text
        normalized.append({**word, "word": text})
        previous_text = text
    return normalized


def join_word_texts(words: Iterable[dict]) -> str:
    """拼接词文本：词内已带前导空格的保留，其余按原样相连。"""
    return "".join(str(w.get("word") or "") for w in words).strip()


def group_words_into_lines(
    words: List[dict],
    *,
    gap_ms: int = SENTENCE_GAP_MS,
    max_chars: int = SENTENCE_MAX_CHARS,
    max_words: int = SENTENCE_MAX_WORDS,
) -> List[dict]:
    """把词级结果聚合成字幕行（Scribe 不提供句子级段落）。

    边界条件（任一满足即断句）：强标点结尾 / 与下一个词停顿超过 ``gap_ms`` /
    长度达到 ``max_chars`` / 词数达到 ``max_words``。弱标点仅在行已过半时断句，
    避免逗号把字幕切得过碎。

    返回 ``[{"text", "start", "end"}, ...]``（时间为秒）。
    """
    words = add_inferred_spacing(words)
    lines: List[dict] = []
    current: List[dict] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if not current:
            return
        text = join_word_texts(current)
        if text:
            lines.append(
                {
                    "text": text,
                    "start": float(current[0]["start"]),
                    "end": float(current[-1]["end"]),
                }
            )
        current = []
        current_chars = 0

    for index, word in enumerate(words):
        current.append(word)
        # 用拼接后的实际长度判断，词间空格也要算进字幕行预算。
        current_chars = len(join_word_texts(current))

        text = str(word.get("word") or "").strip()
        next_word = words[index + 1] if index + 1 < len(words) else None
        gap = (
            (float(next_word["start"]) - float(word["end"])) * 1000
            if next_word is not None
            else 0.0
        )

        if text.endswith(_STRONG_END):
            flush()
        elif next_word is None or gap >= gap_ms:
            flush()
        elif current_chars >= max_chars or len(current) >= max_words:
            flush()
        elif text.endswith(_SOFT_END) and current_chars >= max_chars * 0.6:
            flush()

    flush()
    return lines


class ElevenLabsASR(BaseASR):
    """ElevenLabs Scribe 云端转录。

    支持多 API Key 轮询（逗号/分号/空白分隔），单个 key 失败不会中断整体转录。
    """

    def __init__(
        self,
        audio_input: Optional[Union[str, bytes]] = None,
        api_key: str = "",
        base_url: str = "",
        model: str = DEFAULT_MODEL,
        language: str = "",
        need_word_time_stamp: bool = True,
        use_cache: bool = False,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        max_same_key_retries: int = MAX_SAME_KEY_RETRIES,
    ):
        super().__init__(audio_input, use_cache, need_word_time_stamp)

        self.api_keys = parse_api_keys(api_key)
        if not self.api_keys:
            raise ValueError("ElevenLabs API key is required for the Scribe ASR channel")

        self.base_url = normalize_base_url(base_url)
        self.model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.language = normalize_language(language)
        # BaseASR 不保存这个开关，子类各自持有（与 WhisperAPI 一致）。
        self.need_word_time_stamp = need_word_time_stamp
        self.timeout = max(float(timeout or DEFAULT_TIMEOUT_SEC), 1.0)
        self.max_same_key_retries = max(int(max_same_key_retries), 1)
        self._file_name, self._mime_type = self._describe_audio()

    # ------------------------------------------------------------------ 公共 API

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        return self._submit(callback)

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        """词级时间戳（需要时）或按停顿/标点聚合后的字幕行。"""
        words = map_elevenlabs_words(resp_data.get("words"))

        if words and self.need_word_time_stamp:
            return [
                ASRDataSeg(
                    text=word["word"],
                    start_time=int(float(word["start"]) * 1000),
                    end_time=int(float(word["end"]) * 1000),
                )
                for word in words
            ]

        if words:
            return [
                ASRDataSeg(
                    text=line["text"],
                    start_time=int(line["start"] * 1000),
                    end_time=int(line["end"] * 1000),
                )
                for line in group_words_into_lines(words)
            ]

        # 极端情况：没有词级时间戳。退化为整段一条，时间轴取音频时长。
        text = str(resp_data.get("text") or "").strip()
        if not text:
            return []
        return [
            ASRDataSeg(
                text=text,
                start_time=0,
                end_time=int(float(self.audio_duration) * 1000),
            )
        ]

    def _get_key(self) -> str:
        """缓存键：内容 CRC32 + 模型 + 语言 + 端点（不含 API Key，避免密钥落盘）。"""
        return f"{self.crc32_hex}-{self.model}-{self.language}-{self.base_url}"

    # ------------------------------------------------------------------ 内部实现

    def _describe_audio(self) -> tuple[str, str]:
        """返回上传用的文件名与 MIME 类型。"""
        if isinstance(self.audio_input, str):
            suffix = Path(self.audio_input).suffix.lower()
            return Path(self.audio_input).name, _MIME_TYPES.get(suffix, "audio/mpeg")
        return "audio.mp3", "audio/mpeg"

    def _rotated_keys(self) -> List[str]:
        """按模块级 round-robin 游标返回本次尝试顺序。

        与 TTS 侧不同，游标必须在实例之间共享：``ChunkedASR`` 会为每个分块新建
        一个 ``ElevenLabsASR``，实例级游标会让所有分块都从第一个 key 开始。
        """
        keys = self.api_keys
        if not keys:
            return []
        signature = tuple(keys)
        with _key_cursor_lock:
            index = _key_cursors.get(signature, 0) % len(keys)
            _key_cursors[signature] = index + 1
        return keys[index:] + keys[:index]

    def _submit(self, callback: Optional[Callable[[int, str], None]] = None) -> dict:
        keys_to_try = self._rotated_keys()
        last_error: Optional[Exception] = None

        for key_index, api_key in enumerate(keys_to_try):
            if callback:
                callback(5, f"上传音频至 ElevenLabs（key {key_index + 1}/{len(keys_to_try)}）")

            for retry_index in range(self.max_same_key_retries):
                try:
                    data = self._post_once(api_key)
                except Exception as exc:  # noqa: BLE001 - 任何失败都换 key，与 TTS 侧一致
                    last_error = (
                        exc
                        if isinstance(exc, ElevenLabsASRError)
                        else ElevenLabsASRError(str(exc))
                    )
                    # 只有 429 值得在同一个 key 上退避重试；其它错误立刻换 key，
                    # 保证一个坏 key 不会拖停整次转录。
                    if (
                        last_error.retriable
                        and retry_index < self.max_same_key_retries - 1
                    ):
                        delay = last_error.retry_after or min(2**retry_index, 8)
                        logger.warning(
                            "ElevenLabs Scribe rate limited on key %d/%d; retrying in %.1fs",
                            key_index + 1,
                            len(keys_to_try),
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    break

                if callback:
                    callback(100, "ElevenLabs 转录完成")
                return data

            logger.warning(
                "ElevenLabs Scribe API key %d/%d failed: %s; switching to next key",
                key_index + 1,
                len(keys_to_try),
                last_error,
            )

        friendly = _friendly_error(last_error)
        if len(keys_to_try) > 1:
            raise RuntimeError(
                f"All {len(keys_to_try)} ElevenLabs API keys failed; last error: {friendly}"
            ) from last_error
        raise RuntimeError(friendly) from last_error

    def _post_once(self, api_key: str) -> dict:
        """用单个 key 发一次转写请求；把 HTTP 语义翻译成 ElevenLabsASRError。"""
        url = build_speech_to_text_url(self.base_url)
        form: dict[str, str] = {
            "model_id": self.model,
            "timestamps_granularity": "word",
            "tag_audio_events": "false",
        }
        if self.language:
            form["language_code"] = self.language

        try:
            response = requests.post(
                url,
                headers={"xi-api-key": api_key},
                files={
                    "file": (self._file_name, self.file_binary or b"", self._mime_type)
                },
                data=form,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise ElevenLabsASRError(
                f"ElevenLabs Scribe request timed out after {self.timeout:.0f}s",
                retriable=True,
            ) from exc
        except requests.RequestException as exc:
            raise ElevenLabsASRError(
                f"ElevenLabs Scribe request failed: {exc}", retriable=True
            ) from exc

        if response.status_code >= 400:
            detail = (response.text or "")[:300]
            raise ElevenLabsASRError(
                f"ElevenLabs Scribe failed: HTTP {response.status_code} {detail}",
                status_code=response.status_code,
                # 只有 429 在同 key 上重试；5xx 交给换 key（与 TTS 侧一致）。
                retriable=response.status_code == 429,
                retry_after=_retry_after_seconds(response.headers),
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ElevenLabsASRError(
                "ElevenLabs Scribe returned a non-JSON response", status_code=response.status_code
            ) from exc

        if not isinstance(payload, dict):
            raise ElevenLabsASRError("ElevenLabs Scribe returned an unexpected payload")

        return payload


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _needs_ascii_space(previous_text: str, next_text: str) -> bool:
    """判断两个词之间是否需要补空格（仅 ASCII 边界）。"""
    if not previous_text or not next_text:
        return False
    previous_char = previous_text[-1]
    next_char = next_text[0]
    if not next_char.isascii() or not next_char.isalnum():
        return False
    return previous_char.isascii() and (
        previous_char.isalnum() or previous_char in _ASCII_PUNCT
    )


def _retry_after_seconds(headers: Any) -> Optional[float]:
    """从响应头读取 Retry-After（秒），上限 30s。"""
    if not headers:
        return None
    for name, divisor in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        try:
            value = headers.get(name)
        except AttributeError:
            return None
        if value is None:
            continue
        try:
            return max(0.0, min(float(value) / divisor, 30.0))
        except (TypeError, ValueError):
            continue
    return None


def _friendly_error(exc: Optional[Exception]) -> str:
    """把底层的 HTTP/网络错误翻译成用户能看懂的一句话。"""
    if exc is None:
        return "ElevenLabs Scribe 转录失败（未知原因）"
    if isinstance(exc, ElevenLabsASRError):
        status = exc.status_code
        if status in (401, 403):
            return f"ElevenLabs API Key 无效或未授权：{exc}"
        if status == 402:
            return f"ElevenLabs 账户额度或付款问题：{exc}"
        if status == 429:
            return f"ElevenLabs 触发限流（重试后仍失败）：{exc}"
        if status == 422:
            return f"ElevenLabs 拒绝了请求（模型名/语言代码或音频格式不合法）：{exc}"
        return str(exc)
    return f"ElevenLabs Scribe 转录失败：{exc}"


def check_elevenlabs_asr_connection(
    api_key: str,
    base_url: str = "",
    model: str = DEFAULT_MODEL,
    timeout: float = 60,
) -> tuple[bool, str]:
    """用内置测试音频真实调用一次 Scribe，用于设置页的「测试连接」。

    返回 ``(是否成功, 转录文本或错误说明)``。
    """
    from videocaptioner.config import ASSETS_PATH

    test_audio = ASSETS_PATH / "en.mp3"
    if not test_audio.exists():
        return False, f"测试音频不存在：{test_audio}"

    try:
        asr = ElevenLabsASR(
            str(test_audio),
            api_key=api_key,
            base_url=base_url,
            model=model or DEFAULT_MODEL,
            need_word_time_stamp=False,
            use_cache=False,
            timeout=timeout,
            max_same_key_retries=1,
        )
        result = asr.run()
        text = " ".join(seg.text for seg in result.segments).strip()
        if not text:
            return False, "转录成功但没有返回文本，请确认音频有效"
        return True, text
    except Exception as exc:  # noqa: BLE001 - 设置页需要展示任何失败原因
        return False, _friendly_error(exc) if isinstance(exc, ElevenLabsASRError) else str(exc)
