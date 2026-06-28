"""Adapter aligning a user transcript onto an :class:`ASRData` timeline.

The DTW core in :mod:`dtw_aligner` works on plain dicts in seconds; this
module bridges to/from VideoCaptioner's :class:`ASRData` (whose
:class:`ASRDataSeg` timings are milliseconds). The typical flow is:

    asr_result = transcribe(audio)          # accurate timestamps, rough text
    aligned = align_text_to_asr(asr_result, user_text)   # correct text, ASR timing
    aligned.to_srt() / aligned.save(...)

For a full video/audio + transcript → aligned SRT pipeline, use
:class:`TextMatchingTask` (ASR + DTW in one call).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from videocaptioner.core.asr import transcribe
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import TranscribeConfig, TranscribeModelEnum

from .dtw_aligner import align_texts, split_text_into_segments, strip_subtitle_punctuation

# Audio extensions that can be fed to ASR directly (no extraction needed).
_AUDIO_EXTENSIONS = frozenset({"flac", "m4a", "mp3", "wav", "ogg", "opus", "aac", "wma"})

ProgressCallback = Callable[[int, str], None]


def _user_text_to_sentences(
    user_text: str,
    max_chars: int,
    language: str,
    smart_split: bool,
) -> list[str]:
    """Split user transcript for DTW. ``max_chars <= 0`` = split by sentence only."""
    text = user_text.strip()
    if not text:
        return []

    if max_chars <= 0:
        # No length cap, but still split by sentence-ending punctuation so each
        # sentence becomes its own subtitle instead of feeding whole paragraphs
        # to DTW as one giant merged segment.
        return _split_into_sentences(text)

    if language == "en" and smart_split:
        return _split_english_by_words(text, max_chars)
    return split_text_into_segments(text, max_chars=max_chars)


def _split_into_sentences(text: str) -> list[str]:
    """Split by newline then sentence-ending punctuation; never merge across sentences."""
    import re

    sentences: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"([。！？.!?;；])", line)
        for i in range(0, len(parts), 2):
            chunk = parts[i]
            punct = parts[i + 1] if i + 1 < len(parts) else ""
            seg = (chunk + punct).strip()
            if seg:
                sentences.append(seg)
    return sentences if sentences else [text]


def align_text_to_asr(
    asr_data: ASRData,
    user_text: str,
    max_chars: int = 0,
    language: str = "zh",
    smart_split: bool = True,
) -> ASRData:
    """Align ``user_text`` onto ``asr_data``'s timeline via DTW.

    Args:
        asr_data: ASR result with accurate timestamps (ms) and rough text.
        user_text: the user's correct transcript (any plain text).
        max_chars: max characters per subtitle segment; ``0`` or negative = no limit.
        language: language for word-level segmentation ("en" for English, others for char-level).
        smart_split: for English with max_chars>0, split by word boundaries.

    Returns:
        A new :class:`ASRData` whose segments carry the user's text on the
        ASR's timeline (millisecond timings). Sentence punctuation is kept
        during DTW alignment for accurate splitting, then stripped from the
        final subtitle text (ASCII apostrophe ``'`` preserved).
    """
    recognized = [
        {"start": seg.start_time / 1000.0, "end": seg.end_time / 1000.0, "text": seg.text}
        for seg in asr_data.segments
    ]

    user_sentences = _user_text_to_sentences(user_text, max_chars, language, smart_split)

    aligned = align_texts(recognized, user_sentences)
    new_segments = [
        ASRDataSeg(
            text=strip_subtitle_punctuation(s["text"].strip()),
            start_time=int(round(s["start"] * 1000)),
            end_time=int(round(s["end"] * 1000)),
        )
        for s in aligned
        if strip_subtitle_punctuation(s["text"].strip())
    ]
    return ASRData(new_segments)


def _split_english_by_words(text: str, max_chars: int) -> list:
    """将英文文本按单词边界分段

    Args:
        text: 英文文本
        max_chars: 每段最大字符数

    Returns:
        分段后的文本列表
    """
    words = text.split()
    segments = []
    current_segment = []
    current_length = 0

    for word in words:
        word_length = len(word)

        # 如果加上这个单词不超过限制（考虑空格）
        if current_length + word_length + len(current_segment) <= max_chars:
            current_segment.append(word)
            current_length += word_length
        else:
            # 保存当前段
            if current_segment:
                segments.append(" ".join(current_segment))

            # 开始新段
            current_segment = [word]
            current_length = word_length

    # 添加最后一段
    if current_segment:
        segments.append(" ".join(current_segment))

    return segments


@dataclass
class TextMatchingConfig:
    """Configuration for the video/audio + transcript → aligned SRT pipeline."""

    media_path: str
    user_text: str
    output_path: str = ""
    max_chars: int = 0
    language: str = ""
    smart_split: bool = True
    # Full ASR config; if omitted, a FasterWhisper default is used. The caller
    # typically supplies this (with the chosen engine, model dir, api key, ...).
    transcribe_config: Optional[TranscribeConfig] = None


class TextMatchingTask:
    """Pipeline: media → ASR (accurate timestamps) → DTW align (correct text) → SRT.

    Reuses the existing :func:`transcribe` (any registered ASR engine) for the
    timestamp source and :func:`align_text_to_asr` for DTW alignment. Video
    input is auto-converted to audio via ffmpeg (``video2audio``).
    """

    def __init__(self, config: TextMatchingConfig):
        self.config = config

    def execute(self, callback: Optional[ProgressCallback] = None) -> Path:
        """Run the pipeline; returns the output SRT path.

        Progress callback receives ``(percent, message)`` with percent in 0-100.
        """
        cb = callback or (lambda _p, _m: None)
        cfg = self.config
        media = Path(cfg.media_path)
        if not media.exists():
            raise FileNotFoundError(f"Media file not found: {media}")
        if not cfg.user_text.strip():
            raise ValueError("user_text is empty; nothing to align")

        # 1. Ensure we have an audio file (extract from video if needed).
        cb(5, "preparing audio")
        audio_path, temp_audio = self._ensure_audio(media)
        try:
            # 2. ASR transcribe → accurate timestamps + rough text.
            cb(10, "transcribing (ASR)")
            trans_cfg = cfg.transcribe_config or self._default_transcribe_config()

            def _asr_cb(percent: int, message: str) -> None:
                # Map ASR's 0-100 onto the pipeline's 10-65 range.
                cb(10 + int(percent * 0.55), message)

            asr_data = transcribe(str(audio_path), trans_cfg, callback=_asr_cb)
            if not asr_data.segments:
                raise RuntimeError("ASR produced no segments")
        finally:
            if temp_audio and Path(temp_audio).exists():
                Path(temp_audio).unlink(missing_ok=True)

        # 3. DTW align the user's correct transcript onto the ASR timeline.
        cb(70, "aligning transcript via DTW")
        align_language = cfg.language or self._detect_align_language(cfg.user_text)
        aligned = align_text_to_asr(
            asr_data,
            cfg.user_text,
            max_chars=cfg.max_chars,
            language=align_language,
            smart_split=cfg.smart_split,
        )
        if not aligned.segments:
            raise RuntimeError("alignment produced no segments")

        # 4. Save the aligned subtitle.
        cb(95, "saving subtitle")
        out = (
            Path(cfg.output_path)
            if cfg.output_path
            else media.with_name(media.stem + ".aligned.srt")
        )
        aligned.save(str(out))
        cb(100, "completed")
        return out

    def _ensure_audio(self, media: Path) -> tuple[str, Optional[str]]:
        """Return (audio_path, temp_audio_path_or_None). Extracts audio from video."""
        ext = media.suffix.lower().lstrip(".")
        if ext in _AUDIO_EXTENSIONS:
            return str(media), None
        import tempfile

        from videocaptioner.core.utils.video_utils import video2audio

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)  # noqa: SIM115
        tmp.close()
        if not video2audio(str(media), output=tmp.name):
            Path(tmp.name).unlink(missing_ok=True)
            raise RuntimeError(
                f"Failed to extract audio from {media.name} (is ffmpeg installed / does it have an audio track?)"
            )
        return tmp.name, tmp.name

    def _default_transcribe_config(self) -> TranscribeConfig:
        """Minimal default ASR config (FasterWhisper). The caller should usually
        pass a fully-configured ``transcribe_config`` instead."""
        lang = self.config.language
        if lang == "auto":
            lang = ""
        return TranscribeConfig(
            transcribe_model=TranscribeModelEnum.FASTER_WHISPER,
            transcribe_language=lang,
            need_word_time_stamp=True,
        )

    @staticmethod
    def _detect_align_language(user_text: str) -> str:
        """Heuristic when UI language is auto."""
        import re

        if re.search(r"[a-zA-Z]", user_text) and not re.search(r"[一-鿿]", user_text):
            return "en"
        return "zh"

