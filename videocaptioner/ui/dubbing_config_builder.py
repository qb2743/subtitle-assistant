"""Build DubbingConfig from GUI cfg — same semantics as cli/commands/dub.py."""

from __future__ import annotations

import json

from videocaptioner.core.dubbing import DubbingConfig, SpeakerProfile
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


def parse_speaker_voice_maps(raw) -> dict[str, dict[str, str]]:
    """Parse provider-scoped speaker voice mappings from GUI config."""
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(payload, dict):
        return {}

    result: dict[str, dict[str, str]] = {}
    for provider, mapping in payload.items():
        if not isinstance(mapping, dict):
            continue
        clean = {
            str(speaker).strip(): str(voice).strip()
            for speaker, voice in mapping.items()
            if str(speaker).strip() and str(voice).strip()
        }
        if clean:
            result[str(provider).strip().lower()] = clean
    return result


def speaker_voice_map_for_provider(raw, provider: str) -> dict[str, str]:
    """Return one provider's persisted ``speaker -> voice`` mapping."""
    return dict(parse_speaker_voice_maps(raw).get((provider or "").lower(), {}))


def update_speaker_voice_map(raw, provider: str, mapping: dict[str, str]) -> str:
    """Replace one provider mapping and serialize the complete config value."""
    maps = parse_speaker_voice_maps(raw)
    provider_key = (provider or "").strip().lower()
    clean = {
        str(speaker).strip(): str(voice).strip()
        for speaker, voice in mapping.items()
        if str(speaker).strip() and str(voice).strip()
    }
    if provider_key:
        if clean:
            maps[provider_key] = clean
        else:
            maps.pop(provider_key, None)
    return json.dumps(maps, ensure_ascii=False, sort_keys=True)


def _subtitle_style_fields(cfg_src) -> tuple[str, dict | None]:
    """Resolve the existing subtitle-style settings for the dubbing pipeline."""
    if not bool(cfg_src.use_subtitle_style.value) and cfg_src.dubbing_embed_subtitle.value != "hard":
        return "", None

    ass_style = ""
    try:
        from videocaptioner.core.subtitle.style_manager import load_style

        style = load_style(cfg_src.subtitle_style_name.value)
        if style is not None:
            ass_style = style.to_ass_string()
    except Exception:
        ass_style = ""

    rounded_style = {
        "font_name": cfg_src.rounded_bg_font_name.value,
        "font_size": cfg_src.rounded_bg_font_size.value,
        "bg_color": cfg_src.rounded_bg_color.value,
        "text_color": cfg_src.rounded_bg_text_color.value,
        "corner_radius": cfg_src.rounded_bg_corner_radius.value,
        "padding_h": cfg_src.rounded_bg_padding_h.value,
        "padding_v": cfg_src.rounded_bg_padding_v.value,
        "margin_bottom": cfg_src.rounded_bg_margin_bottom.value,
        "line_spacing": cfg_src.rounded_bg_line_spacing.value,
        "letter_spacing": cfg_src.rounded_bg_letter_spacing.value,
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


def _resolve_timing(cfg_src) -> tuple[FitMode, float]:
    timing = cfg_src.dubbing_timing.value or "balanced"
    explicit_max_speed = 2.0
    if timing == "none":
        return "none", explicit_max_speed
    fit_mode: FitMode = "tempo"
    if timing == "natural":
        return fit_mode, min(explicit_max_speed, 1.25)
    if timing == "strict":
        return fit_mode, max(explicit_max_speed, 2.0)
    return fit_mode, explicit_max_speed


def _resolve_audio_mix(cfg_src) -> tuple[bool, float]:
    audio_mode = cfg_src.dubbing_audio_mode.value or "replace"
    explicit_volume = 0.25
    if audio_mode == "replace":
        return False, explicit_volume
    if audio_mode == "mix":
        return True, explicit_volume
    if audio_mode == "duck":
        return True, min(explicit_volume, 0.12)
    return False, explicit_volume


def _llm_fields_for_rewrite(cfg_src) -> tuple[str, str, str]:
    """Subtitle LLM settings used when「自动调整过长行」开启。"""
    service = cfg_src.llm_service.value
    if service == LLMServiceEnum.OPENAI:
        return cfg_src.openai_api_key.value, cfg_src.openai_api_base.value, cfg_src.openai_model.value
    if service == LLMServiceEnum.SILICON_CLOUD:
        return (
            cfg_src.silicon_cloud_api_key.value,
            cfg_src.silicon_cloud_api_base.value,
            cfg_src.silicon_cloud_model.value,
        )
    if service == LLMServiceEnum.DEEPSEEK:
        return cfg_src.deepseek_api_key.value, cfg_src.deepseek_api_base.value, cfg_src.deepseek_model.value
    if service == LLMServiceEnum.OLLAMA:
        return cfg_src.ollama_api_key.value, cfg_src.ollama_api_base.value, cfg_src.ollama_model.value
    if service == LLMServiceEnum.LM_STUDIO:
        return cfg_src.lm_studio_api_key.value, cfg_src.lm_studio_api_base.value, cfg_src.lm_studio_model.value
    if service == LLMServiceEnum.GEMINI:
        return cfg_src.gemini_api_key.value, cfg_src.gemini_api_base.value, cfg_src.gemini_model.value
    if service == LLMServiceEnum.CHATGLM:
        return cfg_src.chatglm_api_key.value, cfg_src.chatglm_api_base.value, cfg_src.chatglm_model.value
    if service == LLMServiceEnum.ANTHROPIC:
        return cfg_src.anthropic_api_key.value, cfg_src.anthropic_api_base.value, cfg_src.anthropic_model.value
    return "", "", ""


def _provider_defaults(provider: str, cfg_src) -> tuple[str, str]:
    """(model, base_url) when cfg 未单独指定。"""
    api_base = (cfg_src.dubbing_api_base.value or "").strip()
    model = (cfg_src.dubbing_model.value or "").strip()

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
        return "dots-tts", (cfg_src.dubbing_dots_url.value or "http://127.0.0.1:7860").strip()
    if provider == "voxcpm":
        return "voxcpm", (cfg_src.dubbing_voxcpm_url.value or "http://127.0.0.1:9880").strip()
    return model, api_base


def create_dubbing_config_from_cfg(
    *,
    include_alignment_audio: bool = False,
    cfg_source=None,
) -> DubbingConfig:
    """Build a GUI dubbing config, opting into video-alignment audio settings.

    Args:
        cfg_source: 配置来源；批量任务传 ConfigSnapshot 固定入队时的设置，
            默认 None 使用全局 cfg（实时值）。
    """
    cfg_src = cfg_source or cfg
    provider = cfg_src.dubbing_provider.value or "edge"
    if provider not in _VALID_PROVIDERS:
        provider = "edge"

    model, base_url = _provider_defaults(provider, cfg_src)
    api_key = getattr(cfg_src, dubbing_api_key_attr(provider)).value or ""

    raw_voice = cfg_src.dubbing_voice.value or ""
    voice = resolve_dubbing_voice(provider, raw_voice)
    voice = normalize_dubbing_voice(provider, model, voice)
    narrator_only = bool(cfg_src.dubbing_narrator_only.value)
    speaker_voice_map = (
        {}
        if narrator_only
        else speaker_voice_map_for_provider(
            cfg_src.dubbing_speaker_voice_map.value, provider
        )
    )
    speaker_profiles = {
        speaker: SpeakerProfile(
            name=speaker,
            voice=normalize_dubbing_voice(provider, model, mapped_voice),
        )
        for speaker, mapped_voice in speaker_voice_map.items()
    }

    fit_mode, max_speed = _resolve_timing(cfg_src)
    mix_original, original_vol = _resolve_audio_mix(cfg_src)
    rewrite = bool(cfg_src.dubbing_adapt_length.value)
    narrator_review = bool(cfg_src.dubbing_narrator_llm_review.value)
    llm_key, llm_base, llm_model = _llm_fields_for_rewrite(cfg_src)
    subtitle_ass_style, subtitle_rounded_style = _subtitle_style_fields(cfg_src)

    local_start_script = ""
    clone_audio_path = ""
    clone_audio_text = ""
    if provider == "dots":
        local_start_script = (cfg_src.dubbing_dots_start_script.value or "").strip()
        clone_audio_path = (cfg_src.dubbing_clone_audio_path.value or "").strip()
        clone_audio_text = (cfg_src.dubbing_clone_audio_text.value or "").strip()
    elif provider == "voxcpm":
        local_start_script = (cfg_src.dubbing_voxcpm_start_script.value or "").strip()
        clone_audio_path = (cfg_src.dubbing_clone_audio_path.value or "").strip()
        clone_audio_text = (cfg_src.dubbing_clone_audio_text.value or "").strip()
    elif provider == "fishaudio":
        clone_audio_path = (cfg_src.dubbing_clone_audio_path.value or "").strip()
        clone_audio_text = (cfg_src.dubbing_clone_audio_text.value or "").strip()

    return DubbingConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        voice=voice,
        speaker_profiles=speaker_profiles,
        speed=float(cfg_src.dubbing_speed.value),
        tts_workers=int(cfg_src.dubbing_tts_workers.value),
        fit_mode=fit_mode,
        max_speed=max_speed,
        rewrite_too_long=rewrite,
        rewrite_threshold=1.15,
        llm_api_key=llm_key if (rewrite or narrator_review) else "",
        llm_api_base=llm_base if (rewrite or narrator_review) else "",
        llm_model=llm_model if (rewrite or narrator_review) else "",
        mix_original_audio=mix_original,
        original_audio_volume=original_vol,
        dubbed_audio_volume=(
            10 ** (float(cfg_src.dubbing_dubbed_audio_gain_db.value) / 20)
            if include_alignment_audio
            else 1.0
        ),
        clone_audio_path=clone_audio_path,
        clone_audio_text=clone_audio_text,
        extra={
            "start_script": local_start_script,
            "service_start_timeout": int(cfg_src.dubbing_local_start_timeout.value),
            "voxcpm_version": (cfg_src.dubbing_voxcpm_version.value or "v2"),
        },
        fixed_line_pause=bool(cfg_src.dubbing_fixed_line_pause.value),
        fixed_line_pause_ms=int(cfg_src.dubbing_fixed_line_pause_ms.value),
        subtitle_gap_ms=int(cfg_src.dubbing_subtitle_gap_ms.value),
        video_autorate=bool(cfg_src.dubbing_video_autorate.value),
        embed_subtitle=(cfg_src.dubbing_embed_subtitle.value or "none"),
        separate_vocal=(
            bool(cfg_src.dubbing_separate_vocal.value) if include_alignment_audio else False
        ),
        embed_bgm=(
            bool(cfg_src.dubbing_embed_bgm.value) if include_alignment_audio else False
        ),
        bgm_loop=(
            bool(cfg_src.dubbing_bgm_loop.value) if include_alignment_audio else True
        ),
        bgm_volume=(
            float(cfg_src.dubbing_bgm_volume.value) if include_alignment_audio else 0.8
        ),
        extra_bgm_path=(
            (cfg_src.dubbing_extra_bgm_path.value or "")
            if include_alignment_audio
            else ""
        ),
        enable_diarization=bool(cfg_src.dubbing_enable_diarization.value),
        speaker_count=int(cfg_src.dubbing_speaker_count.value),
        narrator_only=narrator_only,
        narrator_llm_review=narrator_review,
        diarization_language=diarization_language_from_transcribe(
            cfg_src.transcribe_language.value
        ),
        random_mirror=bool(getattr(cfg_src, "dubbing_random_mirror").value),
        random_color=bool(getattr(cfg_src, "dubbing_random_color").value),
        canvas=str(getattr(cfg_src, "dubbing_canvas").value or "off"),
        output_dir=str(getattr(cfg_src, "dubbing_output_dir").value or ""),
        subtitle_render_mode=cfg_src.subtitle_render_mode.value,
        subtitle_layout=cfg_src.subtitle_layout.value,
        subtitle_ass_style=subtitle_ass_style,
        subtitle_rounded_style=subtitle_rounded_style,
    )
