from videocaptioner.core.dubbing.subtitle_parser import split_speaker


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
