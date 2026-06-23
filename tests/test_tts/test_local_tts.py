"""Tests for the local Gradio TTS engines (Dots-TTS, VoxCPM) and GradioBaseTTS.

``gradio_client`` is not installed; the client and ``handle_file`` are faked
so no real service or network is needed.
"""

from pathlib import Path

import pytest
from pydub import AudioSegment

from videocaptioner.core.tts import DotsTTS, GradioBaseTTS, TTSConfig, TTSDataSeg, VoxCPMTTS


def _wav(path: Path, duration_ms: int = 100) -> Path:
    AudioSegment.silent(duration=duration_ms, frame_rate=48000).export(path, format="wav")
    return path


def _config(**overrides) -> TTSConfig:
    defaults = {"model": "dots-tts", "api_key": "", "base_url": "http://127.0.0.1:7860"}
    defaults.update(overrides)
    return TTSConfig(**defaults)


class _NoDefaultEngine(GradioBaseTTS):
    service_name = "testengine"
    # no default_api_url -> base_url is required

    def _build_predict_kwargs(self, segment):  # type: ignore[override]
        return {}


def test_gradio_base_requires_url_when_no_default():
    with pytest.raises(ValueError, match="service URL"):
        _NoDefaultEngine(TTSConfig(model="t", api_key="", base_url=""))


def test_dots_uses_default_url_when_blank():
    tts = DotsTTS(TTSConfig(model="dots-tts", api_key="", base_url=""))
    assert tts.api_url == "http://127.0.0.1:7860"


def test_dots_prefixes_http_if_missing():
    tts = DotsTTS(TTSConfig(model="dots-tts", api_key="", base_url="127.0.0.1:9999"))
    assert tts.api_url == "http://127.0.0.1:9999"


def test_dots_build_kwargs_with_clone(tmp_path, monkeypatch):
    ref = _wav(tmp_path / "ref.wav")
    tts = DotsTTS(_config())
    monkeypatch.setattr(tts, "_handle_file", lambda p: f"handled:{p}")
    seg = TTSDataSeg(text="你好世界", clone_audio_path=str(ref), clone_audio_text="你好")
    kwargs = tts._build_predict_kwargs(seg)
    assert kwargs["text"] == "你好世界"
    assert kwargs["prompt_audio_path"] == f"handled:{ref}"
    assert kwargs["prompt_text"] == "你好"
    assert kwargs["api_name"] == "/run_synthesis"
    assert kwargs["num_steps"] == 10
    assert kwargs["guidance_scale"] == 1.2


def test_dots_requires_reference_audio(tmp_path):
    tts = DotsTTS(_config())
    seg = TTSDataSeg(text="你好")  # no clone_audio_path
    with pytest.raises(ValueError, match="reference audio"):
        tts._build_predict_kwargs(seg)


def test_dots_rejects_missing_ref_file(tmp_path):
    tts = DotsTTS(_config())
    seg = TTSDataSeg(text="你好", clone_audio_path=str(tmp_path / "nope.wav"))
    with pytest.raises(ValueError, match="reference audio"):
        tts._build_predict_kwargs(seg)


def test_voxcpm_build_kwargs_with_clone(tmp_path, monkeypatch):
    ref = _wav(tmp_path / "ref.wav")
    tts = VoxCPMTTS(TTSConfig(model="voxcpm", api_key="", base_url="http://127.0.0.1:9880"))
    monkeypatch.setattr(tts, "_handle_file", lambda p: f"handled:{p}")
    seg = TTSDataSeg(text="测试克隆", clone_audio_path=str(ref), clone_audio_text="参考文本")
    kwargs = tts._build_predict_kwargs(seg)
    assert kwargs["text"] == "测试克隆"
    assert kwargs["ref_wav"] == f"handled:{ref}"
    assert kwargs["prompt_text_value"] == "参考文本"
    assert kwargs["use_prompt_text"] is True
    assert kwargs["api_name"] == "/generate"
    assert kwargs["dit_steps"] == 10
    assert kwargs["cfg_value"] == 2


def test_voxcpm_build_kwargs_for_v1_and_hf(tmp_path, monkeypatch):
    ref = _wav(tmp_path / "ref.wav")
    seg = TTSDataSeg(text="测试克隆", clone_audio_path=str(ref), clone_audio_text="参考文本")

    v1 = VoxCPMTTS(TTSConfig(model="voxcpm", api_key="", base_url="http://127.0.0.1:9880", voxcpm_version="v1"))
    monkeypatch.setattr(v1, "_handle_file", lambda p: f"handled:{p}")
    kwargs = v1._build_predict_kwargs(seg)
    assert kwargs["text_input"] == "测试克隆"
    assert kwargs["prompt_wav_path_input"] == f"handled:{ref}"
    assert kwargs["prompt_text_input"] == "参考文本"
    assert kwargs["inference_timesteps_input"] == 10

    hf = VoxCPMTTS(TTSConfig(model="voxcpm", api_key="", base_url="http://127.0.0.1:9880", voxcpm_version="hf"))
    monkeypatch.setattr(hf, "_handle_file", lambda p: f"handled:{p}")
    kwargs = hf._build_predict_kwargs(seg)
    assert kwargs["text_input"] == "测试克隆"
    assert kwargs["reference_wav_path_input"] == f"handled:{ref}"
    assert kwargs["use_prompt_text"] is True


def test_voxcpm_requires_reference_audio(tmp_path):
    tts = VoxCPMTTS(TTSConfig(model="voxcpm", api_key="", base_url="http://127.0.0.1:9880"))
    seg = TTSDataSeg(text="你好")
    with pytest.raises(ValueError, match="reference audio"):
        tts._build_predict_kwargs(seg)


def test_synthesize_writes_audio(tmp_path, monkeypatch):
    ref = _wav(tmp_path / "ref.wav")
    returned = _wav(tmp_path / "gradio_out.wav", duration_ms=200)
    tts = DotsTTS(_config())
    monkeypatch.setattr(tts, "_ensure_service_ready", lambda **kw: None)
    monkeypatch.setattr(tts, "_handle_file", lambda p: f"handled:{p}")

    class _FakeClient:
        last_kwargs = None

        def predict(self, **kwargs):
            _FakeClient.last_kwargs = kwargs
            return [str(returned)]  # gradio returns [filepath, ...]

    monkeypatch.setattr(tts, "_get_client", lambda: _FakeClient())

    seg = TTSDataSeg(text="你好世界", clone_audio_path=str(ref), clone_audio_text="你好")
    out = tmp_path / "out.wav"
    tts._synthesize(seg, str(out))

    assert seg.audio_path == str(out)
    assert out.exists() and out.stat().st_size > 0
    assert seg.voice == "clone"
    assert _FakeClient.last_kwargs["api_name"] == "/run_synthesis"
    assert _FakeClient.last_kwargs["prompt_audio_path"].startswith("handled:")


def test_is_service_ready_false_on_connection_error(monkeypatch):
    from urllib.error import URLError

    def _raise(*a, **k):
        raise URLError("no connection")

    monkeypatch.setattr("videocaptioner.core.tts.gradio_base.urlopen", _raise)
    tts = DotsTTS(_config(base_url="http://127.0.0.1:9"))
    assert tts._is_service_ready() is False


def test_ensure_service_ready_raises_when_down_and_no_script(monkeypatch):
    tts = DotsTTS(_config())
    monkeypatch.setattr(tts, "_is_service_ready", lambda: False)
    with pytest.raises(RuntimeError, match="not reachable"):
        tts._ensure_service_ready(start_script="", timeout=5)


def test_extract_wav_path_shapes():
    assert GradioBaseTTS._extract_wav_path("/tmp/a.wav") == "/tmp/a.wav"
    assert GradioBaseTTS._extract_wav_path(["/tmp/a.wav", "meta"]) == "/tmp/a.wav"
    assert GradioBaseTTS._extract_wav_path({"value": "/tmp/a.wav"}) == "/tmp/a.wav"
    with pytest.raises(RuntimeError):
        GradioBaseTTS._extract_wav_path(123)
