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

ELEVENLABS_MODEL_ITEMS = [
    "eleven_flash_v2_5 - Flash v2.5 快速（推荐）",
    "eleven_multilingual_v2 - Multilingual v2 高保真",
    "eleven_v3 - v3 最强表现力 70+语言",
    "eleven_turbo_v2_5 - Turbo v2.5 快速",
    "eleven_monolingual_v1 - Monolingual v1 仅英文",
]

FISHAUDIO_MODEL_ITEMS = [
    "s2.1-pro - s2.1 Pro 高保真（推荐）",
    "s2.1-pro-free - s2.1 Pro 免费版（开发测试）",
    "s2-pro - s2 Pro（上一代）",
    "s1 - s1（旧版，13 语种）",
]

_MODEL_ITEMS_BY_PROVIDER = {
    "elevenlabs": ELEVENLABS_MODEL_ITEMS,
    "fishaudio": FISHAUDIO_MODEL_ITEMS,
}

_DEFAULT_MODELS = {
    "edge": "edge-tts",
    "elevenlabs": "eleven_flash_v2_5",
    "gemini": "gemini-3.1-flash-tts-preview",
    "siliconflow": "FunAudioLLM/CosyVoice2-0.5B",
    "openai": "tts-1",
    "fishaudio": "s2.1-pro",
    "dots": "dots-tts",
    "voxcpm": "voxcpm",
}


def dubbing_model_options(provider: str) -> list[tuple[str, str]]:
    """Return display text and model id for providers with model choices."""
    return [
        (item, item.split(" - ", 1)[0])
        for item in _MODEL_ITEMS_BY_PROVIDER.get(provider, ())
    ]


def resolve_dubbing_model(provider: str, model: str) -> str:
    """Keep Fish Audio and ElevenLabs models within their provider."""
    model = (model or "").strip()
    options = dubbing_model_options(provider)
    if options:
        valid = {model_id for _text, model_id in options}
        return model if model in valid else options[0][1]
    return model or _DEFAULT_MODELS.get(provider, "")


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
    if provider == "fishaudio":
        # Fish Audio 音色 = reference_id（model _id），直接透传；空则由
        # Fish 回退到 base model 默认音色。
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
    "fishaudio",
)

_DEFAULT_SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"
_DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_SILICONFLOW_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
_DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-tts-preview"
_DEFAULT_FISHAUDIO_BASE = "https://api.fish.audio"

_DUBBING_API_KEY_ATTRS = {
    "elevenlabs": "dubbing_api_key_elevenlabs",
    "siliconflow": "dubbing_api_key_siliconflow",
    "openai": "dubbing_api_key_openai",
    "gemini": "dubbing_api_key_gemini",
    "fishaudio": "dubbing_api_key_fishaudio",
}


def _subtitle_style_fields() -> tuple[str, dict | None]:
    """Resolve the existing subtitle-style settings for the dubbing pipeline."""
    if not bool(cfg.use_subtitle_style.value) and cfg.dubbing_embed_subtitle.value != "hard":
        return "", None

    ass_style = ""
    try:
        from videocaptioner.core.subtitle.style_manager import load_style

        style = load_style(cfg.subtitle_style_name.value)
        if style is not None:
            ass_style = style.to_ass_string()
    except Exception:
        ass_style = ""

    rounded_style = {
        "font_name": cfg.rounded_bg_font_name.value,
        "font_size": cfg.rounded_bg_font_size.value,
        "bg_color": cfg.rounded_bg_color.value,
        "text_color": cfg.rounded_bg_text_color.value,
        "corner_radius": cfg.rounded_bg_corner_radius.value,
        "padding_h": cfg.rounded_bg_padding_h.value,
        "padding_v": cfg.rounded_bg_padding_v.value,
        "margin_bottom": cfg.rounded_bg_margin_bottom.value,
        "line_spacing": cfg.rounded_bg_line_spacing.value,
        "letter_spacing": cfg.rounded_bg_letter_spacing.value,
    }
    return ass_style, rounded_style


def dubbing_api_key_attr(provider: str) -> str:
    """该 provider 在 cfg 上对应的 API Key 属性名；无独立字段回退到旧的 dubbing_api_key。"""
    return _DUBBING_API_KEY_ATTRS.get(provider, "dubbing_api_key")


def diarization_language_from_transcribe(language) -> str:
    """Map the transcription language to the matching speaker embedding."""
    name = getattr(language, "name", "")
    if name in {"CHINESE", "YUE"}:
        return "zh"
    if name == "ENGLISH":
        return "en"
    if name == "AUTO":
        return "auto"
    return "multi"


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
        return resolve_dubbing_model(provider, model), ""
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
    if provider == "fishaudio":
        model = resolve_dubbing_model(provider, model)
        if not api_base:
            api_base = _DEFAULT_FISHAUDIO_BASE
        return model, api_base
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
    api_key = getattr(cfg, dubbing_api_key_attr(provider)).value or ""

    raw_voice = cfg.dubbing_voice.value or ""
    voice = resolve_dubbing_voice(provider, raw_voice)
    voice = normalize_dubbing_voice(provider, model, voice)

    fit_mode, max_speed = _resolve_timing()
    mix_original, original_vol = _resolve_audio_mix()
    rewrite = bool(cfg.dubbing_adapt_length.value)
    narrator_review = bool(cfg.dubbing_narrator_llm_review.value)
    llm_key, llm_base, llm_model = _llm_fields_for_rewrite()
    subtitle_ass_style, subtitle_rounded_style = _subtitle_style_fields()

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
    elif provider == "fishaudio":
        clone_audio_path = (cfg.dubbing_clone_audio_path.value or "").strip()
        clone_audio_text = (cfg.dubbing_clone_audio_text.value or "").strip()

    return DubbingConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        voice=voice,
        speed=float(cfg.dubbing_speed.value),
        tts_workers=int(cfg.dubbing_tts_workers.value),
        fit_mode=fit_mode,
        max_speed=max_speed,
        rewrite_too_long=rewrite,
        rewrite_threshold=1.15,
        llm_api_key=llm_key if (rewrite or narrator_review) else "",
        llm_api_base=llm_base if (rewrite or narrator_review) else "",
        llm_model=llm_model if (rewrite or narrator_review) else "",
        mix_original_audio=mix_original,
        original_audio_volume=original_vol,
        dubbed_audio_volume=10
        ** (float(cfg.dubbing_dubbed_audio_gain_db.value) / 20),
        clone_audio_path=clone_audio_path,
        clone_audio_text=clone_audio_text,
        extra={
            "start_script": local_start_script,
            "service_start_timeout": int(cfg.dubbing_local_start_timeout.value),
            "voxcpm_version": (cfg.dubbing_voxcpm_version.value or "v2"),
        },
        fixed_line_pause=bool(cfg.dubbing_fixed_line_pause.value),
        fixed_line_pause_ms=int(cfg.dubbing_fixed_line_pause_ms.value),
        subtitle_gap_ms=int(cfg.dubbing_subtitle_gap_ms.value),
        video_autorate=bool(cfg.dubbing_video_autorate.value),
        embed_subtitle=(cfg.dubbing_embed_subtitle.value or "none"),
        separate_vocal=bool(cfg.dubbing_separate_vocal.value),
        embed_bgm=bool(cfg.dubbing_embed_bgm.value),
        bgm_loop=bool(cfg.dubbing_bgm_loop.value),
        bgm_volume=float(cfg.dubbing_bgm_volume.value),
        extra_bgm_path=(cfg.dubbing_extra_bgm_path.value or ""),
        enable_diarization=bool(cfg.dubbing_enable_diarization.value),
        speaker_count=int(cfg.dubbing_speaker_count.value),
        narrator_only=bool(cfg.dubbing_narrator_only.value),
        narrator_llm_review=narrator_review,
        diarization_language=diarization_language_from_transcribe(
            cfg.transcribe_language.value
        ),
        random_mirror=bool(getattr(cfg, "dubbing_random_mirror").value),
        random_color=bool(getattr(cfg, "dubbing_random_color").value),
        canvas=str(getattr(cfg, "dubbing_canvas").value or "off"),
        output_dir=str(getattr(cfg, "dubbing_output_dir").value or ""),
        subtitle_render_mode=cfg.subtitle_render_mode.value,
        subtitle_layout=cfg.subtitle_layout.value,
        subtitle_ass_style=subtitle_ass_style,
        subtitle_rounded_style=subtitle_rounded_style,
    )
