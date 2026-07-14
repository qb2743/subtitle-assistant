from pathlib import Path

from pydub import AudioSegment

from videocaptioner.core.dubbing import DubbingConfig, DubbingPipeline
from videocaptioner.core.dubbing.models import elevenlabs_concurrent_per_key
from videocaptioner.core.dubbing.pipeline import default_dubbed_audio_path, resolve_tts_worker_count
from videocaptioner.core.speech import SynthesisResult


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
