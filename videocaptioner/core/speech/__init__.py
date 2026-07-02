"""Speech synthesis provider layer for dubbing."""

from .api_keys import parse_api_keys
from .local_tts import LocalGradioSpeechSynthesizer, is_local_tts_provider
from .models import SpeechProviderConfig, SynthesisRequest, SynthesisResult
from .providers import (
    EdgeTTSSpeechSynthesizer,
    ElevenLabsSpeechSynthesizer,
    FishAudioSpeechSynthesizer,
    GeminiSpeechSynthesizer,
    OpenAISpeechSynthesizer,
    SiliconFlowSpeechSynthesizer,
    SpeechSynthesizer,
    create_speech_synthesizer,
    list_elevenlabs_voices,
)

__all__ = [
    "EdgeTTSSpeechSynthesizer",
    "ElevenLabsSpeechSynthesizer",
    "FishAudioSpeechSynthesizer",
    "GeminiSpeechSynthesizer",
    "LocalGradioSpeechSynthesizer",
    "OpenAISpeechSynthesizer",
    "SiliconFlowSpeechSynthesizer",
    "SpeechProviderConfig",
    "SpeechSynthesizer",
    "SynthesisRequest",
    "SynthesisResult",
    "create_speech_synthesizer",
    "is_local_tts_provider",
    "list_elevenlabs_voices",
    "parse_api_keys",
]
