"""Build DubbingConfig from GUI cfg — same semantics as cli/commands/dub.py."""

from __future__ import annotations

from videocaptioner.core.dubbing import DubbingConfig
from videocaptioner.core.dubbing.models import FitMode
from videocaptioner.core.dubbing.presets import normalize_dubbing_voice
from videocaptioner.core.entities import LLMServiceEnum
from videocaptioner.core.speech.providers import EdgeTTSSpeechSynthesizer
from videocaptioner.ui.common.config import cfg

_OPENAI_TTS_VOICES = frozenset(
    {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
)


def resolve_dubbing_voice(provider: str, voice: str) -> str:
    """Return a voice id valid for the given TTS provider."""
    voice = (voice or "").strip()
    if provider == "edge":
        if voice.endswith("Neural"):
            return voice
        return EdgeTTSSpeechSynthesizer.DEFAULT_VOICE
    if provider == "openai":
        if voice in _OPENAI_TTS_VOICES:
            return voice
        return "alloy"
    if provider == "elevenlabs":
        if voice.endswith("Neural"):
            return ""
        return voice
    if provider == "gemini":
        from videocaptioner.core.dubbing.presets import GEMINI_VOICES

        if voice.endswith("Neural"):
            return "Kore"
        for known in GEMINI_VOICES:
            if voice.lower() == known.lower():
                return known
        return voice or "Kore"
    if provider == "siliconflow":
        if voice.endswith("Neural"):
            return ""
        return voice
    return voice


_VALID_PROVIDERS = (
    "siliconflow",
    "gemini",
    "edge",
    "elevenlabs",
    "dots",
    "voxcpm",
    "openai",
)

_DEFAULT_ELEVENLABS_MODEL = "eleven_flash_v2_5"
_DEFAULT_SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"
_DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_SILICONFLOW_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
_DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-tts-preview"


def _resolve_timing() -> tuple[FitMode, float]:
    timing = cfg.dubbing_timing.value or "balanced"
    explicit_max_speed = 2.0
    if timing == "none":
        return "none", explicit_max_speed
    fit_mode: FitMode = "tempo"
    if timing == "natural":
        return fit_mode, min(explicit_max_speed, 1.25)
    if timing == "strict":
        return fit_mode, max(explicit_max_speed, 2.0)
    return fit_mode, explicit_max_speed


def _resolve_audio_mix() -> tuple[bool, float]:
    audio_mode = cfg.dubbing_audio_mode.value or "replace"
    explicit_volume = 0.25
    if audio_mode == "replace":
        return False, explicit_volume
    if audio_mode == "mix":
        return True, explicit_volume
    if audio_mode == "duck":
        return True, min(explicit_volume, 0.12)
    return False, explicit_volume


def _llm_fields_for_rewrite() -> tuple[str, str, str]:
    """Subtitle LLM settings used when「自动调整过长行」开启。"""
    service = cfg.llm_service.value
    if service == LLMServiceEnum.OPENAI:
        return cfg.openai_api_key.value, cfg.openai_api_base.value, cfg.openai_model.value
    if service == LLMServiceEnum.SILICON_CLOUD:
        return (
            cfg.silicon_cloud_api_key.value,
            cfg.silicon_cloud_api_base.value,
            cfg.silicon_cloud_model.value,
        )
    if service == LLMServiceEnum.DEEPSEEK:
        return cfg.deepseek_api_key.value, cfg.deepseek_api_base.value, cfg.deepseek_model.value
    if service == LLMServiceEnum.OLLAMA:
        return cfg.ollama_api_key.value, cfg.ollama_api_base.value, cfg.ollama_model.value
    if service == LLMServiceEnum.LM_STUDIO:
        return cfg.lm_studio_api_key.value, cfg.lm_studio_api_base.value, cfg.lm_studio_model.value
    if service == LLMServiceEnum.GEMINI:
        return cfg.gemini_api_key.value, cfg.gemini_api_base.value, cfg.gemini_model.value
    if service == LLMServiceEnum.CHATGLM:
        return cfg.chatglm_api_key.value, cfg.chatglm_api_base.value, cfg.chatglm_model.value
    if service == LLMServiceEnum.ANTHROPIC:
        return cfg.anthropic_api_key.value, cfg.anthropic_api_base.value, cfg.anthropic_model.value
    return "", "", ""


def _provider_defaults(provider: str) -> tuple[str, str]:
    """(model, base_url) when cfg 未单独指定。"""
    api_base = (cfg.dubbing_api_base.value or "").strip()
    model = (cfg.dubbing_model.value or "").strip()

    if provider == "openai":
        if not model:
            model = "tts-1"
        if not api_base:
            api_base = "https://api.openai.com/v1"
        return model, api_base
    if provider == "elevenlabs":
        if not model:
            model = _DEFAULT_ELEVENLABS_MODEL
        return model, ""
    if provider == "siliconflow":
        if not model:
            model = _DEFAULT_SILICONFLOW_MODEL
        if not api_base:
            api_base = _DEFAULT_SILICONFLOW_BASE
        return model, api_base
    if provider == "gemini":
        if not model:
            model = _DEFAULT_GEMINI_MODEL
        if not api_base:
            api_base = _DEFAULT_GEMINI_BASE
        return model, api_base
    if provider == "edge":
        return model or "edge-tts", ""
    if provider == "dots":
        return "dots-tts", (cfg.dubbing_dots_url.value or "http://127.0.0.1:7860").strip()
    if provider == "voxcpm":
        return "voxcpm", (cfg.dubbing_voxcpm_url.value or "http://127.0.0.1:9880").strip()
    return model, api_base


def create_dubbing_config_from_cfg() -> DubbingConfig:
    """配音面板全局 cfg → DubbingConfig（批量配音 / 配音页线程共用）。"""
    provider = cfg.dubbing_provider.value or "edge"
    if provider not in _VALID_PROVIDERS:
        provider = "edge"

    model, base_url = _provider_defaults(provider)
    api_key = cfg.dubbing_api_key.value or ""

    raw_voice = cfg.dubbing_voice.value or ""
    voice = resolve_dubbing_voice(provider, raw_voice)
    voice = normalize_dubbing_voice(provider, model, voice)

    fit_mode, max_speed = _resolve_timing()
    mix_original, original_vol = _resolve_audio_mix()
    rewrite = bool(cfg.dubbing_adapt_length.value)
    llm_key, llm_base, llm_model = _llm_fields_for_rewrite()

    local_start_script = ""
    clone_audio_path = ""
    clone_audio_text = ""
    if provider == "dots":
        local_start_script = (cfg.dubbing_dots_start_script.value or "").strip()
        clone_audio_path = (cfg.dubbing_clone_audio_path.value or "").strip()
        clone_audio_text = (cfg.dubbing_clone_audio_text.value or "").strip()
    elif provider == "voxcpm":
        local_start_script = (cfg.dubbing_voxcpm_start_script.value or "").strip()
        clone_audio_path = (cfg.dubbing_clone_audio_path.value or "").strip()
        clone_audio_text = (cfg.dubbing_clone_audio_text.value or "").strip()

    return DubbingConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        voice=voice,
        speed=float(cfg.dubbing_speed.value),
        fit_mode=fit_mode,
        max_speed=max_speed,
        rewrite_too_long=rewrite,
        rewrite_threshold=1.15,
        llm_api_key=llm_key if rewrite else "",
        llm_api_base=llm_base if rewrite else "",
        llm_model=llm_model if rewrite else "",
        mix_original_audio=mix_original,
        original_audio_volume=original_vol,
        clone_audio_path=clone_audio_path,
        clone_audio_text=clone_audio_text,
        extra={
            "start_script": local_start_script,
            "service_start_timeout": int(cfg.dubbing_local_start_timeout.value),
            "voxcpm_version": (cfg.dubbing_voxcpm_version.value or "v2"),
        },
        fixed_line_pause=bool(cfg.dubbing_fixed_line_pause.value),
        fixed_line_pause_ms=int(cfg.dubbing_fixed_line_pause_ms.value),
    )