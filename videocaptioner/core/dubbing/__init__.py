"""Subtitle dubbing pipeline."""

from .models import DubbingConfig, DubbingResult, DubbingSegment, SpeakerProfile
from .pipeline import DubbingPipeline
from .presets import (
    ElevenLabsVoice,
    available_dubbing_presets,
    elevenlabs_voice_options,
    get_dubbing_preset,
)

__all__ = [
    "DubbingConfig",
    "DubbingPipeline",
    "DubbingResult",
    "DubbingSegment",
    "ElevenLabsVoice",
    "SpeakerProfile",
    "available_dubbing_presets",
    "elevenlabs_voice_options",
    "get_dubbing_preset",
]
