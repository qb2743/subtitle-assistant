import json
import subprocess
from pathlib import Path

from pydub import AudioSegment

from videocaptioner.core.diarization.assign import write_speaker_json
from videocaptioner.core.dubbing import (
    DubbingConfig,
    DubbingPipeline,
    DubbingSegment,
    SpeakerProfile,
)
from videocaptioner.core.dubbing.models import elevenlabs_concurrent_per_key
from videocaptioner.core.dubbing.pipeline import default_dubbed_audio_path, resolve_tts_worker_count
from videocaptioner.core.entities import SubtitleLayoutEnum, SubtitleRenderModeEnum
from videocaptioner.core.speech import SynthesisResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FFMPEG = str(PROJECT_ROOT / "ffmpeg.exe") if (PROJECT_ROOT / "ffmpeg.exe").is_file() else "ffmpeg"
FFPROBE = str(PROJECT_ROOT / "ffprobe.exe") if (PROJECT_ROOT / "ffprobe.exe").is_file() else "ffprobe"


def _make_test_video(path: Path, duration: int = 2) -> None:
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=320x240:d={duration}:r=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def _video_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = result.stdout.strip().split(",")
    return int(width), int(height)


class FakeSynthesizer:
    calls = []

    def synthesize(self, request):
        self.calls.append(request.text)
        audio = AudioSegment.silent(duration=350, frame_rate=24000)
        Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)
        audio.export(request.output_path, format="wav")
        return SynthesisResult(
            output_path=request.output_path,
            voice=request.voice or "fake",
            format="wav",
            provider_metadata={},
        )


def test_default_dubbed_audio_path_matches_subtitle_stem():
    assert default_dubbed_audio_path(r"C:\work\【字幕】demo.srt") == r"C:\work\【字幕】demo.mp3"
    assert default_dubbed_audio_path("/a/b/caption.ass", "wav") == "/a/b/caption.wav"


def test_dubbing_pipeline_creates_timeline_audio(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n[Alice] Hello\n\n"
        "2\n00:00:01,200 --> 00:00:02,000\n[Bob] Hi\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )

    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        speaker_profiles={
            "Alice": SpeakerProfile(name="Alice", voice="Aoede"),
            "Bob": SpeakerProfile(name="Bob", voice="Puck"),
        },
    )
    result = DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert output.exists()
    assert result.duration_ms == 2000
    assert len(result.segments) == 2
    assert result.segments[0].speaker == "Alice"
    assert result.segments[1].speaker == "Bob"
    assert [segment.voice for segment in result.segments] == ["Aoede", "Puck"]
    assert not output.with_suffix(".dubbing.json").exists()


def test_speaker_sidecar_profiles_reach_tts_requests(tmp_path, monkeypatch):
    srt = tmp_path / "translated.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nFirst line\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nSecond line\n",
        encoding="utf-8",
    )
    write_speaker_json(["spk0", "spk1"], tmp_path / "translated.speaker.json")
    captured_requests = []

    class CapturingSynthesizer(FakeSynthesizer):
        def synthesize(self, request):
            captured_requests.append((request.text, request.voice))
            return super().synthesize(request)

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: CapturingSynthesizer(),
    )
    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        speaker_profiles={
            "spk0": SpeakerProfile(name="spk0", voice="Aoede"),
            "spk1": SpeakerProfile(name="spk1", voice="Puck"),
        },
    )

    result = DubbingPipeline(config).run(
        str(srt),
        str(tmp_path / "dub.wav"),
        work_dir=str(tmp_path / "parts"),
    )

    assert [segment.speaker for segment in result.segments] == ["spk0", "spk1"]
    assert [segment.voice for segment in result.segments] == ["Aoede", "Puck"]
    assert dict(captured_requests) == {
        "First line": "Aoede",
        "Second line": "Puck",
    }


def test_extra_bgm_is_mixed_without_reembed_switch(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"
    calls = []

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )

    def fake_mix(dubbed_audio, **kwargs):
        calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(Path(dubbed_audio).read_bytes())
        return kwargs["output_path"]

    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.mix_background", fake_mix)
    config = DubbingConfig(
        provider="edge",
        api_key="",
        base_url="",
        model="edge-tts",
        voice="zh-CN-XiaoxiaoNeural",
        embed_bgm=False,
        bgm_loop=True,
        extra_bgm_path="bgm.mp3",
    )

    DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert calls[0]["instrument_path"] is None
    assert calls[0]["extra_bgm_path"] == "bgm.mp3"
    assert calls[0]["loop"] is True


def test_dubbing_pipeline_uses_configured_workers(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOne\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nTwo\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\nThree\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"
    seen_workers = []

    class CapturingExecutor:
        def __init__(self, max_workers):
            seen_workers.append(max_workers)
            from concurrent.futures import ThreadPoolExecutor

            self._executor = ThreadPoolExecutor(max_workers=max_workers)

        def __enter__(self):
            return self._executor.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._executor.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.ThreadPoolExecutor", CapturingExecutor)

    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        tts_workers=2,
    )
    DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert seen_workers == [2]


def test_dubbing_pipeline_caps_elevenlabs_workers(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOne\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nTwo\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\nThree\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"
    seen_workers = []

    class CapturingExecutor:
        def __init__(self, max_workers):
            seen_workers.append(max_workers)
            from concurrent.futures import ThreadPoolExecutor

            self._executor = ThreadPoolExecutor(max_workers=max_workers)

        def __enter__(self):
            return self._executor.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._executor.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.ThreadPoolExecutor", CapturingExecutor)

    config = DubbingConfig(
        provider="elevenlabs",
        api_key="test",
        base_url="",
        model="eleven_multilingual_v2",
        voice="21m00Tcm4TlvDq8ikWAM",
        tts_workers=5,
    )
    DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert seen_workers == [2]


def test_elevenlabs_concurrent_per_key_by_model():
    assert elevenlabs_concurrent_per_key("eleven_flash_v2_5") == 4
    assert elevenlabs_concurrent_per_key("eleven_turbo_v2_5") == 4
    assert elevenlabs_concurrent_per_key("eleven_multilingual_v2") == 2


def test_resolve_tts_worker_count_elevenlabs_scales_with_keys():
    cfg = DubbingConfig(
        provider="elevenlabs",
        api_key="k1,k2,k3",
        base_url="",
        model="eleven_flash_v2_5",
        tts_workers=20,
    )
    assert resolve_tts_worker_count(cfg, 10) == 10
    assert resolve_tts_worker_count(cfg, 20) == 12

    cfg_v2 = DubbingConfig(
        provider="elevenlabs",
        api_key="k1,k2,k3",
        base_url="",
        model="eleven_multilingual_v2",
        tts_workers=5,
    )
    assert resolve_tts_worker_count(cfg_v2, 10) == 6


def test_resolve_tts_worker_count_fishaudio_scales_with_unique_keys():
    cfg = DubbingConfig(
        provider="fishaudio",
        api_key="k1,k2,k3",
        base_url="",
        model="s2.1-pro",
        tts_workers=16,
    )
    assert resolve_tts_worker_count(cfg, 100) == 48
    assert resolve_tts_worker_count(cfg, 20) == 20

    cfg.tts_workers = 2
    assert resolve_tts_worker_count(cfg, 20) == 6

    cfg.api_key = "k1,k1;k2 k2"
    cfg.tts_workers = 5
    assert resolve_tts_worker_count(cfg, 20) == 10


def test_dubbing_pipeline_elevenlabs_workers_scale_with_api_keys(tmp_path, monkeypatch):
    lines = []
    for i in range(8):
        start = i
        end = i + 1
        lines.append(
            f"{i + 1}\n00:00:{start:02d},000 --> 00:00:{end:02d},000\nLine {i + 1}\n\n"
        )
    srt = tmp_path / "input.srt"
    srt.write_text("".join(lines), encoding="utf-8")
    output = tmp_path / "dub.wav"
    seen_workers = []

    class CapturingExecutor:
        def __init__(self, max_workers):
            seen_workers.append(max_workers)
            from concurrent.futures import ThreadPoolExecutor

            self._executor = ThreadPoolExecutor(max_workers=max_workers)

        def __enter__(self):
            return self._executor.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._executor.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    monkeypatch.setattr("videocaptioner.core.dubbing.pipeline.ThreadPoolExecutor", CapturingExecutor)

    config = DubbingConfig(
        provider="elevenlabs",
        api_key="key-a,key-b",
        base_url="",
        model="eleven_flash_v2_5",
        voice="21m00Tcm4TlvDq8ikWAM",
        tts_workers=5,
    )
    DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert seen_workers == [8]


def test_dubbing_pipeline_silences_failed_segment_and_continues(tmp_path, monkeypatch):
    """A segment whose synthesis fails (all keys exhausted) must not abort the
    dub: it's replaced with a silence placeholder so the quota already spent
    on other lines is not wasted. This is the "配音不要停" guarantee.
    """
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOK\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nBOOM\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\nOK again\n",
        encoding="utf-8",
    )
    output = tmp_path / "dub.wav"

    class FlakySynthesizer:
        def synthesize(self, request):
            if request.text == "BOOM":
                raise RuntimeError("all keys failed")
            audio = AudioSegment.silent(duration=500, frame_rate=24000)
            Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)
            audio.export(request.output_path, format="wav")
            return SynthesisResult(
                output_path=request.output_path,
                voice=request.voice or "fake",
                format="wav",
                provider_metadata={},
            )

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FlakySynthesizer(),
    )

    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
    )
    result = DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    # The run completed and produced audio despite the mid-batch failure.
    assert output.exists()
    assert len(result.segments) == 3
    # The failed segment is flagged; the other two are clean.
    failed = [seg for seg in result.segments if seg.warning]
    assert len(failed) == 1
    assert failed[0].text == "BOOM"
    assert "静音占位" in failed[0].warning
    # A matching warning was surfaced in the result.
    assert any("字幕段 2" in w and "静音占位" in w for w in result.warnings)


def test_pipeline_real_video_filters_and_output_dir(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOne\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nTwo\n",
        encoding="utf-8",
    )
    video = tmp_path / "input.mp4"
    _make_test_video(video)
    output_dir = tmp_path / "rendered"

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        random_color=True,
        canvas="1080x1920",
        output_dir=str(output_dir),
    )

    result = DubbingPipeline(config).run(
        str(srt),
        str(tmp_path / "requested.wav"),
        video_path=str(video),
        work_dir=str(tmp_path / "parts"),
    )

    assert result.audio_path.parent == output_dir
    assert result.video_path is not None and result.video_path.parent == output_dir
    assert result.audio_path.is_file()
    assert result.video_path.is_file()
    assert _video_dimensions(result.video_path) == (1080, 1920)


def test_pipeline_diarization_assigns_role_profiles_before_tts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "videocaptioner.core.diarization.diarize",
        lambda *_args, **_kwargs: [
            {"start": 0.0, "end": 1.0, "speaker": "spk0"},
            {"start": 1.0, "end": 2.0, "speaker": "spk1"},
        ],
    )
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        enable_diarization=True,
        speaker_profiles={
            "spk0": SpeakerProfile(name="spk0", voice="Kore"),
            "spk1": SpeakerProfile(name="spk1", voice="Puck"),
        },
    )
    pipeline = DubbingPipeline(config)
    segments = [
        DubbingSegment(index=1, start_ms=0, end_ms=1000, text="One"),
        DubbingSegment(index=2, start_ms=1000, end_ms=2000, text="Two"),
    ]

    result = pipeline._apply_diarization_and_narrator_filter(
        segments,
        "unused.mp4",
        tmp_path / "dub.wav",
        tmp_path,
        lambda *_args: None,
        [],
    )
    pipeline._apply_speakers(result)

    assert [segment.speaker for segment in result] == ["spk0", "spk1"]
    assert [segment.voice for segment in result] == ["Kore", "Puck"]


def test_pipeline_keeps_strict_filter_when_review_artifact_writes_fail(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "videocaptioner.core.diarization.diarize",
        lambda *_args, **_kwargs: [
            {"start": 0.0, "end": 1.0, "speaker": "spk0"},
            {"start": 1.0, "end": 2.0, "speaker": "spk1"},
            {"start": 2.0, "end": 3.0, "speaker": "spk0"},
        ],
    )
    monkeypatch.setattr(
        "videocaptioner.core.diarization.assign.write_speaker_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    pipeline = DubbingPipeline(
        DubbingConfig(
            provider="gemini",
            api_key="test",
            base_url="",
            model="gemini-3.1-flash-tts-preview",
            voice="Kore",
            enable_diarization=True,
            narrator_only=True,
        )
    )
    monkeypatch.setattr(
        pipeline,
        "_write_dropped_subtitles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )
    segments = [
        DubbingSegment(index=1, start_ms=0, end_ms=1000, text="Narrator one"),
        DubbingSegment(index=2, start_ms=1000, end_ms=2000, text="Dialogue"),
        DubbingSegment(index=3, start_ms=2000, end_ms=3000, text="Narrator two"),
    ]
    warnings = []

    result = pipeline._apply_diarization_and_narrator_filter(
        segments,
        "unused.mp4",
        tmp_path / "dub.wav",
        tmp_path,
        lambda *_args: None,
        warnings,
    )

    assert [segment.text for segment in result] == ["Narrator one", "Narrator two"]
    assert any("标签文件写入失败" in warning for warning in warnings)
    assert any("删除字幕清单写入失败" in warning for warning in warnings)
    assert not any("说话人识别失败" in warning for warning in warnings)


def test_pipeline_diarization_writes_sidecars_and_llm_restores(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n旁白一\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n误标的旁白\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\n旁白二\n",
        encoding="utf-8",
    )
    video = tmp_path / "input.mp4"
    _make_test_video(video, duration=3)
    output_dir = tmp_path / "rendered"
    seen_languages = []
    reviewed = {}

    def fake_diarize(
        audio_path,
        num_speakers=0,
        language="zh",
        progress=None,
        isolate_process=False,
    ):
        seen_languages.append(language)
        if progress:
            progress(100, "done")
        return [
            {"start": 0.0, "end": 1.0, "speaker": "spk0"},
            {"start": 1.0, "end": 2.0, "speaker": "spk1"},
            {"start": 2.0, "end": 3.0, "speaker": "spk0"},
        ]

    monkeypatch.setattr("videocaptioner.core.diarization.diarize", fake_diarize)

    def fake_judge(kept_segments, dropped_segments, *_args, **_kwargs):
        reviewed["kept"] = [segment.text for segment in kept_segments]
        reviewed["dropped"] = [segment.text for segment in dropped_segments]
        return [0]

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.narrator_llm_judge.judge_dropped",
        fake_judge,
    )
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: FakeSynthesizer(),
    )
    config = DubbingConfig(
        provider="gemini",
        api_key="test",
        base_url="",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        enable_diarization=True,
        diarization_language="en",
        narrator_only=True,
        narrator_llm_review=True,
        llm_api_key="llm-key",
        llm_api_base="https://example.invalid/v1",
        llm_model="test-model",
        speaker_profiles={
            "spk0": SpeakerProfile(name="spk0", voice="Kore"),
            "spk1": SpeakerProfile(name="spk1", voice="Puck"),
        },
        output_dir=str(output_dir),
    )

    result = DubbingPipeline(config).run(
        str(srt),
        str(tmp_path / "requested.wav"),
        video_path=str(video),
        work_dir=str(tmp_path / "parts"),
    )

    speaker_sidecar = output_dir / "requested.speaker.json"
    dropped_sidecar = output_dir / "requested.narrator_dropped.srt"
    assert seen_languages == ["en"]
    assert json.loads(speaker_sidecar.read_text(encoding="utf-8")) == [
        "spk0",
        "spk1",
        "spk0",
    ]
    assert dropped_sidecar.is_file()
    assert dropped_sidecar.read_text(encoding="utf-8") == ""
    assert reviewed == {
        "kept": ["旁白一", "旁白二"],
        "dropped": ["误标的旁白"],
    }
    assert len(result.segments) == 3
    assert {segment.speaker for segment in result.segments} == {"spk0"}
    assert {segment.voice for segment in result.segments} == {"Kore"}
    assert not any("过滤删除" in warning for warning in result.warnings)
    assert result.video_path is not None and result.video_path.is_file()


def test_burn_subtitles_uses_configured_style(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nStyled\n",
        encoding="utf-8",
    )
    calls = []

    def fake_styled(video_path, asr_data, output_path, render_mode, layout, **kwargs):
        calls.append((video_path, output_path, render_mode, layout, kwargs))

    monkeypatch.setattr(
        "videocaptioner.core.utils.video_utils.add_subtitles_with_style", fake_styled
    )
    monkeypatch.setattr(
        "videocaptioner.core.utils.video_utils.add_subtitles",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy path used")),
    )
    config = DubbingConfig(
        provider="edge",
        api_key="",
        base_url="",
        model="edge-tts",
        subtitle_render_mode=SubtitleRenderModeEnum.ROUNDED_BG,
        subtitle_layout=SubtitleLayoutEnum.ONLY_ORIGINAL,
        subtitle_rounded_style={"font_size": 32},
    )

    DubbingPipeline(config)._burn_subtitles(
        "input.mp4", str(srt), "output.mp4"
    )

    assert len(calls) == 1
    assert calls[0][2] == SubtitleRenderModeEnum.ROUNDED_BG
    assert calls[0][3] == SubtitleLayoutEnum.ONLY_ORIGINAL
    assert calls[0][4]["rounded_style"] == {"font_size": 32}


def test_display_only_subtitles_are_merged_but_never_sent_to_tts(
    tmp_path, monkeypatch
):
    narrator = tmp_path / "narrator.srt"
    narrator.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nNarration\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nMore narration\n",
        encoding="utf-8",
    )
    original = tmp_path / "original.srt"
    original.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nOriginal dialogue\n",
        encoding="utf-8",
    )
    captured = []

    class CapturingSynthesizer(FakeSynthesizer):
        def synthesize(self, request):
            captured.append(request.text)
            return super().synthesize(request)

    monkeypatch.setattr(
        "videocaptioner.core.dubbing.pipeline.create_speech_synthesizer",
        lambda _config: CapturingSynthesizer(),
    )
    config = DubbingConfig(
        provider="edge",
        api_key="",
        base_url="",
        model="edge-tts",
        voice="zh-CN-XiaoxiaoNeural",
    )

    result = DubbingPipeline(config).run(
        str(narrator),
        str(tmp_path / "dub.wav"),
        display_subtitle_path=str(original),
        protected_subtitle_path=str(original),
        work_dir=str(tmp_path / "parts"),
    )

    assert captured == ["Narration", "More narration"]
    assert result.adjusted_subtitle_path is not None
    content = result.adjusted_subtitle_path.read_text(encoding="utf-8")
    assert "Narration" in content
    assert "Original dialogue" in content
