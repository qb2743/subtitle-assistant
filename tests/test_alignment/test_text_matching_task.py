"""Tests for the TextMatchingTask orchestration (media -> ASR -> DTW -> SRT).

`transcribe` and `video2audio` are faked so no real ASR/ffmpeg is needed.
"""

from pathlib import Path

import pytest

import videocaptioner.core.alignment.text_matcher as tm_module
from videocaptioner.core.alignment import TextMatchingConfig, TextMatchingTask
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg


def _make_asr() -> ASRData:
    return ASRData(
        [
            ASRDataSeg(text="你好世界", start_time=0, end_time=2000),
            ASRDataSeg(text="今天天气真好", start_time=2000, end_time=4000),
        ]
    )


def _patch_transcribe(monkeypatch, asr_data=None, record=None):
    def _fake_transcribe(audio_path, config, callback=None):
        if record is not None:
            record["audio_path"] = audio_path
        if callback:
            callback(50, "transcribing")
        return asr_data if asr_data is not None else _make_asr()

    monkeypatch.setattr(tm_module, "transcribe", _fake_transcribe)


def test_audio_input_no_extraction(tmp_path, monkeypatch):
    record: dict = {}
    _patch_transcribe(monkeypatch, record=record)
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"fake audio")
    out = tmp_path / "out.srt"

    result = TextMatchingTask(
        TextMatchingConfig(
            media_path=str(audio),
            user_text="你好世界\n今天天气真好",
            output_path=str(out),
        )
    ).execute()

    assert result == out
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "你好世界" in content
    assert "今天天气真好" in content
    assert "-->" in content
    # transcribe received the audio path directly (no extraction).
    assert record["audio_path"] == str(audio)


def test_video_input_extracts_audio(tmp_path, monkeypatch):
    record: dict = {}
    _patch_transcribe(monkeypatch, record=record)

    # Inject a fake video_utils module (the real one pulls PIL/fontTools/...).
    import sys
    import types

    fake_mod = types.ModuleType("videocaptioner.core.utils.video_utils")

    def _fake_video2audio(input_file, output="", audio_track_index=0):
        Path(output).write_bytes(b"fake wav")
        return True

    fake_mod.video2audio = _fake_video2audio
    monkeypatch.setitem(sys.modules, "videocaptioner.core.utils.video_utils", fake_mod)

    video = tmp_path / "input.mp4"
    video.write_bytes(b"fake video")
    out = tmp_path / "out.srt"

    TextMatchingTask(
        TextMatchingConfig(
            media_path=str(video), user_text="你好世界", output_path=str(out)
        )
    ).execute()

    assert out.exists()
    # transcribe received a temp .wav (extracted), not the .mp4.
    assert record["audio_path"].endswith(".wav")
    assert record["audio_path"] != str(video)


def test_default_output_path(tmp_path, monkeypatch):
    _patch_transcribe(monkeypatch)
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x")
    result = TextMatchingTask(
        TextMatchingConfig(media_path=str(audio), user_text="你好世界")
    ).execute()
    assert result == tmp_path / "clip.aligned.srt"
    assert result.exists()


def test_missing_media_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        TextMatchingTask(
            TextMatchingConfig(media_path=str(tmp_path / "nope.mp4"), user_text="hi")
        ).execute()


def test_empty_text_raises(tmp_path):
    audio = tmp_path / "x.wav"
    audio.write_bytes(b"x")
    with pytest.raises(ValueError):
        TextMatchingTask(
            TextMatchingConfig(media_path=str(audio), user_text="   ")
        ).execute()


def test_progress_callback_reports_stages(tmp_path, monkeypatch):
    _patch_transcribe(monkeypatch)
    audio = tmp_path / "x.wav"
    audio.write_bytes(b"x")
    progress: list = []
    TextMatchingTask(
        TextMatchingConfig(
            media_path=str(audio), user_text="你好世界", output_path=str(tmp_path / "o.srt")
        )
    ).execute(callback=lambda p, m: progress.append((p, m)))
    # Starts with "preparing audio" (5%) and reaches "completed" (100%).
    assert progress[0] == (5, "preparing audio")
    assert any(p == 100 for p, _ in progress)
    # ASR + align + save stages all reported.
    msgs = [m for _p, m in progress]
    assert any("transcribing" in m for m in msgs)
    assert any("aligning" in m for m in msgs)
