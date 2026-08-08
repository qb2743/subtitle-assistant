"""Tests for scanline speaker-to-subtitle assignment (``core/diarization/assign.py``).

Ports pyVideoTrans ``_assign_speakers`` semantics and verifies the adapted
"no overlap → ''" behaviour used by the narrator filter.
"""

from videocaptioner.core.diarization.assign import (
    assign_speakers,
    assign_speakers_ms,
    read_speaker_json,
    remap_speakers_ms,
    speaker_sidecar_path,
    write_speaker_json,
)
from videocaptioner.core.dubbing.models import DubbingSegment


def _seg(index, start_ms, end_ms, text="t"):
    return DubbingSegment(index=index, start_ms=start_ms, end_ms=end_ms, text=text)


# ---------------------------------------------------------- scanning line


def test_full_overlap_single_speaker():
    out = assign_speakers_ms(
        [(0, 1000), (2000, 3000)],
        [((0, 1000), "spk0")],
    )
    assert out == ["spk0", ""]


def test_partial_overlap_above_threshold():
    # 重叠 300ms > 0.2 * 500ms = 100ms → 标注。
    out = assign_speakers_ms([(100, 600)], [((0, 400), "spk0")])
    assert out == ["spk0"]


def test_no_overlap_gives_empty():
    out = assign_speakers_ms([(0, 500)], [((1000, 2000), "spk0")])
    assert out == [""]


def test_single_speaker_below_threshold_gives_empty():
    # 重叠 150ms <= 0.2 * 1000ms = 200ms → 不标注。
    out = assign_speakers_ms([(0, 1000)], [((100, 250), "spk0")])
    assert out == [""]


def test_multi_speaker_takes_longest_overlap():
    # spk0 重叠 400ms,spk1 重叠 700ms → spk1。
    out = assign_speakers_ms(
        [(0, 1000)],
        [((0, 400), "spk0"), ((300, 1000), "spk1")],
    )
    assert out == ["spk1"]


def test_tie_duration_picks_first_in_start_order():
    # 两个说话人各重叠 500ms 并列 → 取开始时间更早的 spk0。
    out = assign_speakers_ms(
        [(0, 1000)],
        [((0, 500), "spk0"), ((500, 1000), "spk1")],
    )
    assert out == ["spk0"]


def test_diars_unsorted_input_is_sorted_internally():
    out = assign_speakers_ms(
        [(0, 1000)],
        [((500, 1000), "spk1"), ((0, 500), "spk0")],  # 无序输入
    )
    assert out == ["spk0"]


def test_multiple_subtitles_partial_and_no_overlap_mixed():
    out = assign_speakers_ms(
        [(0, 1000), (1500, 2000), (3000, 4000)],
        [((0, 1000), "spk0")],
    )
    assert out == ["spk0", "", ""]


# ---------------------------------------------------- assign_speakers (segments)


def test_assign_speakers_with_dubbing_segments_and_seconds_input():
    segments = [
        _seg(1, 0, 1000),
        _seg(2, 2000, 3000),
        _seg(3, 5000, 6000),
    ]
    diarizations = [
        {"start": 0.0, "end": 1.0, "speaker": "spk0"},
        {"start": 5.5, "end": 6.5, "speaker": "spk1"},
    ]
    out = assign_speakers(segments, diarizations)
    assert out == ["spk0", "", "spk1"]


def test_assign_speakers_millisecond_boundary_rounding():
    # 秒级浮点 → 毫秒 int(round)。0.9995s -> 1000ms 覆盖整段。
    segments = [_seg(1, 0, 1000)]
    diarizations = [{"start": 0.0, "end": 0.9995, "speaker": "spk0"}]
    out = assign_speakers(segments, diarizations)
    assert out == ["spk0"]


# ------------------------------------------------------- timeline remapping


def test_remap_speakers_survives_split_and_removed_rows():
    out = remap_speakers_ms(
        [(0, 1000), (1000, 2000), (2000, 3000)],
        ["spk0", "spk1", "spk0"],
        [(0, 400), (400, 1000), (2000, 3000)],
    )

    assert out == ["spk0", "spk0", "spk0"]


def test_remap_speakers_uses_dominant_overlap_for_merged_row():
    out = remap_speakers_ms(
        [(0, 500), (500, 2000)],
        ["spk0", "spk1"],
        [(0, 2000)],
    )

    assert out == ["spk1"]


def test_remap_speakers_ignores_unlabelled_source_rows():
    out = remap_speakers_ms(
        [(0, 1000), (1000, 2000)],
        ["", "spk1"],
        [(0, 1000), (1000, 2000)],
    )

    assert out == ["", "spk1"]


# ------------------------------------------------------------ sidecar json


def test_write_and_read_speaker_json_roundtrip(tmp_path):
    path = tmp_path / "sub.speaker.json"
    speaker_labels = ["spk0", "", "spk1"]
    assert write_speaker_json(speaker_labels, path) == str(path)
    assert path.exists()
    assert read_speaker_json(path) == speaker_labels


def test_read_speaker_json_missing_or_invalid(tmp_path):
    assert read_speaker_json(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert read_speaker_json(bad) == []
    invalid_encoding = tmp_path / "invalid-encoding.json"
    invalid_encoding.write_bytes(b"\xff\xfe\xfa")
    assert read_speaker_json(invalid_encoding) == []


def test_speaker_sidecar_path_replaces_subtitle_suffix(tmp_path):
    subtitle = tmp_path / "movie.translated.srt"

    assert speaker_sidecar_path(subtitle) == tmp_path / "movie.translated.speaker.json"
