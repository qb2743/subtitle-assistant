from videocaptioner.core.diarization.assign import write_speaker_json
from videocaptioner.core.dubbing.subtitle_parser import (
    load_dubbing_segments,
    split_speaker,
)


def test_split_speaker_bracket_format():
    speaker, text = split_speaker("[Alice] Hello there")

    assert speaker == "Alice"
    assert text == "Hello there"


def test_split_speaker_chinese_bracket_format():
    speaker, text = split_speaker("【小明】你好，今天开始测试。")

    assert speaker == "小明"
    assert text == "你好，今天开始测试。"


def test_split_speaker_keeps_colon_text_as_script():
    speaker, text = split_speaker("Bob: This is a line.")

    assert speaker == "default"
    assert text == "Bob: This is a line."


def test_split_speaker_keeps_colon_text_without_space_as_script():
    speaker, text = split_speaker("Bob:This is a line.")

    assert speaker == "default"
    assert text == "Bob:This is a line."


def test_split_speaker_does_not_treat_inline_time_as_speaker():
    speaker, text = split_speaker("By 6:13 PM that same evening")

    assert speaker == "default"
    assert text == "By 6:13 PM that same evening"


def test_split_speaker_does_not_treat_spaced_inline_time_as_speaker():
    speaker, text = split_speaker("By 6: 13 PM that same evening")

    assert speaker == "default"
    assert text == "By 6: 13 PM that same evening"


def test_split_speaker_default():
    speaker, text = split_speaker("No explicit speaker")

    assert speaker == "default"
    assert text == "No explicit speaker"


def test_load_dubbing_segments_applies_matching_speaker_sidecar(tmp_path):
    subtitle = tmp_path / "translated.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nFirst line\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nSecond line\n",
        encoding="utf-8",
    )
    write_speaker_json(["", "spk1"], tmp_path / "translated.speaker.json")

    segments = load_dubbing_segments(str(subtitle))

    assert [segment.speaker for segment in segments] == ["default", "spk1"]
    assert [segment.text for segment in segments] == ["First line", "Second line"]
    assert "spk0" not in subtitle.read_text(encoding="utf-8")


def test_load_dubbing_segments_ignores_mismatched_speaker_sidecar(tmp_path):
    subtitle = tmp_path / "translated.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nFirst line\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nSecond line\n",
        encoding="utf-8",
    )
    write_speaker_json(["spk0"], tmp_path / "translated.speaker.json")

    segments = load_dubbing_segments(str(subtitle))

    assert [segment.speaker for segment in segments] == ["default", "default"]


def test_embedded_speaker_takes_precedence_over_sidecar(tmp_path):
    subtitle = tmp_path / "translated.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n[Alice] First line\n",
        encoding="utf-8",
    )
    write_speaker_json(["spk0"], tmp_path / "translated.speaker.json")

    segment = load_dubbing_segments(str(subtitle))[0]

    assert segment.speaker == "Alice"
    assert segment.text == "First line"


def test_json_subtitles_load_matching_speaker_sidecar(tmp_path):
    subtitle = tmp_path / "translated.json"
    subtitle.write_text(
        '[{"start_time": 0, "end_time": 1000, "text": "First line"}]',
        encoding="utf-8",
    )
    write_speaker_json(["spk0"], tmp_path / "translated.speaker.json")

    segments = load_dubbing_segments(str(subtitle))

    assert [segment.speaker for segment in segments] == ["spk0"]
