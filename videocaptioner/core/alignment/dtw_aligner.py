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

The char-level DTW distance is *phonetic-aware* (see :func:`_char_cost`):
exact chars cost 0, CJK homophones and acoustically confusable English
letter pairs cost < 1, so an ASR mishearing (师姐 vs 世界) no longer derails
the warping path. Long transcripts (> ``_CHUNK_CELL_THRESHOLD`` cells) are
aligned with a two-pass chunked DTW (:func:`_chunked_dtw_path`) so the n*m
distance matrix never blows up in memory.

Data format used internally (seconds, floats)::

    {"start": float, "end": float, "text": str}
"""

import re
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import numpy as np
from dtw import dtw

try:
    from pypinyin import Style, pinyin

    _HAS_PYPINYIN = True
except ImportError:  # pragma: no cover - falls back to exact-char matching
    Style = None
    pinyin = None
    _HAS_PYPINYIN = False

from videocaptioner.core.utils.logger import setup_logger

logger = setup_logger("alignment.dtw")

# CJK + ASCII punctuation and whitespace stripped before char-level matching.
_PUNCTUATION = set("。，！？；：、,.!?;: 　「」『』“”‘’（）()【】[]\"\"…—–·《》〈〉-")

# Punctuation removed from final subtitle text (ASCII apostrophe ' and spaces kept;
# curly quotes ‘ ’ “ ” are stripped — English normalizes ’ to ' first so it survives).
_SUBTITLE_STRIP_PUNCT = set(
    "。，！？；：、,.!?;:　「」『』“”‘’（）()【】[]\"\"…—–·《》〈〉-"
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[a-zA-Z]")

# Acoustically confusable ASCII letter pairs (lowercased): ASR often mishears
# one for the other, so a sub-1 cost keeps the DTW path on track.
_CONFUSABLE_LETTERS = frozenset(
    frozenset(p)
    for p in (
        "vf", "bp", "dt", "sz", "mn", "ie", "ae", "ou",
        "ck", "gj", "lr", "wv", "xs", "qw", "ph", "cz",
    )
)

# Above this many distance-matrix cells, alignment switches from a single
# global char DTW to the two-pass chunked DTW (:func:`_chunked_dtw_path`).
# A global n*m float64 matrix costs 8 bytes × 2 (distance + cost): 2M cells
# ≈ 32MB, beyond which quadratic memory/time is no longer acceptable.
_CHUNK_CELL_THRESHOLD = 2_000_000
# Coarse pass groups user/ASR text into units of ~this many stripped chars.
_COARSE_UNIT_CHARS = 60
# Defensive cap on the distinct-char block when building a distance matrix
# (see :func:`_build_distance_matrix`); beyond it, fall back to plain
# vectorized exact matching.
_DISTINCT_BLOCK_MAX = 4_000_000


# Contractions/possessives where ' is an apostrophe, not a quote: Juho's, don't,
# they're, we've, you'll, I'm, she'd. Curly ' is what sources usually ship.
_ENGLISH_APOSTROPHE = re.compile(r"[’‘]['‘]?(?:s|t|re|ve|ll|m|d)\b", re.IGNORECASE)

# Decimal / version numbers: 2.5, 13.5, 1.0.0 — the '.' must not be treated as a
# sentence boundary or stripped from subtitle text.
_DECIMAL_NUMBER_RE = re.compile(r"\d+(?:\.\d+)+")
# Private-use placeholders so re.split on sentence punctuation cannot break them.
_DEC_PH_PREFIX = ""
_DEC_PH_SUFFIX = ""


def protect_decimal_numbers(text: str) -> tuple[str, list[str]]:
    """Replace ``2.5`` / ``1.0.0`` with placeholders; return (text, store)."""
    store: list[str] = []

    def _repl(match: re.Match) -> str:
        store.append(match.group(0))
        return f"{_DEC_PH_PREFIX}{len(store) - 1}{_DEC_PH_SUFFIX}"

    return _DECIMAL_NUMBER_RE.sub(_repl, text), store


def restore_decimal_numbers(text: str, store: list[str]) -> str:
    """Undo :func:`protect_decimal_numbers`."""
    for i, value in enumerate(store):
        text = text.replace(f"{_DEC_PH_PREFIX}{i}{_DEC_PH_SUFFIX}", value)
    return text


def _is_decimal_dot(text: str, index: int) -> bool:
    """True when ``text[index]`` is ``.`` between two digits (e.g. 2.5, 1.0.0)."""
    if index < 0 or index >= len(text) or text[index] != ".":
        return False
    return (
        index > 0
        and index + 1 < len(text)
        and text[index - 1].isdigit()
        and text[index + 1].isdigit()
    )


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

    Decimal points inside numbers (``2.5``, ``1.0.0``) are kept so measurements
    and versions are not mangled into ``25`` / ``100``.
    """
    if not text:
        return text
    if _should_normalize_apostrophe(text, language):
        text = text.replace("‘", "'").replace("’", "'")
    return "".join(
        c
        for i, c in enumerate(text)
        if c not in _SUBTITLE_STRIP_PUNCT or _is_decimal_dot(text, i)
    )


def remove_punctuation(text: str) -> str:
    """Strip CJK + ASCII punctuation and whitespace for char-level matching.

    Decimal points inside numbers are kept so ``2.5`` stays distinguishable from
    ``25`` when matching against ASR that also preserves the decimal.
    """
    out: list[str] = []
    for i, c in enumerate(text):
        if not c.strip():
            continue
        if c in _PUNCTUATION and not _is_decimal_dot(text, i):
            continue
        out.append(c)
    return "".join(out)


@lru_cache(maxsize=16384)
def _pinyin_feature(ch: str) -> Optional[Tuple[str, str, str, str]]:
    """``(tone3, plain, initial, final)`` for a CJK char, else ``None``."""
    if not _CJK_RE.fullmatch(ch) or not _HAS_PYPINYIN:
        return None
    try:
        tone3 = pinyin(ch, style=Style.TONE3)[0][0]
        plain = pinyin(ch, style=Style.NORMAL)[0][0]
        initial = pinyin(ch, style=Style.INITIALS)[0][0]
        final = pinyin(ch, style=Style.FINALS)[0][0]
    except Exception:
        return None
    if tone3 == ch:  # pypinyin passed the char through (not CJK readable)
        return None
    return (tone3, plain, initial, final)


@lru_cache(maxsize=65536)
def _char_cost(a: str, b: str) -> float:
    """Per-char-pair DTW cost: 0 = same, <1 = phonetically confusable, 1 = unrelated.

    CJK pairs are scored via pinyin: exact homophones (部署/部属) cost 0.25,
    same syllable with a different tone (师姐/世界) 0.4, shared initial or
    final 0.7. Confusable English letter pairs cost 0.6. ASCII case is
    ignored (it carries no phonetic information). Everything else costs 1.
    """
    if a == b:
        return 0.0
    if a.lower() == b.lower():
        return 0.0
    if _CJK_RE.fullmatch(a) and _CJK_RE.fullmatch(b):
        pa, pb = _pinyin_feature(a), _pinyin_feature(b)
        if pa and pb:
            if pa[0] == pb[0]:
                return 0.25
            if pa[1] == pb[1]:
                return 0.4
            if (pa[2] and pa[2] == pb[2]) or (pa[3] and pa[3] == pb[3]):
                return 0.7
    elif _LATIN_RE.fullmatch(a) and _LATIN_RE.fullmatch(b):
        if frozenset((a.lower(), b.lower())) in _CONFUSABLE_LETTERS:
            return 0.6
    return 1.0


def _build_distance_matrix(user_chars: List[str], rec_chars: List[str]) -> np.ndarray:
    """n_user x n_rec float64 cost matrix for dtw-python (requires "double").

    Built from a distinct-char block + indexing so the Python per-pair cost
    loop only runs over unique chars — the full n*m matrix is materialized
    once (vectorized), not cell by cell.
    """
    u_unique = list(dict.fromkeys(user_chars))
    r_unique = list(dict.fromkeys(rec_chars))
    if len(u_unique) * len(r_unique) > _DISTINCT_BLOCK_MAX:  # defensive
        u_arr = np.array(user_chars, dtype="U1")[:, None]
        r_arr = np.array(rec_chars, dtype="U1")[None, :]
        return (u_arr != r_arr).astype(np.float64)
    block = np.empty((len(u_unique), len(r_unique)), dtype=np.float64)
    for i, uc in enumerate(u_unique):
        for j, rc in enumerate(r_unique):
            block[i, j] = _char_cost(uc, rc)
    u_pos = {c: i for i, c in enumerate(u_unique)}
    r_pos = {c: i for i, c in enumerate(r_unique)}
    u_index = np.array([u_pos[c] for c in user_chars], dtype=np.intp)
    r_index = np.array([r_pos[c] for c in rec_chars], dtype=np.intp)
    return block[np.ix_(u_index, r_index)]


def _is_word_level_text(text: str) -> bool:
    """True when a recognized segment is a single word (word-level ASR output):
    one whitespace-delimited token, or at most two CJK characters."""
    if not text:
        return False
    if _CJK_RE.search(text):
        return len(text) <= 2 and not _LATIN_RE.search(text)
    return len(text.split()) == 1


def split_text_into_segments(text: str, max_chars: int = 30) -> List[str]:
    """Split long text into subtitle-friendly short sentences.

    Priority: newlines → sentence punctuation (。！？；.!?;) → comma punctuation
    (，,、) → hard char-count split. Each returned segment is ≤ ``max_chars``
    where possible.

    Decimal points inside numbers (``2.5``, ``13.5``) are never treated as
    sentence boundaries.
    """
    segments: List[str] = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        protected, store = protect_decimal_numbers(line)
        # Split on major sentence punctuation, keeping the punctuation.
        sentences = re.split(r"([。！？；.!?;])", protected)
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
                    segments.append(
                        restore_decimal_numbers(current_segment.strip(), store)
                    )
                if len(full_sentence) <= max_chars:
                    current_segment = full_sentence
                else:
                    sub_segments = _split_long_sentence(full_sentence, max_chars)
                    for sub in sub_segments[:-1]:
                        segments.append(restore_decimal_numbers(sub.strip(), store))
                    current_segment = sub_segments[-1] if sub_segments else ""
        if current_segment.strip():
            segments.append(restore_decimal_numbers(current_segment.strip(), store))

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
    stats: Optional[Dict] = None,
) -> List[Dict]:
    """DTW-align user sentences onto recognized segment timestamps.

    Args:
        recognized_segments: ASR output, ``[{"start", "end", "text"}]`` (seconds).
        user_sentences: the user's correct transcript, split into sentences.
        allow_pause_split: split long sentences at relative pauses.
        stats: optional dict filled with ``match_rate`` (phonetic similarity of
            the warping path, 0-100), ``word_level`` (ASR segments are single
            words), ``chunked`` (two-pass chunked DTW was used), and char counts.

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

    # Char-level DTW path with a phonetic-aware distance (see _char_cost).
    # Long inputs switch to a two-pass chunked alignment so the n*m distance
    # matrix never blows up in memory/time (see _CHUNK_CELL_THRESHOLD).
    path, mean_cost, chunked = _compute_dtw_path(
        user_chars, recognized_chars, user_sentences, recognized_segments
    )
    match_rate = (1.0 - mean_cost) * 100
    logger.debug("DTW similarity: %.1f%% (chunked=%s)", match_rate, chunked)

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
            if seg_info["char_idx"] >= total - 1:
                # Last char of the segment sits at its end: with word-level ASR
                # timestamps this lands the char exactly on the word boundary,
                # so inter-word gaps below measure real pauses, not halves.
                user_char_times[i] = segment["end"]
            else:
                user_char_times[i] = (
                    segment["start"] + (seg_info["char_idx"] / total) * segment_duration
                )
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
        start_pos = orig_positions[s]
        end_pos = orig_positions[e - 1] + 1
        next_pos = orig_positions[e] if e < n_user else len(user_text_full)
        while end_pos < next_pos and (
            not user_text_full[end_pos].strip() or user_text_full[end_pos] in _PUNCTUATION
        ):
            end_pos += 1
        text = user_text_full[start_pos:end_pos]
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

    if stats is not None:
        stats["match_rate"] = match_rate
        stats["word_level"] = all(
            _is_word_level_text(remove_punctuation(seg["text"])) for seg in recognized_segments
        )
        stats["chunked"] = chunked
        stats["user_chars"] = n_user
        stats["recognized_chars"] = n_recognized
    return aligned_segments


def _coarse_unit_ranges(
    lengths: List[int], target: int, split_long: bool
) -> List[Tuple[int, int]]:
    """Group consecutive item lengths into coarse units of ~``target`` chars.

    Returns ``(start, end)`` ranges into the globally stripped char sequence
    (stripping commutes with concatenation, so per-item stripped lengths line
    up with the global stripped sequence). ``split_long`` hard-splits a single
    over-long item so a pathological punctuation-less paragraph cannot create
    a giant unit.
    """
    units: List[Tuple[int, int]] = []
    pos = 0
    start = 0
    acc = 0
    for n in lengths:
        if n <= 0:
            continue
        if split_long and n > target:
            if acc:
                units.append((start, pos))
                acc = 0
            cur = pos
            remaining = n
            while remaining > target:
                units.append((cur, cur + target))
                cur += target
                remaining -= target
            units.append((cur, cur + remaining))
            pos += n
            start = pos
            continue
        if acc and acc + n > target:
            units.append((start, pos))
            start = pos
            acc = 0
        acc += n
        pos += n
    if acc:
        units.append((start, pos))
    return units


def _chunked_dtw_path(
    user_chars: List[str],
    rec_chars: List[str],
    user_sentences: List[str],
    recognized_segments: List[Dict],
) -> Optional[Tuple[List[Tuple[int, int]], float]]:
    """Two-pass DTW for long text (see ``_CHUNK_CELL_THRESHOLD``).

    Pass 1 (coarse): group both texts into units of ~``_COARSE_UNIT_CHARS``
    chars and DTW the unit grid, scoring each pair with the cosine of their
    char-count vectors (``U @ R.T`` — vectorized, no per-pair Python loop).
    Pass 2 (fine): for each user unit, run the exact char DTW against the
    recognized window the coarse path assigned, plus a one-unit margin.

    Returns ``(path, mean_path_cost)``, or ``None`` when the stripped
    sequences are inconsistent with per-sentence stripping (caller falls back
    to the global DTW).
    """
    user_lengths = [len(remove_punctuation(s)) for s in user_sentences]
    rec_lengths = [len(remove_punctuation(seg["text"])) for seg in recognized_segments]
    if "".join(remove_punctuation(s) for s in user_sentences) != "".join(user_chars) or (
        "".join(remove_punctuation(seg["text"]) for seg in recognized_segments) != "".join(rec_chars)
    ):
        return None
    user_units = _coarse_unit_ranges(user_lengths, _COARSE_UNIT_CHARS, split_long=True)
    # Rec units are split_long too: a single huge ASR segment would otherwise
    # become one giant unit and every user unit's anchor would collapse onto
    # its midpoint, dragging the fine paths to the wrong place.
    rec_units = _coarse_unit_ranges(rec_lengths, _COARSE_UNIT_CHARS, split_long=True)
    if not user_units or not rec_units:
        return None

    distinct = sorted(
        {c for us, ue in user_units for c in user_chars[us:ue]}
        | {c for rs, re in rec_units for c in rec_chars[rs:re]}
    )
    col = {c: i for i, c in enumerate(distinct)}
    U = np.zeros((len(user_units), len(distinct)), dtype=np.float32)
    for k, (us, ue) in enumerate(user_units):
        for c in user_chars[us:ue]:
            U[k, col[c]] += 1
    R = np.zeros((len(rec_units), len(distinct)), dtype=np.float32)
    for k, (rs, re) in enumerate(rec_units):
        for c in rec_chars[rs:re]:
            R[k, col[c]] += 1

    norm_u = np.sqrt(np.einsum("ij,ij->i", U, U))
    norm_r = np.sqrt(np.einsum("ij,ij->i", R, R))
    cos = (U @ R.T) / np.maximum(norm_u[:, None] * norm_r[None, :], 1e-9)
    alignment = dtw((1.0 - cos).astype(np.float64))
    coarse_path = list(zip(alignment.index1, alignment.index2))

    unit_to_rec: Dict[int, List[int]] = {}
    for i, j in coarse_path:
        unit_to_rec.setdefault(i, []).append(j)

    full_path: List[Tuple[int, int]] = []
    path_len = 0
    cost_sum = 0.0
    for k, (us, ue) in enumerate(user_units):
        on_path = unit_to_rec.get(k)
        if not on_path:
            continue
        lo = max(0, min(on_path) - 1)
        hi = min(len(rec_units), max(on_path) + 2)  # exclusive; +2 = one-unit margin
        r_start = rec_units[lo][0]
        r_end = rec_units[hi - 1][1]
        win_user = user_chars[us:ue]
        win_rec = rec_chars[r_start:r_end]
        if not win_user or not win_rec:
            continue
        matrix = _build_distance_matrix(win_user, win_rec)
        raw_matrix = matrix
        # Bias the window toward the diagonal through the coarse anchor, and
        # pad zero rows above/below so the path may start/end at that diagonal
        # instead of being forced through the window corners. With identical
        # chars everywhere an unconstrained DTW is free to wander into the
        # margin, and a corner-forced path cannot cheaply escape mismatched
        # margin columns — the tiny bias (far below any real cost 0.25+) breaks
        # the zero-cost ties toward the true correspondence, and the zero rows
        # emulate open-begin/open-end (dtw-python's own flags need 'N'-norm
        # step patterns). Padding rows are dropped from the result.
        anchor_i = (len(win_user) - 1) // 2
        mid_unit = (min(on_path) + max(on_path)) // 2
        anchor_j = (rec_units[mid_unit][0] + rec_units[mid_unit][1] - 1) // 2 - r_start
        d = anchor_j - anchor_i
        ii = np.arange(len(win_user))[:, None]
        jj = np.arange(len(win_rec))[None, :]
        matrix = matrix + 1e-3 * np.abs(ii - jj + d)
        a = dtw(
            np.vstack(
                [
                    np.zeros((1, len(win_rec))),
                    matrix,
                    np.zeros((1, len(win_rec))),
                ]
            )
        )
        idx1 = np.asarray(a.index1)
        idx2 = np.asarray(a.index2)
        # Drop the padding rows and remap to window coordinates.
        valid = (idx1 >= 1) & (idx1 <= len(win_user))
        idx1 = idx1[valid] - 1
        idx2 = idx2[valid]
        for i, j in zip(idx1, idx2):
            full_path.append((us + int(i), r_start + int(j)))
        path_len += len(idx1)
        # Mean cost uses the *unbiased* matrix so match_rate stays consistent
        # with the global path (the bias only breaks ties, it is not content).
        cost_sum += float(np.sum(raw_matrix[idx1, idx2]))
    if not path_len:
        return None
    return full_path, cost_sum / path_len


def _compute_dtw_path(
    user_chars: List[str],
    rec_chars: List[str],
    user_sentences: List[str],
    recognized_segments: List[Dict],
) -> Tuple[List[Tuple[int, int]], float, bool]:
    """Char-level DTW path + mean path cost, dispatching to the two-pass
    chunked implementation for long inputs (see ``_CHUNK_CELL_THRESHOLD``).

    Returns ``(path, mean_path_cost, chunked)``.
    """
    n_user, n_rec = len(user_chars), len(rec_chars)
    if n_user * n_rec <= _CHUNK_CELL_THRESHOLD:
        matrix = _build_distance_matrix(user_chars, rec_chars)
        alignment = dtw(matrix)
        idx1, idx2 = alignment.index1, alignment.index2
        path = list(zip(idx1, idx2))
        mean_cost = float(np.mean(matrix[idx1, idx2])) if path else 0.0
        return path, mean_cost, False
    chunked = _chunked_dtw_path(user_chars, rec_chars, user_sentences, recognized_segments)
    if chunked is None:
        # Degenerate stripped-sequence mismatch; accept the memory cost of the
        # global DTW rather than misalign (vanishingly rare in practice).
        matrix = _build_distance_matrix(user_chars, rec_chars)
        alignment = dtw(matrix)
        idx1, idx2 = alignment.index1, alignment.index2
        path = list(zip(idx1, idx2))
        mean_cost = float(np.mean(matrix[idx1, idx2])) if path else 0.0
        return path, mean_cost, False
    return chunked[0], chunked[1], True


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
    stats: Optional[Dict] = None,
) -> List[Dict]:
    """Full alignment pipeline: DTW match → merge tiny → fix overlaps → optimize durations.

    ``stats`` (optional) is filled by the DTW match — see
    :func:`match_user_text_to_timestamps`.
    """
    aligned = match_user_text_to_timestamps(
        recognized_segments,
        user_sentences,
        allow_pause_split=allow_pause_split,
        stats=stats,
    )
    aligned = _merge_tiny_segments(aligned)
    aligned = fix_overlapping_timestamps(aligned)
    aligned = optimize_subtitle_duration(aligned)
    return aligned
