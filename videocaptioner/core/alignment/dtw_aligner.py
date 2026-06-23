"""DTW-based transcript alignment (ported from txt2srt).

Given ASR-recognized segments that carry accurate timestamps and a
user-supplied correct transcript, this module aligns the user's text onto the
recognized timeline using character-level Dynamic Time Warping. The output is
the user's correct text with the ASR's accurate timing.

Pipeline (see :func:`align_texts`):

1. :func:`match_user_text_to_timestamps` — DTW-align the user's character
   sequence to the recognized character sequence and interpolate a timestamp
   for every user character, then group characters back into user sentences.
2. :func:`fix_overlapping_timestamps` — enforce strictly non-overlapping,
   in-order segments with sane min/max durations.
3. :func:`optimize_subtitle_duration` — fill small inter-segment gaps.

Data format used internally (seconds, floats)::

    {"start": float, "end": float, "text": str}
"""

import re
from typing import Dict, List

import numpy as np
from dtw import dtw

from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("alignment.dtw")

# CJK + ASCII punctuation and whitespace stripped before char-level matching.
_PUNCTUATION = set("。，！？；：、,.!?;: 　「」『』“”‘’（）()【】[]")

# Punctuation removed from final subtitle text (apostrophe ' and spaces kept).
_SUBTITLE_STRIP_PUNCT = set(
    "。，！？；：、,.!?;:　「」『』“”‘’（）()【】[]\"\"…—–·《》〈〉"
)


def strip_subtitle_punctuation(text: str) -> str:
    """Remove punctuation from displayed subtitle text; keep ASCII apostrophe '."""
    if not text:
        return text
    return "".join(c for c in text if c not in _SUBTITLE_STRIP_PUNCT)


def remove_punctuation(text: str) -> str:
    """Strip CJK + ASCII punctuation and whitespace for char-level matching."""
    return "".join(c for c in text if c.strip() and c not in _PUNCTUATION)


def split_text_into_segments(text: str, max_chars: int = 30) -> List[str]:
    """Split long text into subtitle-friendly short sentences.

    Priority: newlines → sentence punctuation (。！？；.!?;) → comma punctuation
    (，,、) → hard char-count split. Each returned segment is ≤ ``max_chars``
    where possible.
    """
    segments: List[str] = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Split on major sentence punctuation, keeping the punctuation.
        sentences = re.split(r"([。！？；.!?;])", line)
        current_segment = ""
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            punct = sentences[i + 1] if i + 1 < len(sentences) else ""
            if not sentence.strip():
                continue
            full_sentence = sentence + punct
            potential = current_segment + full_sentence
            if len(potential) <= max_chars:
                current_segment = potential
            else:
                if current_segment:
                    segments.append(current_segment.strip())
                if len(full_sentence) <= max_chars:
                    current_segment = full_sentence
                else:
                    sub_segments = _split_long_sentence(full_sentence, max_chars)
                    for sub in sub_segments[:-1]:
                        segments.append(sub.strip())
                    current_segment = sub_segments[-1] if sub_segments else ""
        if current_segment.strip():
            segments.append(current_segment.strip())

    return segments


def _split_long_sentence(sentence: str, max_chars: int) -> List[str]:
    """Split a sentence that exceeds ``max_chars`` (by comma, then by chars)."""
    if len(sentence) <= max_chars:
        return [sentence]

    segments: List[str] = []
    parts = re.split(r"([，,、])", sentence)
    current = ""
    for i in range(0, len(parts), 2):
        part = parts[i]
        comma = parts[i + 1] if i + 1 < len(parts) else ""
        if not part.strip():
            continue
        full_part = part + comma
        potential = current + full_part
        if len(potential) <= max_chars:
            current = potential
        else:
            if current:
                segments.append(current.strip())
            if len(full_part) > max_chars:
                force_split = _force_split_by_chars(full_part, max_chars)
                segments.extend(force_split[:-1])
                current = force_split[-1] if force_split else ""
            else:
                current = full_part
    if current.strip():
        segments.append(current.strip())
    return segments if segments else [sentence]


def _force_split_by_chars(text: str, max_chars: int) -> List[str]:
    """Hard-split text by char count, preferring to break at a comma/space."""
    segments: List[str] = []
    while len(text) > max_chars:
        split_pos = max_chars
        for i in range(max_chars - 1, max(0, max_chars - 10), -1):
            if text[i] in "，,、 　":
                split_pos = i + 1
                break
        segments.append(text[:split_pos].strip())
        text = text[split_pos:].strip()
    if text:
        segments.append(text)
    return segments


def match_user_text_to_timestamps(
    recognized_segments: List[Dict],
    user_sentences: List[str],
) -> List[Dict]:
    """DTW-align user sentences onto recognized segment timestamps.

    Args:
        recognized_segments: ASR output, ``[{"start", "end", "text"}]`` (seconds).
        user_sentences: the user's correct transcript, split into sentences.

    Returns:
        Aligned segments ``[{"start", "end", "text"}]`` (seconds) using the
        user's text on the recognized timeline.
    """
    if not recognized_segments or not user_sentences:
        logger.debug("Empty recognized segments or user sentences; nothing to align")
        return []

    recognized_chars = list(remove_punctuation("".join(seg["text"] for seg in recognized_segments)))
    user_chars = list(remove_punctuation("".join(user_sentences)))
    n_user = len(user_chars)
    n_recognized = len(recognized_chars)
    if n_user == 0 or n_recognized == 0:
        logger.debug("No characters left after punctuation removal; nothing to align")
        return []

    logger.debug("Aligning %d user chars to %d recognized chars", n_user, n_recognized)

    # Char-level distance matrix (0 = same char, 1 = different), vectorized.
    # dtw-python's Cython backend requires float64 ("double").
    user_arr = np.array(user_chars, dtype="U1")[:, None]
    rec_arr = np.array(recognized_chars, dtype="U1")[None, :]
    distance_matrix = (user_arr != rec_arr).astype(np.float64)

    alignment = dtw(distance_matrix)
    path = list(zip(alignment.index1, alignment.index2))
    match_rate = (1 - alignment.normalizedDistance) * 100
    logger.debug("DTW similarity: %.1f%%", match_rate)

    # Map each recognized char index -> its owning segment + position.
    recognized_char_to_segment: List[Dict] = []
    for seg_idx, segment in enumerate(recognized_segments):
        seg_text = remove_punctuation(segment["text"])
        total = len(seg_text)
        for char_idx in range(total):
            recognized_char_to_segment.append(
                {"seg_idx": seg_idx, "char_idx": char_idx, "total_chars": total, "segment": segment}
            )

    # For each user char, the recognized segment it maps to (via the DTW path).
    user_char_to_segment: List = [None] * n_user
    for user_idx, rec_idx in path:
        if rec_idx < len(recognized_char_to_segment):
            user_char_to_segment[user_idx] = recognized_char_to_segment[rec_idx]

    # Interpolate a timestamp for each user char within its mapped segment.
    last_end = recognized_segments[-1]["end"]
    user_char_times: List = [None] * n_user
    for i in range(n_user):
        seg_info = user_char_to_segment[i]
        if seg_info is None:
            continue
        segment = seg_info["segment"]
        segment_duration = segment["end"] - segment["start"]
        total = seg_info["total_chars"]
        if total > 0:
            user_char_times[i] = segment["start"] + (seg_info["char_idx"] / total) * segment_duration
        else:
            user_char_times[i] = segment["start"]

    # Linear interpolation for any user char that did not match.
    for i in range(n_user):
        if user_char_times[i] is not None:
            continue
        prev_time = 0.0
        for j in range(i - 1, -1, -1):
            if user_char_times[j] is not None:
                prev_time = user_char_times[j]
                break
        next_time = last_end
        for j in range(i + 1, n_user):
            if user_char_times[j] is not None:
                next_time = user_char_times[j]
                break
        user_char_times[i] = (prev_time + next_time) / 2

    # Consume user chars sentence-by-sentence to assign each sentence a span.
    aligned_segments: List[Dict] = []
    char_idx = 0
    for sentence in user_sentences:
        if not sentence.strip():
            continue
        sentence_chars = remove_punctuation(sentence)
        if len(sentence_chars) == 0:
            if aligned_segments:
                last = aligned_segments[-1]["end"]
                aligned_segments.append({"start": last, "end": last + 0.5, "text": sentence.strip()})
            continue

        start_char_idx = char_idx
        end_char_idx = min(char_idx + len(sentence_chars), n_user)
        if start_char_idx >= n_user:
            if aligned_segments:
                last = aligned_segments[-1]["end"]
                aligned_segments.append(
                    {"start": last, "end": last + len(sentence_chars) * 0.15, "text": sentence.strip()}
                )
            break

        start_time = user_char_times[start_char_idx]
        end_time = user_char_times[min(end_char_idx - 1, n_user - 1)]
        if end_time - start_time < 0.5:
            end_time = start_time + max(0.5, len(sentence_chars) * 0.15)
        aligned_segments.append({"start": start_time, "end": end_time, "text": sentence.strip()})
        char_idx = end_char_idx

    if len(aligned_segments) < len(user_sentences):
        logger.debug(
            "%d sentence(s) could not be matched; estimated durations used",
            len(user_sentences) - len(aligned_segments),
        )
    return aligned_segments


def fix_overlapping_timestamps(segments: List[Dict]) -> List[Dict]:
    """Enforce strictly non-overlapping, in-order segments with sane durations."""
    if not segments:
        return segments

    segments = sorted(segments, key=lambda x: x["start"])
    fixed: List[Dict] = []
    duration_fixed = 0

    for i, segment in enumerate(segments):
        start = segment["start"]
        end = segment["end"]
        text = segment["text"]
        text_chars = len(remove_punctuation(text))
        max_duration = max(3.0, 1.0 + text_chars * 0.25)
        min_duration = max(1.0, 0.5 + text_chars * 0.15)

        if i > 0:
            prev_end = fixed[-1]["end"]
            if start < prev_end:
                start = prev_end

        duration = end - start
        if duration > max_duration:
            end = start + max_duration
            duration = end - start
            duration_fixed += 1
        if duration < min_duration:
            end = start + min_duration

        if end <= start:
            end = start + max(1.0, text_chars * 0.15)

        if i + 1 < len(segments):
            next_start = segments[i + 1]["start"]
            if end > next_start:
                end = next_start

        if end <= start:
            end = start + 0.5

        fixed.append({"start": start, "end": end, "text": text})

    if duration_fixed:
        logger.debug("Fixed %d over-long duration(s)", duration_fixed)
    return fixed


def optimize_subtitle_duration(segments: List[Dict], max_extension: float = 0.5) -> List[Dict]:
    """Fill small inter-segment gaps (and extend the last segment) for readability."""
    if not segments:
        return segments
    for i in range(len(segments) - 1):
        curr = segments[i]
        gap = segments[i + 1]["start"] - curr["end"]
        if gap > 0:
            extend_by = min(max_extension, gap - 0.1)
            if extend_by > 0:
                curr["end"] += extend_by
    segments[-1]["end"] += 0.5
    return segments


def align_texts(
    recognized_segments: List[Dict],
    user_sentences: List[str],
) -> List[Dict]:
    """Full alignment pipeline: DTW match → fix overlaps → optimize durations."""
    aligned = match_user_text_to_timestamps(recognized_segments, user_sentences)
    aligned = fix_overlapping_timestamps(aligned)
    aligned = optimize_subtitle_duration(aligned)
    return aligned
