"""Provider-neutral speech synthesis models."""

from dataclasses import dataclass, field
from typing import Literal, Optional

SpeechProvider = Literal["siliconflow", "gemini", "edge", "elevenlabs", "dots", "voxcpm", "openai", "fishaudio"]
AudioFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]

# Fish Audio defaults to five concurrent requests on Starter accounts. Elevated
# and High Volume accounts allow 15 and 50; Enterprise is custom. The quota is
# shared across all keys from one account/team, so key-count multiplication is
# valid only when the configured keys belong to separate accounts/teams.
# https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits
FISHAUDIO_CONCURRENT_PER_ACCOUNT_DEFAULT = 5


@dataclass
class SpeechProviderConfig:
    """Connection and default synthesis options for one provider."""

    provider: SpeechProvider
    api_key: str
    model: str
    base_url: str = ""
    default_voice: str = ""
    response_format: AudioFormat = "mp3"
    sample_rate: int = 32000
    speed: float = 1.0
    gain: float = 0
    timeout: int = 90
    style_prompt: str = ""
    clone_audio_path: str = ""
    clone_audio_text: str = ""
    # Provider-specific options that don't fit the shared fields above.
    # ElevenLabs reads: stability, similarity_boost, style, use_speaker_boost.
    extra: dict = field(default_factory=dict)


@dataclass
class SynthesisRequest:
    """One utterance synthesis request."""

    text: str
    output_path: str
    voice: Optional[str] = None
    style_prompt: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None


@dataclass
class SynthesisResult:
    """Result from a provider call."""

    output_path: str
    voice: str
    format: AudioFormat
    provider_metadata: dict
