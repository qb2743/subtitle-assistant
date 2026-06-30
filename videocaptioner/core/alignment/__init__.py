"""Transcript alignment: align a correct user transcript onto ASR timestamps.

Public API:

- :func:`align_text_to_asr` — adapter for :class:`ASRData` (the main entrypoint).
- :func:`align_texts` — full DTW pipeline on plain dicts (seconds).
- :func:`match_user_text_to_timestamps` — the DTW core.
- :func:`fix_overlapping_timestamps`, :func:`optimize_subtitle_duration` — post-processing.
- :func:`split_text_into_segments`, :func:`remove_punctuation` — text helpers.
"""

from .audio_boundary_snapper import snap_subtitles_to_audio_boundaries
from .dtw_aligner import (
    align_texts,
    fix_overlapping_timestamps,
    match_user_text_to_timestamps,
    optimize_subtitle_duration,
    remove_punctuation,
    split_text_into_segments,
    strip_subtitle_punctuation,
)
from .text_matcher import TextMatchingConfig, TextMatchingTask, align_text_to_asr

__all__ = [
    "TextMatchingConfig",
    "TextMatchingTask",
    "align_text_to_asr",
    "align_texts",
    "fix_overlapping_timestamps",
    "match_user_text_to_timestamps",
    "optimize_subtitle_duration",
    "remove_punctuation",
    "snap_subtitles_to_audio_boundaries",
    "split_text_into_segments",
    "strip_subtitle_punctuation",
]
