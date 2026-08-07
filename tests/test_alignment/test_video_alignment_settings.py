import json
from types import SimpleNamespace

import videocaptioner.ui.thread.video_translation_thread as video_thread_module
import videocaptioner.ui.view.dubbing_interface as dubbing_module
import videocaptioner.ui.view.home_interface as home_module
import videocaptioner.ui.view.video_alignment_interface as alignment_module
from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.dubbing.subtitle_parser import load_dubbing_segments
from videocaptioner.core.entities import TranscribeLanguageEnum
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.ui.thread.video_translation_thread import (
    REVIEW_WAIT_TIMEOUT_SECONDS,
    VideoTranslationThread,
    _job_output_dir,
    _load_pending_narrator_restores,
    _organize_outputs,
    _save_narrator_review_artifacts,
    _write_dubbing_subtitle,
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

    def currentText(self):
        return self.items[self.index][0] if self.items else ""

    def currentData(self):
        return self.items[self.index][1] if self.items else None

    def clear(self):
        self.items.clear()
        self.index = 0

    def addItem(self, text, userData=None):
        self.items.append((text, userData))

    def blockSignals(self, _blocked):
        pass

    def setEnabled(self, enabled):
        self.enabled = enabled


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

    def setEnabled(self, enabled):
        self.enabled = enabled


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
        subtitle_action=_item("rewrite"),
    )
    monkeypatch.setattr(alignment_module, "cfg", fake_cfg)
    interface = SimpleNamespace(
        tts_provider_combo=_Combo([("edge - Edge TTS", "edge")]),
        speaker_count_combo=_Combo([("auto", 0), ("3", 3)]),
        canvas_combo=_Combo([("off", "off"), ("portrait", "1080x1920")]),
        embed_combo=_Combo([("none", "none"), ("hard", "hard")]),
        subtitle_action_combo=_Combo([("翻译", "translate"), ("洗稿", "rewrite")]),
        _update_subtitle_action_ui=lambda: None,
    )

    alignment_module.VideoAlignmentInterface._load_config(interface)

    assert interface.canvas_combo.index == 1
    assert interface.embed_combo.index == 1
    assert interface.subtitle_action_combo.index == 1


def test_alignment_voice_options_match_provider_and_target_language():
    english_edge = alignment_module.alignment_voice_options(
        "edge", TargetLanguage.ENGLISH_US
    )
    assert english_edge
    assert all(voice.startswith("en-") for _name, voice in english_edge)

    openai = dict(alignment_module.alignment_voice_options("openai", None))
    assert openai["Nova - 女声"] == "nova"
    assert alignment_module.alignment_voice_options("voxcpm", None) == []


def test_alignment_provider_switch_drops_previous_provider_voice(monkeypatch):
    fake_cfg = SimpleNamespace(
        dubbing_provider=_item("edge"),
        dubbing_voice=_item("zh-CN-XiaoxiaoNeural"),
    )
    monkeypatch.setattr(alignment_module, "cfg", fake_cfg)
    voice_combo = _Combo([])
    interface = SimpleNamespace(
        tts_provider_combo=_Combo([("openai - OpenAI TTS", None)]),
        target_language_combo=_Widget(TargetLanguage.ENGLISH),
        tts_voice_combo=voice_combo,
        _tts_provider_id=lambda: "openai",
    )

    alignment_module.VideoAlignmentInterface._refresh_tts_voices(interface)

    assert voice_combo.currentData() == "alloy"
    assert all(data != "zh-CN-XiaoxiaoNeural" for _name, data in voice_combo.items)


def test_alignment_provider_switch_uses_matching_model(monkeypatch):
    fake_cfg = SimpleNamespace(
        dubbing_provider=_item("fishaudio"),
        dubbing_model=_item("s2.1-pro"),
    )
    monkeypatch.setattr(alignment_module, "cfg", fake_cfg)
    model_combo = _Combo([])
    interface = SimpleNamespace(
        tts_provider_combo=_Combo([("elevenlabs - ElevenLabs", None)]),
        tts_model_combo=model_combo,
        _tts_provider_id=lambda: "elevenlabs",
    )

    alignment_module.VideoAlignmentInterface._refresh_tts_models(interface)

    assert model_combo.currentData() == "eleven_flash_v2_5"
    assert all(not data.startswith("s2") for _name, data in model_combo.items)


def test_home_refreshes_dubbing_controls_when_switching_pages():
    events = []
    dubbing = SimpleNamespace(
        load_config=lambda: events.append("dubbing"),
        objectName=lambda: "DubbingInterface",
    )
    alignment = SimpleNamespace(
        _config_loading=False,
        _load_config=lambda: events.append("alignment-config"),
        _refresh_tts_models=lambda: events.append("alignment-model"),
        _refresh_tts_voices=lambda: events.append("alignment-voice"),
        objectName=lambda: "VideoAlignmentInterface",
    )
    interface = SimpleNamespace(
        dubbing_interface=dubbing,
        video_alignment_interface=alignment,
        stackedWidget=SimpleNamespace(widget=lambda index: (dubbing, alignment)[index]),
        pivot=SimpleNamespace(setCurrentItem=lambda name: events.append(name)),
    )

    home_module.HomeInterface.onCurrentIndexChanged(interface, 0)
    home_module.HomeInterface.onCurrentIndexChanged(interface, 1)

    assert events == [
        "dubbing",
        "DubbingInterface",
        "alignment-config",
        "alignment-model",
        "alignment-voice",
        "VideoAlignmentInterface",
    ]
    assert alignment._config_loading is False


def test_dubbing_page_preserves_empty_fish_clone_voice(monkeypatch):
    fake_cfg = SimpleNamespace(
        dubbing_provider=_item("fishaudio"),
        dubbing_voice=_item(""),
    )
    monkeypatch.setattr(dubbing_module, "cfg", fake_cfg)

    assert dubbing_module._configured_voice_for_provider("fishaudio") == ""
    assert dubbing_module._configured_voice_for_provider("elevenlabs") is None


def test_extra_bgm_enables_loop_and_volume_controls():
    loop = _Widget(False)
    slider = _Widget(0)
    spin = _Widget(0)
    interface = SimpleNamespace(
        split_switch=_Widget(True),
        max_cjk_spin=_Widget(28),
        max_words_spin=_Widget(20),
        diarization_switch=_Widget(False),
        speaker_count_combo=_Widget(0),
        narrator_only_switch=_Widget(False),
        llm_review_switch=_Widget(False),
        embed_bgm_switch=_Widget(False),
        extra_bgm_edit=_Widget("D:/music/bgm.mp3"),
        bgm_loop_switch=loop,
        bgm_volume_slider=slider,
        bgm_volume_spin=spin,
    )

    alignment_module.VideoAlignmentInterface._update_enabled(interface)

    assert loop.enabled is True
    assert slider.enabled is True
    assert spin.enabled is True


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


def test_video_translation_freezes_subtitle_config(monkeypatch):
    config = SimpleNamespace(subtitle_action="translate")
    monkeypatch.setattr(
        video_thread_module.TaskFactory,
        "create_subtitle_task",
        lambda *args, **kwargs: SimpleNamespace(subtitle_config=config),
    )

    thread = VideoTranslationThread("episode.mp4", subtitle_action="rewrite")

    assert thread.subtitle_config is config
    assert config.subtitle_action == "rewrite"


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


def test_dubbing_subtitle_uses_only_same_language_rewrite(tmp_path):
    subtitle = tmp_path / "rewrite.srt"
    data = ASRData(
        [
            ASRDataSeg(
                "When the boy was born",
                0,
                1200,
                translated_text="The boy came into the world",
            )
        ]
    ).to_json()

    _write_dubbing_subtitle(subtitle, data)

    content = subtitle.read_text(encoding="utf-8")
    assert "The boy came into the world" in content
    assert "When the boy was born" not in content
    assert load_dubbing_segments(str(subtitle))[0].text == "The boy came into the world"


def test_translation_review_passes_structured_edits_to_worker(tmp_path):
    subtitle = tmp_path / "rewrite.srt"
    data = ASRData(
        [ASRDataSeg("Original", 0, 1000, translated_text="Edited rewrite")]
    ).to_json()
    continued = []
    interface = SimpleNamespace(
        subtitle_editor=SimpleNamespace(
            model=SimpleNamespace(_data=data),
            subtitle_path=str(subtitle),
            setVisible=lambda _visible: None,
        ),
        editor_title=SimpleNamespace(setVisible=lambda _visible: None),
        confirm_translation_btn=SimpleNamespace(setVisible=lambda _visible: None),
        workflow_thread=SimpleNamespace(
            continue_translation=lambda value: continued.append(value),
            cancel=lambda: None,
        ),
        _on_error=lambda _message: None,
    )

    alignment_module.VideoAlignmentInterface._finish_translation_review(interface)

    assert continued == [data]
    assert "Edited rewrite" in subtitle.read_text(encoding="utf-8")
    assert "Original" not in subtitle.read_text(encoding="utf-8")


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
