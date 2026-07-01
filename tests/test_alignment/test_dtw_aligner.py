"""Tests for the DTW alignment core (ported from txt2srt)."""

from videocaptioner.core.alignment import (
    align_texts,
    fix_overlapping_timestamps,
    match_user_text_to_timestamps,
    optimize_subtitle_duration,
    remove_punctuation,
    split_text_into_segments,
)


def test_remove_punctuation():
    assert remove_punctuation("你好，世界！") == "你好世界"
    assert remove_punctuation("Hello, world!") == "Helloworld"
    assert remove_punctuation("") == ""


def test_strip_subtitle_punctuation():
    from videocaptioner.core.alignment import strip_subtitle_punctuation

    assert (
        strip_subtitle_punctuation("A diver got trapped in a narrow crevice and drowned to death.")
        == "A diver got trapped in a narrow crevice and drowned to death"
    )
    assert strip_subtitle_punctuation("it's fine.") == "it's fine"
    # Curly apostrophe (U+2019) normalized to ASCII ' only in English.
    assert strip_subtitle_punctuation("Juho’s body.", language="en") == "Juho's body"
    # English contraction detected from text even without explicit language:
    # 's after a letter → apostrophe → normalized to ASCII.
    assert strip_subtitle_punctuation("don’t go.") == "don't go"
    # French/Spanish-style quotes (' ') without an English contraction pattern
    # are quote punctuation, not apostrophes — stripped, not normalized.
    assert strip_subtitle_punctuation("‘Bonjour’ mon ami.") == "Bonjour mon ami"
    # In non-English (e.g. Chinese) ' ' are quote punctuation — left as-is, then
    # removed by the strip set (they're in _SUBTITLE_STRIP_PUNCT).
    assert strip_subtitle_punctuation("他说‘你好’。", language="zh") == "他说你好"


def test_split_text_by_newline():
    segs = split_text_into_segments("你好。\n世界！\n测试", max_chars=30)
    assert segs == ["你好。", "世界！", "测试"]


def test_split_text_accumulates_under_max_chars():
    # Short sentences combine into one segment when under the limit.
    segs = split_text_into_segments("你好。世界！", max_chars=30)
    assert segs == ["你好。世界！"]


def test_split_text_respects_max_chars():
    text = "这是一段比较长的测试文本需要被切分" * 3
    segs = split_text_into_segments(text, max_chars=10)
    assert len(segs) > 1
    assert all(len(s) <= 10 for s in segs)


def test_match_aligns_identical_text():
    recognized = [
        {"start": 0.0, "end": 2.0, "text": "你好世界"},
        {"start": 2.0, "end": 4.0, "text": "今天天气真好"},
    ]
    aligned = match_user_text_to_timestamps(recognized, ["你好世界", "今天天气真好"])
    assert len(aligned) == 2
    assert aligned[0]["text"] == "你好世界"
    assert aligned[1]["text"] == "今天天气真好"
    assert aligned[0]["start"] < 0.5
    assert 1.5 < aligned[1]["start"] < 4.0
    assert aligned[1]["start"] >= aligned[0]["start"]


def test_match_empty_inputs():
    assert match_user_text_to_timestamps([], ["a"]) == []
    assert match_user_text_to_timestamps([{"start": 0, "end": 1, "text": "a"}], []) == []


def test_match_handles_extra_user_chars():
    recognized = [{"start": 0.0, "end": 3.0, "text": "你好世界"}]
    aligned = match_user_text_to_timestamps(recognized, ["你好世界啊"])
    assert len(aligned) == 1
    assert aligned[0]["text"] == "你好世界啊"
    assert 0.0 <= aligned[0]["start"] <= 3.0


def test_fix_overlapping_timestamps_removes_overlap():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "第一句"},
        {"start": 1.0, "end": 3.0, "text": "第二句"},  # overlaps the first
    ]
    fixed = fix_overlapping_timestamps(segs)
    assert fixed[1]["start"] >= fixed[0]["end"]


def test_fix_overlapping_timestamps_caps_long_duration():
    segs = [{"start": 0.0, "end": 100.0, "text": "短"}]
    fixed = fix_overlapping_timestamps(segs)
    # 1 char -> max_duration = max(3.0, 1.0 + 0.25) = 3.0
    assert fixed[0]["end"] - fixed[0]["start"] <= 3.0


def test_optimize_duration_fills_gaps():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "一"},
        {"start": 2.0, "end": 3.0, "text": "二"},
    ]
    optimized = optimize_subtitle_duration(segs)
    # No gap between subtitles: first end == next start (2.0), capped by max
    # (1 char -> 3.0s max, so 2.0 fits) → abuts the second.
    assert optimized[0]["end"] == 2.0
    # last segment: natural end (3.0) already ≥ per-text min (0.8s) and ≤ max
    # (3.0s), no extension past the voice → stays at its natural end
    assert optimized[1]["end"] == 3.0


def test_align_texts_full_pipeline_no_overlap():
    recognized = [
        {"start": 0.0, "end": 2.0, "text": "你好世界"},
        {"start": 2.0, "end": 4.0, "text": "今天天气真好"},
        {"start": 4.0, "end": 6.0, "text": "我们去公园"},
    ]
    aligned = align_texts(recognized, ["你好世界", "今天天气真好", "我们去公园"])
    assert len(aligned) == 3
    for i in range(len(aligned) - 1):
        assert aligned[i]["end"] <= aligned[i + 1]["start"] + 1e-6
    assert aligned[0]["start"] >= 0.0
    assert aligned[-1]["end"] <= 6.0 + 1.0


def test_align_texts_splits_long_sentence_at_pause():
    # A long punctuation-less user sentence aligned to word-level ASR segments
    # with a real pause (1s gap between "你好世界" at [0,1] and "今天天气真好" at
    # [2,3]). The relative-pause split must break the sentence at the pause so
    # it becomes 2 subtitles instead of one over-long one.
    recognized = [
        {"start": 0.0, "end": 1.0, "text": "你好世界"},
        {"start": 2.0, "end": 3.0, "text": "今天天气真好"},
    ]
    aligned = align_texts(recognized, ["你好世界今天天气真好"])
    assert len(aligned) == 2
    assert aligned[0]["text"] == "你好世界"
    assert aligned[1]["text"] == "今天天气真好"
    # Subtitles abut (no gap): first end == next start.
    assert aligned[0]["end"] <= aligned[1]["start"] + 1e-6


def test_align_texts_never_overlaps_after_optimize():
    # Regression: optimize_subtitle_duration's min-duration floor used to push
    # a short segment's end past the next segment's start, reintroducing
    # overlap after fix_overlapping_timestamps removed it. A 1-char segment
    # immediately followed by another must end before the next starts.
    recognized = [
        {"start": 0.0, "end": 0.3, "text": "a"},
        {"start": 0.4, "end": 1.0, "text": "bc"},
    ]
    aligned = align_texts(recognized, ["a", "bc"])
    assert aligned[0]["end"] <= aligned[1]["start"] + 1e-6


def test_align_texts_merges_tiny_fragments():
    # Regression: gap-splitting used to break "to" into "t" | "o" when DTW
    # straddled a pause. Tiny fragments must merge into the following segment.
    recognized = [
        {"start": 0.0, "end": 0.5, "text": "t"},
        {"start": 0.5, "end": 1.0, "text": "o"},
    ]
    aligned = align_texts(recognized, ["to"])
    assert len(aligned) == 1
    assert aligned[0]["text"] == "to"
