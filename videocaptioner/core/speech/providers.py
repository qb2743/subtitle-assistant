"""Speech synthesis provider implementations."""

import asyncio
import base64
import hashlib
import threading
import time
import wave
from pathlib import Path
from typing import Any, Protocol

import edge_tts
import requests

try:  # elevenlabs is an optional dependency for the ElevenLabs provider
    from elevenlabs import ElevenLabs, UnauthorizedError, VoiceSettings
    from elevenlabs.core import ApiError as ElevenLabsApiError
except ImportError:  # pragma: no cover - exercised only without the SDK installed
    ElevenLabs = None
    VoiceSettings = None
    UnauthorizedError = None
    ElevenLabsApiError = None

try:  # openai is a core dependency; guarded so the module still imports without it
    from openai import OpenAI as _OpenAIClient
except ImportError:  # pragma: no cover
    _OpenAIClient = None

from videocaptioner.core.utils.cache import get_tts_cache
from videocaptioner.core.utils.logger import setup_logger

from .api_keys import parse_api_keys
from .models import SpeechProviderConfig, SynthesisRequest, SynthesisResult

logger = setup_logger("speech")


class SpeechSynthesizer(Protocol):
    """Provider-neutral synthesis interface used by the dubbing pipeline."""

    config: SpeechProviderConfig

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """Synthesize one utterance to ``request.output_path``."""
        ...


def create_speech_synthesizer(config: SpeechProviderConfig) -> SpeechSynthesizer:
    if config.provider == "siliconflow":
        return SiliconFlowSpeechSynthesizer(config)
    if config.provider == "gemini":
        return GeminiSpeechSynthesizer(config)
    if config.provider == "edge":
        return EdgeTTSSpeechSynthesizer(config)
    if config.provider == "elevenlabs":
        return ElevenLabsSpeechSynthesizer(config)
    if config.provider == "openai":
        return OpenAISpeechSynthesizer(config)
    if config.provider in ("dots", "voxcpm"):
        from .local_tts import LocalGradioSpeechSynthesizer

        return LocalGradioSpeechSynthesizer(config)
    raise ValueError(f"Unsupported speech provider: {config.provider}")


class EdgeTTSSpeechSynthesizer:
    """Microsoft Edge online TTS synthesizer.

    This provider uses the unofficial Edge read-aloud endpoint through edge-tts.
    It does not require an API key and does not support voice cloning.
    """

    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

    def __init__(self, config: SpeechProviderConfig):
        self.config = config

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if request.clone_audio_path or request.clone_audio_text:
            raise ValueError("Edge TTS does not support voice cloning")
        voice = request.voice or self.config.default_voice or self.DEFAULT_VOICE
        path = Path(request.output_path).with_suffix(".mp3")
        path.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(self._save(request.text, voice, path))
        if not path.exists() or path.stat().st_size <= 0:
            raise ValueError("Edge TTS returned an empty audio file")
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format="mp3",
            provider_metadata={
                "rate": self._edge_rate(),
                "volume": self._edge_volume(),
                "pitch": "+0Hz",
            },
        )

    async def _save(self, text: str, voice: str, path: Path) -> None:
        communicate = edge_tts.Communicate(
            text=text.strip(),
            voice=voice,
            rate=self._edge_rate(),
            volume=self._edge_volume(),
            pitch="+0Hz",
            connect_timeout=min(self.config.timeout, 30),
            receive_timeout=self.config.timeout,
        )
        await communicate.save(str(path))

    def _edge_rate(self) -> str:
        percent = round((self.config.speed - 1.0) * 100)
        percent = max(-50, min(100, percent))
        return f"{percent:+d}%"

    def _edge_volume(self) -> str:
        percent = round(self.config.gain)
        percent = max(-50, min(50, percent))
        return f"{percent:+d}%"


class SiliconFlowSpeechSynthesizer:
    """SiliconFlow CosyVoice2-compatible synthesizer."""

    DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"

    def __init__(self, config: SpeechProviderConfig):
        if not config.api_key:
            raise ValueError("SiliconFlow API key is required")
        self.config = config
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.cache = get_tts_cache()

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        voice = self._resolve_voice(request)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": self._build_input(request),
            "voice": voice,
            "response_format": self.config.response_format,
            "sample_rate": self.config.sample_rate,
            "speed": self.config.speed,
            "gain": self.config.gain,
            "stream": False,
        }
        response = self._post_speech(payload)
        path = Path(request.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format=self.config.response_format,
            provider_metadata={"content_type": response.headers.get("content-type", "")},
        )

    def _post_speech(self, payload: dict[str, Any]) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/audio/speech",
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if not response.content:
                    raise ValueError("SiliconFlow TTS returned an empty audio body")
                if "json" in content_type.lower():
                    raise ValueError(f"SiliconFlow TTS returned JSON instead of audio: {response.text[:300]}")
                return response
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"SiliconFlow TTS failed after retries: {last_error}")

    def _resolve_voice(self, request: SynthesisRequest) -> str:
        if request.clone_audio_path and request.clone_audio_text:
            return self._upload_voice(request.clone_audio_path, request.clone_audio_text)
        voice = request.voice or self.config.default_voice
        if not voice:
            voice = f"{self.config.model}:alex"
        return voice

    def _build_input(self, request: SynthesisRequest) -> str:
        prompt = request.style_prompt or self.config.style_prompt
        if prompt:
            return f"{prompt.strip()}<|endofprompt|>{request.text.strip()}"
        return request.text

    def _upload_voice(self, audio_path: str, transcript: str) -> str:
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Voice clone reference audio not found: {audio_path}")
        cache_key = self._voice_cache_key(audio_file, transcript)
        cached = self.cache.get(cache_key)
        if cached:
            return str(cached)

        custom_name = f"videocaptioner_{hashlib.md5(cache_key.encode()).hexdigest()[:12]}"
        with audio_file.open("rb") as f:
            response = requests.post(
                f"{self.base_url}/uploads/audio/voice",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                files={"file": (audio_file.name, f, _guess_mime(audio_file))},
                data={
                    "model": self.config.model,
                    "customName": custom_name,
                    "text": transcript,
                },
                timeout=self.config.timeout,
            )
        response.raise_for_status()
        uri = response.json().get("uri")
        if not uri:
            raise ValueError(f"SiliconFlow upload did not return a voice uri: {response.text}")
        self.cache.set(cache_key, uri, expire=86400 * 2)
        return str(uri)

    def _voice_cache_key(self, audio_file: Path, transcript: str) -> str:
        digest = hashlib.md5(audio_file.read_bytes()).hexdigest()
        raw = f"speech_voice:{self.config.model}:{digest}:{transcript}"
        return hashlib.md5(raw.encode()).hexdigest()


class GeminiSpeechSynthesizer:
    """Gemini native speech generation synthesizer."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    SAMPLE_RATE = 24000

    def __init__(self, config: SpeechProviderConfig):
        if not config.api_key:
            raise ValueError("Gemini API key is required")
        self.config = config

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        voice = request.voice or self.config.default_voice or "Kore"
        prompt = self._build_prompt(request)
        response = requests.post(
            self._model_url(),
            headers={
                "x-goog-api-key": self.config.api_key,
                "Content-Type": "application/json",
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": voice,
                            }
                        }
                    },
                },
            },
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        pcm = self._extract_pcm(response.json())
        path = Path(request.output_path).with_suffix(".wav")
        self._write_wav(pcm, path)
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format="wav",
            provider_metadata={"sample_rate": self.SAMPLE_RATE},
        )

    def _model_url(self) -> str:
        base_url = (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        if base_url.endswith("/v1beta"):
            return f"{base_url}/models/{self.config.model}:generateContent"
        return f"{base_url}/v1beta/models/{self.config.model}:generateContent"

    def _build_prompt(self, request: SynthesisRequest) -> str:
        prompt = request.style_prompt or self.config.style_prompt
        if prompt:
            return f"{prompt.strip()}\n\nTranscript:\n{request.text.strip()}"
        return f"Read this subtitle line naturally and clearly.\n\nTranscript:\n{request.text.strip()}"

    @staticmethod
    def _extract_pcm(data: dict[str, Any]) -> bytes:
        try:
            for part in data["candidates"][0]["content"]["parts"]:
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data and inline_data.get("data"):
                    return base64.b64decode(inline_data["data"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Invalid Gemini TTS response: {data}") from exc
        raise ValueError(f"Gemini TTS response did not include audio: {data}")

    @classmethod
    def _write_wav(cls, pcm: bytes, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(cls.SAMPLE_RATE)
            wf.writeframes(pcm)


class ElevenLabsSpeechSynthesizer:
    """ElevenLabs text-to-speech synthesizer backed by the official SDK.

    Supports Voice ID selection (``request.voice`` / ``config.default_voice``)
    and tuning of the voice settings via ``config.extra``:

    - ``stability`` (0.0-1.0, default 0.5)
    - ``similarity_boost`` (0.0-1.0, default 0.75)
    - ``style`` (0.0-1.0, default 0.0)
    - ``use_speaker_boost`` (bool, default True)

    The shared ``config.speed`` is forwarded to the voice settings. Voice
    cloning from a reference audio is not supported by this provider.

    Multiple API keys may be supplied in ``config.api_key`` (comma/semicolon/
    whitespace separated). Keys are used in round-robin order across calls;
    on a quota or authorization failure the next key is tried automatically.
    """

    DEFAULT_MODEL = "eleven_multilingual_v2"
    DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel — a stable public voice
    OUTPUT_FORMAT = "mp3_44100_128"

    def __init__(self, config: SpeechProviderConfig):
        if ElevenLabs is None:
            raise ImportError(
                "The 'elevenlabs' package is required for the ElevenLabs speech "
                "provider. Install it with `pip install elevenlabs`."
            )
        self.config = config
        self.api_keys = parse_api_keys(config.api_key)
        if not self.api_keys:
            raise ValueError("At least one ElevenLabs API key is required")
        self._key_index = 0
        self._key_lock = threading.Lock()

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if request.clone_audio_path or request.clone_audio_text:
            raise ValueError("ElevenLabs speech provider does not support voice cloning")

        voice = request.voice or self.config.default_voice or self.DEFAULT_VOICE
        model = self.config.model or self.DEFAULT_MODEL
        stability = self._extra("stability", 0.5)
        similarity_boost = self._extra("similarity_boost", 0.75)
        style = self._extra("style", 0.0)
        use_speaker_boost = self._extra("use_speaker_boost", True)
        voice_settings = VoiceSettings(
            speed=self.config.speed,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
        )

        keys_to_try = self._rotated_keys()
        last_error: Exception | None = None
        attempted = 0
        for key_index, api_key in enumerate(keys_to_try):
            attempted += 1
            try:
                client = ElevenLabs(
                    api_key=api_key,
                    base_url=self.config.base_url or None,
                    timeout=self.config.timeout,
                )
                response = client.text_to_speech.convert(
                    voice_id=voice,
                    text=request.text.strip(),
                    model_id=model,
                    output_format=self.OUTPUT_FORMAT,
                    apply_text_normalization="auto",
                    voice_settings=voice_settings,
                )
                # The SDK returns a lazy Iterator[bytes]; the HTTP request (and
                # any 401/quota error) happens on iteration, so the write loop
                # MUST stay inside this try to trigger key rotation on failure.
                path = Path(request.output_path).with_suffix(".mp3")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as f:
                    for chunk in response:
                        if chunk:
                            f.write(chunk)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ElevenLabs API key %d/%d failed: %s",
                    key_index + 1,
                    len(keys_to_try),
                    exc,
                )
                if key_index < len(keys_to_try) - 1 and self._should_try_next_key(exc):
                    continue
                break

            if not path.exists() or path.stat().st_size <= 0:
                raise ValueError("ElevenLabs TTS returned an empty audio file")

            return SynthesisResult(
                output_path=str(path),
                voice=voice,
                format="mp3",
                provider_metadata={
                    "model_id": model,
                    "output_format": self.OUTPUT_FORMAT,
                    "stability": stability,
                    "similarity_boost": similarity_boost,
                    "style": style,
                    "use_speaker_boost": use_speaker_boost,
                    "speed": self.config.speed,
                    "api_key_index": key_index,
                },
            )

        if attempted > 1:
            raise RuntimeError(
                f"All {attempted} ElevenLabs API keys failed; last error: "
                f"{self._friendly_error(last_error)}"
            ) from last_error
        raise RuntimeError(self._friendly_error(last_error)) from last_error

    def _rotated_keys(self) -> list[str]:
        """Return the key list rotated by a thread-safe round-robin cursor.

        Each call advances the cursor by one so concurrent synth requests
        spread across keys. The returned list is the rotation order to try
        (first element is the preferred key, remainder are fallbacks).
        """
        keys = self.api_keys
        if not keys:
            return []
        with self._key_lock:
            idx = self._key_index % len(keys)
            self._key_index += 1
        return keys[idx:] + keys[:idx]

    def _should_try_next_key(self, error: Exception) -> bool:
        """Whether a failure looks like a per-key quota/auth problem."""
        if UnauthorizedError is not None and isinstance(error, UnauthorizedError):
            return True
        if ElevenLabsApiError is not None and isinstance(error, ElevenLabsApiError):
            status = getattr(error, "status_code", None)
            if status in (401, 402, 403, 404, 429):
                return True
            body = str(getattr(error, "body", "") or "").lower()
            if any(word in body for word in ("quota", "rate", "limit", "unauthorized", "permission")):
                return True
        return False

    def _extra(self, key: str, default):
        value = self.config.extra.get(key)
        return default if value is None else value

    @staticmethod
    def _friendly_error(exc: Exception | None) -> str:
        if exc is None:
            return "ElevenLabs TTS failed for an unknown reason"
        if UnauthorizedError is not None and isinstance(exc, UnauthorizedError):
            return "ElevenLabs API key is invalid or unauthorized"
        if ElevenLabsApiError is not None and isinstance(exc, ElevenLabsApiError):
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                return "ElevenLabs API key is invalid or unauthorized"
            if status == 402 or status == 429:
                return "ElevenLabs quota exceeded or rate limited"
            body = str(getattr(exc, "body", "") or "")
            return f"ElevenLabs API error ({status}): {body[:200]}"
        return f"ElevenLabs TTS failed: {exc}"


class OpenAISpeechSynthesizer:
    """OpenAI (and OpenAI-compatible) TTS via the official SDK.

    A custom ``base_url`` lets you point this at any OpenAI-format TTS wrapper
    (``POST {base_url}/audio/speech`` with ``{model, input, voice,
    response_format, speed}``). Voice cloning is not supported.
    """

    DEFAULT_MODEL = "tts-1"
    DEFAULT_VOICE = "alloy"

    def __init__(self, config: SpeechProviderConfig):
        if _OpenAIClient is None:
            raise ImportError(
                "The 'openai' package is required for the OpenAI speech provider. "
                "Install it with `pip install openai`."
            )
        if not config.api_key:
            raise ValueError("OpenAI TTS API key is required")
        self.config = config
        self.client = _OpenAIClient(
            api_key=config.api_key,
            base_url=config.base_url or None,
            timeout=config.timeout,
            max_retries=int(self._extra("max_retries", 3)),
        )

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if request.clone_audio_path or request.clone_audio_text:
            raise ValueError("OpenAI TTS does not support voice cloning")
        voice = request.voice or self.config.default_voice or self.DEFAULT_VOICE
        model = self.config.model or self.DEFAULT_MODEL
        fmt = self.config.response_format or "mp3"
        path = Path(request.output_path).with_suffix(f".{fmt}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=request.text.strip(),
            response_format=fmt,
            speed=self.config.speed,
        ) as response:
            response.stream_to_file(str(path))
        if not path.exists() or path.stat().st_size <= 0:
            raise ValueError("OpenAI TTS returned an empty audio file")
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format=fmt,
            provider_metadata={
                "model": model,
                "base_url": self.config.base_url,
            },
        )

    def _extra(self, key: str, default):
        value = self.config.extra.get(key)
        return default if value is None else value


def list_elevenlabs_voices(
    api_key: str,
    base_url: str = "",
    timeout: int = 90,
    include_legacy: bool = True,
) -> list[dict[str, Any]]:
    """List the ElevenLabs voices available to ``api_key`` via the SDK.

    Wraps ``client.voices.get_all()`` (the key's own + shared + legacy
    premade voices) and returns a normalized list of dicts with keys
    ``voice_id``, ``name``, ``category``, ``labels``, ``preview_url``.

    This is the authoritative, per-key voice list (it includes cloned and
    voice-library voices the static ``ELEVENLABS_PREMADE_VOICES`` catalog in
    ``presets.py`` does not know about). It makes one authenticated API call.
    """
    if ElevenLabs is None:
        raise ImportError(
            "The 'elevenlabs' package is required to list ElevenLabs voices. "
            "Install it with `pip install elevenlabs`."
        )
    if not api_key:
        raise ValueError("ElevenLabs API key is required")
    client = ElevenLabs(api_key=api_key, base_url=base_url or None, timeout=timeout)
    response = client.voices.get_all(show_legacy=include_legacy)
    voices: list[dict[str, Any]] = []
    for voice in response.voices:
        voices.append(
            {
                "voice_id": voice.voice_id,
                "name": voice.name,
                "category": voice.category,
                "labels": dict(voice.labels or {}),
                "preview_url": voice.preview_url,
            }
        )
    return voices


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".opus":
        return "audio/opus"
    if suffix == ".pcm":
        return "audio/pcm"
    return "audio/mpeg"
