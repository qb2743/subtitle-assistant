"""Tests for the DTW alignment core (ported from txt2srt)."""

import videocaptioner.core.alignment.dtw_aligner as dtw_mod
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


def test_split_text_keeps_decimal_numbers_intact():
    # "2.5" must not be treated as a sentence-ending period.
    segs = split_text_into_segments("About 2.5 kilometers from Tulum", max_chars=80)
    assert segs == ["About 2.5 kilometers from Tulum"]
    # Even under a tight length cap, the decimal stays whole (never "2." / "5 ").
    tight = split_text_into_segments("About 2.5 kilometers from Tulum", max_chars=30)
    joined = " ".join(tight)
    assert "2.5" in joined
    assert "2." not in joined.replace("2.5", "")
    assert not any(s.strip().startswith("5 ") for s in tight)

    segs = split_text_into_segments(
        "The cave is 2.5 kilometers long and 13.5 meters deep.", max_chars=80
    )
    assert segs == ["The cave is 2.5 kilometers long and 13.5 meters deep."]

    # Real sentence periods still split when over max_chars; decimals stay whole.
    segs = split_text_into_segments(
        "Version 1.0 was released in 2020. Next came 2.0.", max_chars=45
    )
    assert segs == ["Version 1.0 was released in 2020.", "Next came 2.0."]
    assert "1.0" in segs[0] and "2.0" in segs[1]


def test_strip_keeps_decimal_points():
    from videocaptioner.core.alignment import strip_subtitle_punctuation

    assert (
        strip_subtitle_punctuation("About 2.5 kilometers from Tulum.")
        == "About 2.5 kilometers from Tulum"
    )
    assert strip_subtitle_punctuation("He scored 3.14 points.") == "He scored 3.14 points"
    # Non-decimal periods still stripped.
    assert strip_subtitle_punctuation("Hello. World!") == "Hello World"


def test_remove_punctuation_keeps_decimal_points():
    assert remove_punctuation("About 2.5 kilometers") == "About2.5kilometers"
    assert remove_punctuation("2.5") == "2.5"
    assert remove_punctuation("Hello, world!") == "Helloworld"


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


# --- phonetic-aware distance (#1) ---


def test_homophones_cost_less_than_unrelated_chars():
    # 师姐/世界 share syllables (shī-jiě / shì-jiè): same initial+final, tone
    # differs — cheaper than an unrelated pair, so DTW paths survive ASR
    # mishearings instead of derailing.
    assert 0 < dtw_mod._char_cost("师", "世") < 1
    assert 0 < dtw_mod._char_cost("姐", "界") < 1
    # Exact homophones (部署/部属) cost even less than tone-shifted pairs.
    assert dtw_mod._char_cost("署", "属") < dtw_mod._char_cost("师", "世")
    # 好(hǎo) shares the 'h' initial with 坏(huài) -> 0.7; fully unrelated
    # pairs (好/天: h-t initials, ao-ian finals) cost 1.
    assert dtw_mod._char_cost("好", "坏") < 1.0
    assert dtw_mod._char_cost("好", "天") == 1.0
    # ASCII case carries no phonetic information.
    assert dtw_mod._char_cost("h", "H") == 0.0
    # Confusable English letter pairs cost less than unrelated ones.
    assert 0 < dtw_mod._char_cost("v", "f") < 1
    assert dtw_mod._char_cost("x", "f") == 1.0


def test_match_rate_higher_for_homophone_errors():
    # Same ASR text; user text with homophone errors (师姐 vs 世界) must score
    # a higher match rate than one with unrelated chars — the phonetic matrix
    # treats mishearings as near-matches.
    recognized = [{"start": 0.0, "end": 2.0, "text": "你好师姐"}]
    homophone = {}
    match_user_text_to_timestamps(recognized, ["你好世界"], stats=homophone)
    unrelated = {}
    match_user_text_to_timestamps(recognized, ["你好坏事"], stats=unrelated)
    assert homophone["match_rate"] > unrelated["match_rate"]
    assert homophone["match_rate"] > 70


# --- word-level timestamp awareness (#2) ---


def test_word_level_segments_snap_to_word_boundaries():
    # Word-level ASR: each segment is one word. Subtitle boundaries must land
    # exactly on word starts/ends (last char of each word sits at the word's
    # end), and the word-level flag must be reported.
    recognized = [
        {"start": 0.0, "end": 0.4, "text": "今天"},
        {"start": 0.4, "end": 0.9, "text": "天气"},
        {"start": 0.9, "end": 1.4, "text": "真好"},
    ]
    stats = {}
    aligned = match_user_text_to_timestamps(recognized, ["今天天气真好"], stats=stats)
    assert stats["word_level"] is True
    assert len(aligned) == 1
    assert aligned[0]["text"] == "今天天气真好"
    assert aligned[0]["start"] == 0.0
    assert aligned[0]["end"] == 1.4


def test_sentence_level_segments_report_word_level_false():
    stats = {}
    match_user_text_to_timestamps(
        [{"start": 0.0, "end": 2.0, "text": "今天天气真好"}],
        ["今天天气真好"],
        stats=stats,
    )
    assert stats["word_level"] is False


# --- chunked two-pass DTW (#3) ---


def test_global_path_used_below_threshold():
    stats = {}
    match_user_text_to_timestamps(
        [{"start": 0.0, "end": 1.0, "text": "你好"}], ["你好"], stats=stats
    )
    assert stats["chunked"] is False


def test_chunked_path_matches_global_for_identical_text(monkeypatch):
    monkeypatch.setattr(dtw_mod, "_CHUNK_CELL_THRESHOLD", 300)
    text = "一二三四五六七八九十" * 3  # 30 chars -> 900 cells > 300
    stats = {}
    aligned = match_user_text_to_timestamps(
        [{"start": 0.0, "end": 3.0, "text": text}], [text], stats=stats
    )
    assert stats["chunked"] is True
    assert len(aligned) == 1
    assert aligned[0]["text"] == text
    assert aligned[0]["start"] == 0.0
    assert aligned[0]["end"] == 3.0


def test_chunked_path_matches_global_across_sentences(monkeypatch):
    # Multi-sentence text split into several coarse units: the two-pass path
    # must produce the same subtitles as the global DTW.
    sentences = [f"第{i}句的测试内容" for i in range(40)]
    recognized = [
        {"start": i * 1.0, "end": i * 1.0 + 1.0, "text": s}
        for i, s in enumerate(sentences)
    ]

    monkeypatch.setattr(dtw_mod, "_CHUNK_CELL_THRESHOLD", 10**9)
    global_aligned = match_user_text_to_timestamps(recognized, sentences)
    monkeypatch.setattr(dtw_mod, "_CHUNK_CELL_THRESHOLD", 1000)
    chunked_aligned = match_user_text_to_timestamps(recognized, sentences)

    assert len(global_aligned) == len(chunked_aligned) == 40
    for a, b in zip(global_aligned, chunked_aligned):
        assert a["text"] == b["text"]
        assert abs(a["start"] - b["start"]) < 1e-6
        assert abs(a["end"] - b["end"]) < 1e-6


def test_chunked_path_keeps_user_text_with_missing_sentence(monkeypatch):
    # User manuscript contains a sentence the ASR never heard; chunked DTW must
    # still emit it (estimated duration), not drop it.
    monkeypatch.setattr(dtw_mod, "_CHUNK_CELL_THRESHOLD", 300)
    rec_text = "一二三四五六七八九十" * 3
    user_text = "一二三四五六七八九十" * 2 + "完全不同的句子内容"
    aligned = match_user_text_to_timestamps(
        [{"start": 0.0, "end": 3.0, "text": rec_text}], [user_text]
    )
    assert len(aligned) >= 1
    assert "".join(a["text"] for a in aligned) == user_text


def test_chunked_path_long_single_sentence_spans_full_timeline(monkeypatch):
    # A 320-char punctuation-less sentence must still map onto the whole
    # segment timeline when chunked (regression: rec units used to stay
    # unsplit, collapsing every anchor onto one giant unit's midpoint).
    monkeypatch.setattr(dtw_mod, "_CHUNK_CELL_THRESHOLD", 10_000)
    text = "今天天气很好我们一起去公园散步" * 20
    stats = {}
    aligned = match_user_text_to_timestamps(
        [{"start": 0.0, "end": 40.0, "text": text}], [text], stats=stats
    )
    assert stats["chunked"] is True
    assert len(aligned) == 1
    assert aligned[0]["start"] == 0.0
    assert aligned[0]["end"] == 40.0


# --- stats (#4) ---


def test_stats_expose_match_rate_and_counts():
    stats = {}
    match_user_text_to_timestamps(
        [{"start": 0.0, "end": 1.0, "text": "你好世界"}], ["你好世界"], stats=stats
    )
    assert 99.0 < stats["match_rate"] <= 100.0
    assert stats["user_chars"] == 4
    assert stats["recognized_chars"] == 4
