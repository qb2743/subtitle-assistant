"""Tests for the fixed inter-line pause dubbing mode."""

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
from videocaptioner.core.dubbing.models import DubbingSegment


def _segment(index: int, duration_ms: int) -> DubbingSegment:
    seg = DubbingSegment(index=index, start_ms=0, end_ms=duration_ms, text=f"line {index}")
    seg.fitted_path = f"/fake/seg{index}.wav"
    seg.fitted_duration_ms = duration_ms
    return seg


def _pipeline(**overrides) -> DubbingPipeline:
    defaults = {
        "provider": "edge",
        "api_key": "",
        "base_url": "",
        "model": "edge-tts",
        "fixed_line_pause": True,
        "fixed_line_pause_ms": 1000,
    }
    defaults.update(overrides)
    return DubbingPipeline(DubbingConfig(**defaults))


def test_fixed_pause_timeline_ignores_srt_and_inserts_silence(tmp_path, monkeypatch):
    silence_files: list[tuple[str, int]] = []

    def _fake_silence(path: str, duration_ms: int) -> str:
        silence_files.append((path, duration_ms))
        return path

    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.create_silence_file", _fake_silence)

    segments = [_segment(1, 2000), _segment(2, 1500), _segment(3, 3000)]
    timeline, total_ms = _pipeline()._build_fixed_pause_timeline(segments, tmp_path)

    # 3 segments + 2 silence pauses (no pause after the last line).
    assert len(timeline) == 5
    assert timeline[0] == ("/fake/seg1.wav", 0)
    assert timeline[1] == (str(tmp_path / "pause_0000.wav"), 2000)
    assert timeline[2] == ("/fake/seg2.wav", 3000)  # 2000 + 1000 pause
    assert timeline[3] == (str(tmp_path / "pause_0001.wav"), 4500)  # 3000 + 1500
    assert timeline[4] == ("/fake/seg3.wav", 5500)  # 4500 + 1000 pause
    # Total = 2000 + 1000 + 1500 + 1000 + 3000
    assert total_ms == 8500
    assert silence_files == [
        (str(tmp_path / "pause_0000.wav"), 1000),
        (str(tmp_path / "pause_0001.wav"), 1000),
    ]


def test_fixed_pause_no_pause_when_zero_ms(tmp_path, monkeypatch):
    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.create_silence_file", lambda p, d: p)
    segments = [_segment(1, 2000), _segment(2, 1500)]
    timeline, total_ms = _pipeline(fixed_line_pause_ms=0)._build_fixed_pause_timeline(segments, tmp_path)
    assert timeline == [("/fake/seg1.wav", 0), ("/fake/seg2.wav", 2000)]
    assert total_ms == 3500


def test_fixed_pause_skips_tempo_fit(tmp_path):
    # In fixed-pause mode there is no target timeline, so _fit_segment returns
    # the source unchanged even when the synthesized audio is far longer than
    # the SRT target (which would normally force a tempo fit).
    pipeline = _pipeline()
    seg = DubbingSegment(index=1, start_ms=0, end_ms=1000, text="line 1")  # target = 1000ms
    seg.synthesized_path = "/fake/raw.wav"
    seg.synthesized_duration_ms = 5000  # 5x the target → would force a fit normally
    assert pipeline._fit_segment(seg, tmp_path) == "/fake/raw.wav"
    assert seg.speed_factor == 1.0
