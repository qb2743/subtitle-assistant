"""Data models for subtitle dubbing."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

DubbingProvider = Literal["siliconflow", "gemini", "edge", "elevenlabs", "dots", "voxcpm", "openai", "fishaudio"]
FitMode = Literal["none", "tempo"]

# ElevenLabs per-account concurrency (free tier; varies by model family).
# Flash / Turbo: 4 simultaneous TTS requests per key; other models (e.g. Multilingual v2): 2.
ELEVENLABS_CONCURRENT_PER_KEY_DEFAULT = 2
ELEVENLABS_CONCURRENT_PER_KEY_FLASH = 4


def elevenlabs_concurrent_per_key(model: str) -> int:
    """Max in-flight TTS requests per API key for the given ElevenLabs model id."""
    mid = (model or "").strip().lower()
    if "flash" in mid or "turbo" in mid:
        return ELEVENLABS_CONCURRENT_PER_KEY_FLASH
    return ELEVENLABS_CONCURRENT_PER_KEY_DEFAULT


# Backward-compatible alias (default-tier cap only).
ELEVENLABS_CONCURRENT_PER_KEY = ELEVENLABS_CONCURRENT_PER_KEY_DEFAULT
ELEVENLABS_MAX_TTS_WORKERS = ELEVENLABS_CONCURRENT_PER_KEY_DEFAULT


@dataclass
class SpeakerProfile:
    """Voice settings for one speaker."""

    name: str
    voice: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None
    style_prompt: Optional[str] = None


@dataclass
class DubbingSegment:
    """One timed utterance to synthesize and place on the output timeline."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str = "default"
    voice: Optional[str] = None
    style_prompt: Optional[str] = None
    clone_audio_path: Optional[str] = None
    clone_audio_text: Optional[str] = None
    synthesized_path: str = ""
    fitted_path: str = ""
    synthesized_duration_ms: int = 0
    fitted_duration_ms: int = 0
    rewritten_text: Optional[str] = None
    speed_factor: float = 1.0
    warning: Optional[str] = None

    @property
    def target_duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def text_for_tts(self) -> str:
        return self.rewritten_text or self.text


@dataclass
class DubbingConfig:
    """Runtime configuration for dubbing."""

    provider: DubbingProvider
    api_key: str
    base_url: str
    model: str
    voice: str = ""
    response_format: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"] = "mp3"
    sample_rate: int = 32000
    speed: float = 1.0
    gain: float = 0
    timeout: int = 90
    use_cache: bool = True
    tts_workers: int = 5
    speaker_profiles: dict[str, SpeakerProfile] = field(default_factory=dict)
    style_prompt: str = ""
    fit_mode: FitMode = "tempo"
    max_speed: float = 1.35
    target_padding_ms: int = 80
    rewrite_too_long: bool = False
    rewrite_threshold: float = 1.15
    llm_api_key: str = ""
    llm_api_base: str = ""
    llm_model: str = ""
    mix_original_audio: bool = False
    original_audio_volume: float = 0.25
    dubbed_audio_volume: float = 1.0
    clone_audio_path: str = ""
    clone_audio_text: str = ""
    # Provider-specific options forwarded to the speech provider config.
    # ElevenLabs reads: stability, similarity_boost, style, use_speaker_boost.
    extra: dict = field(default_factory=dict)
    # Fixed inter-line pause: ignore the SRT timeline and lay segments
    # end-to-end with a silent pause between each line.
    fixed_line_pause: bool = False
    fixed_line_pause_ms: int = 1000
    # 语音间隔(毫秒):每条配音结束后插入的静音,字幕时间轴整体顺延(保留原时间轴)。
    # 与 fixed_line_pause 互斥:仅当 !fixed_line_pause 且 >0 时生效。
    subtitle_gap_ms: int = 0
    # 视频变速:音频超槽时逐段减速视频画面(需要 video_path)。
    video_autorate: bool = False
    # 嵌入硬字幕:"none" 不嵌入 | "hard" 烧录进输出视频。
    embed_subtitle: str = "none"
    # 视频减速上限倍数(pts_factor 上限)。
    max_video_slowdown: float = 2.0
    # 背景音(阶段2):分离人声/背景声。为 True 且提供 video_path 时,在 TTS 前
    # 从视频提取的音频中分离出背景伴奏轨缓存到 work 目录。
    separate_vocal: bool = False
    # 背景音回嵌:时间轴组装后、mux 前把分离出的背景伴奏(或 extra_bgm)混回配音轨。
    embed_bgm: bool = False
    # 背景音短于配音时是否循环。
    bgm_loop: bool = True
    # 背景音音量(线性,如 0.8)。
    bgm_volume: float = 0.8
    # 额外背景音乐路径;为空则不使用。
    extra_bgm_path: str = ""


@dataclass
class DubbingResult:
    """Outputs and per-segment metadata from a dubbing run."""

    audio_path: Path
    video_path: Optional[Path]
    segments: list[DubbingSegment]
    duration_ms: int
    warnings: list[str] = field(default_factory=list)
    # 字幕时间轴顺延(subtitle_gap_ms>0)时导出的调整后字幕路径;无则 None。
    adjusted_subtitle_path: Optional[Path] = None
