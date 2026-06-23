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
    # gap 1.0s -> extend_by = min(0.5, 1.0 - 0.1) = 0.5 -> first end 1.5
    assert optimized[0]["end"] == 1.5
    # last segment always extended by 0.5
    assert optimized[1]["end"] == 3.5


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
