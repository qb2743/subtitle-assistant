"""Integration tests for the `align` CLI command (DTW text alignment)."""

from argparse import Namespace

from videocaptioner.cli.commands.align import run

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:04,000
大家好今天给大家介绍一款软件

2
00:00:04,000 --> 00:00:08,000
这个软件可以自动生成字幕

3
00:00:08,000 --> 00:00:12,000
并且支持多语言翻译和配音
"""

USER_TEXT = (
    "大家好，今天给大家介绍一款软件。\n"
    "这个软件可以自动生成字幕。\n"
    "并且支持多语言翻译和配音。"
)


def _args(**overrides) -> Namespace:
    base = dict(subtitle="", text=None, text_file=None, max_chars=30, output=None, quiet=False)
    base.update(overrides)
    return Namespace(**base)


def test_align_command_produces_corrected_srt(tmp_path):
    srt_path = tmp_path / "asr.srt"
    srt_path.write_text(SAMPLE_SRT, encoding="utf-8")
    out_path = tmp_path / "aligned.srt"

    rc = run(_args(subtitle=str(srt_path), text=USER_TEXT, output=str(out_path)), {})

    assert rc == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    # The user's correct text (with punctuation) replaces the ASR text.
    assert "大家好，今天给大家介绍一款软件。" in content
    assert "这个软件可以自动生成字幕。" in content
    assert "并且支持多语言翻译和配音。" in content
    assert "-->" in content
    assert content.strip().count("-->") == 3


def test_align_command_reads_text_file(tmp_path):
    srt_path = tmp_path / "asr.srt"
    srt_path.write_text(SAMPLE_SRT, encoding="utf-8")
    text_path = tmp_path / "transcript.txt"
    text_path.write_text(USER_TEXT, encoding="utf-8")
    out_path = tmp_path / "aligned.srt"

    rc = run(_args(subtitle=str(srt_path), text_file=str(text_path), output=str(out_path)), {})

    assert rc == 0
    assert "大家好，今天给大家介绍一款软件。" in out_path.read_text(encoding="utf-8")


def test_align_command_missing_subtitle(tmp_path):
    rc = run(_args(subtitle=str(tmp_path / "nope.srt"), text="你好"), {})
    assert rc != 0  # FILE_NOT_FOUND


def test_align_command_empty_text(tmp_path):
    srt_path = tmp_path / "asr.srt"
    srt_path.write_text(SAMPLE_SRT, encoding="utf-8")
    rc = run(_args(subtitle=str(srt_path), text="   "), {})
    assert rc != 0  # USAGE_ERROR


def test_align_command_default_output_path(tmp_path):
    srt_path = tmp_path / "asr.srt"
    srt_path.write_text(SAMPLE_SRT, encoding="utf-8")
    rc = run(_args(subtitle=str(srt_path), text=USER_TEXT), {})  # no --output
    assert rc == 0
    assert (tmp_path / "asr.aligned.srt").exists()
