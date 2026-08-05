import json
import subprocess
from pathlib import Path

from pydub import AudioSegment

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
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
    )
    result = DubbingPipeline(config).run(str(srt), str(output), work_dir=str(tmp_path / "parts"))

    assert output.exists()
    assert result.duration_ms == 2000
    assert len(result.segments) == 2
    assert result.segments[0].speaker == "Alice"
    assert result.segments[1].speaker == "Bob"
    assert not output.with_suffix(".dubbing.json").exists()


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


def test_pipeline_diarization_writes_sidecars_and_llm_restores(tmp_path, monkeypatch):
    srt = tmp_path / "input.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n旁白一\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\n旁白二\n",
        encoding="utf-8",
    )
    video = tmp_path / "input.mp4"
    _make_test_video(video, duration=3)
    output_dir = tmp_path / "rendered"
    seen_languages = []

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
    monkeypatch.setattr(
        "videocaptioner.core.dubbing.narrator_llm_judge.judge_dropped",
        lambda *args, **kwargs: [0],
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
    assert len(result.segments) == 3
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
