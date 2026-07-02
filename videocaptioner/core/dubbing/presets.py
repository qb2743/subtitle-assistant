"""Dubbing provider/model/voice presets."""

from dataclasses import dataclass

SILICONFLOW_COSYVOICE2_MODEL = "FunAudioLLM/CosyVoice2-0.5B"

SILICONFLOW_VOICE_ALIASES = {
    "anna": f"{SILICONFLOW_COSYVOICE2_MODEL}:anna",
    "alex": f"{SILICONFLOW_COSYVOICE2_MODEL}:alex",
    "benjamin": f"{SILICONFLOW_COSYVOICE2_MODEL}:benjamin",
}

GEMINI_VOICES = {
    "Achird",
    "Aoede",
    "Autonoe",
    "Callirrhoe",
    "Charon",
    "Despina",
    "Enceladus",
    "Erinome",
    "Fenrir",
    "Gacrux",
    "Iapetus",
    "Kore",
    "Laomedeia",
    "Leda",
    "Orus",
    "Puck",
    "Pulcherrima",
    "Rasalgethi",
    "Sadachbia",
    "Sadaltager",
    "Schedar",
    "Sulafat",
    "Umbriel",
    "Vindemiatrix",
    "Zephyr",
    "Zubenelgenubi",
}

# Fish Audio 官方默认音色（始终可用，不依赖账户自建）。
# 取自 fish.audio/app/default-voices/ 当前 8 个默认音色，reference_id 已通过
# GET /model/<id> 逐个验证（2026-07-02）。旧版 Brian/Dolly 已从默认页移除。
FISHAUDIO_PRESET_VOICES = [
    ("Ethan", "536d3a5e000945adb7038665781a4aca"),
    ("Sarah", "933563129e564b19a115bedd57b7406a"),
    ("Selene", "b347db033a6549378b48d00acb0d06cd"),
    ("Adrian", "bf322df2096a46f18c579d0baa36f41d"),
    ("E-girl", "98655a12fa944e26b274c535e5e03842"),
    ("Hannah", "9a9cf47702da476aa4629e2506d4a857"),
    ("Jordan", "79d0bd3e4e5444b18f7b6d89b5927bf1"),
    ("Laura", "e3cd384158934cc9a01029cd7d278634"),
]

EDGE_VOICE_ALIASES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
    "yunjian": "zh-CN-YunjianNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "yunyang": "zh-CN-YunyangNeural",
    "jenny": "en-US-JennyNeural",
    "guy": "en-US-GuyNeural",
    "aria": "en-US-AriaNeural",
}


@dataclass(frozen=True)
class ElevenLabsVoice:
    """One ElevenLabs premade voice with a friendly alias."""

    alias: str       # short lowercase key, e.g. "roger"
    name: str        # ElevenLabs descriptive name, e.g. "Roger - Laid-Back Casual Resonant"
    voice_id: str    # native voice ID passed to the SDK


# Ported from pyvideotrans voicejson/elevenlabs.json (ElevenLabs premade
# library voices) plus Rachel. These are static convenience entries; the
# authoritative list of voices available to a given API key is fetched
# dynamically via ``list_elevenlabs_voices``.
ELEVENLABS_PREMADE_VOICES: list[ElevenLabsVoice] = [
    ElevenLabsVoice("rachel", "Rachel", "21m00Tcm4TlvDq8ikWAM"),
    ElevenLabsVoice("roger", "Roger - Laid-Back Casual Resonant", "CwhRBWXzGAHq8TQ4Fs17"),
    ElevenLabsVoice("sarah", "Sarah - Mature Reassuring Confident", "EXAVITQu4vr4xnSDxMaL"),
    ElevenLabsVoice("laura", "Laura - Enthusiast Quirky Attitude", "FGY2WhTYpPnrIDTdsKH5"),
    ElevenLabsVoice("charlie", "Charlie - Deep Confident Energetic", "IKne3meq5aSn9XLyUdCD"),
    ElevenLabsVoice("george", "George - Warm Captivating Storyteller", "JBFqnCBsd6RMkjVDRZzb"),
    ElevenLabsVoice("callum", "Callum - Husky Trickster", "N2lVS1w4EtoT3dr4eOWO"),
    ElevenLabsVoice("river", "River - Relaxed Neutral Informative", "SAz9YHcvj6GT2YYXdXww"),
    ElevenLabsVoice("harry", "Harry - Fierce Warrior", "SOYHLrjzK2X1ezoPC6cr"),
    ElevenLabsVoice("liam", "Liam - Energetic Social Media Creator", "TX3LPaxmHKxFdv7VOQHJ"),
    ElevenLabsVoice("alice", "Alice - Clear Engaging Educator", "Xb7hH8MSUJpSbSDYk0k2"),
    ElevenLabsVoice("matilda", "Matilda - Knowledgable Professional", "XrExE9yKIg1WjnnlVkGX"),
    ElevenLabsVoice("will", "Will - Relaxed Optimist", "bIHbv24MWmeRgasZH58o"),
    ElevenLabsVoice("jessica", "Jessica - Playful Bright Warm", "cgSgspJ2msm6clMCkdW9"),
    ElevenLabsVoice("eric", "Eric - Smooth Trustworthy", "cjVigY5qzO86Huf0OWal"),
    ElevenLabsVoice("bella", "Bella - Professional Bright Warm", "hpp4J3VqNfWAUOO0d1Us"),
    ElevenLabsVoice("chris", "Chris - Charming Down-to-Earth", "iP95p4xoKVk53GoZ742B"),
    ElevenLabsVoice("brian", "Brian - Deep Resonant and Comforting", "nPczCjzI2devNBz1zQrb"),
    ElevenLabsVoice("daniel", "Daniel - Steady Broadcaster", "onwK4e9ZLuTAKqWW03F9"),
    ElevenLabsVoice("lily", "Lily - Velvety Actress", "pFZP5JQG7iQjIQuC4Bku"),
    ElevenLabsVoice("adam", "Adam - Dominant Firm", "pNInz6obpgDQGcFmaJgB"),
    ElevenLabsVoice("bill", "Bill - Wise Mature Balanced", "pqHfZKP75CvOlQylNhV4"),
    ElevenLabsVoice("brian-classic", "Brian", "1Q14Hl4wBAL1DIHYXY2j"),
]

# Accepted voice keys (short alias or full descriptive name, case-insensitive)
# mapped to the native voice ID. Raw voice IDs (custom/cloned/library voices
# not in this catalog) are passed through unchanged by normalize_dubbing_voice.
ELEVENLABS_VOICE_ALIASES: dict[str, str] = {}
for _voice in ELEVENLABS_PREMADE_VOICES:
    ELEVENLABS_VOICE_ALIASES[_voice.alias] = _voice.voice_id
    ELEVENLABS_VOICE_ALIASES[_voice.name.lower()] = _voice.voice_id
del _voice


@dataclass(frozen=True)
class DubbingPreset:
    name: str
    provider: str
    api_base: str
    model: str
    voice: str
    style_prompt: str = ""


PRESETS: dict[str, DubbingPreset] = {
    "siliconflow-cn-female": DubbingPreset(
        name="siliconflow-cn-female",
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES["anna"],
        style_prompt="请用自然、清晰、适合视频配音的中文语气朗读。",
    ),
    "siliconflow-cn-male": DubbingPreset(
        name="siliconflow-cn-male",
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES["alex"],
        style_prompt="请用自然、清晰、适合视频配音的中文语气朗读。",
    ),
    "siliconflow-cn-deep-male": DubbingPreset(
        name="siliconflow-cn-deep-male",
        provider="siliconflow",
        api_base="https://api.siliconflow.cn/v1",
        model=SILICONFLOW_COSYVOICE2_MODEL,
        voice=SILICONFLOW_VOICE_ALIASES["benjamin"],
        style_prompt="请用沉稳、清晰、适合视频配音的中文语气朗读。",
    ),
    "gemini-en-neutral": DubbingPreset(
        name="gemini-en-neutral",
        provider="gemini",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        style_prompt="Read naturally and clearly for a video dubbing track.",
    ),
    "gemini-en-friendly": DubbingPreset(
        name="gemini-en-friendly",
        provider="gemini",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.1-flash-tts-preview",
        voice="Achird",
        style_prompt="Read in a friendly, natural, conversational voice for a video dubbing track.",
    ),
    "gemini-en-upbeat": DubbingPreset(
        name="gemini-en-upbeat",
        provider="gemini",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-3.1-flash-tts-preview",
        voice="Puck",
        style_prompt="Read in an upbeat, clear, energetic voice for a video dubbing track.",
    ),
    "edge-cn-female": DubbingPreset(
        name="edge-cn-female",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["xiaoxiao"],
    ),
    "edge-cn-male": DubbingPreset(
        name="edge-cn-male",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["yunxi"],
    ),
    "edge-en-female": DubbingPreset(
        name="edge-en-female",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["jenny"],
    ),
    "edge-en-male": DubbingPreset(
        name="edge-en-male",
        provider="edge",
        api_base="",
        model="edge-tts",
        voice=EDGE_VOICE_ALIASES["guy"],
    ),
    "elevenlabs-multilingual-female": DubbingPreset(
        name="elevenlabs-multilingual-female",
        provider="elevenlabs",
        api_base="",
        model="eleven_multilingual_v2",
        voice=ELEVENLABS_VOICE_ALIASES["rachel"],
    ),
    "elevenlabs-multilingual-male": DubbingPreset(
        name="elevenlabs-multilingual-male",
        provider="elevenlabs",
        api_base="",
        model="eleven_multilingual_v2",
        voice=ELEVENLABS_VOICE_ALIASES["adam"],
    ),
    "elevenlabs-narrator": DubbingPreset(
        name="elevenlabs-narrator",
        provider="elevenlabs",
        api_base="",
        model="eleven_multilingual_v2",
        voice=ELEVENLABS_VOICE_ALIASES["george"],
        style_prompt="Read in a warm, captivating storyteller tone for a video dubbing track.",
    ),
}


def get_dubbing_preset(name: str) -> DubbingPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown dubbing preset: {name}. Available presets: {available}") from exc


def available_dubbing_presets() -> list[str]:
    return sorted(PRESETS)


def normalize_dubbing_voice(provider: str, model: str, voice: str) -> str:
    """Convert user-facing voice names to provider-native voice IDs."""
    if not voice:
        return voice
    if provider == "siliconflow":
        lowered = voice.lower()
        if lowered in SILICONFLOW_VOICE_ALIASES:
            return SILICONFLOW_VOICE_ALIASES[lowered]
        if ":" not in voice and "/" not in voice:
            return f"{model}:{voice}"
        return voice
    if provider == "gemini":
        for known in GEMINI_VOICES:
            if voice.lower() == known.lower():
                return known
        return voice
    if provider == "edge":
        lowered = voice.lower()
        if lowered in EDGE_VOICE_ALIASES:
            return EDGE_VOICE_ALIASES[lowered]
        return voice
    if provider == "elevenlabs":
        lowered = voice.strip().lower()
        if lowered in ELEVENLABS_VOICE_ALIASES:
            return ELEVENLABS_VOICE_ALIASES[lowered]
        # Not a known alias: assume it is a raw voice ID (custom/cloned/
        # library voice) and pass it through unchanged.
        return voice
    if provider == "fishaudio":
        # Fish Audio voice = a model _id (from /model upload) or a preset
        # reference_id; both are opaque tokens, pass through unchanged.
        return voice
    return voice


def validate_dubbing_voice(provider: str, voice: str) -> str | None:
    """Return an error message when a voice does not match provider constraints."""
    if not voice:
        return None
    if provider == "gemini" and voice not in GEMINI_VOICES:
        available = ", ".join(sorted(GEMINI_VOICES))
        return f"Unknown Gemini voice: {voice}. Available voices: {available}"
    if provider == "siliconflow" and ":" not in voice:
        return "SiliconFlow voice must be a built-in alias or a provider voice ID like model:voice"
    if provider == "edge":
        normalized = normalize_dubbing_voice(provider, "", voice)
        if normalized in EDGE_VOICE_ALIASES.values():
            return None
        if not normalized.endswith("Neural") or normalized.count("-") < 2:
            aliases = ", ".join(sorted(EDGE_VOICE_ALIASES))
            return f"Edge TTS voice must be a short alias ({aliases}) or a full voice ID like zh-CN-XiaoxiaoNeural"
    if provider == "elevenlabs":
        normalized = normalize_dubbing_voice(provider, "", voice)
        if normalized in ELEVENLABS_VOICE_ALIASES.values():
            return None
        # Otherwise accept any opaque token as a raw voice ID (the user's
        # cloned/library voices are not in the static catalog). Flag only
        # obvious mistakes such as descriptive names with spaces.
        stripped = voice.strip()
        if stripped and not any(ch.isspace() for ch in stripped):
            return None
        aliases = ", ".join(sorted(v.alias for v in ELEVENLABS_PREMADE_VOICES))
        return (
            f"ElevenLabs voice must be a short alias ({aliases}), a full voice "
            f"name, or a raw voice ID. Got: {voice!r}"
        )
    if provider == "fishaudio":
        # Voice is an opaque model _id / reference_id (from Fish /model upload
        # or a shared model). Accept any non-empty token; empty is also OK
        # (Fish falls back to the base model's default voice).
        return None
    return None


def elevenlabs_voice_options() -> list[ElevenLabsVoice]:
    """Return the static catalog of ElevenLabs premade voices (for UI/CLI)."""
    return list(ELEVENLABS_PREMADE_VOICES)
