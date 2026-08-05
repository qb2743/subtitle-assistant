import json
from types import SimpleNamespace

import videocaptioner.ui.view.dubbing_interface as dubbing_module
import videocaptioner.ui.view.video_alignment_interface as alignment_module
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.entities import TranscribeLanguageEnum
from videocaptioner.ui.thread.video_translation_thread import (
    REVIEW_WAIT_TIMEOUT_SECONDS,
    VideoTranslationThread,
    _job_output_dir,
    _load_pending_narrator_restores,
    _organize_outputs,
    _save_narrator_review_artifacts,
)


class _Combo:
    def __init__(self, items):
        self.items = items
        self.index = 0

    def count(self):
        return len(self.items)

    def itemText(self, index):
        return self.items[index][0]

    def findData(self, value):
        return next((i for i, (_, data) in enumerate(self.items) if data == value), -1)

    def setCurrentIndex(self, index):
        self.index = index


class _Widget:
    def __init__(self, value):
        self._value = value

    def currentText(self):
        return str(self._value)

    def currentData(self):
        return self._value

    def isChecked(self):
        return bool(self._value)

    def value(self):
        return self._value

    def text(self):
        return str(self._value)

    def toPlainText(self):
        return str(self._value)


class _UnexpectedWidget:
    def __getattr__(self, name):
        raise AssertionError(f"hidden alignment control was read: {name}")


def _item(value):
    return SimpleNamespace(value=value)


def test_video_alignment_loads_saved_canvas_and_subtitle_mode(monkeypatch):
    fake_cfg = SimpleNamespace(
        dubbing_provider=_item("edge"),
        dubbing_speaker_count=_item(3),
        dubbing_canvas=_item("1080x1920"),
        dubbing_embed_subtitle=_item("hard"),
    )
    monkeypatch.setattr(alignment_module, "cfg", fake_cfg)
    interface = SimpleNamespace(
        tts_provider_combo=_Combo([("edge - Edge TTS", "edge")]),
        speaker_count_combo=_Combo([("auto", 0), ("3", 3)]),
        canvas_combo=_Combo([("off", "off"), ("portrait", "1080x1920")]),
        embed_combo=_Combo([("none", "none"), ("hard", "hard")]),
    )

    alignment_module.VideoAlignmentInterface._load_config(interface)

    assert interface.canvas_combo.index == 1
    assert interface.embed_combo.index == 1


def test_hidden_dubbing_controls_do_not_overwrite_alignment_settings(monkeypatch):
    alignment_values = {
        "dubbing_video_autorate": True,
        "dubbing_subtitle_gap_ms": 350,
        "dubbing_embed_subtitle": "hard",
        "dubbing_random_mirror": True,
        "dubbing_random_color": True,
        "dubbing_canvas": "1080x1920",
        "dubbing_enable_diarization": True,
        "dubbing_speaker_count": 3,
        "dubbing_narrator_only": True,
        "dubbing_narrator_llm_review": True,
        "dubbing_separate_vocal": True,
        "dubbing_embed_bgm": True,
        "dubbing_bgm_loop": True,
        "dubbing_bgm_volume": 0.4,
        "dubbing_extra_bgm_path": "",
        "dubbing_output_dir": "D:/output",
    }
    fake_cfg = SimpleNamespace(
        **{name: _item(value) for name, value in alignment_values.items()},
        dubbing_voice=_item(""),
        dubbing_provider=_item("edge"),
        dubbing_timing=_item("strict"),
        dubbing_audio_mode=_item("mix"),
        dubbing_adapt_length=_item(False),
        dubbing_fixed_line_pause=_item(False),
        dubbing_fixed_line_pause_ms=_item(0),
        dubbing_speed=_item(1.0),
        dubbing_tts_workers=_item(1),
        dubbing_api_base=_item(""),
        dubbing_clone_audio_path=_item(""),
        dubbing_clone_audio_text=_item(""),
        dubbing_local_package_url=_item(""),
        save=lambda: None,
    )
    monkeypatch.setattr(dubbing_module, "cfg", fake_cfg)
    ordinary = _Widget
    hidden = _UnexpectedWidget()
    interface = SimpleNamespace(
        _config_loading=False,
        show_alignment_controls=False,
        provider_combo=ordinary("edge - Edge TTS"),
        timing_combo=ordinary("strict"),
        audio_mode_combo=ordinary("mix"),
        voice_combo=ordinary(""),
        adapt_switch=ordinary(False),
        pause_switch=ordinary(False),
        pause_ms_spin=ordinary(0),
        speed_spin=ordinary(1.0),
        workers_spin=ordinary(1),
        api_base_edit=ordinary(""),
        clone_audio_edit=ordinary(""),
        clone_text_edit=ordinary(""),
        package_url_edit=ordinary(""),
        model_combo=ordinary(""),
        _provider_id=lambda: "edge",
        video_autorate_switch=hidden,
        gap_ms_spin=hidden,
        embed_combo=hidden,
        random_mirror_switch=hidden,
        random_color_switch=hidden,
        canvas_combo=hidden,
        diarization_switch=hidden,
        speaker_count_combo=hidden,
        narrator_only_switch=hidden,
        narrator_llm_review_switch=hidden,
        separate_vocal_switch=hidden,
        embed_bgm_switch=hidden,
        bgm_loop_switch=hidden,
        bgm_volume_spin=hidden,
        extra_bgm_edit=hidden,
        output_dir_edit=hidden,
    )

    dubbing_module.DubbingInterface._persist_dubbing_settings(interface)

    assert {
        name: getattr(fake_cfg, name).value for name in alignment_values
    } == alignment_values


def test_review_countdowns_auto_continue_at_zero():
    stopped = []
    accepted = []
    dialog = SimpleNamespace(
        _remaining_seconds=1,
        _countdown_timer=SimpleNamespace(stop=lambda: stopped.append(True)),
        accept=lambda: accepted.append(True),
    )
    alignment_module.NarratorReviewDialog._tick_countdown(dialog)

    confirmed = []
    interface = SimpleNamespace(
        _translation_review_remaining=1,
        _confirm_translation=lambda: confirmed.append(True),
    )
    alignment_module.VideoAlignmentInterface._tick_translation_review(interface)

    assert stopped == [True]
    assert accepted == [True]
    assert confirmed == [True]


def test_background_review_wait_has_timeout():
    waits = []
    event = SimpleNamespace(wait=lambda timeout: waits.append(timeout) or False)

    VideoTranslationThread._wait_for_review(event, "test")

    assert waits == [REVIEW_WAIT_TIMEOUT_SECONDS]
    assert REVIEW_WAIT_TIMEOUT_SECONDS == 40


def test_video_translation_outputs_to_per_video_folder(tmp_path):
    video = tmp_path / "episode.mp4"

    assert _job_output_dir(video, "") == tmp_path / "episode_视频翻译"
    assert _job_output_dir(video, str(tmp_path / "exports")) == (
        tmp_path / "exports" / "episode_视频翻译"
    )


def test_video_translation_keeps_only_deliverables_in_output_root(tmp_path):
    output = tmp_path / "episode_视频翻译"
    intermediate = output / "中间文件"
    intermediate.mkdir(parents=True)
    video = tmp_path / "episode.mp4"
    translated = intermediate / "episode-translated.srt"
    translated.write_text("translated", encoding="utf-8")
    adjusted = output / "episode-translated.adjusted.srt"
    adjusted.write_text("adjusted", encoding="utf-8")
    audio = output / "episode-translated.mp3"
    audio.write_bytes(b"audio")
    (intermediate / adjusted.name).write_text("old", encoding="utf-8")
    (intermediate / audio.name).write_bytes(b"old")

    final_subtitle = _organize_outputs(output, video, translated)

    assert final_subtitle.read_text(encoding="utf-8") == "adjusted"
    assert sorted(path.name for path in output.iterdir()) == [
        "episode_最终字幕.srt",
        "中间文件",
    ]
    assert (intermediate / adjusted.name).read_text(encoding="utf-8") == "adjusted"
    assert (intermediate / audio.name).read_bytes() == b"audio"


def test_narrator_review_artifacts_keep_actual_deleted_rows(tmp_path):
    source = tmp_path / "source.srt"
    filtered = tmp_path / "source-narrator.srt"
    data = ASRData(
        [
            ASRDataSeg("解说", 0, 1000),
            ASRDataSeg("原片对白", 1000, 2000),
        ]
    )
    data.to_srt(save_path=str(source))
    ASRData([data.segments[0]]).to_srt(save_path=str(filtered))
    dropped = [
        {
            "index": 1,
            "start_time": 1000,
            "end_time": 2000,
            "speaker": "spk1",
            "text": "原片对白",
            "reason": "other_speaker",
            "llm_label": "dialogue",
        }
    ]

    review = _save_narrator_review_artifacts(
        source, filtered, {"dropped_count": 1}, dropped, data
    )

    payload = json.loads(review.read_text(encoding="utf-8"))
    assert payload["dropped"] == dropped
    assert "原片对白" in source.with_name("source-narrator-dropped.srt").read_text(
        encoding="utf-8"
    )

    payload["restore_on_next_run"] = [1]
    review.write_text(json.dumps(payload), encoding="utf-8")
    assert _load_pending_narrator_restores(source) == {1}


def test_alignment_uses_multilingual_model_for_auto_and_other_languages():
    interface = SimpleNamespace(
        source_language_combo=_Widget(TranscribeLanguageEnum.AUTO)
    )
    assert alignment_module.VideoAlignmentInterface._requires_multilingual_diarization(
        interface
    )

    interface.source_language_combo = _Widget(TranscribeLanguageEnum.JAPANESE)
    assert alignment_module.VideoAlignmentInterface._requires_multilingual_diarization(
        interface
    )

    interface.source_language_combo = _Widget(TranscribeLanguageEnum.ENGLISH)
    assert not alignment_module.VideoAlignmentInterface._requires_multilingual_diarization(
        interface
    )
