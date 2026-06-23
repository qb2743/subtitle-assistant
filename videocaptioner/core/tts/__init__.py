"""TTS (Text-To-Speech) 模块

提供多种 TTS 服务的统一接口
"""

from .base import BaseTTS
from .dots_tts import DotsTTS
from .gradio_base import GradioBaseTTS
from .openai_fm import OpenAIFmTTS
from .openai_tts import OpenAITTS
from .siliconflow import SiliconFlowTTS, VoiceCloneManager
from .status import TTSStatus
from .tts_data import TTSConfig, TTSData, TTSDataSeg
from .voxcpm_tts import VoxCPMTTS

__all__ = [
    "BaseTTS",
    "DotsTTS",
    "GradioBaseTTS",
    "OpenAITTS",
    "OpenAIFmTTS",
    "SiliconFlowTTS",
    "VoxCPMTTS",
    "VoiceCloneManager",
    "TTSStatus",
    "TTSConfig",
    "TTSData",
    "TTSDataSeg",
]
