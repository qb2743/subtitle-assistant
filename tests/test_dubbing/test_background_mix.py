"""Tests for background mixing (``core/dubbing/background_mix.py``).

Covers the pure command builder ``build_mix_command`` (two/three-way mix,
volume, loop switch) and an ffmpeg integration test that synthesizes two short
wavs and runs ``mix_background``, asserting the output exists, its duration
matches the first (dubbed) input, and loop works for a short bgm.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from videocaptioner.core.dubbing.background_mix import (
    build_mix_command,
    mix_background,
)

_ffmpeg = shutil.which("ffmpeg")
_ffprobe = shutil.which("ffprobe")


def _have_ffmpeg() -> bool:
    if not _ffmpeg or not _ffprobe:
        return False
    try:
        subprocess.run([_ffmpeg, "-version"], capture_output=True, check=True, timeout=20)
        return True
    except Exception:
        return False


# ------------------------------------------------------------- pure builder


def test_build_mix_two_inputs_volume_and_loop():
    cmd = build_mix_command(
        "dub.wav",
        instrument_path="inst.wav",
        volume=0.8,
        loop=True,
        extra_bgm_path=None,
        output_path="out.wav",
    )
    # 输入顺序:dubbed 在前,instrument 在后;loop=True 时背景输入带 -stream_loop -1。
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == "dub.wav"
    assert "-stream_loop" in cmd
    assert cmd[cmd.index("-stream_loop") + 1] == "-1"
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]volume=0.800[a1]" in fc
    assert "amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]" in fc
    assert cmd[-1] == "out.wav"


def test_build_mix_no_loop_drops_stream_loop():
    cmd = build_mix_command(
        "dub.wav",
        instrument_path="inst.wav",
        volume=1.0,
        loop=False,
        extra_bgm_path=None,
        output_path="out.wav",
    )
    assert "-stream_loop" not in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]volume=1.000[a1]" in fc


def test_build_mix_three_way_extra_bgm():
    cmd = build_mix_command(
        "dub.wav",
        instrument_path="inst.wav",
        volume=0.5,
        loop=True,
        extra_bgm_path="bgm.mp3",
        output_path="out.wav",
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    # 三路混音:instrument 与 extra_bgm 都乘 volume。
    assert "[1:a]volume=0.500[a1]" in fc
    assert "[2:a]volume=0.500[a2]" in fc
    assert "amix=inputs=3:duration=first:dropout_transition=2:normalize=0[a]" in fc
    # -stream_loop -1 应出现在两个背景输入前。
    assert cmd.count("-stream_loop") == 2


def test_build_mix_extra_bgm_only():
    cmd = build_mix_command(
        "dub.wav",
        instrument_path=None,
        volume=0.8,
        loop=True,
        extra_bgm_path="bgm.mp3",
        output_path="out.wav",
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]" in fc
    assert "[1:a]volume=0.800[a1]" in fc


def test_build_mix_no_bgm_raises():
    with pytest.raises(ValueError):
        build_mix_command(
            "dub.wav",
            instrument_path=None,
            volume=0.8,
            loop=True,
            extra_bgm_path=None,
            output_path="out.wav",
        )


# --------------------------------------------------------------- ffmpeg


def _make_tone(path, seconds, freq=440):
    subprocess.run(
        [
            _ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}:sample_rate=44100",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )


def _audio_duration_ms(path) -> int:
    out = subprocess.run(
        [
            _ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout or "{}")
    duration = float(data.get("streams", [{}])[0].get("duration", 0))
    return int(round(duration * 1000))


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_mix_background_output_exists_and_duration_matches_first(tmp_path):
    dub = tmp_path / "dub.wav"
    inst = tmp_path / "inst.wav"
    _make_tone(dub, seconds=3.0)
    _make_tone(inst, seconds=3.0, freq=220)
    out = tmp_path / "out.wav"
    result = mix_background(str(dub), instrument_path=str(inst), volume=0.8, loop=True, output_path=str(out))
    assert result == str(out)
    assert out.exists() and out.stat().st_size > 0
    # duration=first → 以配音轨(3s)为总时长。
    assert abs(_audio_duration_ms(out) - 3000) < 150


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_mix_background_keeps_dubbed_level_when_bgm_is_silent(tmp_path):
    dub = tmp_path / "dub.wav"
    bgm = tmp_path / "bgm.wav"
    out = tmp_path / "out.wav"
    dubbed = (
        Sine(440).to_audio_segment(duration=1000).apply_gain(-18).set_channels(2)
    )
    dubbed.export(dub, format="wav")
    AudioSegment.silent(duration=1000, frame_rate=dubbed.frame_rate).set_channels(
        2
    ).export(bgm, format="wav")

    mix_background(
        str(dub),
        extra_bgm_path=str(bgm),
        volume=0.8,
        loop=False,
        output_path=str(out),
    )

    assert abs(AudioSegment.from_file(out).dBFS - dubbed.dBFS) < 1


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_mix_background_loop_short_bgm_covers_duration(tmp_path):
    # 背景音 1s 远短于配音 4s,loop=True 时循环补足,输出时长远超背景音本身。
    dub = tmp_path / "dub.wav"
    inst = tmp_path / "inst.wav"
    _make_tone(dub, seconds=4.0)
    _make_tone(inst, seconds=1.0, freq=330)
    out = tmp_path / "out.wav"
    mix_background(str(dub), instrument_path=str(inst), volume=0.8, loop=True, output_path=str(out))
    assert out.exists()
    # 时长以配音轨为准,且覆盖到 4s(loop 生效,而不是 1s 提前结束)。
    assert _audio_duration_ms(out) >= 3800
    assert abs(_audio_duration_ms(out) - 4000) < 150


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe not available")
def test_mix_background_three_way(tmp_path):
    dub = tmp_path / "dub.wav"
    inst = tmp_path / "inst.wav"
    bgm = tmp_path / "bgm.wav"
    _make_tone(dub, seconds=2.0)
    _make_tone(inst, seconds=2.0, freq=220)
    _make_tone(bgm, seconds=2.0, freq=660)
    out = tmp_path / "out.wav"
    mix_background(
        str(dub),
        instrument_path=str(inst),
        volume=0.5,
        loop=True,
        extra_bgm_path=str(bgm),
        output_path=str(out),
    )
    assert out.exists() and out.stat().st_size > 0
    assert abs(_audio_duration_ms(out) - 2000) < 150


def test_mix_background_default_output_path(tmp_path):
    dub = tmp_path / "voice.wav"
    _make_tone(dub, seconds=1.0)
    inst = tmp_path / "inst.wav"
    _make_tone(inst, seconds=1.0, freq=220)
    result = mix_background(str(dub), instrument_path=str(inst))
    # 默认输出:dubbed 同目录为其 stem_bgm.wav。
    assert result == str(tmp_path / "voice_bgm.wav")
    assert Path(result).exists()
