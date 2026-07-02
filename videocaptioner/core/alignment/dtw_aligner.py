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

# Punctuation removed from final subtitle text (ASCII apostrophe ' and spaces kept;
# curly quotes ‘ ’ “ ” are stripped — English normalizes ’ to ' first so it survives).
_SUBTITLE_STRIP_PUNCT = set(
    "。，！？；：、,.!?;:　「」『』“”‘’（）()【】[]\"\"…—–·《》〈〉"
)


# Contractions/possessives where ' is an apostrophe, not a quote: Juho's, don't,
# they're, we've, you'll, I'm, she'd. Curly ' is what sources usually ship.
_ENGLISH_APOSTROPHE = re.compile(r"[’‘]['‘]?(?:s|t|re|ve|ll|m|d)\b", re.IGNORECASE)


def _should_normalize_apostrophe(text: str, language: str) -> bool:
    """True when ' is used as an English apostrophe, not a quote punctuation.

    Explicit English (``language`` starts with "en") → always. Otherwise detect
    an English contraction/possessive pattern in the text so French/Spanish/etc.
    quote usage ('¡hola!') is not mistreated.
    """
    if language.lower().startswith("en"):
        return True
    return bool(_ENGLISH_APOSTROPHE.search(text))


def strip_subtitle_punctuation(text: str, language: str = "") -> str:
    """Remove punctuation from displayed subtitle text; keep ASCII apostrophe '.

    Curly apostrophes (' ') are normalized to ASCII ' when the text is English
    (explicit ``language`` = "en", or an English contraction/possessive like
    "Juho's", "don't" is detected). In other languages ' ' are quote
    punctuation and are stripped, not normalized.
    """
    if not text:
        return text
    if _should_normalize_apostrophe(text, language):
        text = text.replace("‘", "'").replace("’", "'")
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
    allow_pause_split: bool = True,
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
    # Track each stripped user char's index in the original joined text so that
    # after gap-splitting we can slice the original text (preserving spaces /
    # mid-sentence punctuation) for each sub-segment.
    user_text_full = "".join(user_sentences)
    _stripped = [(c, i) for i, c in enumerate(user_text_full) if c.strip() and c not in _PUNCTUATION]
    user_chars = [c for c, _ in _stripped]
    orig_positions = [p for _, p in _stripped]
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

    # Group user chars back into subtitle segments. Within each user sentence,
    # split at *relative* pauses: a gap that is much larger than the sentence's
    # typical inter-char gap means the speaker paused → start a new subtitle.
    # Relative (not absolute) so evenly-spaced ASR text isn't over-split, while
    # real pauses — gaps several× the median — still break long punctuation-less
    # sentences at natural speech pauses.
    PAUSE_RATIO = 3.0
    PAUSE_MIN = 0.25

    def _char_end_time(idx: int) -> float:
        """End time of a user char = end of the recognized word it maps to."""
        info = user_char_to_segment[idx]
        if info:
            return info["segment"]["end"]
        if idx + 1 < n_user and user_char_times[idx + 1] is not None:
            return user_char_times[idx + 1]
        return last_end

    def _append_sub(out: List[Dict], s: int, e: int) -> None:
        """Append a sub-segment spanning user chars [s, e) using original text."""
        if e <= s:
            return
        start_time = user_char_times[s]
        if start_time is None:
            start_time = user_char_times[s - 1] if s > 0 and user_char_times[s - 1] is not None else 0.0
        end_time = _char_end_time(e - 1)
        if end_time - start_time < 0.5:
            end_time = start_time + 0.5
        text = user_text_full[orig_positions[s] : orig_positions[e - 1] + 1]
        if text.strip():
            out.append({"start": start_time, "end": end_time, "text": text})

    def _pause_threshold(lo: int, hi: int) -> float:
        """Median inter-char gap within [lo, hi); threshold = max(median*ratio, PAUSE_MIN)."""
        gaps = []
        for k in range(lo + 1, hi):
            a, b = user_char_times[k - 1], user_char_times[k]
            if a is not None and b is not None and b > a:
                gaps.append(b - a)
        if not gaps:
            return float("inf")
        gaps.sort()
        median = gaps[len(gaps) // 2]
        return max(median * PAUSE_RATIO, PAUSE_MIN)

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

        # Walk the sentence's chars; cut a new sub-segment at each pause.
        # When the user disabled length-based splitting (max_chars <= 0), keep
        # each sentence as a single subtitle regardless of internal pauses —
        # splitting "reached 135 | meters" mid-sentence is worse than a long line.
        threshold = _pause_threshold(start_char_idx, end_char_idx)
        sub_start = start_char_idx
        if allow_pause_split:
            for k in range(start_char_idx + 1, end_char_idx):
                t_prev = user_char_times[k - 1]
                t_curr = user_char_times[k]
                if t_prev is not None and t_curr is not None and t_curr - t_prev >= threshold:
                    _append_sub(aligned_segments, sub_start, k)
                    sub_start = k
        _append_sub(aligned_segments, sub_start, end_char_idx)
        char_idx = end_char_idx

    if len(aligned_segments) < len(user_sentences):
        logger.debug(
            "%d sentence(s) could not be matched; estimated durations used",
            len(user_sentences) - len(aligned_segments),
        )
    return aligned_segments


def _merge_tiny_segments(segments: List[Dict], min_chars: int = 2) -> List[Dict]:
    """Merge fragments too short to stand alone into the following segment.

    Gap-splitting can break a word across two subtitles when DTW maps its
    chars to times straddling a pause threshold (e.g. "to" → "t" | "o").
    Merge any fragment whose stripped content is < ``min_chars`` chars into the
    next segment so a lone letter never becomes its own subtitle.
    """
    if len(segments) < 2:
        return segments
    merged: List[Dict] = []
    for seg in segments:
        tiny = len(remove_punctuation(seg["text"])) < min_chars
        if tiny and merged:
            prev = merged[-1]
            prev["text"] = prev["text"] + seg["text"]
            prev["end"] = max(prev["end"], seg["end"])
        else:
            merged.append(seg)
    return merged


def fix_overlapping_timestamps(segments: List[Dict]) -> List[Dict]:
    """Enforce strictly non-overlapping, in-order segments with a max-duration cap.

    Min-duration padding is left to :func:`optimize_subtitle_duration` so that
    it can fill gaps against the *next* segment's start; doing it here would
    force long sentences to overrun (the old ``0.5 + chars*0.15`` formula pushed
    a 20-char sentence to ≥3.5s even when the voice had ended).
    """
    if not segments:
        return segments

    segments = sorted(segments, key=lambda x: x["start"])
    fixed: List[Dict] = []

    for i, segment in enumerate(segments):
        start = segment["start"]
        end = segment["end"]
        text = segment["text"]
        text_chars = len(remove_punctuation(text))
        max_duration = max(3.0, 1.0 + text_chars * 0.25)

        if i > 0 and start < fixed[-1]["end"]:
            start = fixed[-1]["end"]

        if end - start > max_duration:
            end = start + max_duration

        if i + 1 < len(segments) and end > segments[i + 1]["start"]:
            end = segments[i + 1]["start"]

        if end <= start:
            end = start + max(1.0, text_chars * 0.15)

        fixed.append({"start": start, "end": end, "text": text})

    return fixed


def optimize_subtitle_duration(segments: List[Dict], max_gap_fill: float = 2.0) -> List[Dict]:
    """Make durations readable: no gaps between subtitles, capped by max duration.

    Each segment's end is extended to the next segment's start (so subtitles
    abut — current ends, next immediately begins), capped by a per-text max
    duration so a short line doesn't span a long silence. The min-duration
    floor is applied only when it fits before the next start. The last segment
    keeps its natural end (lifted to min, capped at max) — no extension past
    the voice.
    """
    if not segments:
        return segments

    def _bounds(text: str) -> tuple[float, float]:
        chars = len(remove_punctuation(text))
        return max(0.8, 0.3 + chars * 0.06), max(3.0, 1.0 + chars * 0.25)

    for i in range(len(segments) - 1):
        curr = segments[i]
        next_start = segments[i + 1]["start"]
        min_dur, max_dur = _bounds(curr["text"])
        # Fill the gap: end at next_start (no gap), capped by max duration.
        desired = min(curr["start"] + max_dur, next_start)
        # Lift to min duration, but never past next_start (no overlap).
        desired = max(desired, min(curr["start"] + min_dur, next_start))
        # Never shrink below the natural end either.
        desired = max(desired, curr["end"])
        curr["end"] = desired

    last = segments[-1]
    min_dur, max_dur = _bounds(last["text"])
    desired = max(last["start"] + min_dur, last["end"])
    desired = min(desired, last["start"] + max_dur)
    last["end"] = desired
    return segments


def align_texts(
    recognized_segments: List[Dict],
    user_sentences: List[str],
    allow_pause_split: bool = True,
) -> List[Dict]:
    """Full alignment pipeline: DTW match → merge tiny → fix overlaps → optimize durations."""
    aligned = match_user_text_to_timestamps(recognized_segments, user_sentences, allow_pause_split=allow_pause_split)
    aligned = _merge_tiny_segments(aligned)
    aligned = fix_overlapping_timestamps(aligned)
    aligned = optimize_subtitle_duration(aligned)
    return aligned
