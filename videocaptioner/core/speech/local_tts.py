"""Speech-layer adapter for local Gradio TTS engines (Dots-TTS, VoxCPM).

The dubbing pipeline speaks the ``core.speech`` single-utterance interface
(``synthesize(SynthesisRequest) -> SynthesisResult``), while the local engines
live in ``core.tts`` (batch ``BaseTTS``). This adapter wraps a local engine so
the dubbing pipeline can select ``dots`` / ``voxcpm`` like any other provider.

Voice cloning is mandatory: the request must carry ``clone_audio_path`` (the
reference audio) and ``clone_audio_text`` (its transcript); the underlying
engine raises a clear error if either is missing.
"""

from pathlib import Path

from videocaptioner.core.tts.dots_tts import DotsTTS
from videocaptioner.core.tts.tts_data import TTSConfig, TTSDataSeg
from videocaptioner.core.tts.voxcpm_tts import VoxCPMTTS

from .models import SpeechProviderConfig, SynthesisRequest, SynthesisResult

_LOCAL_ENGINES = {"dots": DotsTTS, "voxcpm": VoxCPMTTS}


class LocalGradioSpeechSynthesizer:
    """Adapt a local Gradio TTS engine to the dubbing speech interface."""

    OUTPUT_FORMAT = "wav"

    def __init__(self, config: SpeechProviderConfig):
        engine_cls = _LOCAL_ENGINES.get(config.provider)
        if engine_cls is None:
            raise ValueError(f"Unsupported local TTS provider: {config.provider}")
        self.config = config
        self.engine = engine_cls(self._to_tts_config(config))
        self.service_name = self.engine.service_name

    @staticmethod
    def _to_tts_config(config: SpeechProviderConfig) -> TTSConfig:
        extra = config.extra or {}
        return TTSConfig(
            model=config.model or config.provider,
            api_key=config.api_key or "",
            base_url=config.base_url,
            voice=config.default_voice or None,
            response_format=config.response_format,
            speed=config.speed,
            timeout=config.timeout,
            start_script=extra.get("start_script", ""),
            service_start_timeout=int(extra.get("service_start_timeout", 180)),
            voxcpm_version=extra.get("voxcpm_version", "v2"),
        )

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        segment = TTSDataSeg(
            text=request.text,
            voice=request.voice,
            clone_audio_path=request.clone_audio_path or self.config.clone_audio_path,
            clone_audio_text=request.clone_audio_text or self.config.clone_audio_text,
        )
        path = Path(request.output_path).with_suffix(f".{self.OUTPUT_FORMAT}")
        self.engine._synthesize(segment, str(path))
        voice = request.voice or self.config.default_voice or "clone"
        return SynthesisResult(
            output_path=str(path),
            voice=voice,
            format=self.OUTPUT_FORMAT,
            provider_metadata={
                "engine": self.service_name,
                "provider": self.config.provider,
            },
        )


def is_local_tts_provider(provider: str) -> bool:
    """Whether ``provider`` is a local Gradio TTS engine (dots/voxcpm)."""
    return provider in _LOCAL_ENGINES
